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


def test_finance_api_port_is_reachable_only_by_nginx_www_data():
    """B11 F1: only nginx (www-data) serves the public PSD2 callback to 127.0.0.1:9935."""
    accept = "ip daddr 127.0.0.1 tcp dport 9935 meta skuid $WWW_DATA_UID accept"
    drop = "ip daddr 127.0.0.1 tcp dport 9935 drop"
    assert accept in POLICY and drop in POLICY
    assert POLICY.index(accept) < POLICY.index(drop)
    assert "define WWW_DATA_UID = __WWW_DATA_UID__" in POLICY


def test_render_step_resolves_the_numeric_www_data_uid():
    assert "id -u www-data" in RENDER
    assert "__WWW_DATA_UID__" in RENDER


def test_finance_mcp_port_is_reachable_only_by_the_gateway_uid():
    accept = "ip daddr 127.0.0.1 tcp dport { 9931, 9932, 9936 } meta skuid $GATEWAY_UID accept"
    drop = "ip daddr 127.0.0.1 tcp dport { 9931, 9932, 9936 } drop"
    assert POLICY.index(accept) < POLICY.index(drop)
