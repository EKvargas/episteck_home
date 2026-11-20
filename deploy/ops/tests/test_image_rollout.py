import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT_REL = "deploy/ops/image-rollout.sh"
SCRIPT = (REPO / SCRIPT_REL).read_text(encoding="utf-8")
BASH = shutil.which("bash")
needs_bash = pytest.mark.skipif(BASH is None, reason="bash not available")
PLACEHOLDER = "REPLACE_WITH_COMMIT_SHA"


def run_bash(code, **kw):
    # script path stays repo-relative with cwd at the repo root (Git Bash breaks on Windows paths)
    return subprocess.run([BASH, "-c", code], cwd=REPO, capture_output=True, text=True, **kw)


@needs_bash
def test_script_is_valid_strict_bash_that_starts_at_root():
    r = subprocess.run([BASH, "-n", SCRIPT_REL], cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "set -euo pipefail" in SCRIPT
    assert re.search(r"^cd /$", SCRIPT, re.M)


def test_components_accounts_and_restart_order():
    assert SCRIPT.index("home-bff-mint home-bff") >= 0
    for account in ("svc-nutrition", "svc-home-bff", "svc-home-hub"):
        assert account in SCRIPT
    assert "nutrition nutrition-mcp" in SCRIPT
    assert "localhost/episteck-nutrition" in SCRIPT
    assert "localhost/episteck-home-bff" in SCRIPT
    assert "localhost/episteck-home-hub" in SCRIPT


def test_every_repo_template_has_exactly_one_placeholder():
    expected = {
        "deploy/nutrition": ["nutrition.container", "nutrition-mcp.container"],
        "deploy/home-bff": ["home-bff.container", "home-bff-mint.container"],
        "deploy/home-hub": ["svc-home-hub.container"],
    }
    for d, names in expected.items():
        for n in names:
            text = (REPO / d / n).read_text(encoding="utf-8")
            assert text.count(PLACEHOLDER) == 1, f"{d}/{n}"
            assert f"{d}/{n}" in SCRIPT or n in SCRIPT


@needs_bash
def test_render_replaces_only_the_image_line(tmp_path):
    sha = "a" * 40
    out = tmp_path / "out.container"
    tpl = "deploy/nutrition/nutrition.container"
    r = run_bash(f"source {SCRIPT_REL} --lib && render_quadlet {tpl} {sha} {out.as_posix()}")
    assert r.returncode == 0, r.stderr
    old = (REPO / tpl).read_text(encoding="utf-8").splitlines()
    new = out.read_text(encoding="utf-8").splitlines()
    assert len(old) == len(new)
    diff = [(a, b) for a, b in zip(old, new) if a != b]
    assert len(diff) == 1
    assert diff[0][1] == f"Image=localhost/episteck-nutrition:{sha}"
    assert PLACEHOLDER not in out.read_text(encoding="utf-8")


@needs_bash
def test_render_refuses_a_template_without_or_with_two_placeholders(tmp_path):
    none = tmp_path / "none.container"
    none.write_text("[Container]\nImage=localhost/x:1\n")
    two = tmp_path / "two.container"
    two.write_text(f"[Container]\nImage=a:{PLACEHOLDER}\nImage=b:{PLACEHOLDER}\n")
    for t in (none, two):
        out = tmp_path / "o.container"
        r = run_bash(f"source {SCRIPT_REL} --lib && render_quadlet {t.as_posix()} {'b' * 40} {out.as_posix()}")
        assert r.returncode != 0
        assert not out.exists()


def test_apply_refuses_a_short_sha_and_backs_up_before_writing():
    assert "^[0-9a-f]{40}$" in SCRIPT
    apply = SCRIPT[SCRIPT.index("step_apply()"):SCRIPT.index("step_verify()")]
    assert apply.index("need_sha") < apply.index("image exists")
    assert apply.index("BACKUP_ROOT") < apply.index("install -m")
    assert apply.index("sha256sum") < apply.index("install -m")
    assert "/var/backups/episteck" in SCRIPT
    assert apply.index("rollback_cmd") < apply.index("install -m")
    assert "diff -u" in apply
    assert "reload_restart" in apply and "rollback" in apply
    assert "daemon-reload" in SCRIPT


@needs_bash
def test_need_sha_rejects_short_and_uppercase():
    for bad in ("abc123", "A" * 40, "main", ""):
        r = run_bash(f"source {SCRIPT_REL} --lib && need_sha '{bad}'")
        assert r.returncode != 0, bad
    r = run_bash(f"source {SCRIPT_REL} --lib && need_sha {'c' * 40}")
    assert r.returncode == 0


def test_nutrition_verify_requires_bls_in_both_containers():
    v = SCRIPT[SCRIPT.index("verify_nutrition()"):SCRIPT.index("verify_home_bff()")]
    assert "_build_provider().search_food('Apfel')[0].food_id" in v
    assert "printenv BLS_DB" in v
    assert "bls:" in v and "FAIL" in v
    assert "nutrition-mcp" in v and "PSN-00013" in v and "9930" in v and "9931" in v
    assert "for c in nutrition nutrition-mcp" in v


def test_never_prints_environment_files():
    for pat in (r"(cat|sed|head|tail|less|grep)\b[^\n]*(\.env\b|EnvironmentFile|secrets/)",):
        assert not re.search(pat, SCRIPT), pat
    assert "printenv BLS_DB" in SCRIPT and "printenv\n" not in SCRIPT
    assert re.search(r"</dev/null", SCRIPT)


def _sandbox(tmp_path, restart_fails):
    sha = "d" * 40
    qdir = tmp_path / "q"
    qdir.mkdir()
    build = tmp_path / "build" / sha
    for t in ("deploy/home-bff/home-bff-mint.container", "deploy/home-bff/home-bff.container"):
        (build / t).parent.mkdir(parents=True, exist_ok=True)
        text = (REPO / t).read_text(encoding="utf-8")
        (build / t).write_text(text, encoding="utf-8", newline="\n")
        live = text.replace(PLACEHOLDER, "oldsha") + "NodeOnly=1\n"
        (qdir / Path(t).name).write_text(live, encoding="utf-8", newline="\n")
    stub = f"""
export TMPDIR={tmp_path.as_posix()}
source {SCRIPT_REL} --lib
load_component home-bff
QDIR={qdir.as_posix()}; BUILD_BASE={(tmp_path / "build").as_posix()}; BACKUP_ROOT={(tmp_path / "bk").as_posix()}
sleep() {{ :; }}; own() {{ :; }}
install() {{ if [ "$1" = -d ]; then mkdir -p "${{@: -1}}"; else command install "$@"; fi; }}
as_account() {{
  shift
  case "$*" in
    *"image exists"*) return 0 ;;
    *"restart home-bff-mint"*) {"return 1" if restart_fails else "return 0"} ;;
  esac
  return 0
}}
"""
    return sha, qdir, stub


@needs_bash
def test_apply_prints_rollback_command_when_a_restart_fails(tmp_path):
    sha, qdir, stub = _sandbox(tmp_path, True)
    r = run_bash(stub + f"step_apply {sha}")
    assert r.returncode != 0
    assert r.stdout.count("rollback /") + r.stdout.count("rollback C:") + r.stdout.count("rollback ") >= 2
    assert "== rollback command" in r.stdout
    assert "FAIL: a restart failed" in r.stdout


@needs_bash
def test_apply_success_prints_rollback_command_and_exits_zero(tmp_path):
    sha, qdir, stub = _sandbox(tmp_path, False)
    r = run_bash(stub + f"step_apply {sha}")
    assert r.returncode == 0, r.stderr
    assert "home-bff rollback" in r.stdout
    assert f"Image=localhost/episteck-home-bff:{sha}" in (qdir / "home-bff.container").read_text()


@needs_bash
def test_preview_writes_nothing_and_prints_the_diff(tmp_path):
    sha, qdir, stub = _sandbox(tmp_path, False)
    before = {p.name: p.read_bytes() for p in qdir.iterdir()}
    r = run_bash(stub + f"step_preview {sha}")
    assert r.returncode == 0, r.stderr
    assert "diff -u home-bff.container" in r.stdout
    assert "-NodeOnly=1" in r.stdout
    assert {p.name: p.read_bytes() for p in qdir.iterdir()} == before
    assert not (tmp_path / "bk").exists()
