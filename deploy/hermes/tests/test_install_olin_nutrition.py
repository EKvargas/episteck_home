"""Static checks on Ultron's nutrition installer, install-olin-nutrition.sh (plan 2, Task 4).
Nothing here touches a node: bash runs only `-n`, the argument checks that stop before any change,
and small parts of the script (the Berlin-to-UTC conversion, the symlink refusal, the stop on the
notes helper's exit, the config readers) on sample files.

Run from the repo root:
    python -m pytest deploy/hermes/tests -q
"""
from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# Git for Windows bash and the step/function extractors, shared with Ana's installer tests.
from test_install_home_agent_ana import (BASH, INSTALL as ANA_INSTALL, _case, _code_lines,
                                         _cron_prompt, _function, needs_bash)

ROOT = Path(__file__).resolve().parents[3]
HERMES = ROOT / "deploy" / "hermes"
SCRIPT_REL = "deploy/hermes/install-olin-nutrition.sh"
SCRIPT = ROOT / SCRIPT_REL
SHARED_SKILL = HERMES / "skills" / "olin-nutrition" / "SKILL.md"
HELPER = HERMES / "ultron_nutrition_notes.py"
POINTER_SECTION = HERMES / "home-agent" / "nutrition-pointer-section.md"
DIARY_POINTER = HERMES / "home-agent" / "nutrition-diary-pointer.md"
SERVER = ROOT / "services" / "nutrition" / "app" / "mcp" / "server.py"
SKILLS_ROOT = "/etc/episteck/hermes/skills"
BK = "/var/backups/episteck/hermes-nutrition-20261123T000000Z"
DST_REMINDER = ("Berlin changes to summer time on the last Sunday of March and back on the last "
                "Sunday of October: re-run 'cron $hm' after each change to keep the check-in at "
                "$hm Berlin time.")
NOTES_SAMPLE = ("# Episteck Home Agent\n\n## Tool invocation mechanics\n\n"
                "- `mcp__nutrition__get_daily_nutrition_gap` requires `date`.\n\n"
                "## Nutrition intake capture\n\n1. old rule\n\n## Consumer-product health claims\n\nc\n")


def _text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _run_script(*args: str) -> subprocess.CompletedProcess:
    # The script goes in on stdin, as on the node (`sudo -n bash -s -- <step> [arg]`).
    return subprocess.run([BASH, "-s", "--", *args], input=SCRIPT.read_bytes(), cwd=ROOT,
                          capture_output=True)


def _bash(cwd: Path, source: str, call: str) -> subprocess.CompletedProcess:
    """Run part of the script under strict bash; the caller checks the exit status. Git for
    Windows would rewrite a /etc/... argument for the Windows python: MSYS_NO_PATHCONV stops it."""
    return subprocess.run([BASH, "-c", f"set -euo pipefail\n{source}\n{call}"], cwd=cwd,
                          capture_output=True, text=True, encoding="utf-8",
                          env={**os.environ, "MSYS_NO_PATHCONV": "1"})


def _q(path: Path | str) -> str:
    return shlex.quote(Path(path).as_posix())


PY = _q(sys.executable)


def _to_utc(hm: str, offset: str) -> str:
    result = _bash(ROOT, _function(_text(), "to_utc"), f"to_utc {hm} {offset}")
    assert result.returncode == 0, result.stderr
    assert result.stdout.endswith("\n") and result.stdout.count("\n") == 1, result.stdout
    return result.stdout[:-1]


def _notes_tree(base: Path) -> Path:
    notes = base / "episteck-home-agent"
    (notes / "references").mkdir(parents=True)
    (notes / "SKILL.md").write_bytes(NOTES_SAMPLE.encode("utf-8"))
    (notes / "references" / "nutrition-diary.md").write_bytes(b"# old diary workflows\n")
    return notes


def _symlink(target: Path, link: Path) -> None:
    try:
        os.symlink(target, link, target_is_directory=target.is_dir())
    except OSError as exc:  # Windows without Developer Mode
        pytest.skip(f"cannot create symlinks here: {exc}")


# --- the script as a whole -------------------------------------------------------------------

