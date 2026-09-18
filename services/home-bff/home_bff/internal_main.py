"""Unix-socket entrypoint for the internal delegation mint app."""
from __future__ import annotations

import logging
import os
import socket
import stat
import uuid
import ctypes
import errno
from contextlib import contextmanager
from pathlib import Path

import uvicorn

from .config import Settings
from .internal_app import create_internal_app

_SOCKET_MODE = 0o660
_BIND_UMASK = 0o117

try:  # pragma: no cover - unavailable on Windows; Unix proof runs in WSL.
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None


@contextmanager
def _socket_directory_lock(parent: Path):
    """Serialize compliant creators while they inspect/recreate the pathname."""
    if fcntl is None or not hasattr(os, "O_DIRECTORY"):
        yield
        return
    directory_fd = os.open(
        str(parent), os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        fcntl.flock(directory_fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(directory_fd, fcntl.LOCK_UN)
        os.close(directory_fd)


def _same_inode(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _same_generation(left: os.stat_result, right: os.stat_result) -> bool:
    # Rename updates ctime on the same inode, so generation identity is the
    # device/inode pair. The mutation test deliberately consumes reused inode
    # slots before introducing a replacement entry.
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _path_exists(path: Path) -> bool:
    return os.path.lexists(str(path))


def _listener_is_active(path: Path) -> bool:
    """Return true only when a connect proves a live listener owns the path."""
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    probe.settimeout(0.2)
    try:
        probe.connect(str(path))
    except OSError as error:
        if error.errno in {errno.ECONNREFUSED, errno.ENOENT, errno.ENOTCONN}:
            return False
        raise RuntimeError("unable to determine mint socket liveness") from error
    finally:
        probe.close()
    return True


def _remove_owned_stale_socket(path: Path, expected: os.stat_result) -> None:
    """Atomically quarantine and verify the exact stale inode before unlinking."""
    quarantine = path.with_name(f".{path.name}.stale-{uuid.uuid4().hex}")
    entry_fd = None
    pinned = expected
    if os.name == "posix" and hasattr(os, "O_PATH"):
        entry_fd = os.open(
            str(path),
            os.O_PATH | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        )
        pinned = os.fstat(entry_fd)
        if not _same_inode(pinned, expected) or not stat.S_ISSOCK(pinned.st_mode):
            os.close(entry_fd)
            raise RuntimeError("mint socket namespace changed")
    try:
        os.rename(path, quarantine)
        captured = quarantine.lstat()
        if not _same_inode(captured, pinned):
            raise RuntimeError("mint socket namespace changed")
        if not stat.S_ISSOCK(captured.st_mode) or captured.st_uid != expected.st_uid:
            raise RuntimeError("mint socket namespace changed")
        quarantine.unlink()
    except BaseException:
        # Restore the captured entry only when the original name is still empty;
        # never overwrite a replacement inserted by another namespace actor.
        if _path_exists(quarantine) and not _path_exists(path):
            os.rename(quarantine, path)
        raise
    finally:
        if entry_fd is not None:
            os.close(entry_fd)


def _fchmodat_empty_path(file_descriptor: int, mode: int) -> None:
    """Apply mode to a pinned O_PATH entry without reopening its pathname."""
    libc = ctypes.CDLL(None, use_errno=True)
    fchmodat = libc.fchmodat
    fchmodat.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint, ctypes.c_int]
    fchmodat.restype = ctypes.c_int
    if fchmodat(file_descriptor, b"", mode, 0x1000) != 0:  # AT_EMPTY_PATH
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number))


def _chmod_socket_path(path: Path, expected: os.stat_result) -> None:
    """chmod without following a swapped symlink, then verify the inode again."""
    if os.name == "posix" and hasattr(os, "O_PATH"):
        entry_fd = os.open(
            str(path),
            os.O_PATH | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        )
        try:
            pinned = os.fstat(entry_fd)
            if not _same_inode(pinned, expected) or not stat.S_ISSOCK(pinned.st_mode):
                raise RuntimeError("mint socket namespace changed")
            try:
                _fchmodat_empty_path(entry_fd, _SOCKET_MODE)
            except OSError as error:
                # Some rootless container/seccomp profiles reject
                # fchmodat(AT_EMPTY_PATH) for socket inodes. Keep the pinned
                # identity check and use a no-follow pathname operation under
                # the directory lock as the constrained fallback.
                if error.errno not in {
                    errno.EINVAL,
                    errno.ENOSYS,
                    errno.EOPNOTSUPP,
                }:
                    raise
                current = path.lstat()
                if not _same_inode(current, pinned) or not stat.S_ISSOCK(
                    current.st_mode
                ):
                    raise RuntimeError("mint socket namespace changed") from None
                os.chmod(path, _SOCKET_MODE, follow_symlinks=False)
        finally:
            os.close(entry_fd)
    else:  # pragma: no cover - Unix ownership semantics are tested in WSL.
        try:
            os.chmod(path, _SOCKET_MODE, follow_symlinks=False)
        except NotImplementedError:
            current = path.lstat()
            if not _same_inode(current, expected):
                raise RuntimeError("mint socket namespace changed") from None
            os.chmod(path, _SOCKET_MODE)
    created = path.lstat()
    if not _same_inode(created, expected):
        raise RuntimeError("mint socket namespace changed")
    if not stat.S_ISSOCK(created.st_mode):
        raise RuntimeError("mint socket path is not a socket")
    if created.st_uid != expected.st_uid:
        raise RuntimeError("mint socket has unexpected namespace owner")
    if stat.S_IMODE(created.st_mode) != _SOCKET_MODE:
        raise RuntimeError("mint socket mode is not exactly 0660")


def create_mint_socket(path: Path, *, expected_uid: int) -> socket.socket:
    """Create a verified, listening mint socket, replacing only owned stale state."""
    path = Path(path)
    with _socket_directory_lock(path.parent):
        try:
            existing = path.lstat()
        except FileNotFoundError:
            existing = None
        if existing is not None:
            if not stat.S_ISSOCK(existing.st_mode):
                raise RuntimeError("refusing to remove a non-socket mint path")
            if existing.st_uid != expected_uid:
                raise RuntimeError("refusing to remove a mint socket with wrong owner")
            if _listener_is_active(path):
                raise RuntimeError("refusing to replace an active mint socket")
            _remove_owned_stale_socket(path, existing)

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        previous_umask = os.umask(_BIND_UMASK)
        try:
            sock.bind(str(path))
            sock.listen(128)
        except BaseException:
            sock.close()
            raise
        finally:
            os.umask(previous_umask)

        try:
            created = path.lstat()
            if not stat.S_ISSOCK(created.st_mode):
                raise RuntimeError("mint socket path is not a socket")
            if created.st_uid != expected_uid:
                raise RuntimeError("mint socket has unexpected namespace owner")
            _chmod_socket_path(path, created)
        except BaseException:
            try:
                current = path.lstat()
                if _same_inode(current, created):
                    path.unlink()
            except (FileNotFoundError, UnboundLocalError):
                pass
            sock.close()
            raise
        return sock


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    if not hasattr(os, "getuid"):
        raise RuntimeError("the internal mint listener requires Unix")

    settings = Settings.from_env()
    sock = create_mint_socket(
        Path(settings.mint_socket_path),
        expected_uid=os.getuid(),
    )
    config = uvicorn.Config(create_internal_app(settings), access_log=False)
    try:
        uvicorn.Server(config).run(sockets=[sock])
    finally:
        sock.close()


if __name__ == "__main__":
    main()
