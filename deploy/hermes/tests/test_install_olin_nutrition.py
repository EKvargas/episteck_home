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
    for step in ("preflight", "install", "cron", "mirror", "verify", "rollback-cron", "rollback"):
        assert re.search(rf"^  {re.escape(step)}\)", text, re.M), step
    # Every agent command runs through runuser with the user bus set and stdin pinned: /dev/null,
    # or for as_agent_from a file root names (a backup), never the script's own stdin.
    helper = _function(text, "as_agent")
    fed = _function(text, "as_agent_from")
    for part in ("runuser -u", '"HOME=/home/$AGENT"', '"XDG_RUNTIME_DIR=/run/user/$u"',
                 '"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$u/bus"'):
        assert part in helper and part in fed, part
    assert '"$@" </dev/null' in helper
    assert 'local src="$1" u; shift' in fed and '"$@" <"$src"' in fed
    calls = [line for line in _code_lines(text) if re.search(r"\bas_agent_from ", line)]
    assert len(calls) == 4  # two restores and two config comparisons, each fed from a backup
    for line in calls:
        assert re.search(r'as_agent_from "\$bk/[\w.-]+" ', line), line
    for line in _code_lines(text):
        runs = line.replace('[ -x "$VPY" ]', "")  # root only checks that the venv python exists
        if '"$HERMES"' in runs or '"$VPY"' in runs or "systemctl --user" in runs:
            assert "as_agent " in line, line
        assert not re.search(r"\brunuser\b", line) or line.strip() in helper + fed, line
        assert "/dev/stdin" not in line and "<&0" not in line, line
    unknown = _run_script("no-such-step")
    assert unknown.returncode == 2 and b"usage:" in unknown.stderr and b"mirror <on|off>" in unknown.stderr


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
    assert inst.index("agent_copy") < inst.index("install -m 644") < inst.index("ultron_nutrition_notes.py")
    assert 'bk="$BACKUPS/hermes-nutrition-$(date -u +%Y%m%dT%H%M%SZ)"' in inst
    first_change = inst.index("install -d -m 755")
    owner_mode = ("stat -c '%a %U:%G' \"$NOTES/SKILL.md\" \"$NOTES/references/nutrition-diary.md\" "
                  '> "$bk/notes-owner-mode"')
    assert (inst.index("refuse_links") < inst.index("nutrition_keys") < inst.index("plan1_live")
            < inst.index('install -d -m 700 "$bk"') < inst.index(owner_mode) < inst.index("agent_copy")
            < first_change)
    # Ultron's files are read by the agent (agent_copy, same_as_agent); the skill in /etc is root's.
    for src, dest in (('"$CONFIG"', '"$bk/config.yaml"'), ('"$NOTES/SKILL.md"', '"$bk/SKILL.md"'),
                      ('"$NOTES/references/nutrition-diary.md"', '"$bk/nutrition-diary.md"')):
        assert inst.index(f"agent_copy {src} {dest}") < first_change, src
        assert inst.index(f"same_as_agent {src} {dest}") < first_change, src  # sha256 of copy and original
        assert inst.index(f"agent_copy {src} {dest}") < inst.index(f"same_as_agent {src} {dest}"), src
    skill = ('"$SKILL_DIR/SKILL.md"', '"$bk/olin-nutrition-SKILL.md"')
    assert inst.index("cp -p %s %s" % skill) < first_change
    stopped = ("cannot record the notes' owner and mode in $bk: nothing was changed")
    assert inst.index(owner_mode) < inst.index(stopped) < first_change  # a failed stat says so
    assert inst.index("same %s %s" % skill) < first_change
    # The installed skill is backed up only when an earlier install left one.
    assert inst.index('if [ -f "$SKILL_DIR/SKILL.md" ]; then') < inst.index('"$bk/olin-nutrition-SKILL.md"')
    before = inst[:first_change]
    assert before.count("backup mismatch") == 2 and "exit 1" in before
    assert 'echo "backup OK: $bk  (rollback: rollback $bk)"' in before
    assert 'sha256sum < "$1")" = "$(sha256sum < "$2")"' in _function(t, "same")


def test_install_warns_when_the_backup_holds_rewritten_notes():
    inst = _case(_text(), "install")
    check = inst.index('if contains "$bk/SKILL.md" "$SRC/home-agent/nutrition-pointer-section.md"; then')
    assert inst.index('echo "backup OK: $bk') < check < inst.index("install -d -m 755")
    assert ('echo "WARNING: this backup holds already-rewritten notes; roll back with the first '
            'install\'s backup" >&2') in inst[check:]


