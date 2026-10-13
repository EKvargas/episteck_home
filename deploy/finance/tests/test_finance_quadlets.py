"""Static checks on the svc-finance deploy artifacts (nothing here touches a node).

Run from the repo root:  python -m pytest deploy/finance/tests -q
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
DEPLOY = ROOT / "deploy" / "finance"
UNITS = ("finance-api.container", "finance-mcp.container", "finance-sync.container")
MAX_SYNCS_PER_DAY = 2  # each sync = balances + transactions = 2 data requests; PSD2 cap is 4


def parse(path: Path) -> dict[str, dict[str, list[str]]]:
    """Minimal systemd/Quadlet parser that keeps repeated keys (Environment=, Volume=)."""
    sections: dict[str, dict[str, list[str]]] = {}
    current = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = sections.setdefault(line[1:-1], defaultdict(list))
            continue
        key, _, value = line.partition("=")
        current[key.strip()].append(value.strip())
    return sections


def unit(name):
    return parse(DEPLOY / name)


def values(name, section, key):
    return unit(name).get(section, {}).get(key, [])


@pytest.mark.parametrize("name", UNITS)
def test_all_units_use_the_same_pinned_image(name):
    images = {values(n, "Container", "Image")[0] for n in UNITS}
    assert len(images) == 1
    image = images.pop()
    assert image.startswith("localhost/episteck-finance:")
    assert not image.endswith(":latest")


def test_api_and_mcp_publish_loopback_only_on_their_ports():
    assert values("finance-api.container", "Container", "PublishPort") == ["127.0.0.1:9935:9935"]
    assert values("finance-mcp.container", "Container", "PublishPort") == ["127.0.0.1:9936:9936"]
    assert values("finance-sync.container", "Container", "PublishPort") == []
    for name in UNITS:
        assert "0.0.0.0" not in (DEPLOY / name).read_text(encoding="utf-8").replace("--host 0.0.0.0", "")


def test_exec_commands():
    assert values("finance-api.container", "Container", "Exec") == [
        "uvicorn app.main:app --host 0.0.0.0 --port 9935"]
    assert values("finance-mcp.container", "Container", "Exec") == ["python -m app.mcp.server"]
    assert values("finance-sync.container", "Container", "Exec") == ["python -m app.sync"]


@pytest.mark.parametrize("name", ["finance-api.container", "finance-mcp.container"])
def test_request_serving_units_see_only_the_pepper_never_provider_secrets(name):
    mounts = values(name, "Container", "Volume")
    assert not any(m.split(":")[0].rstrip("/").endswith("/secrets") for m in mounts)
    pepper = [m for m in mounts if m.split(":")[0].endswith("/secrets/pepper")]
    assert len(pepper) == 1 and ":ro" in pepper[0]
    assert values(name, "Container", "Environment").count("FINANCE_PEPPER_FILE=/run/secrets/pepper") == 1
    assert not any(e.startswith("FINANCE_SECRETS_DIR") for e in values(name, "Container", "Environment"))


HOME_AUTH = "/srv/episteck/services/finance/secrets/home-auth.env"


@pytest.mark.parametrize("name", ["finance-api.container", "finance-mcp.container"])
def test_request_serving_units_load_the_home_credential_as_a_plain_env_file(name):
    # Quadlet hands EnvironmentFile to `podman --env-file`, which has no optional "-" prefix:
    # "-/srv/..." is read as a relative path and the container never starts.
    assert HOME_AUTH in values(name, "Container", "EnvironmentFile")
    assert not any(v.startswith("-") for v in values(name, "Container", "EnvironmentFile"))


def test_sync_unit_never_loads_the_home_credential():
    assert HOME_AUTH not in values("finance-sync.container", "Container", "EnvironmentFile")


def test_sync_unit_gets_the_secrets_directory_read_only_and_data_read_write():
    mounts = values("finance-sync.container", "Container", "Volume")
    secrets = [m for m in mounts if m.split(":")[0].rstrip("/").endswith("/secrets")]
    assert len(secrets) == 1 and ":ro" in secrets[0]
    data = [m for m in mounts if m.split(":")[0].rstrip("/").endswith("/data")]
    assert len(data) == 1 and ":ro" not in data[0]


@pytest.mark.parametrize("name", UNITS)
def test_hardening_and_memory_limit(name):
    c = unit(name)["Container"]
    assert c["NoNewPrivileges"] == ["true"]
    assert c["DropCapability"] == ["ALL"]
    assert c["ReadOnly"] == ["true"]
    assert any("--memory=" in a for a in c["PodmanArgs"])


def test_sync_unit_is_a_one_shot_with_no_install_section():
    parsed = unit("finance-sync.container")
    assert "Install" not in parsed
    assert parsed["Service"]["Type"] == ["oneshot"]
    assert parsed["Service"]["Restart"] == ["no"]


def test_api_and_mcp_restart_and_start_at_boot():
    for name in ("finance-api.container", "finance-mcp.container"):
        parsed = unit(name)
        assert parsed["Service"]["Restart"] == ["always"]
        assert parsed["Install"]["WantedBy"] == ["default.target"]


def test_timer_triggers_the_sync_service_at_most_twice_a_day():
    timer = parse(DEPLOY / "finance-sync.timer")
    assert timer["Timer"]["Unit"] == ["finance-sync.service"]
    assert timer["Timer"]["Persistent"] == ["true"]
    assert timer["Install"]["WantedBy"] == ["timers.target"]
    calendar = timer["Timer"]["OnCalendar"]
    assert len(calendar) == 1
    hours = re.search(r"\*-\*-\*\s+([\d:,]+)$", calendar[0]).group(1).split(",")
    assert 1 <= len(hours) <= MAX_SYNCS_PER_DAY


def test_no_secret_material_in_any_deploy_artifact():
    pattern = re.compile(r"BEGIN [A-Z ]*PRIVATE KEY|://[^/\s:@]+:[^/\s@]+@|Bearer ey|password\s*=\s*\S", re.I)
    for path in [*DEPLOY.glob("finance-*"), ROOT / "services" / "finance" / "Dockerfile"]:
        assert not pattern.search(path.read_text(encoding="utf-8")), path.name


def test_dockerfile_installs_the_package_and_copies_no_secrets():
    text = (ROOT / "services" / "finance" / "Dockerfile").read_text(encoding="utf-8")
    assert text.startswith("FROM python:3.11-slim")
    assert "pip install" in text and "COPY services/finance/app" in text
    assert not re.search(r"COPY .*(secret|\.env|\.pem|\.sqlite)", text, re.I)


def test_ports_are_documented_in_the_deployment_table():
    deployment = (ROOT / "docs" / "architecture" / "DEPLOYMENT.md").read_text(encoding="utf-8")
    assert "127.0.0.1:9935" in deployment and "127.0.0.1:9936" in deployment
    assert "finance.sqlite" in deployment  # backup entry


# --- bring-up script and runbook ---------------------------------------------------------
import shutil
import subprocess

BRINGUP = DEPLOY / "bringup.sh"
RUNBOOK = ROOT / "docs" / "runbooks" / "finance-i1-nuremberg-bringup.md"


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_bringup_script_is_syntactically_valid():
    result = subprocess.run(["bash", "-n", BRINGUP.relative_to(ROOT).as_posix()], cwd=ROOT,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_bringup_script_is_strict_and_has_every_step_and_a_rollback():
    text = BRINGUP.read_text(encoding="utf-8")
    assert "set -euo pipefail" in text
    for step in ("preflight", "create-user", "create-dirs", "build", "install", "enable-timer",
                 "verify", "apply-backup", "rollback-units", "rollback-backup", "purge"):
        assert re.search(rf"^\s*{step}\)", text, re.M), step


def test_bringup_script_never_prints_or_pipes_secrets():
    text = BRINGUP.read_text(encoding="utf-8")
    assert not re.search(r"cat\s+\S*(secrets|restic|\.env)", text)
    assert "| sh" not in text and "| bash" not in text
    assert "rm -rf" not in text.replace("rm -rf --one-file-system", "")  # purge is explicit


def test_purge_requires_an_explicit_confirmation_argument():
    text = BRINGUP.read_text(encoding="utf-8")
    assert "--i-understand-this-deletes-financial-data" in text


def test_runbook_marks_secret_steps_as_own_terminal_and_has_rollbacks():
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "OWN TERMINAL" in text and "never through the chat" in text.lower()
    assert text.count("Rollback") >= 4
    assert "9935" in text and "9936" in text


PROVISION = DEPLOY / "provision-home-credentials.sh"


def test_provision_script_is_syntactically_valid():
    import subprocess
    import shutil
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash not available")
    subprocess.run([bash, "-n", str(PROVISION)], check=True)


def test_provision_script_never_prints_the_credential():
    text = PROVISION.read_text(encoding="utf-8")
    assert "set -euo pipefail" in text
    # The secret and key only ever travel through the ssh pipe into the 600 file.
    assert not re.search(r"echo[^\n]*(secret|\$key)", text)
    assert "| $NODE_SSH" in text and "umask 077" in text
    assert "--rotate" in text and "refusing" in text
