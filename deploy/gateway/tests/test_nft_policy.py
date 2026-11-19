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


BOOT_UNIT = (ROOT / "episteck-gateway-nft.service").read_text(encoding="utf-8")


def test_boot_unit_loads_only_the_dedicated_table_before_the_gateway():
    """The table must survive a reboot, without ever flushing ufw's ruleset."""
    assert "ExecStart=/usr/sbin/nft -f /etc/episteck/nft/episteck-gateway.nft" in BOOT_UNIT
    assert "Before=network-pre.target shutdown.target episteck-mcp-gateway.service" in BOOT_UNIT
    assert "WantedBy=multi-user.target" in BOOT_UNIT
    assert "Type=oneshot" in BOOT_UNIT and "RemainAfterExit=yes" in BOOT_UNIT
    assert "flush" not in BOOT_UNIT.replace("never flushes", "")


def test_finance_mcp_port_is_reachable_only_by_the_gateway_uid():
    accept = "ip daddr 127.0.0.1 tcp dport { 9931, 9932, 9936 } meta skuid $GATEWAY_UID accept"
    drop = "ip daddr 127.0.0.1 tcp dport { 9931, 9932, 9936 } drop"
    assert POLICY.index(accept) < POLICY.index(drop)


def test_ana_port_is_reachable_only_by_ana_uid():
    accept = "ip daddr 127.0.0.1 tcp dport 9937 meta skuid $ANA_UID accept"
    drop = "ip daddr 127.0.0.1 tcp dport 9937 drop"
    assert accept in POLICY and drop in POLICY
    assert POLICY.index(accept) < POLICY.index(drop)
    assert "define ANA_UID = __HOME_AGENT_ANA_UID__" in POLICY


def test_owner_and_ana_never_cross():
    for line in POLICY.splitlines():
        if "accept" not in line:
            continue
        if "dport 9934" in line:
            assert "$ANA_UID" not in line
        if "dport 9937" in line:
            assert "$HERMES_UID" not in line


def test_render_step_resolves_the_numeric_ana_uid():
    assert "id -u home-agent-ana" in RENDER
    assert "__HOME_AGENT_ANA_UID__" in RENDER
    assert "ana_uid" in RENDER and "not numeric" in RENDER


def test_render_step_refuses_an_ana_uid_that_collides_with_a_reserved_uid():
    """Ana's uid must never be root, Hermes (1003), the gateway or www-data."""
    assert 'case "$ana_uid" in' in RENDER
    assert '0|1003|"$gateway_uid"|"$www_data_uid")' in RENDER
    assert "home-agent-ana uid collides with a reserved uid" in RENDER
    # The collision check runs after the numeric checks and before anything is rendered.
    numeric = RENDER.index("not numeric")
    collision = RENDER.index("home-agent-ana uid collides with a reserved uid")
    assert numeric < collision < RENDER.index("sed ")