@needs_bash
def test_script_is_strict_bash_lf_and_starts_at_root():
    result = subprocess.run([BASH, "-n", SCRIPT_REL], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert b"\r" not in SCRIPT.read_bytes()
    text = _text()
    assert text.startswith("#!/bin/bash\n")
    assert "set -x" not in text
    assert text.index("\nset -euo pipefail\n") < text.index("\ncd /\n") < text.index("\ncase ")
    for step in ("preflight", "install", "cron", "verify", "rollback-cron", "rollback"):
        assert re.search(rf"^  {re.escape(step)}\)", text, re.M), step
    # Every agent command runs through runuser with the user bus set and stdin pinned.
    helper = _function(text, "as_agent")
    for part in ("runuser -u", '"HOME=/home/$AGENT"', '"XDG_RUNTIME_DIR=/run/user/$u"',
                 '"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$u/bus"', '"$@" </dev/null'):
        assert part in helper, part
    for line in _code_lines(text):
        if '"$HERMES"' in line or "systemctl --user" in line:
            assert "as_agent " in line, line
        assert not re.search(r"\brunuser\b", line) or line.strip() in helper, line
    unknown = _run_script("no-such-step")
    assert unknown.returncode == 2 and b"usage:" in unknown.stderr


def test_skill_is_installed_root_owned_from_the_shared_source():
    text = _text()
    for line in ("AGENT=home-agent", "SRC=/var/lib/episteck/hermes-nutrition/deploy/hermes",
                 f"SKILLS_ROOT={SKILLS_ROOT}", "SKILL_DIR=$SKILLS_ROOT/olin-nutrition",
                 "NOTES=/home/home-agent/.hermes/skills/episteck-home-agent",
                 "CRON_NAME=olin-nutrition-checkin", "BACKUPS=/var/backups/episteck"):
        assert re.search(rf"^{re.escape(line)}$", text, re.M), line
    need = _function(text, "need_src")
    for path in (SHARED_SKILL, HELPER, POINTER_SECTION, DIARY_POINTER):
        rel = path.relative_to(HERMES).as_posix()
        assert path.is_file(), rel
        assert rel in need, rel  # checked before any step uses it
        assert f'"$SRC/{rel}"' in text, rel  # the script reads the file shipped at this commit
    install = _case(text, "install")
    assert 'install -d -m 755 -o root -g root /etc/episteck/hermes "$SKILLS_ROOT" "$SKILL_DIR"' in install
    assert ('install -m 644 -o root -g root "$SRC/skills/olin-nutrition/SKILL.md" '
            '"$SKILL_DIR/SKILL.md"') in install
    verify = _case(text, "verify")
    assert '= "644 root:root" ]' in verify
    assert 'cmp -s "$SRC/skills/olin-nutrition/SKILL.md" "$SKILL_DIR/SKILL.md"' in verify
    assert 'if as_agent test -w "$SKILL_DIR/SKILL.md"; then bad' in verify
    assert 'if as_agent test -r "$SKILL_DIR/SKILL.md"; then ok' in verify


def test_backup_happens_before_any_change():
    t = SCRIPT.read_text(encoding="utf-8")
    inst = _case(t, "install")
    assert inst.index("cp -p") < inst.index("install -m 644") < inst.index("ultron_nutrition_notes.py")
    assert 'bk="$BACKUPS/hermes-nutrition-$(date -u +%Y%m%dT%H%M%SZ)"' in inst
    first_change = inst.index("install -d -m 755")
    assert (inst.index("refuse_links") < inst.index("nutrition_keys") < inst.index('install -d -m 700 "$bk"')
            < inst.index("cp -p") < first_change)
    for src, dest in (('"$CONFIG"', '"$bk/config.yaml"'), ('"$NOTES/SKILL.md"', '"$bk/SKILL.md"'),
                      ('"$NOTES/references/nutrition-diary.md"', '"$bk/nutrition-diary.md"')):
        assert inst.index(f"cp -p {src} {dest}") < first_change, src
        assert inst.index(f"same {src} {dest}") < first_change, src  # sha256 of copy and original
    before = inst[:first_change]
    assert "backup mismatch" in before and "exit 1" in before
    assert 'echo "backup OK: $bk  (rollback: rollback $bk)"' in before
    assert 'sha256sum < "$1")" = "$(sha256sum < "$2")"' in _function(t, "same")


@needs_bash
def test_helper_exit_3_stops_the_install(tmp_path):
    inst = _case(_text(), "install")
    call = inst.index('"$PY" -I "$SRC/ultron_nutrition_notes.py" "$NOTES/SKILL.md" '
                      '"$SRC/home-agent/nutrition-pointer-section.md"')
    start = inst.rindex("rc=0", 0, call)
    end = inst.index("\n    fi\n", call) + len("\n    fi")
    block = inst[start:end]
    assert 'if [ "$rc" -ne 0 ]; then' in block and 'exit "$rc"' in block
    assert 'if [ "$rc" -eq 3 ]; then' in block and "by hand" in block and "rollback: rollback $bk" in block
    # Nothing else changes after a stop: the diary note and the restart come after this block.
    assert end < inst.index("nutrition-diary-pointer.md") < inst.index("restart_gateway")
    src = tmp_path / "src"
    (src / "home-agent").mkdir(parents=True)
    (src / "ultron_nutrition_notes.py").write_bytes(HELPER.read_bytes())
    (src / "home-agent" / "nutrition-pointer-section.md").write_bytes(POINTER_SECTION.read_bytes())
    setup = f"PY={PY}; SRC={_q(src)}; bk={BK}"

    def run(notes: Path) -> subprocess.CompletedProcess:
        return _bash(tmp_path, f"{setup}; NOTES={_q(notes)}", f"{block}\necho continued")

    good = _notes_tree(tmp_path / "good")
    result = run(good)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "continued\n"  # the change list is printed after the block
    assert "## Nutrition\n" in (good / "SKILL.md").read_text(encoding="utf-8")
    changed = _notes_tree(tmp_path / "changed")
    by_hand = NOTES_SAMPLE.replace("## Nutrition intake capture", "## Food")
    (changed / "SKILL.md").write_bytes(by_hand.encode("utf-8"))
    result = run(changed)
    assert result.returncode == 3 and "continued" not in result.stdout
    assert "nutrition heading not found" in result.stderr and "by hand" in result.stderr
    assert f"rollback: rollback {BK}" in result.stderr
    assert (changed / "SKILL.md").read_bytes() == by_hand.encode("utf-8")
    missing = tmp_path / "missing"  # any other non-zero exit stops too (here a traceback, exit 1)
    missing.mkdir()
    result = run(missing)
    assert result.returncode not in (0, 3) and "continued" not in result.stdout
    assert f"rollback: rollback {BK}" in result.stderr and "by hand" not in result.stderr


def test_install_changes_no_config_key_and_keeps_note_owners():
    text = _text()
    inst = _case(text, "install")
    assert "config set" not in text and "save_config" not in text
    helper = inst.index("ultron_nutrition_notes.py")
    diary = inst.index('install -o "$AGENT" -g "$AGENT" -m 644 "$SRC/home-agent/nutrition-diary-pointer.md" '
                       '"$NOTES/references/nutrition-diary.md"')
    unchanged = inst.index('cmp -s "$bk/config.yaml" "$CONFIG"')
    restart = inst.index("restart_gateway")
    assert helper < diary < unchanged < restart
    assert "exit 1" in inst[unchanged:restart]
    assert inst.index('stat -c \'%a %U:%G %n\' "$NOTES/SKILL.md" "$NOTES/references/nutrition-diary.md"') > diary
    # The helper rewrites the notes in place (same inode): no move or copy over them here.
    for line in _code_lines(inst):
        assert not re.search(r"\bmv\b", line), line
    assert POINTER_SECTION.read_text(encoding="utf-8").startswith("## Nutrition\n")


def test_preflight_is_read_only_and_dry_runs_the_helper_on_a_copy():
    pre = _case(_text(), "preflight")
    for part in ("need_src", '"$HERMES" --version', "nutrition_keys", 'tz="$(hermes_tz)"',
                 '[ "$(date +%z)" = "+0000" ]', '[ -e "$SKILL_DIR" ]', "$(cron_count)",
                 'links="$(home_links)"', 'tmp="$(mktemp -d)"', 'cp "$NOTES/SKILL.md" "$tmp/SKILL.md"',
                 '"$PY" -I "$SRC/ultron_nutrition_notes.py" "$tmp/SKILL.md" '
                 '"$SRC/home-agent/nutrition-pointer-section.md"',
                 'rm -f "$tmp/SKILL.md"', 'rmdir "$tmp"', "finish preflight"):
        assert part in pre, part
    # The copy is made only when no notes path is a symlink.
    assert pre.index('if [ -n "$links" ]; then') < pre.index('cp "$NOTES/SKILL.md"')
    for line in _code_lines(pre):
        assert not re.search(r"\binstall -|cp -p|cron create|cron_remove|restart_gateway|config set|"
                             r"\bchmod\b|\bchown\b", line), line
        if re.search(r"\b(cp|rm|rmdir)\b", line):
            assert "$tmp" in line, line


# --- the evening check-in --------------------------------------------------------------------

@needs_bash
def test_cron_converts_berlin_time_to_utc_and_reminds_about_dst(tmp_path):
    assert _to_utc("21:45", "+0100") == "45 20"
    assert _to_utc("00:30", "+0100") == "30 23"
    assert _to_utc("21:45", "+0200") == "45 19"
    assert "last Sunday of March" in SCRIPT.read_text(encoding="utf-8")
    # Plain integers, base 10 (08 and 09 are not octal), wrapping both ways across midnight.
    assert _to_utc("21:05", "+0100") == "5 20"
    assert _to_utc("09:08", "+0100") == "8 8"
    assert _to_utc("08:09", "+0000") == "9 8"
    assert _to_utc("00:00", "+0200") == "0 22"
    assert _to_utc("01:59", "+0200") == "59 23"
    assert _to_utc("23:30", "-0100") == "30 0"
    assert _to_utc("12:00", "+0530") == "30 6"
    cron = _case(_text(), "cron")
    assert 'off="$(TZ=Europe/Berlin date +%z)"' in cron
    assert "+0100|+0200) ;;" in cron  # a missing tzdata would give +0000: refused
    assert 'sched="$(to_utc "$hm" "$off")"' in cron
    assert cron.index('sched="$(to_utc') < cron.index("cron_remove") < cron.index("cron create")
    assert '"$sched * * *" "$CRON_PROMPT"' in cron
    assert f'echo "{DST_REMINDER}"' in cron
    assert cron.index("cron create") < cron.index("last Sunday of March")
    assert "scheduled '$sched * * *' in UTC" in cron


@needs_bash
def test_cron_rejects_bad_times():
    text = _text()
    cron = _case(text, "cron")
    re_line = "re='^([01][0-9]|2[0-3]):[0-5][0-9]$'"
    assert re_line in cron and re_line in _case(ANA_INSTALL.read_text(encoding="utf-8"), "cron")
    assert cron.index("[[ $hm =~ $re ]]") < cron.index("need_src")
    for bad in ("24:00", "9:5", "21:60", "7:30", "2145", "21:45 ", ""):
        result = _run_script("cron", bad)
        assert result.returncode == 2, (bad, result.stderr)
        assert b"usage: cron <HH:MM>" in result.stderr, bad
    # A good time passes the check and stops at the next one: the source is not here.
    result = _run_script("cron", "21:45")
    assert result.returncode == 2 and b"extract deploy/hermes" in result.stderr


def test_cron_prompt_is_english_and_ends_with_the_question():
    text = _text()
    prompt = _cron_prompt(text)
    lines = prompt.split("\n")
    assert len(lines) == 5
    # The header and steps 1-3 mirror Ana's check-in.
    assert lines[:4] == _cron_prompt(ANA_INSTALL.read_text(encoding="utf-8")).split("\n")[:4]
    four = lines[4]
    assert four.startswith("4. Otherwise write ONE short message in English")
    for part in ("as day and month", "no weekday", "free sugars against the reference",
                 "uncounted items", "When profile_version is not null",
                 "energy and protein from nutrients against their targets"):
        assert part in four, part
    assert prompt.endswith("The message ends with exactly: Was that everything today?")
    assert "Spanish" not in prompt and "¿" not in prompt
    # The job list is searched for the job name: the prompt must not contain it.
    assert "olin-nutrition-checkin" not in prompt
    skill = SHARED_SKILL.read_text(encoding="utf-8")
    assert "\n## Evening check-in (cron)\n" in skill and '"Evening check-in (cron)"' in prompt
    required = re.search(r"requires_tools: \[(.*?)\]", skill, re.S).group(1)
    for tool in re.findall(r"mcp__\w+", prompt):
        assert tool in required, tool


def test_cron_requires_utc_and_this_commits_skill():
    cron = _case(_text(), "cron")
    marks = [cron.index("[[ $hm =~ $re ]]"), cron.index("need_src"),
             cron.index('[ -f "$SKILL_DIR/SKILL.md" ]'),
             cron.index('cmp -s "$SRC/skills/olin-nutrition/SKILL.md" "$SKILL_DIR/SKILL.md"'),
             cron.index("grep -q '^## Evening check-in (cron)$' \"$SKILL_DIR/SKILL.md\""),
             cron.index('[ "$(date +%z)" = "+0000" ]'), cron.index('tz="$(hermes_tz)"'),
             cron.index('if [ -n "$tz" ] && [ "$tz" != UTC ] && [ "$tz" != Etc/UTC ]; then'),
             cron.index('off="$(TZ=Europe/Berlin date +%z)"'), cron.index("cron_remove"),
             cron.index("cron create")]
    assert marks == sorted(marks)
    checks = cron[marks[2]:marks[-2]]
    assert checks.count("exit 2") == 3 and checks.count("exit 1") == 3  # skill x3; UTC, tz, Berlin
    create = cron[marks[-1]:]
    for part in ('--name "$CRON_NAME"', "--deliver telegram", "--failure-deliver local",
                 "--skill olin-nutrition"):
        assert part in create, part
    assert cron.count("cron create") == 1  # re-running replaces the job, never adds a second
    assert create.index('[ "$(cron_count)" -gt 0 ]') < create.index("cron_show")
    # The job is looked up by name in every job, paused ones included.
    assert "cron list --all" in _function(_text(), "cron_count")
    assert "cron list --all" in _function(_text(), "cron_show")


# --- verify and rollback ---------------------------------------------------------------------

def test_verify_reports_drift_and_never_fixes():
    text = _text()
    verify = _case(text, "verify")
    tools = re.search(r"^NUTRITION_TOOLS=\((.*?)\)$", text, re.M | re.S).group(1).split()
    served = set(re.findall(r"@mcp\.tool\b[^\n]*\ndef (\w+)\(", SERVER.read_text(encoding="utf-8")))
    assert len(tools) == 20 == len(set(tools)) and set(tools) == served
    assert {"propose_profile", "get_period_summary"} <= set(tools)
    for part in ('as_agent "$HERMES" mcp test nutrition', 'for t in "${NUTRITION_TOOLS[@]}"; do',
                 'for f in "$NOTES/SKILL.md" "$NOTES/references/nutrition-diary.md"; do',
                 '"644 $AGENT:$AGENT"',
                 'contains "$NOTES/SKILL.md" "$SRC/home-agent/nutrition-pointer-section.md"',
                 'grep -qF get_daily_nutrition_gap "$NOTES/SKILL.md"',
                 'cmp -s "$SRC/home-agent/nutrition-diary-pointer.md" "$NOTES/references/nutrition-diary.md"',
                 'links="$(home_links)"', "nutrition_keys", "cron_show",
                 "systemctl --user is-active --quiet hermes-gateway.service", "finish verify"):
        assert part in verify, part
    for line in _code_lines(verify):
        assert not re.search(r"\b(install|cp|mv|rm|rmdir|chmod|chown|tee|sed)\b|cron create|"
                             r"cron_remove|config set|restart", line), line


@needs_bash
def test_rollback_restores_notes_and_removes_the_job_first():
    text = _text()
    rb = _case(text, "rollback")
    marks = [rb.index('"$BACKUPS"/hermes-nutrition-*)'),
             rb.index("for f in config.yaml SKILL.md nutrition-diary.md; do"),
             rb.index("refuse_links"), rb.index("cron_remove"),
             rb.index('cp -p "$bk/SKILL.md" "$NOTES/SKILL.md"'),
             rb.index('cp -p "$bk/nutrition-diary.md" "$NOTES/references/nutrition-diary.md"'),
             rb.index('same "$bk/SKILL.md" "$NOTES/SKILL.md"'),
             rb.index('cmp -s "$bk/config.yaml" "$CONFIG"'), rb.index('cp -p "$bk/config.yaml" "$CONFIG"'),
             rb.index('rm -f "$SKILL_DIR/SKILL.md"'), rb.index('rmdir "$SKILL_DIR"'),
             rb.index("restart_gateway")]
    assert marks == sorted(marks)
    assert 'same "$bk/nutrition-diary.md" "$NOTES/references/nutrition-diary.md"' in rb
    assert "stat -c '%a %U:%G %n' \"$NOTES/SKILL.md\" \"$NOTES/references/nutrition-diary.md\"" in rb
    assert _case(text, "rollback-cron").strip() == "rollback-cron)\n    cron_remove"
    for args in (("rollback",), ("rollback", "/tmp/x"),
                 ("rollback", "/var/backups/episteck/hermes-b9-20261123T000000Z")):
        result = _run_script(*args)
        assert result.returncode == 2 and b"usage: rollback <backup-dir" in result.stderr, args
    result = _run_script("rollback", BK)  # the right name, but no such directory here
    assert result.returncode == 1 and b"no config.yaml in" in result.stderr


def test_rollback_never_removes_the_skills_root():
    text = _text()
    removals = [line for line in _code_lines(text) if re.search(r"\b(rm|rmdir)\b", line)]
    assert removals
    for line in removals:
        targets = set(re.findall(r'"([^"]+)"', line))
        assert targets <= {"$SKILL_DIR/SKILL.md", "$SKILL_DIR", "$tmp/SKILL.md", "$tmp"}, line
        assert "SKILLS_ROOT" not in line and "/etc/episteck" not in line, line
    assert not re.search(r"\brm\s+-[a-zA-Z]*[rR]", text)  # never recursive
    assert "$SKILLS_ROOT" not in _case(text, "rollback")  # it holds olin-finance


# --- safety ----------------------------------------------------------------------------------

# Every path under the agent's home that install or rollback writes as root, or writes into, and
# the directories leading to them (R3, R12), relative to /home/home-agent.
HOME_CHAIN = ("", ".hermes", ".hermes/config.yaml", ".hermes/skills",
              ".hermes/skills/episteck-home-agent", ".hermes/skills/episteck-home-agent/SKILL.md",
              ".hermes/skills/episteck-home-agent/references",
              ".hermes/skills/episteck-home-agent/references/nutrition-diary.md")


def _home_tree(base: Path) -> Path:
    home = base / "home-agent"
    _notes_tree(home / ".hermes" / "skills")
    (home / ".hermes" / "config.yaml").write_bytes(b"model: {}\n")
    return home


@needs_bash
def test_symlinks_under_the_notes_stop_install_and_rollback(tmp_path):
    text = _text()
    for step in ("install", "rollback"):
        body = _case(text, step)
        first_change = min(body.index(m) for m in ("install -d", "cp -p", "cron_remove") if m in body)
        assert body.index("refuse_links") < first_change, step
    # Rollback writes config.yaml too: a link there would make root write (and chown) its target.
    assert 'cp -p "$bk/config.yaml" "$CONFIG"' in _case(text, "rollback")
    for step in ("preflight", "verify"):
        assert 'links="$(home_links)"' in _case(text, step), step
    refuse = _function(text, "refuse_links")
    assert 'links="$(home_links)"' in refuse and "exit 1" in refuse and ">&2" in refuse
    guard = _function(text, "home_links")
    listed = re.search(r"for p in (.*?); do", guard, re.S).group(1).replace("\\\n", " ").split()
    assert listed == ['"$AGENT_HOME"', '"$HHOME"', '"$CONFIG"', '"$HHOME/skills"', '"$NOTES"',
                      '"$NOTES/SKILL.md"', '"$NOTES/references"', '"$NOTES/references/nutrition-diary.md"']
    # The script's own definitions, so the test walks the same chain the node has.
    paths = [re.search(rf"^{name}=.*$", text, re.M).group(0)
             for name in ("AGENT_HOME", "HHOME", "CONFIG", "NOTES")]
    assert paths == ["AGENT_HOME=/home/$AGENT", "HHOME=$AGENT_HOME/.hermes", "CONFIG=$HHOME/config.yaml",
                     "NOTES=/home/home-agent/.hermes/skills/episteck-home-agent"]
    source = "\n".join([_function(text, "home_links"), refuse])

    def run(home: Path) -> subprocess.CompletedProcess:
        setup = (f"AGENT_HOME={_q(home)}; {paths[1]}; {paths[2]}; "
                 "NOTES=$HHOME/skills/episteck-home-agent")  # what NOTES is under AGENT_HOME
        return _bash(tmp_path, source, f"{setup}; refuse_links; echo passed")

    result = run(_home_tree(tmp_path / "clean"))
    assert result.returncode == 0 and result.stdout == "passed\n", result.stderr
    for i, rel in enumerate(HOME_CHAIN):
        base = tmp_path / f"case{i}"
        elsewhere = _home_tree(base / "elsewhere")  # where a planted link would make root write
        if rel:
            home = _home_tree(base / "real")
            if (home / rel).is_dir():
                shutil.rmtree(home / rel)
            else:
                (home / rel).unlink()
            _symlink(elsewhere / rel, home / rel)
        else:
            home = base / "linked-home"
            _symlink(elsewhere, home)
        result = run(home)
        assert result.returncode != 0 and "passed" not in result.stdout, rel
        assert "refusing: symlink" in result.stderr and "nothing was changed" in result.stderr, rel


@needs_bash
def test_never_reads_secrets(tmp_path):
    text = _text()
    for line in _code_lines(text):
        assert not re.search(r"\.env\b|auth\.json|memor|token|secret|password", line, re.I), line
    # Ultron's notes, config.yaml and their backups are hashed, compared, copied, never shown.
    private = re.compile(r'\$NOTES|\$CONFIG|\$bk/|\$tmp/SKILL\.md')
    for line in _code_lines(text):
        if not private.search(line):
            continue
        assert not re.search(r"\b(cat|less|more|head|tail|tee|xxd|od|strings|base64|diff|awk|sed)\b",
                             line), line
        assert "$(<" not in line, line
        if re.search(r"\bgrep\b", line):
            assert re.search(r"grep -[a-zA-Z]*[qc]", line), line
    # `contains` answers with its exit status only.
    pointer = tmp_path / "pointer.md"
    pointer.write_bytes(POINTER_SECTION.read_bytes())
    notes = tmp_path / "SKILL.md"
    notes.write_bytes(("# A\n\nSECRET-NOTE\n\n" + POINTER_SECTION.read_text(encoding="utf-8")
                       + "\n## B\n").encode("utf-8"))
    other = tmp_path / "other.md"
    other.write_bytes(b"# A\n\nSECRET-NOTE\n")
    source = f"PY={PY}\n" + _function(text, "contains")
    yes = _bash(tmp_path, source, f"contains {_q(notes)} {_q(pointer)}")
    no = _bash(tmp_path, source, f"contains {_q(other)} {_q(pointer)}")
    assert (yes.returncode, yes.stdout, no.returncode, no.stdout) == (0, "", 1, "")


@needs_bash
def test_config_readers_print_only_the_named_keys(tmp_path):
    text = _text()
    source = (f"PY={PY}; SKILLS_ROOT={SKILLS_ROOT}; CONFIG={_q(tmp_path / 'config.yaml')}\n"
              + _function(text, "nutrition_keys") + "\n" + _function(text, "hermes_tz"))

    def run(config: str, call: str) -> subprocess.CompletedProcess:
        (tmp_path / "config.yaml").write_bytes(config.encode("utf-8"))
        return _bash(tmp_path, source, call)

    live = ("model:\n  api_key: SECRET-MODEL\n"
            "mcp_servers:\n"
            "  home:\n    url: http://127.0.0.1:9934/gateway/home/\n"
            "    headers:\n      Authorization: Bearer SECRET-H\n"
            "  finance:\n    url: http://127.0.0.1:9934/gateway/finance/\n    enabled: true\n"
            "  nutrition:\n    url: http://127.0.0.1:9934/gateway/nutrition/\n    enabled: true\n"
            "    headers:\n      Authorization: Bearer SECRET-N\n"
            f"skills:\n  external_dirs: {SKILLS_ROOT}\n")
    result = run(live, "nutrition_keys")
    assert result.returncode == 0, result.stderr
    assert result.stdout == ("mcp_servers: ['finance', 'home', 'nutrition']\n"
                             "mcp_servers.nutrition.url: http://127.0.0.1:9934/gateway/nutrition/\n"
                             "mcp_servers.nutrition.enabled: True\n"
                             "mcp_servers.nutrition keys: ['enabled', 'headers', 'url']\n"
                             f"skills.external_dirs: {SKILLS_ROOT}\n")
    assert "SECRET" not in result.stdout + result.stderr
    listed = live.replace(f"external_dirs: {SKILLS_ROOT}", f"external_dirs: [/opt/x, {SKILLS_ROOT}]")
    assert run(listed, "nutrition_keys").returncode == 0
    assert run(live.replace(f"external_dirs: {SKILLS_ROOT}", "external_dirs: /opt/x"),
               "nutrition_keys").returncode == 1
    no_server = live.replace("  nutrition:\n", "  nutrition_old:\n")
    assert run(no_server, "nutrition_keys").returncode == 1
    assert run(live, "hermes_tz").stdout == "\n"
    assert run(live + "timezone: UTC\n", "hermes_tz").stdout == "UTC\n"
    assert run(live + "timezone: Europe/Berlin\n", "hermes_tz").stdout == "Europe/Berlin\n"
