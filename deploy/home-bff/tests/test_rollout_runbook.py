import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")
GATEWAY_README = (ROOT.parent / "gateway" / "README.md").read_text(encoding="utf-8")
START = README.index("### Per-person runtimes rollout")
END = README.index("### Transition flag")
SECTION = README[START:END]
NGINX_TEST = "sudo -u svc-home-gateway nginx -e /dev/stderr -t"


def flat(text):
    return re.sub(r"\s+", " ", text)


def test_every_nginx_test_runs_as_the_gateway_user():
    assert "nginx -t" not in SECTION
    assert SECTION.count(NGINX_TEST) >= 2
    for match in re.finditer(r"nginx -e /dev/stderr -t", SECTION):
        assert SECTION[: match.end()].endswith(NGINX_TEST)
    assert "nginx -t" not in GATEWAY_README
    assert GATEWAY_README.count(NGINX_TEST) >= 2


def test_rollback_61_has_a_before_and_an_after_3_3_case():
    start = SECTION.index("6. Rollback")
    rollback = flat(SECTION[start:])
    before = rollback.index("Before 3.3")
    after = rollback.index("After 3.3")
    assert before < after
    before_case = rollback[before:after]
    after_case = rollback[after:]
    assert "sudo rm /etc/episteck/mcp-gateway/nginx-mcp-gateway.conf.new" in before_case
    assert "no `.old`" in before_case
    assert "nginx-mcp-gateway.conf.old" not in before_case
    old = after_case.index("nginx-mcp-gateway.conf.old")
    reload = after_case.index("systemctl reload episteck-mcp-gateway.service")
    remove = after_case.index("sudo rm /etc/episteck/mcp-gateway/nginx-mcp-gateway.conf.new")
    assert old < reload < remove


def test_precondition_names_the_owner_hermes_user_and_the_id_checks():
    pre = flat(SECTION[: SECTION.index("**Staging commands.**")])
    assert "the owner's Hermes user (uid 1003)" in pre
    assert "`id home-agent-ana`" in pre
    assert "`id home-agent`" in pre
    assert "no `episteck-gw`" in pre


def test_step_3_2_previews_then_applies_the_bff_image():
    step = flat(SECTION[SECTION.index("2. The BFF image is built") : SECTION.index("3. Only now")])
    preview = step.index("deploy/ops/image-rollout.sh home-bff preview <SHA>")
    apply = step.index("deploy/ops/image-rollout.sh home-bff apply <SHA>")
    assert preview < apply
    assert "Image=" in step and "RUNTIME_IDS" in step


def test_integration_precondition_names_the_container_run():
    pre = flat(SECTION[: SECTION.index("**Staging commands.**")])
    assert "ubuntu:26.04" in pre
    assert "Isolated integration harness" in pre


def test_gateway_readme_nft_rollback_never_deletes_the_table():
    text = flat(GATEWAY_README)
    assert "On test rollback delete only" not in text
    assert (
        "On rollback, restore the previous boot file and restart "
        "episteck-gateway-nft.service. Never delete the table at runtime (that drops "
        "every rule until the next boot) and never flush the global ruleset."
    ) in text


def test_wsl_run_does_not_satisfy_the_container_precondition():
    pre = flat(SECTION[: SECTION.index("**Staging commands.**")])
    assert "does NOT satisfy this precondition" in pre
    assert "must pass before step 3.3" in pre
    assert "(WSL Ubuntu 24.04, nginx 1.24.0)" in pre
    gateway = flat(GATEWAY_README)
    assert "still to do before step 3.3" in gateway
    assert "docker run --rm" in gateway and "ubuntu:26.04" in gateway


def test_step_3_2_builds_before_the_window_and_only_previews_then_applies():
    step = flat(SECTION[SECTION.index("2. The BFF image is built") : SECTION.index("3. Only now")])
    assert "before the window" in step
    assert "deploy/ops/image-rollout.sh home-bff build <SHA>" in step
    assert "deploy/ops/README.md" in step
    assert "only runs preview, then apply" in step