@needs_bash
def test_install_refuses_unless_the_plan1_backend_is_live(tmp_path):
    text = _text()
    assert re.search(r"^PLAN1_TOOLS=\(propose_profile get_period_summary\)$", text, re.M)
    inst = _case(text, "install")
    refuse = inst[inst.index("plan1_live"):inst.index('bk="$BACKUPS')]
    assert "exit 2" in refuse and "runbook C1" in refuse and "Nothing was changed" in refuse
    probe = _function(text, "plan1_live")
    assert 'as_agent "$HERMES" mcp test nutrition' in probe
    # preflight only reports it: the backend is rolled out after C0.
    pre = _case(text, "preflight")
    line = next(ln for ln in pre.splitlines() if "plan1_live" in ln)
    assert line.strip().startswith("if plan1_live; then echo") and "bad " not in line and "ok " not in line
    assert "install refuses until it is" in pre
    source = (f"{_function(text, 'plan1_live')}\nPLAN1_TOOLS=(propose_profile get_period_summary)\n"
              'as_agent() { cat mcp.txt; }\nHERMES=hermes')

    def live(listing: str) -> int:
        (tmp_path / "mcp.txt").write_text(listing, encoding="utf-8")
        return _bash(tmp_path, source, "plan1_live").returncode

    assert live("Tools (20): close_day propose_profile get_period_summary void_intake\n") == 0
    assert live("Tools (13): close_day get_day_summary void_intake\n") == 1
    assert live("Tools (19): propose_profile void_intake\n") == 1
    assert live("401 Unauthorized\n") == 1


@needs_bash
def test_helper_exit_3_stops_the_install(tmp_path):
    inst = _case(_text(), "install")
    # The helper writes into the agent's home, so it runs as the agent (stdin /dev/null).
    call = inst.index('out="$(as_agent "$PY" -I "$SRC/ultron_nutrition_notes.py" "$NOTES/SKILL.md" '
                      '"$SRC/home-agent/nutrition-pointer-section.md" 2>&1)" || rc=$?')
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
    # Stand-in for as_agent (no runuser here): logs what ran as the agent, stdin /dev/null.
    setup = (f"PY={PY}; SRC={_q(src)}; bk={BK}\n"
             'as_agent() { printf "%s\\n" "${@: -2:1}" >> as-agent.log; "$@" </dev/null; }')

    def run(notes: Path) -> subprocess.CompletedProcess:
        return _bash(tmp_path, f"{setup}\nNOTES={_q(notes)}", f"{block}\necho continued")

    good = _notes_tree(tmp_path / "good")
    result = run(good)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "continued\n"  # the change list is printed after the block
    assert "## Nutrition\n" in (good / "SKILL.md").read_text(encoding="utf-8")
    assert (tmp_path / "as-agent.log").read_text(encoding="utf-8") == f"{(good / 'SKILL.md').as_posix()}\n"
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
    assert "config set" not in text
    # Only the mirror step saves config.yaml, through MIRROR_PY; install never does.
    mirror_py = re.search(r"^MIRROR_PY='([^']*)'$", text, re.M | re.S).group(0)
    assert text.count("save_config") == mirror_py.count("save_config") == 2  # import and call
    assert "MIRROR_PY" not in inst and "save_config" not in inst
    helper = inst.index("ultron_nutrition_notes.py")
    # Written as the agent: the file is home-agent's, no chown by root.
    diary = inst.index('as_agent install -m 644 "$SRC/home-agent/nutrition-diary-pointer.md" '
                       '"$NOTES/references/nutrition-diary.md"')
    assert 'install -o "$AGENT"' not in text
    unchanged = inst.index('as_agent_from "$bk/config.yaml" cmp -s - "$CONFIG"')
    restart = inst.index("restart_gateway")
    assert helper < diary < unchanged < restart
    assert "exit 1" in inst[unchanged:restart]
    assert inst.index('stat -c \'%a %U:%G %n\' "$NOTES/SKILL.md" "$NOTES/references/nutrition-diary.md"') > diary
    # The helper rewrites the notes in place (same inode): no move or copy over them here.
    for line in _code_lines(inst):
        assert not re.search(r"\bmv\b", line), line
    assert POINTER_SECTION.read_text(encoding="utf-8").startswith("## Nutrition\n")


AGENT_PATHS = re.compile(r'"\$(NOTES|CONFIG|HHOME|AGENT_HOME)\b')


