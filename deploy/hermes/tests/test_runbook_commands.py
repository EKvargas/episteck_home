"""Every step the profile rollout runbook names must exist as a case label in its script."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RUNBOOK = ROOT / "docs/runbooks/nutrition-profile-rollout.md"

NUT_HELPER = (
    'NUT() { $SSH "sudo -n bash -s -- $*" < deploy/hermes/install-olin-nutrition.sh; }'
)

# helper -> (regex finding its uses, script, minimum distinct steps the runbook must use)
HELPERS = {
    "NUT": (r"\bNUT ([a-z][a-z-]*)", ROOT / "deploy/hermes/install-olin-nutrition.sh", 5),
    "ANA": (r"\bANA ([a-z][a-z-]*)", ROOT / "deploy/hermes/install-home-agent-ana.sh", 4),
    "ROLL": (r"\bROLL nutrition ([a-z][a-z-]*)", ROOT / "deploy/ops/image-rollout.sh", 5),
}


def _uses(pattern: str) -> set[str]:
    return set(re.findall(pattern, RUNBOOK.read_text(encoding="utf-8")))


def _text() -> str:
    return RUNBOOK.read_text(encoding="utf-8")


def _stage(name: str) -> str:
    text = _text()
    start = text.index(f"\n## {name}.")
    end = text.find("\n## ", start + 1)
    return text[start:] if end == -1 else text[start:end]


def _labels(script: Path) -> set[str]:
    text = script.read_text(encoding="utf-8")
    return set(re.findall(r"^\s*([a-z][a-z0-9-]*)\)", text, flags=re.M))


def test_every_named_step_exists_in_its_script():
    for helper, (pattern, script, minimum) in HELPERS.items():
        steps = _uses(pattern)
        assert len(steps) >= minimum, f"{helper}: only {sorted(steps)} found"
        labels = _labels(script)
        for step in sorted(steps):
            assert re.search(rf"^\s*{re.escape(step)}\)", script.read_text(encoding="utf-8"), re.M), (
                f"{helper} {step}: no case label in {script.name}"
            )
            assert step in labels


def test_runbook_defines_the_nut_helper_exactly():
    assert NUT_HELPER in RUNBOOK.read_text(encoding="utf-8").splitlines()


def test_runbook_names_the_required_steps():
    assert {"preflight", "install", "cron", "mirror", "verify", "rollback"} <= _uses(HELPERS["NUT"][0])
    assert {"preflight", "configure", "verify", "cron"} <= _uses(HELPERS["ANA"][0])
    assert {"baseline", "build", "preview", "apply", "verify", "rollback"} <= _uses(HELPERS["ROLL"][0])


def test_ssh_helper_uses_the_home_ssh_config():
    lines = [line for line in _text().splitlines() if line.startswith("SSH=")]
    assert lines == ['SSH="ssh -F $HOME/.ssh/config episteck-node1"   # $HOME expands here; '
                     "Git Bash's has no spaces"]


def test_staging_never_destroys_the_copy_a_rollback_needs():
    # A second staging run must not replace .prev, which C2's and C4's rollbacks put back (R20).
    text = _text()
    assert not re.search(r"rm -rf /var/lib/episteck/hermes-[a-z]+\.prev", text)
    for name, stage in (("hermes-nutrition", "C0"), ("hermes-ana", "C4")):
        body = _stage(stage)
        guard = (f"$SSH 'if [ -e /var/lib/episteck/{name}.prev ]; then echo \"refusing: "
                 f"/var/lib/episteck/{name}.prev exists; keep it")
        assert guard in body, name
        after = body[body.index(guard):]
        assert after.index("exit 1; fi;") < after.index(f"sudo -n mv /var/lib/episteck/{name} "
                                                       f"/var/lib/episteck/{name}.prev")
        # The extraction runs only when the move step succeeded.
        assert "' \\\n     && git archive $SHA deploy/hermes | $SSH" in after
    assert "release 1 copy the C4 rollback needs" in _stage("C4")
    # Every put-back of .prev is guarded, as C0's undo is (M23).
    for line in text.splitlines():
        if re.search(r"mv /var/lib/episteck/hermes-nutrition\.prev ", line):
            assert "if [ -d /var/lib/episteck/hermes-nutrition.prev ]; then" in line, line


def test_c2_has_the_mirror_decision_after_verify_and_before_c3():
    c2 = _stage("C2")
    decision = c2.index("**Owner decision: mirror the check-in into Ultron's chat.**")
    assert c2.index("NUT verify") < decision < len(c2)
    part = c2[decision:]
    assert "`NUT mirror on`" in part and "Finance's cron deliveries are then also mirrored" in part
    assert '"cierra el día" or "close today"' in part
    assert "upstream issue #118863" in part and "C3 step 7" in part and "C4" in part
    assert "#118863" in _stage("C3") and "#118863" in _stage("C4")
    assert "If `NUT mirror on` was run: `NUT mirror off`" in c2


def test_c2_states_the_next_dst_dates_and_lists_finances_job():
    c2 = _stage("C2")
    assert "**2027-03-28**" in c2 and "**2027-10-31**" in c2
    assert "Hermes v0.21.2 has no per-job timezone" in c2
    assert ("$SSH 'sudo -n runuser -u home-agent -- env HOME=/home/home-agent "
            "/home/home-agent/.hermes/hermes-agent/venv/bin/hermes cron list --all'") in c2
    assert "`olin-finance-pending` and `olin-nutrition-checkin` both listed" in c2
    assert "config.yaml differs from the install-time backup in <dir>; not touched" in c2
    assert "exits 1 after the gateway restart when anything warned" in c2


def test_counts_and_rollback_warnings_agree():
    text = _text()
    c3 = _stage("C3")
    checks = re.findall(r"^(\d)\. ", c3, re.M)
    assert checks == [str(n) for n in range(1, 8)]
    assert "**Verification:** all seven checks pass." in c3
    assert "- [ ] C3: all seven checks pass." in text
    for stage in ("C3", "C5"):
        assert "Do not roll back C1 or C2 while Ana's B6 mode changes are live" in _stage(stage), stage


def test_c0_c1_c3_c4_c5_wording():
    assert "install-time thresholds" in _stage("C0") and "recorded here, not a stop" in _stage("C0")
    assert "Ana's real release 1 row" in _stage("C1")
    c3 = _stage("C3")
    assert "refusal through the skill" in c3 and "covered by plan 1's tests" in c3
    c4 = _stage("C4")
    assert "except `ANA cron <HH:MM>` (Berlin time): always re-run it" in c4
    assert "Skip the parts already done." not in c4
    # So its rollback always puts the release 1 prompt back too.
    assert "cron <HH:MM>\"   # always: C4 re-created the check-in" in c4 and "only if C4" not in c4
    assert "pregnancy week 28" in _stage("C5") and "third-trimester supplement" in _stage("C5")
