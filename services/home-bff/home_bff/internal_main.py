"""Unix-socket entrypoint for the internal delegation mint app."""
from __future__ import annotations

import logging
import os
import socket
import stat
from pathlib import Path

import uvicorn

from .config import Settings
from .internal_app import create_internal_app

_SOCKET_MODE = 0o660
_BIND_UMASK = 0o117


def create_mint_socket(path: Path, *, expected_uid: int) -> socket.socket:
    """Create a verified mint socket, replacing only an owned stale socket."""
    path = Path(path)
    try:
        existing = path.lstat()
    except FileNotFoundError:
        pass
    else:
        if not stat.S_ISSOCK(existing.st_mode):
            raise RuntimeError("refusing to remove a non-socket mint path")
        if existing.st_uid != expected_uid:
            raise RuntimeError("refusing to remove a mint socket with wrong owner")
        path.unlink()

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    previous_umask = os.umask(_BIND_UMASK)
    try:
        sock.bind(str(path))
    except BaseException:
        sock.close()
        raise
    finally:
        os.umask(previous_umask)

    try:
        os.chmod(path, _SOCKET_MODE)
        created = path.lstat()
        if not stat.S_ISSOCK(created.st_mode):
            raise RuntimeError("mint socket path is not a socket")
        if created.st_uid != expected_uid:
            raise RuntimeError("mint socket has unexpected namespace owner")
        if stat.S_IMODE(created.st_mode) != _SOCKET_MODE:
            raise RuntimeError("mint socket mode is not exactly 0660")
    except BaseException:
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
