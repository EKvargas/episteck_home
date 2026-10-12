from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY = (ROOT / "episteck-gateway.nft").read_text(encoding="utf-8")
RENDER = (ROOT / "render-nft.sh").read_text(encoding="utf-8")


def test_policy_uses_numeric_sender_uid_controls_in_output():
    assert "table inet episteck_gateway" in POLICY
    assert "type filter hook output" in POLICY
    assert "meta skuid $HERMES_UID accept" in POLICY
    assert "meta skuid $GATEWAY_UID accept" in POLICY
    assert "tcp dport 9934 drop" in POLICY
    assert "tcp dport { 9931, 9932, 9936 } drop" in POLICY
    assert "flush ruleset" not in POLICY


def test_render_step_resolves_and_records_only_numeric_gateway_uid():
    assert "id -u svc-home-gateway" in RENDER
    assert "__SVC_HOME_GATEWAY_UID__" in POLICY
    assert "sed" in RENDER
    assert "nft --" not in RENDER


def test_policy_mutation_would_remove_the_required_deny():
    mutated = POLICY.replace("tcp dport 9934 drop", "", 1)
    assert "tcp dport 9934 drop" in POLICY
    assert "tcp dport 9934 drop" not in mutated


def test_9936_is_reachable_by_the_gateway_uid_only():
    lines = [l.strip() for l in POLICY.splitlines() if "9936" in l]
    assert lines == [
        "ip daddr 127.0.0.1 tcp dport { 9931, 9932, 9936 } meta skuid $GATEWAY_UID accept",
        "ip daddr 127.0.0.1 tcp dport { 9931, 9932, 9936 } drop",
    ]
    assert "$HERMES_UID" not in "".join(lines)


def test_no_other_ports_or_wildcards_are_widened():
    import re

    ports = set(re.findall(r"tcp dport (?:\{ ([\d, ]+) \}|(\d+))", POLICY))
    flat = {p for pair in ports for g in pair for p in g.replace(" ", "").split(",") if p}
    assert flat == {"9931", "9932", "9934", "9936"}
    assert POLICY.count("ip daddr 127.0.0.1") == 4
    assert "0.0.0.0" not in POLICY and "daddr any" not in POLICY
