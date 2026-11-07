"""Static checks on the owner's write-only secret drop (nothing here touches a node).

The script runs as root through one locked SSH key, so these tests pin the properties that
keep a pasted secret from leaking: hidden prompt, no echo, no read-back, no overwrite, a
format check per slot, mode 600 and a log line without the value.

Run from the repo root:  python -m pytest deploy/secret-drop/tests -q
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
SCRIPT = HERE / "secret-drop"
README = HERE / "README.md"


def text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def code_lines() -> list[str]:
    return [l for l in text().splitlines() if l.strip() and not l.lstrip().startswith("#")]


def slots() -> list[list[str]]:
    block = re.search(r"^SLOTS=\(\n(.*?)^\)", text(), re.S | re.M)
    assert block, "SLOTS=( ... ) block not found"
    return [line.strip().strip('"').split("|") for line in block.group(1).splitlines()
            if line.strip() and not line.strip().startswith("#")]


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_the_script_is_valid_bash():
    # bytes on stdin: a Windows path gets mangled by Git/WSL bash, and text mode would add \r
    subprocess.run(["bash", "-n"], input=SCRIPT.read_bytes(), check=True)


def test_the_script_is_strict_private_and_has_a_fixed_path():
    body = text()
    assert "set -euo pipefail" in body
    assert re.search(r"^umask 077$", body, re.M)
    assert re.search(r"^export PATH=/usr/sbin:/usr/bin:/sbin:/bin$", body, re.M)


def test_the_secret_is_read_hidden_with_a_timeout():
    reads = [l for l in code_lines() if re.search(r"\bread\b.*\bsecret\b", l)]
    assert len(reads) == 1
    assert re.search(r"read -r -s -t \d+", reads[0])


def test_the_secret_is_written_once_and_never_echoed_or_logged():
    uses = [l for l in code_lines() if "$secret" in l or "${secret" in l]
    writes = [l for l in uses if ">>" in l and "$target" in l]
    checks = [l for l in uses if "=~" in l]
    assert len(writes) == 2  # env line or file body: exactly one runs per drop
    assert len(checks) == 1
    assert set(uses) == set(writes) | set(checks), "secret used outside the write and the format check"
    for line in code_lines():
        if "logger" in line or line.lstrip().startswith(("say", "echo")):
            assert "$secret" not in line and "${secret" not in line


def test_the_secret_is_unset_after_use_and_on_a_bad_format():
    assert len(re.findall(r"\bunset secret\b", text())) >= 2


def test_a_filled_slot_is_never_overwritten():
    body = text()
    assert re.search(r'grep -q "\^\$\{key\}=" "\$target"', body)
    assert re.search(r'\[ ! -e "\$target" \]', body)


def test_the_target_ends_up_600_and_owned_by_the_slot_owner():
    body = text()
    assert 'chown "$owner:$owner" "$target"' in body
    assert 'chmod 600 "$target"' in body


def test_every_slot_is_complete_and_its_format_is_anchored():
    rows = slots()
    assert rows, "at least one slot"
    names = [r[0] for r in rows]
    assert len(names) == len(set(names))
    for name, kind, target, owner, key, fmt, label in rows:
        assert re.fullmatch(r"[a-z][a-z0-9-]*", name)
        assert kind in {"env", "file"}
        assert target.startswith("/")
        assert re.fullmatch(r"[a-z][a-z0-9_-]*", owner)
        assert (kind == "env") == bool(key)
        assert fmt.startswith("^") and fmt.endswith("$")
        assert label


def test_the_readme_key_line_is_locked_to_the_drop():
    line = next(l for l in README.read_text(encoding="utf-8").splitlines()
                if "secret-drop-phone" in l and "ssh-ed25519" in l)
    assert line.lstrip("` ").startswith('restrict,pty,command="sudo -n /usr/local/sbin/secret-drop"')