def test_root_never_writes_into_the_agents_home():
    # Ultron can run code, so it could swap a path for a symlink between a check and a write
    # (R16): every write into /home/home-agent runs as home-agent; root copies nothing out of it.
    text = _text()
    writes = re.compile(r"\b(cp|install|mv|tee|rm|rmdir|chmod|chown|ln|touch|truncate)\b|"
                        r"sed -i|ultron_nutrition_notes\.py|MIRROR_PY|>>? *\"\$")
    seen = 0
    for step in ("install", "mirror", "rollback"):
        for line in _code_lines(_case(text, step)):
            if not (AGENT_PATHS.search(line) or "MIRROR_PY" in line) or not writes.search(line):
                continue
            targets = re.findall(r'"([^"]+)"', line)
            if "ultron_nutrition_notes.py" in line or "MIRROR_PY" in line or "tee" in line:
                into_home = True  # the helper, the config save and tee write the agent's files
            else:
                into_home = bool(targets) and AGENT_PATHS.match(f'"{targets[-1]}')
            if into_home:
                seen += 1
                assert re.search(r"(^|\$\()\s*as_agent(_from)? ", line.strip()), (step, line)
            else:  # the notes' owner and mode, as metadata, into root's own 0700 backup directory
                assert targets[-1] == "$bk/notes-owner-mode" and re.match(r"\s*stat -c ", line), (step, line)
    assert seen == 5  # helper, diary pointer, MIRROR_PY, and the two notes restores
    # The old root writes are gone.
    for line in _code_lines(text):
        assert not re.search(r'cp -p "\$bk/[^"]*" "\$(NOTES|CONFIG)', line), line


def test_preflight_is_read_only_and_dry_runs_the_helper_on_a_copy():
    pre = _case(_text(), "preflight")
    for part in ("need_src", '"$HERMES" --version', "nutrition_keys", 'tz="$(hermes_tz)"',
                 '[ "$(date +%z)" = "+0000" ]', '[ -e "$SKILL_DIR" ]', "$(cron_count)",
                 'echo "cron.mirror_delivery: $(mirror_value)', "if plan1_live; then echo",
                 'links="$(home_links)"', 'tmp="$(mktemp -d)"', 'agent_copy "$NOTES/SKILL.md" "$tmp/SKILL.md"',
                 "the helper dry run is skipped",
                 '"$PY" -I "$SRC/ultron_nutrition_notes.py" "$tmp/SKILL.md" '
                 '"$SRC/home-agent/nutrition-pointer-section.md"',
                 'rm -f "$tmp/SKILL.md"', 'rmdir "$tmp"', "finish preflight"):
        assert part in pre, part
    # The copy is made (by the agent) only when no notes path is a symlink.
    assert pre.index('if [ -n "$links" ]; then') < pre.index('agent_copy "$NOTES/SKILL.md"')
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
                 "uncounted items"):
        assert part in four, part
    # A mode-only or MIGRATED profile version has no targets: a nutrient goes in only with one (R15).
    assert four.endswith(
        "It gives the free sugars against the reference and the uncounted items, or says that "
        "nothing is logged yet. For energy_kcal and protein_g in nutrients, it gives known against "
        "target only when the target of that nutrient is not null, and leaves out a nutrient whose "
        "target is null, even when profile_version is set. A day with no targets gets the free "
        "sugars part only. The message ends with exactly: Was that everything today?")
    assert "When profile_version is not null" not in prompt
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
                 'echo "cron.mirror_delivery: $(mirror_value)',
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
             rb.index("for f in config.yaml SKILL.md nutrition-diary.md notes-owner-mode; do"),
             rb.index("refuse_links"), rb.index("cron_remove"),
             rb.index('as_agent_from "$bk/SKILL.md" tee "$NOTES/SKILL.md" >/dev/null'),
             rb.index('as_agent_from "$bk/nutrition-diary.md" tee "$NOTES/references/nutrition-diary.md" '
                      '>/dev/null'),
             rb.index('same_as_agent "$NOTES/SKILL.md" "$bk/SKILL.md"'),
             rb.index('as_agent_from "$bk/config.yaml" cmp -s - "$CONFIG"'),
             rb.index('if [ -f "$bk/olin-nutrition-SKILL.md" ]; then'),
             rb.index('install -m 644 -o root -g root "$bk/olin-nutrition-SKILL.md" "$SKILL_DIR/SKILL.md"'),
             rb.index('rm -f "$SKILL_DIR/SKILL.md"'), rb.index('rmdir "$SKILL_DIR"'),
             rb.index("restart_gateway"), rb.index('if [ "$WARNINGS" -gt 0 ]; then')]
    assert marks == sorted(marks)
    assert 'same_as_agent "$NOTES/references/nutrition-diary.md" "$bk/nutrition-diary.md"' in rb
    # Owner and mode of the restored notes are compared with what install recorded.
    assert ("stat -c '%a %U:%G' \"$NOTES/SKILL.md\" \"$NOTES/references/nutrition-diary.md\" "
            '| cmp -s - "$bk/notes-owner-mode"') in rb
    assert "stat -c '%a %U:%G %n' \"$NOTES/SKILL.md\" \"$NOTES/references/nutrition-diary.md\"" in rb
    # config.yaml is compared, never written (R17): install never changes it.
    assert '"$CONFIG"' in rb and not re.search(r'(cp|install|tee|mv)\b[^\n]*"\$CONFIG"', rb)
    assert ('warn "config.yaml differs from the install-time backup in $bk; not touched"') in rb
    assert _case(text, "rollback-cron").strip() == "rollback-cron)\n    cron_remove"
    for args in (("rollback",), ("rollback", "/tmp/x"),
                 ("rollback", "/var/backups/episteck/hermes-b9-20261123T000000Z")):
        result = _run_script(*args)
        assert result.returncode == 2 and b"usage: rollback <backup-dir" in result.stderr, args
    result = _run_script("rollback", BK)  # the right name, but no such directory here
    assert result.returncode == 1 and b"no config.yaml in" in result.stderr


