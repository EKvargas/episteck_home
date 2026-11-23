"""Static checks on Ana's Hermes installer, her media purge units and her gateway drop-in
(Nutrition R1, Task 9). Nothing here touches a node: bash runs only `-n`, the argument checks
that stop before any change, and the small parsers that read .env, the login log and the tool
list, on sample files.

Run from the repo root:
    python -m pytest deploy/hermes/tests -q
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
HERMES = ROOT / "deploy" / "hermes"
ANA = HERMES / "home-agent-ana"
INSTALL_REL = "deploy/hermes/install-home-agent-ana.sh"
INSTALL = ROOT / INSTALL_REL
CONFIG = ANA / "config-ana.yaml"
SKILL = HERMES / "skills" / "olin-nutrition" / "SKILL.md"
UNITS = ANA / "systemd"
SERVICE = UNITS / "ana-media-purge.service"
TIMER = UNITS / "ana-media-purge.timer"
DROPIN = UNITS / "hermes-gateway-memory.conf"

HERMES_COMMIT = "a89c1e1135a97dc1262926d93933357fbacd2bd2"
INSTALLER_SHA256 = "38547c22f4dd2224ba68a13bc3479309abb17e295b2a2ef79c2d1b8293bd822e"
SKILLS_ROOT = "/etc/episteck/hermes-ana/skills"
OWNER_SKILLS_ROOT = "/etc/episteck/hermes/skills"
GW = "http://127.0.0.1:9937"
CRON_PROMPT = (
    'Scheduled evening check-in. Follow the skill section "Evening check-in (cron)".\n'
    "1. Call mcp__home__whoami once, then mcp__nutrition__get_day_summary once with "
    "subject_person_id set to its actor_person_id and no date. Call no other tool and save "
    "nothing.\n"
    "2. If day_status is COMPLETE, or a call returns an error other than an access refusal, "
    "your whole final response is exactly [SILENT].\n"
    "3. If a call returns an access refusal, reply with the permission line from the skill "
    "and stop.\n"
    "4. Otherwise write ONE short message in Spanish as that section says. It names the day "
    "it is about as day and month in Spanish words, no weekday (for example 20 de noviembre), "
    "taken from the date of get_day_summary, and ends with exactly: ¿Eso fue todo hoy?"
)
MEDIA_DIRS = ("%h/.hermes/cache/audio", "%h/.hermes/audio_cache", "%h/.hermes/cache/images",
              "%h/.hermes/image_cache")


def _find_bash():
    """Git for Windows bash on Windows (System32 bash.exe is WSL and cannot see C:/ paths)."""
    if sys.platform != "win32":
        return shutil.which("bash")
    git = shutil.which("git")
    if git:
        root = Path(git).resolve().parent.parent  # <git>/cmd/git.exe or <git>/bin/git.exe
        for rel in ("bin/bash.exe", "usr/bin/bash.exe"):
            cand = root / rel
            if cand.is_file():
                return str(cand)
    return None


BASH = _find_bash()
needs_bash = pytest.mark.skipif(BASH is None, reason="no Git for Windows bash (or bash on PATH) found")


def _text() -> str:
    return INSTALL.read_text(encoding="utf-8")


def _code_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]


def _case(text: str, step: str) -> str:
    start = re.search(rf"^  {re.escape(step)}\)", text, re.M).start()
    return text[start:text.index("\n    ;;", start)]


def _function(text: str, name: str) -> str:
    match = re.search(rf"^{re.escape(name)}\(\) \{{.*?^\}}$", text, re.M | re.S)
    assert match, f"{name}() not found"
    return match.group(0)


def _cron_prompt(text: str) -> str:
    return re.search(r"^CRON_PROMPT='([^']*)'$", text, re.M | re.S).group(1)


def _run_script(*args: str) -> subprocess.CompletedProcess:
    # The script goes in on stdin, as on the node (`sudo -n bash -s -- <step> [arg]`).
    return subprocess.run([BASH, "-s", "--", *args], input=INSTALL.read_bytes(), cwd=ROOT,
                          capture_output=True)


def _run_function(tmp_path: Path, source: str, call: str) -> str:
    result = subprocess.run([BASH, "-c", f"{source}\n{call}"], cwd=tmp_path, capture_output=True)
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    return result.stdout.decode("utf-8")


def _unit(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")]


# --- the script as a whole -------------------------------------------------------------------

@needs_bash
def test_script_is_valid_strict_bash_that_starts_at_root():
    result = subprocess.run([BASH, "-n", INSTALL_REL], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    text = _text()
    assert text.startswith("#!/bin/bash\n")
    assert "set -euo pipefail" in text and "set -x" not in text
    assert re.search(r"^cd /$", text, re.M)
    for step in ("preflight", "user", "install", "configure", "env", "telegram", "login",
                 "login-check", "gateway", "cron", "purge", "verify", "stop", "rollback-config",
                 "remove"):
        assert re.search(rf"^  {re.escape(step)}\)", text, re.M), step
    # Every agent command runs through runuser with the user bus set and stdin pinned.
    helper = _function(text, "as_user")
    for part in ("runuser -u", '"HOME=/home/$who"', '"XDG_RUNTIME_DIR=/run/user/$u"',
                 '"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$u/bus"', '"$@" </dev/null'):
        assert part in helper, part
    assert re.search(r'^as_agent\(\) \{ as_user "\$AGENT" "\$@"; \}$', text, re.M)
    for line in _code_lines(text):
        assert not re.search(r"\brunuser\b", line) or "runuser -u \"$who\"" in line, line
    unknown = _run_script("no-such-step")
    assert unknown.returncode == 2 and b"usage:" in unknown.stderr


def test_hermes_is_pinned_and_the_installer_is_hash_checked_before_it_runs():
    text = _text()
    assert re.search(r"^AGENT=home-agent-ana$", text, re.M)
    assert re.search(rf"^HERMES_COMMIT={HERMES_COMMIT}$", text, re.M)
    assert re.search(r"^INSTALLER_URL=https://raw\.githubusercontent\.com/NousResearch/hermes-agent/"
                     r"\$HERMES_COMMIT/scripts/install\.sh$", text, re.M)
    assert re.search(rf"^INSTALLER_SHA256={INSTALLER_SHA256}$", text, re.M)
    install = _case(text, "install")
    run = install.index('bash "$f" --commit "$HERMES_COMMIT" --skip-setup --skip-browser '
                        '--skip-computer-use --no-skills')
    download = install.index('curl -fsSL --max-time 120 -o "$f" "$INSTALLER_URL"')
    compare = install.index('if [ "$sum" != "$INSTALLER_SHA256" ]; then')
    assert download < install.index('sha256sum "$f"') < compare < run
    assert "exit 1" in install[compare:run]  # a mismatch stops before the run
    assert install.index("check_hermes") > run
    check = _function(text, "check_hermes")
    assert "*v0.21.2*" in check and "--version" in check
    assert 'rev-parse HEAD' in check and '"$HERMES_COMMIT"' in check
    preflight = _case(text, "preflight")
    assert 'sha256sum "$OWNER_HERMES/hermes-agent/scripts/install.sh"' in preflight
    assert '"$INSTALLER_SHA256"' in preflight
    assert 'as_user "$OWNER" git -C "$OWNER_HERMES/hermes-agent" rev-parse HEAD' in preflight
    assert '"$HERMES_COMMIT"' in preflight
    assert not re.search(r"\|\s*(ba)?sh\b", text)  # never curl | bash


def test_agent_uses_only_port_9937_and_no_finance():
    text = _text()
    assert re.search(rf"^GW={re.escape(GW)}$", text, re.M)
    ports = re.findall(r"127\.0\.0\.1:(\d+)", text)
    assert set(ports) == {"9937", "9934"}
    lines = [line for line in text.splitlines() if "9934" in line]
    assert len(lines) == 1, lines
    verify = _case(text, "verify")
    assert lines[0] in verify and "--max-time 5" in lines[0] and "|| rc=$?" in lines[0]
    after = verify[verify.index(lines[0]):]
    assert 'if [ "$rc" = 28 ]; then ok' in after
    assert f'"$GW/gateway/home/"' in verify
    config = CONFIG.read_text(encoding="utf-8")
    assert f"url: {GW}/gateway/home/" in config and f"url: {GW}/gateway/nutrition/" in config
    for path in (INSTALL, SERVICE, TIMER, DROPIN, CONFIG):
        body = path.read_text(encoding="utf-8")
        assert "finance" not in body.lower(), path.name
        if path is not INSTALL:
            assert "9934" not in body, path.name


def test_the_owners_agent_is_only_read():
    text = _text()
    assert re.search(r"^OWNER=home-agent$", text, re.M)
    uses = [line for line in _code_lines(text)
            if re.search(r"\$OWNER\b|\$OWNER_|/home/home-agent/", line)]
    assert uses
    for line in uses:
        if 'as_user "$OWNER"' in line:
            assert ("rev-parse HEAD" in line
                    or "systemctl --user show hermes-gateway.service -p NRestarts --value" in line), line
        bare = (line.replace('>> "$ENVF"', "").replace("2>/dev/null", "")
                .replace("scripts/install.sh", ""))
        assert not re.search(r"\b(restart|stop|disable|enable|start|install|cp|mv|rm|chmod|chown|"
                             r"sed|tee|truncate|kill|pkill|userdel|usermod)\b", bare), line
        assert ">" not in bare, line
    # The two Kimi lines go root-to-root into Ana's .env: copied, never printed or held in a variable.
    env = _case(text, "env")
    assert 'grep -m 1 "^$key=" "$OWNER_ENV" >> "$ENVF"' in env
    assert "for key in KIMI_API_KEY KIMI_BASE_URL; do" in env
    assert not re.search(r'=\s*"\$\(grep[^c]*"\$OWNER_ENV"', text)


def test_ana_skills_root_is_not_the_owners():
    text = _text()
    assert re.search(rf"^SKILLS_ROOT={re.escape(SKILLS_ROOT)}$", text, re.M)
    assert re.search(r"^SKILL_DIR=\$SKILLS_ROOT/olin-nutrition$", text, re.M)
    assert OWNER_SKILLS_ROOT not in text and "/etc/episteck/hermes/" not in text
    yaml = pytest.importorskip("yaml")
    assert yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["skills"] == {"external_dirs": SKILLS_ROOT}
    configure = _case(text, "configure")
    assert 'install -d -m 755 -o root -g root /etc/episteck/hermes-ana "$SKILLS_ROOT" "$SKILL_DIR"' in configure
    assert ('install -m 644 -o root -g root "$SHARED_SKILL" '
            '"$SKILL_DIR/SKILL.md"') in configure
    verify = _case(text, "verify")
    assert 'as_agent test -w "$SKILL_DIR/SKILL.md"' in verify
    assert 'cmp -s "$SHARED_SKILL" "$SKILL_DIR/SKILL.md"' in verify


@needs_bash
def test_only_skills_and_clarify_remain_on_telegram_and_cron(tmp_path):
    text = _text()
    configure = _case(text, "configure")
    assert "for p in telegram cron; do" in configure
    assert "skills|clarify) ;;" in configure
    assert 'as_agent "$HERMES" tools disable "${extra[@]}" --platform "$p"' in configure
    assert 'as_agent "$HERMES" tools list --platform "$p"' in configure
    assert configure.index("tools disable") > configure.index('agent_config set "$(< "$ANA_SRC/config-ana.yaml")"')
    for step in ("configure", "verify"):
        body = _case(text, step)
        assert '"$(enabled_toolsets "$p" || true)"' in body
        assert 'if [ "$now" = "clarify skills" ]; then' in body
    assert "for p in telegram cron; do" in _case(text, "verify")
    # The parser reads `hermes tools list` output (Hermes 0.21.2 _print_tools_list), colours and all.
    sample = ("Built-in toolsets (telegram):\n"
              "  \x1b[32m✓ enabled\x1b[0m  web  \x1b[2m🔍 Web Search & Scraping\x1b[0m\n"
              "  \x1b[31m✗ disabled\x1b[0m  browser  \x1b[2m🌐 Browser Automation\x1b[0m\n"
              "  ✓ enabled  skills  📚 Skills\n"
              "  ✓ enabled  terminal  💻 Terminal & Processes\n"
              "  ✓ enabled  clarify  ❓ Clarifying Questions\n"
              "\nPlugin toolsets (telegram):\n  ✓ enabled  extra_plugin  🔌 Plugin\n"
              "\nMCP servers:\n  ✓ enabled  home  all tools enabled\n")
    (tmp_path / "list.txt").write_bytes(sample.encode("utf-8"))
    parsed = _run_function(tmp_path, _function(text, "parse_enabled"), "parse_enabled < list.txt")
    assert parsed == "clarify extra_plugin skills terminal web\n"
    helper = _function(text, "enabled_toolsets")
    assert 'tools list --platform "$1"' in helper and "parse_enabled" in helper


@needs_bash
def test_checkin_runs_in_berlin_time_and_refuses_otherwise():
    text = _text()
    yaml = pytest.importorskip("yaml")
    assert yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["timezone"] == "Europe/Berlin"
    cron = _case(text, "cron")
    assert "re='^([01][0-9]|2[0-3]):[0-5][0-9]$'" in cron
    assert cron.index("[[ $hm =~ $re ]]") < cron.index("need_src")
    berlin = cron.index('if [ "$tz" != Europe/Berlin ]; then')
    assert cron.index('tz="$(agent_config tz)"') < berlin < cron.index("cron_remove") < cron.index("cron create")
    assert "exit 1" in cron[berlin:cron.index("cron_remove")]
    assert '"$MM $HH * * *" "$CRON_PROMPT"' in cron
    assert 'HH="${hm%%:*}"' in cron and 'MM="${hm##*:}"' in cron
    assert cron.count("cron create") == 1  # re-running replaces the job, never adds a second
    for bad in ("24:00", "7:30", "21:60", "2130", ""):
        result = _run_script("cron", bad)
        assert result.returncode == 2, (bad, result.stderr)
        assert b"usage: cron <HH:MM>" in result.stderr


def test_checkin_failures_stay_local_and_delivery_is_mirrored():
    cron = _case(_text(), "cron")
    create = cron[cron.index("cron create"):]
    for part in ('--name "$CRON_NAME"', "--deliver telegram", "--failure-deliver local",
                 "--skill olin-nutrition"):
        assert part in create, part
    assert re.search(r"^CRON_NAME=olin-nutrition-checkin$", _text(), re.M)
    yaml = pytest.importorskip("yaml")
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert config["cron"] == {"catch_up_missed": False, "mirror_delivery": True}


def test_checkin_prompt_names_a_skill_section_that_exists():
    text = _text()
    prompt = _cron_prompt(text)
    assert prompt == CRON_PROMPT
    skill = SKILL.read_text(encoding="utf-8")
    assert "\n## Evening check-in (cron)\n" in skill
    assert '"Evening check-in (cron)"' in prompt
    assert prompt.endswith("¿Eso fue todo hoy?") and "¿Eso fue todo hoy?" in skill
    required = re.search(r"requires_tools: \[(.*?)\]", skill, re.S).group(1)
    for tool in re.findall(r"mcp__\w+", prompt):
        assert tool in required, tool
    # The job list is searched for the job name: the prompt must not contain it.
    assert "olin-nutrition-checkin" not in prompt
    cron = _case(text, "cron")
    assert '[ -f "$SKILL_DIR/SKILL.md" ]' in cron
    assert 'cmp -s "$SHARED_SKILL" "$SKILL_DIR/SKILL.md"' in cron
    assert "grep -q '^## Evening check-in (cron)$' \"$SKILL_DIR/SKILL.md\"" in cron
    assert cron.index("grep -q '^## Evening check-in") < cron.index("cron create")


def test_memory_is_off_capped_and_preflighted():
    text = _text()
    yaml = pytest.importorskip("yaml")
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert config["memory"] == {"memory_enabled": False, "user_profile_enabled": False}
    assert _unit(DROPIN) == ["[Service]", "MemoryMax=900M"]
    assert re.search(r"^MIN_AVAILABLE_MB=900$", text, re.M)
    assert re.search(r"^MEMORY_MAX_BYTES=\$\(\(900 \* 1024 \* 1024\)\)", text, re.M)
    check = _function(text, "check_memory")
    assert '[ "$mb" -ge "$MIN_AVAILABLE_MB" ]' in check and "/proc/meminfo" in _function(text, "mem_available_mb")
    assert "check_memory" in _case(text, "preflight")
    install = _case(text, "install")
    assert install.index("check_memory") < install.index("curl")
    gateway = _case(text, "gateway")
    # The cap is in place before the first start.
    assert 'gateway install --no-start-now' in gateway
    assert (gateway.index("gateway install --no-start-now")
            < gateway.index('"$UNIT_DIR/hermes-gateway.service.d/memory.conf"')
            < gateway.index("daemon-reload")
            < gateway.index("enable --now hermes-gateway.service"))
    report = _function(text, "gateway_report")
    assert "memory.max" in report and '"$MEMORY_MAX_BYTES"' in report
    assert "gateway_report" in gateway and "gateway_report" in _case(text, "verify")
    assert "free -m" in _case(text, "verify")


@needs_bash
def test_secrets_are_never_printed(tmp_path):
    text = _text()
    secret = re.compile(r'\$ENVF|\$OWNER_ENV|\$LOGIN_LOG|\.env\b|auth\.json|codex-login\.log')
    for line in _code_lines(text):
        if not secret.search(line):
            continue
        assert not re.search(r"\b(cat|less|more|head|tail|tee|xxd|od|strings|base64)\b", line), line
        if re.search(r"\bgrep\b", line):
            assert re.search(r"grep -[a-zA-Z]*[qc]", line) or line.rstrip().endswith('>> "$ENVF"'), line
        if re.search(r"\bsed\b", line):
            assert "sed -i" in line, line
        if re.search(r"\bawk\b", line):
            assert re.search(r"awk -F= .*\$ENVF|awk '/Open this URL\|Enter this code/", line), line
        if re.search(r"\b(echo|printf|ok|bad)\b", line):
            # Only key names and counts are substituted into a message, never a file's content.
            assert set(re.findall(r"\$\((\w+)", line)) <= {"env_names", "allowed_users_count"}, line
    # Files that hold secrets are created private, as the agent.
    assert 'install -m 600 -o "$AGENT" -g "$AGENT" /dev/null "$ENVF"' in _case(text, "env")
    assert 'install -m 600 -o "$AGENT" -g "$AGENT" /dev/null "$LOGIN_LOG"' in _case(text, "login")
    assert "PYTHONUNBUFFERED=1" in _case(text, "login")
    # Key names and counts come out of .env, never a value.
    (tmp_path / "sample.env").write_bytes(
        b"# a comment with ghp_COMMENTSECRET\nKIMI_API_KEY=sk-kimi-SECRETVALUE\n"
        b"TELEGRAM_BOT_TOKEN=123456789:AAH-SECRET_TOKEN_abcdefghijklmnopqrst\n"
        b"TELEGRAM_ALLOWED_USERS=1234567\nKIMI_BASE_URL=https://example.invalid/v1\n")
    helpers = _function(text, "env_names") + "\n" + _function(text, "allowed_users_count")
    names = _run_function(tmp_path, helpers, "ENVF=sample.env; env_names; allowed_users_count")
    assert names == ("KIMI_API_KEY KIMI_BASE_URL TELEGRAM_ALLOWED_USERS TELEGRAM_BOT_TOKEN\n1\n")
    assert "SECRET" not in names and "1234567" not in names
    # The login log is shown only as its URL line and its code line.
    (tmp_path / "codex-login.log").write_bytes(
        b"Signing in to OpenAI Codex...\nTo continue, follow these steps:\n\n"
        b"  1. Open this URL in your browser:\n     \x1b[94mhttps://auth.openai.com/codex/device\x1b[0m\n\n"
        b"  2. Enter this code:\n     \x1b[94mABCD-1234\x1b[0m\n\n"
        b"Waiting for sign-in... (press Ctrl+C to cancel)\naccess_token=eyJSECRET refresh=SECRET2\n")
    shown = _run_function(tmp_path, _function(text, "login_lines"),
                          "LOGIN_LOG=codex-login.log; login_lines")
    assert shown == "https://auth.openai.com/codex/device\nABCD-1234\n"


_STUB_CONFIG = '''\
"""Stand-in for Hermes 0.21.2 hermes_cli.config: raw read, merged load, save with preserve_keys."""
import copy, json, pathlib
import yaml
PATH = pathlib.Path("config.yaml")
DEFAULTS = {"timezone": "", "memory": {"memory_enabled": True}, "cron": {"mirror_delivery": False}}
def read_raw_config():
    return (yaml.safe_load(PATH.read_text(encoding="utf-8")) or {}) if PATH.exists() else {}
def _merge(base, over):
    out = copy.deepcopy(base)
    for key, value in over.items():
        out[key] = _merge(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else value
    return out
def load_config():
    return _merge(DEFAULTS, read_raw_config())
def save_config(config, *, preserve_keys=None):
    PATH.write_text(yaml.safe_dump(config), encoding="utf-8")
    pathlib.Path("preserved.json").write_text(json.dumps(sorted(map(list, preserve_keys or ()))))
'''


def test_config_keys_go_through_hermes_load_save_and_print_as_paths(tmp_path):
    yaml = pytest.importorskip("yaml")
    program = re.search(r"^CONFIG_PY='([^']*)'$", _text(), re.M | re.S).group(1)
    (tmp_path / "hermes_cli").mkdir()
    (tmp_path / "hermes_cli" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "hermes_cli" / "config.py").write_text(_STUB_CONFIG, encoding="utf-8")
    (tmp_path / "config.yaml").write_text("model:\n  default: other\nkeep_me: 7\n", encoding="utf-8")

    def run(*args):
        result = subprocess.run([sys.executable, "-c", program, *args], cwd=tmp_path,
                                capture_output=True, text=True, encoding="utf-8")
        return result.returncode, result.stdout

    wanted = CONFIG.read_text(encoding="utf-8")
    code, out = run("set", wanted)
    assert code == 0, out
    assert out.splitlines()[0].startswith("changed: model.default, model.provider, fallback_providers,")
    assert out.splitlines()[-1] == "every key is as wanted"
    for value in ("gpt-5.6-sol", "Europe/Berlin", "9937", "kimi"):
        assert value not in out, value  # key paths only, never values
    saved = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    assert saved["keep_me"] == 7 and saved["timezone"] == "Europe/Berlin"
    assert saved["mcp_servers"]["nutrition"]["url"] == f"{GW}/gateway/nutrition/"
    assert ["memory", "memory_enabled"] in yaml.safe_load((tmp_path / "preserved.json").read_text())
    assert run("set", wanted) == (0, "changed: nothing\nevery key is as wanted\n")
    assert run("tz") == (0, "Europe/Berlin\n")
    # check: before the telegram step there is no home channel; after it, all is as wanted.
    code, out = run("check", wanted)
    assert code == 1 and out.endswith("not as wanted: platforms.telegram.home_channel\n")
    channel = ('{"platforms": {"telegram": {"enabled": true, "home_channel": {"platform": "telegram", '
               '"chat_id": "123456789", "user_id": "123456789"}}}}')
    code, out = run("set", channel)
    assert code == 0 and "123456789" not in out
    assert out.startswith("changed: platforms.telegram.home_channel.platform, "
                          "platforms.telegram.home_channel.chat_id, platforms.telegram.home_channel.user_id")
    assert run("check", wanted) == (0, "mcp_servers: home nutrition\nevery key is as wanted\n")
    extra = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    extra["mcp_servers"]["other"] = {"url": "http://127.0.0.1:1/"}
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(extra), encoding="utf-8")
    code, out = run("check", wanted)
    assert code == 1 and "not as wanted: mcp_servers" in out


def test_media_purge_every_ten_minutes_for_media_older_than_ten():
    service = _unit(SERVICE)
    assert "Type=oneshot" in service
    starts = [line for line in service if line.startswith("ExecStart=")]
    assert len(starts) == 2
    media, outputs = starts
    for directory in MEDIA_DIRS:
        assert directory in media, directory
    assert media.startswith("ExecStart=/bin/sh -c '/usr/bin/find ")
    assert "-ignore_readdir_race -type f -mmin +10 -delete 2>/dev/null" in media
    assert outputs.startswith("ExecStart=/bin/sh -c '/usr/bin/find %h/.hermes/cron/output ")
    assert "-ignore_readdir_race -type f -mtime +0 -delete 2>/dev/null" in outputs
    for line in starts:
        assert line.endswith("|| true'") and "$" not in line  # missing dirs never fail the unit
    timer = _unit(TIMER)
    for line in ("[Timer]", "OnBootSec=5min", "OnUnitActiveSec=10min", "WantedBy=timers.target"):
        assert line in timer, line
    purge = _case(_text(), "purge")
    assert ('install -m 644 -o "$AGENT" -g "$AGENT" "$ANA_SRC/systemd/ana-media-purge.service" '
            '"$ANA_SRC/systemd/ana-media-purge.timer" "$UNIT_DIR/"') in purge
    assert "as_agent systemctl --user enable --now ana-media-purge.timer" in purge
    assert "list-timers ana-media-purge.timer" in purge


@needs_bash
def test_media_purge_deletes_old_media_and_keeps_the_rest(tmp_path):
    starts = [line for line in _unit(SERVICE) if line.startswith("ExecStart=")]
    home = tmp_path / "home"
    for rel in (".hermes/cache/audio", ".hermes/audio_cache", ".hermes/cron/output/job"):
        (home / rel).mkdir(parents=True)  # the image caches do not exist: must be ignored
    files = {"old_voice": ".hermes/cache/audio/old.ogg", "new_voice": ".hermes/audio_cache/new.ogg",
             "old_output": ".hermes/cron/output/job/run1.md", "new_output": ".hermes/cron/output/job/run2.md"}
    for rel in files.values():
        (home / rel).write_text("x", encoding="utf-8")
    ages = 'touch -d "20 minutes ago" home/.hermes/cache/audio/old.ogg; ' \
           'touch -d "2 days ago" home/.hermes/cron/output/job/run1.md; ' \
           'touch -d "2 hours ago" home/.hermes/cron/output/job/run2.md'
    subprocess.run([BASH, "-c", ages], cwd=tmp_path, check=True)
    for line in starts:
        command = re.fullmatch(r"ExecStart=/bin/sh -c '(.*)'", line).group(1).replace("%h", "home")
        result = subprocess.run([BASH, "-c", command], cwd=tmp_path, capture_output=True)
        assert result.returncode == 0 and not result.stderr, result.stderr
    assert not (home / files["old_voice"]).exists() and not (home / files["old_output"]).exists()
    assert (home / files["new_voice"]).exists() and (home / files["new_output"]).exists()


@needs_bash
def test_remove_needs_the_exact_word():
    text = _text()
    remove = _case(text, "remove")
    guard = remove.index('if [ "${2:-}" != yes-delete-home-agent-ana ]; then')
    for action in ("do_stop", "tar ", "disable-linger", "userdel -r", "rm -f"):
        assert guard < remove.index(action), action
    assert "exit 2" in remove[guard:remove.index("do_stop")]
    assert remove.index("tar ") < remove.index("userdel -r")
    # ~/.hermes is kept in a root-only (0700) backup directory before the user goes.
    assert remove.index('bk="$(backup_dir)"') < remove.index("tar ")
    assert 'install -d -m 700 "$dir"' in _function(text, "backup_dir")
    assert 'chmod 600 "$bk/hermes.tar.gz"' in remove
    assert "rm -rf" not in text
    for args in (("remove",), ("remove", "yes"), ("remove", "yes-delete-home-agent"),
                 ("remove", "YES-DELETE-HOME-AGENT-ANA")):
        result = _run_script(*args)
        assert result.returncode == 2, args
        assert b"nothing done" in result.stderr, args


@needs_bash
def test_telegram_takes_one_numeric_id_and_sets_the_home_channel():
    text = _text()
    telegram = _case(text, "telegram")
    assert "re='^[0-9]{5,15}$'" in telegram
    assert telegram.index("[[ $tg_id =~ $re ]]") < telegram.index("need_env")
    assert telegram.index("cp -p") < telegram.index("sed -i")  # backed up before the change
    assert "TELEGRAM_ALLOWED_USERS=%s\\nTELEGRAM_HOME_CHANNEL=%s\\n" in telegram
    assert ('"home_channel": {"platform": "telegram", "chat_id": "%s", "user_id": "%s"}'
            in telegram) and '"enabled": true' in telegram
    assert "restart_gateway" in telegram
    for bad in ("", "1234", "12a456", "1234567890123456", "-123456"):
        result = _run_script("telegram", bad)
        assert result.returncode == 2, (bad, result.stderr)
        assert b"usage: telegram" in result.stderr
