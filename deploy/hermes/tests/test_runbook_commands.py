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
    text = RUNBOOK.read_text(encoding="utf-8")
    # The helper definitions are not uses: drop the fenced line starting with "NUT() {" etc.
    return set(re.findall(pattern, text))


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
    assert {"preflight", "install", "cron", "verify", "rollback"} <= _uses(HELPERS["NUT"][0])
    assert {"preflight", "configure", "verify", "cron"} <= _uses(HELPERS["ANA"][0])
    assert {"baseline", "build", "preview", "apply", "verify", "rollback"} <= _uses(HELPERS["ROLL"][0])