def _owner_mode(tmp_path: Path, *paths: Path) -> bytes:
    """What `stat -c '%a %U:%G'` prints for these files here (install records it in the backup)."""
    result = _bash(tmp_path, "", "stat -c '%a %U:%G' " + " ".join(_q(p) for p in paths))
    assert result.returncode == 0, result.stderr
    return result.stdout.encode("utf-8")


def _rollback(tmp_path: Path, *, config_changed=False, cron_fails=False, earlier_skill=None,
              extra_in_skill_dir=False, owner_mode="same") -> tuple[subprocess.CompletedProcess, dict]:
    """Run the script's rollback step on a sample tree. Stand-ins replace what needs the node:
    runuser (as_agent and as_agent_from run the command as the test user; as_agent_from takes its
    stdin from the named file), the job, the gateway restart, and install's -o/-g. `owner_mode` is
    the backup's notes-owner-mode: "same" as the restored notes, "differs", or "missing"."""
    text = _text()
    backups, home, etc = tmp_path / "backups", tmp_path / "home", tmp_path / "etc"
    bk = backups / "hermes-nutrition-20261123T000000Z"
    notes = home / "notes"
    (notes / "references").mkdir(parents=True)
    bk.mkdir(parents=True)
    skill_dir = etc / "skills" / "olin-nutrition"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_bytes(b"this commit's skill\n")
    if extra_in_skill_dir:
        (skill_dir / "notes.txt").write_bytes(b"someone else's\n")
    files = {"config": home / "config.yaml", "notes": notes / "SKILL.md",
             "diary": notes / "references" / "nutrition-diary.md", "skill": skill_dir / "SKILL.md",
             "bk": bk, "skill_dir": skill_dir}
    (bk / "config.yaml").write_bytes(b"model: {}\ncron:\n  catch_up_missed: true\n")
    (bk / "SKILL.md").write_bytes(NOTES_SAMPLE.encode("utf-8"))
    (bk / "nutrition-diary.md").write_bytes(b"# old diary workflows\n")
    if earlier_skill is not None:
        (bk / "olin-nutrition-SKILL.md").write_bytes(earlier_skill)
    live_config = b"model: {}\ncron:\n  catch_up_missed: true\n  mirror_delivery: true\n" \
        if config_changed else (bk / "config.yaml").read_bytes()
    files["config"].write_bytes(live_config)
    files["notes"].write_bytes(b"# Episteck Home Agent\n\n## Nutrition\n\npointer\n")
    files["diary"].write_bytes(DIARY_POINTER.read_bytes())
    if owner_mode == "same":
        (bk / "notes-owner-mode").write_bytes(_owner_mode(tmp_path, files["notes"], files["diary"]))
    elif owner_mode == "differs":
        (bk / "notes-owner-mode").write_bytes(b"600 root:root\n600 root:root\n")
    stand_ins = "\n".join([
        "refuse_links() { :; }",
        'as_agent() { printf "%s\\n" "${@: -1}" >> as-agent.log; "$@" </dev/null; }',
        f'cron_remove() {{ echo cron_remove; return {1 if cron_fails else 0}; }}',
        "restart_gateway() { echo restarted; }",
        'as_agent_from() { local src="$1"; shift; printf "%s %s\\n" "$src" "${@: -1}" >> agent.log; '
        '"$@" <"$src"; }',
        'install() { local d=0 a=(); while [ $# -gt 0 ]; do case "$1" in -o|-g|-m) shift 2 ;; '
        '-d) d=1; shift ;; *) a+=("$1"); shift ;; esac; done; '
        'if [ "$d" = 1 ]; then mkdir -p "${a[@]}"; else cp "${a[0]}" "${a[1]}"; fi; }',
    ])
    source = "\n".join([f"PY={PY}", "WARNINGS=0", _function(text, "warn"), _function(text, "same"),
                        _function(text, "same_as_agent"), stand_ins, f"BACKUPS={_q(backups)}", f"NOTES={_q(notes)}",
                        f"CONFIG={_q(files['config'])}", f"SKILL_DIR={_q(skill_dir)}",
                        "AGENT=home-agent", "CRON_NAME=olin-nutrition-checkin"])
    body = _case(text, "rollback")
    call = f'set -- rollback {_q(bk)}\ncase "$1" in\n{body}\n    ;;\nesac'
    return _bash(tmp_path, source, call), files


