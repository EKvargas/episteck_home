"""The Finance image installs exactly the hashed lock, so a rebuild cannot pick up new versions.

Config-only: reads the Dockerfile, the lock and pyproject.toml as text. The lock is
refreshed deliberately (see the Dockerfile header), never by a rebuild.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SERVICE = ROOT / "services" / "finance"
DOCKERFILE = (SERVICE / "Dockerfile").read_text(encoding="utf-8")
LOCK = (SERVICE / "requirements.lock").read_text(encoding="utf-8")
PYPROJECT = tomllib.loads((SERVICE / "pyproject.toml").read_text(encoding="utf-8"))


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _lock_entries() -> dict[str, tuple[str, list[str]]]:
    """name -> (version, hashes), joining the backslash-continued lines."""
    text = re.sub(r"\\\n\s*", " ", LOCK)
    entries = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==(\S+)(.*)$", line)
        assert match, f"every lock line must be an exact pin: {line[:60]}"
        entries[_norm(match.group(1))] = (match.group(2), re.findall(r"--hash=sha256:[0-9a-f]{64}", match.group(3)))
    return entries


def _pip_installs() -> list[str]:
    return [line for line in DOCKERFILE.splitlines() if re.search(r"\bpip install\b", line)]


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", text))


def test_dockerfile_installs_the_lock_with_hashes_before_the_code():
    installs = _pip_installs()
    assert [i for i in installs if "--require-hashes" in i and "-r requirements.lock" in i]
    assert DOCKERFILE.index("--require-hashes") < DOCKERFILE.index("COPY services/finance/app")


def test_every_pip_install_refuses_unlocked_dependencies():
    installs = _pip_installs()
    assert installs and all("--no-deps" in line for line in installs)
    package = [line for line in installs if re.search(r"\s\.\s*$", line)]
    assert len(package) == 1 and "--no-build-isolation" in package[0], \
        "the package itself must not download build requirements either"
    assert re.search(r"(?m)^RUN pip check\s*$", DOCKERFILE)


def test_every_locked_requirement_is_pinned_and_hashed():
    entries = _lock_entries()
    assert entries
    unhashed = [name for name, (_, hashes) in entries.items() if not hashes]
    assert unhashed == []


def test_lock_satisfies_every_direct_dependency():
    entries = _lock_entries()
    for requirement in PYPROJECT["project"]["dependencies"]:
        match = re.match(r"^([A-Za-z0-9._-]+)(\[[^\]]+\])?\s*(==|>=)\s*(\S+)$", requirement)
        assert match, requirement
        name, extras, op, wanted = match.groups()
        assert _norm(name) in entries, f"{name} missing from the lock"
        locked = entries[_norm(name)][0]
        if op == "==":
            assert locked == wanted, f"{name}: lock {locked} != pyproject {wanted}"
        else:
            assert _version(locked) >= _version(wanted), f"{name}: lock {locked} < {wanted}"
        if extras == "[crypto]":
            assert "cryptography" in entries