@needs_bash
def test_rollback_restores_the_notes_as_the_agent_and_removes_the_skill(tmp_path):
    result, f = _rollback(tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.index("cron_remove") < result.stdout.index("restarted")
    assert result.stdout.endswith("restarted\nrollback: done\n")
    assert "notes restored byte for byte, owner and mode as in the backup:" in result.stdout
    assert f["notes"].read_bytes() == (f["bk"] / "SKILL.md").read_bytes()
    assert f["diary"].read_bytes() == (f["bk"] / "nutrition-diary.md").read_bytes()
    # Both writes went through the agent-side helper, fed from the backup files.
    log = (tmp_path / "agent.log").read_text(encoding="utf-8").splitlines()
    assert log == [f"{(f['bk'] / 'SKILL.md').as_posix()} {f['notes'].as_posix()}",
                   f"{(f['bk'] / 'nutrition-diary.md').as_posix()} {f['diary'].as_posix()}",
                   f"{(f['bk'] / 'config.yaml').as_posix()} {f['config'].as_posix()}"]
    # The restored notes were hashed by the agent, never by root: the two sources it read.
    hashed = (tmp_path / "as-agent.log").read_text(encoding="utf-8").splitlines()
    assert hashed == [f["notes"].as_posix(), f["diary"].as_posix()]
    assert not f["skill_dir"].exists()  # no earlier skill in the backup: the skill goes
    assert "config.yaml is as in the backup" in result.stdout and "WARNING" not in result.stderr


@needs_bash
def test_rollback_never_restores_config_and_exits_1_after_the_restart_on_a_warning(tmp_path):
    result, f = _rollback(tmp_path, config_changed=True, cron_fails=True,
                          earlier_skill=b"the earlier install's skill\n")
    assert result.returncode == 1
    changed = f["config"].read_bytes()
    assert b"mirror_delivery: true" in changed  # someone else's change stays (R17)
    assert (f"WARNING: config.yaml differs from the install-time backup in {f['bk'].as_posix()}; "
            "not touched") in result.stderr
    assert "WARNING: olin-nutrition-checkin is still scheduled" in result.stderr
    assert "rollback: 2 warning(s) above (the gateway was restarted)" in result.stderr
    assert result.stdout.endswith("restarted\n")  # the restart ran before the exit 1
    assert f["notes"].read_bytes() == (f["bk"] / "SKILL.md").read_bytes()
    # The earlier install's skill comes back instead of being deleted.
    assert f["skill"].read_bytes() == b"the earlier install's skill\n"
    assert "restored from the earlier install" in result.stdout


@needs_bash
def test_rollback_reports_notes_that_differ_and_a_skill_dir_that_is_not_empty(tmp_path):
    result, f = _rollback(tmp_path, extra_in_skill_dir=True)
    assert result.returncode == 0, result.stderr
    assert f"note: {f['skill_dir'].as_posix()} is not empty, so it stays" in result.stdout
    assert not f["skill"].exists() and (f["skill_dir"] / "notes.txt").exists()
    # Notes that do not match the backup after the writes are a warning (counted, so exit 1).
    text = _text()
    rb = _case(text, "rollback")
    check = rb[rb.index('    if same_as_agent "$NOTES/SKILL.md"'):rb.index("    stat -c '%a %U:%G %n'")]
    source = "\n".join([f"PY={PY}", "WARNINGS=0", _function(text, "warn"),
                        _function(text, "same_as_agent"), 'as_agent() { "$@" </dev/null; }',
                        f"NOTES={_q(f['notes'].parent)}", f"bk={_q(f['bk'])}"])
    out = _bash(tmp_path, source, f'{check}\necho "warnings=$WARNINGS"')
    assert out.returncode == 0 and out.stdout.endswith("warnings=0\n"), out.stderr
    f["diary"].write_bytes(b"changed after the restore\n")
    out = _bash(tmp_path, source, f'{check}\necho "warnings=$WARNINGS"')
    assert out.returncode == 0 and out.stdout == "warnings=1\n", out.stderr
    assert "WARNING: the notes differ from the backup" in out.stderr


@needs_bash
def test_rollback_warns_when_owner_or_mode_differ_from_what_install_recorded(tmp_path):
    result, f = _rollback(tmp_path, owner_mode="differs")
    assert result.returncode == 1, result.stdout
    assert f["notes"].read_bytes() == (f["bk"] / "SKILL.md").read_bytes()  # content restored
    assert "WARNING: the notes differ from the backup in" in result.stderr
    assert "(content, owner or mode)" in result.stderr
    assert "notes restored byte for byte" not in result.stdout
    assert "rollback: 1 warning(s) above (the gateway was restarted)" in result.stderr
    assert result.stdout.endswith("restarted\n")


@needs_bash
def test_rollback_refuses_a_backup_without_notes_owner_mode_before_any_change(tmp_path):
    result, f = _rollback(tmp_path, owner_mode="missing")
    assert result.returncode == 1
    assert f"no notes-owner-mode in {f['bk'].as_posix()}: nothing was changed" in result.stderr
    assert result.stdout == ""  # no job removal, no restore, no restart
    assert not (tmp_path / "agent.log").exists() and not (tmp_path / "as-agent.log").exists()
    assert f["notes"].read_bytes() == b"# Episteck Home Agent\n\n## Nutrition\n\npointer\n"
    assert f["skill"].exists()


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


# --- reading Ultron's files as Ultron ------------------------------------------------------------

def test_root_never_copies_out_of_the_agents_home():
    # Ultron can swap a path for a symlink after refuse_links ran: a root `cp` would follow it and
    # put a file only root can read into the backup (and a later rollback into Ultron's notes).
    # So the agent reads and root only receives the bytes.
    text = _text()
    for line in _code_lines(text):
        assert not re.search(r'\bcp\b[^\n]*"\$(CONFIG|NOTES|HHOME|AGENT_HOME)', line), line
        assert not re.search(r'\bsame "\$(CONFIG|NOTES)', line), line
        assert not re.search(r'sha256sum < "\$(CONFIG|NOTES)', line), line
        assert 'cmp -s "$bk/config.yaml" "$CONFIG"' not in line, line
    # Every write into a backup directory is the agent's bytes (agent_copy), except the root-owned
    # skill from /etc and the notes' owner and mode (metadata only).
    root_made = {"olin-nutrition-SKILL.md", "notes-owner-mode"}
    copied = set()
    for step in ("preflight", "install", "mirror", "rollback"):
        for line in _code_lines(_case(text, step)):
            copied.update(re.findall(r'agent_copy "[^"]+" "\$(?:bk|tmp)/([\w.-]+)"', line))
            if not re.search(r'\b(cp|install|mv|tee)\b|[^&0-9]>>? *"', line):
                continue
            targets = re.findall(r'"([^"]+)"', line)
            if targets and targets[-1].startswith("$bk/"):
                assert targets[-1][len("$bk/"):] in root_made, (step, line)
    assert copied == {"config.yaml", "SKILL.md", "nutrition-diary.md", "config-after.yaml"}
    # In these steps no line that names the config or a note and reads it (in either argument
    # order) runs as root: it goes through the agent. stat (metadata) is allowed; the key readers
    # and verify are out of scope (they never name "$CONFIG" here).
    reads = re.compile(r"\b(same|cmp|cp|sha256sum|md5sum|cat|grep|diff|head|tail|sed|awk|xxd|od)\b")
    named = re.compile(r"\$\{?(NOTES|CONFIG)\b")
    agent = re.compile(r"\b(as_agent|as_agent_from|agent_copy|same_as_agent)\b")
    for step in ("preflight", "install", "mirror", "rollback"):
        for line in _code_lines(_case(text, step)):
            if "stat -c" in line:  # metadata only; a cmp after it reads stat's output and a backup
                assert not re.search(r'cmp [^|]*"\$(NOTES|CONFIG)', line.split("|", 1)[-1]), (step, line)
                continue
            if named.search(line) and reads.search(line) and not line.lstrip().startswith("echo"):
                assert agent.search(line), (step, line)
    assert 'agent_copy "$NOTES/SKILL.md" "$tmp/SKILL.md"' in _case(text, "preflight")
    assert 'cp -p "$SKILL_DIR/SKILL.md" "$bk/olin-nutrition-SKILL.md"' in _case(text, "install")
    assert 'as_agent cat -- "$1" > "$2"' in _function(text, "agent_copy")
    assert 'as_agent sha256sum -- "$1"' in _function(text, "same_as_agent")


@needs_bash
def test_agent_copy_and_same_as_agent_read_as_the_agent(tmp_path):
    text = _text()
    source = "\n".join([_function(text, "agent_copy"), _function(text, "same_as_agent"),
                        'as_agent() { printf "%s\\n" "$*" >> as-agent.log; "$@" </dev/null; }'])
    (tmp_path / "agent-file").write_bytes(b"the agent's bytes\n")
    (tmp_path / "root-same").write_bytes(b"the agent's bytes\n")
    (tmp_path / "root-other").write_bytes(b"something else\n")
    (tmp_path / "root-empty").write_bytes(b"")
    copy = _bash(tmp_path, source, "agent_copy agent-file copy")
    assert copy.returncode == 0, copy.stderr
    assert (tmp_path / "copy").read_bytes() == b"the agent's bytes\n"
    assert (tmp_path / "as-agent.log").read_text(encoding="utf-8") == "cat -- agent-file\n"
    # The script calls both helpers where set -e does not apply (&& chains, if): so do these
    # cases, otherwise errexit would stop the shell inside a helper and hide a missing guard.
    gone = _bash(tmp_path, source, 'if agent_copy no-such-file copy2; then echo ok; else echo failed; fi')
    assert gone.stdout == "failed\n"  # the agent cannot read it
    chained = _bash(tmp_path, source, 'agent_copy no-such-file copy3 && echo ok || echo failed')
    assert chained.stdout == "failed\n"
    (tmp_path / "as-agent.log").unlink()

    def same(agent_file: str, root_file: str, prefix: str = "") -> str:
        result = _bash(tmp_path, source, f"{prefix}if same_as_agent {agent_file} {root_file}; "
                                         "then echo equal; else echo unequal; fi")
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    assert same("agent-file", "root-same") == "equal"
    assert (tmp_path / "as-agent.log").read_text(encoding="utf-8") == "sha256sum -- agent-file\n"
    assert same("agent-file", "root-other") == "unequal"
    assert same("no-such-file", "root-same") == "unequal"
    assert same("no-such-file", "root-empty") == "unequal"  # never equal by accident
    assert same("no-such-file", "no-such-root-file") == "unequal"  # both unreadable: empty hashes
    # The agent prints nothing (an unreadable file seen through a stand-in): still unequal.
    assert same("agent-file", "root-empty", prefix="as_agent() { :; }\n") == "unequal"
    assert same("agent-file", "no-such-root-file") == "unequal"


# --- safety ----------------------------------------------------------------------------------

# Every path under the agent's home that install, mirror or rollback writes (as the agent), and
# the directories leading to them (R3, R12); root only stats them or runs key checks. Relative to
# /home/home-agent. The refusal is defence in depth: root no longer writes there (R16).
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
    for step in ("install", "mirror", "rollback"):
        body = _case(text, step)
        first_change = min(body.index(m) for m in ("install -d", "cp -p", "cron_remove", "as_agent", "agent_copy")
                           if m in body)
        assert body.index("refuse_links") < first_change, step
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
        # The one tee: the agent writes a backup back into its notes, its output thrown away.
        shown = re.sub(r'as_agent_from "\$bk/[\w.-]+" tee "\$NOTES/[\w./-]+" >/dev/null', "", line)
        assert not re.search(r"\b(cat|less|more|head|tail|tee|xxd|od|strings|base64|diff|awk|sed)\b",
                             shown), line
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


# --- the mirror step (R18) ---------------------------------------------------------------------

@needs_bash
def test_mirror_value_prints_only_that_key(tmp_path):
    text = _text()
    source = f"PY={PY}; CONFIG={_q(tmp_path / 'config.yaml')}\n" + _function(text, "mirror_value")

    def value(config: str) -> str:
        (tmp_path / "config.yaml").write_bytes(config.encode("utf-8"))
        result = _bash(tmp_path, source, "mirror_value")
        assert result.returncode == 0, result.stderr
        return result.stdout

    secret = "model:\n  api_key: SECRET-MODEL\n"
    assert value(secret) == "unset\n"
    assert value(secret + "cron:\n  catch_up_missed: true\n") == "unset\n"
    assert value(secret + "cron:\n  mirror_delivery: true\n") == "true\n"
    assert value(secret + "cron:\n  mirror_delivery: false\n") == "false\n"
    assert value(secret + "cron:\n  mirror_delivery: maybe\n") == "not a boolean\n"
    for step in ("preflight", "verify"):
        assert 'echo "cron.mirror_delivery: $(mirror_value)' in _case(text, step), step


@needs_bash
def test_config_drift_names_other_changed_keys_never_values(tmp_path):
    source = f"PY={PY}\n" + _function(_text(), "config_drift")
    before = ("model:\n  default: gpt\n  api_key: SECRET-A\nmcp_servers:\n  finance:\n"
              "    url: http://127.0.0.1:9934/gateway/finance/\ncron:\n  catch_up_missed: true\n")

    def drift(after: str, old: str = before) -> subprocess.CompletedProcess:
        (tmp_path / "before.yaml").write_bytes(old.encode("utf-8"))
        (tmp_path / "after.yaml").write_bytes(after.encode("utf-8"))
        return _bash(tmp_path, source, "config_drift before.yaml after.yaml")

    same = drift(before.replace("catch_up_missed: true\n", "catch_up_missed: true\n  mirror_delivery: true\n"))
    assert (same.returncode, same.stdout) == (0, "no other key changed\n"), same.stderr
    # A cron block that only gains the key, or a re-ordered file, is no drift either.
    bare = "model:\n  default: gpt\n"
    assert drift("cron:\n  mirror_delivery: true\nmodel:\n  default: gpt\n", bare).returncode == 0
    assert drift("model: {default: gpt}\ncron: {}\n", bare).returncode == 0
    changed = drift(before.replace("SECRET-A", "SECRET-B").replace("catch_up_missed: true", "catch_up_missed: false")
                    + "timezone: UTC\n")
    assert changed.returncode == 1
    assert changed.stdout == "other keys changed: cron.catch_up_missed, model.api_key, timezone\n"
    assert "SECRET" not in changed.stdout + changed.stderr
    dropped = drift(before.replace("  finance:\n    url: http://127.0.0.1:9934/gateway/finance/\n", "  {}\n"))
    assert dropped.returncode == 1 and "mcp_servers" in dropped.stdout


@needs_bash
def test_mirror_step_backs_up_sets_one_key_checks_and_restarts():
    text = _text()
    mirror = _case(text, "mirror")
    marks = [mirror.index('case "${2:-}" in'), mirror.index("refuse_links"),
             mirror.index('[ -x "$VPY" ]'), mirror.index('before="$(mirror_value)"'),
             mirror.index('bk="$BACKUPS/hermes-nutrition-mirror-$(date -u +%Y%m%dT%H%M%SZ)"'),
             mirror.index('install -d -m 700 "$bk"'), mirror.index('agent_copy "$CONFIG" "$bk/config.yaml"'),
             mirror.index('same_as_agent "$CONFIG" "$bk/config.yaml"'), mirror.index('echo "backup OK: $bk'),
             mirror.index('as_agent "$VPY" -I -c "$MIRROR_PY" "$want"'),
             mirror.index('[ "$(mirror_value)" = "$val" ]'),
             mirror.index('agent_copy "$CONFIG" "$bk/config-after.yaml"'),
             mirror.index('config_drift "$bk/config.yaml" "$bk/config-after.yaml"'),
             mirror.index("restart_gateway")]
    assert marks == sorted(marks)
    assert 'config_drift "$bk/config.yaml" "$CONFIG"' not in mirror  # compared as two root files
    # Each check after the save stops before the restart.
    after_save = mirror[marks[9]:marks[-1]]
    assert after_save.count("exit 1") == 4 and after_save.count("the gateway was not restarted") == 4
    # A failed read of config.yaml after the change has its own message and stops before the drift check.
    read = ('agent_copy "$CONFIG" "$bk/config-after.yaml" \\\n'
            '      || { echo "could not read config.yaml as $AGENT after the change: the gateway was '
            'not restarted (backup: $bk)" >&2; exit 1; }')
    assert read in mirror
    assert mirror.index(read) < mirror.index('config_drift "$bk/config.yaml" "$bk/config-after.yaml"')
    assert "on) want=on; val=true ;;" in mirror and "off) want=off; val=false ;;" in mirror
    # A rollback with this directory refuses: it holds config.yaml only.
    assert "hermes-nutrition-mirror-" in mirror and "config.yaml only" in mirror
    for bad in ((), ("yes",), ("ON",), ("true",)):
        result = _run_script("mirror", *bad)
        assert result.returncode == 2 and b"usage: mirror <on|off>" in result.stderr, bad


def test_mirror_sets_only_its_key_through_hermes_config(tmp_path):
    from test_install_home_agent_ana import _STUB_CONFIG
    yaml = pytest.importorskip("yaml")
    program = re.search(r"^MIRROR_PY='([^']*)'$", _text(), re.M | re.S).group(1)
    (tmp_path / "hermes_cli").mkdir()
    (tmp_path / "hermes_cli" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "hermes_cli" / "config.py").write_text(_STUB_CONFIG, encoding="utf-8")
    (tmp_path / "config.yaml").write_text("model:\n  default: other\ncron:\n  catch_up_missed: true\n"
                                          "keep_me: 7\n", encoding="utf-8")

    def run(arg: str) -> tuple[int, str]:
        result = subprocess.run([sys.executable, "-c", program, arg], cwd=tmp_path,
                                capture_output=True, text=True, encoding="utf-8")
        return result.returncode, result.stdout

    assert run("on") == (0, "changed: cron.mirror_delivery\ncron.mirror_delivery in effect: true\n")
    saved = yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8"))
    assert saved == {"model": {"default": "other"}, "cron": {"catch_up_missed": True, "mirror_delivery": True},
                     "keep_me": 7}
    assert yaml.safe_load((tmp_path / "preserved.json").read_text()) == [["cron", "mirror_delivery"]]
    assert run("on") == (0, "changed: nothing\ncron.mirror_delivery in effect: true\n")
    assert run("off") == (0, "changed: cron.mirror_delivery\ncron.mirror_delivery in effect: false\n")
    # No cron block at all: one is added with only this key.
    (tmp_path / "config.yaml").write_text("keep_me: 7\n", encoding="utf-8")
    assert run("on")[0] == 0
    assert yaml.safe_load((tmp_path / "config.yaml").read_text(encoding="utf-8")) == {
        "keep_me": 7, "cron": {"mirror_delivery": True}}
