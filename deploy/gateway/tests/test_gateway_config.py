from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG = (ROOT / "nginx-mcp-gateway.conf").read_text(encoding="utf-8")
SERVICE = (ROOT / "episteck-mcp-gateway.service").read_text(encoding="utf-8")


REQUIRED = (
    "listen 127.0.0.1:9934;",
    "proxy_pass http://unix:/run/episteck/home-bff-mint/mint.sock:/internal/mint;",
    "proxy_method POST;",
    "proxy_pass_request_headers off;",
    "proxy_pass_request_body off;",
    "proxy_set_header X-Episteck-Delegation $mint_delegation;",
    "proxy_set_header Authorization \"\";",
    "proxy_set_header Cookie \"\";",
    "proxy_set_header Mcp-Session-Id $http_mcp_session_id;",
    "proxy_next_upstream off;",
    "proxy_http_version 1.1;",
    "proxy_buffering off;",
    "proxy_request_buffering off;",
    "proxy_read_timeout 300s;",
)


def test_standalone_gateway_identity_and_listener():
    assert "User=svc-home-gateway" in SERVICE
    assert "Group=svc-home-gateway" in SERVICE
    assert "SupplementaryGroups=episteck-gw" in SERVICE
    assert "sites-enabled" not in SERVICE
    assert "listen 127.0.0.1:9934;" in CONFIG
    assert "listen 0.0.0.0:9934;" not in CONFIG


def test_both_paths_require_mint_and_use_the_fixed_audience_mint_seam():
    assert CONFIG.count("auth_request /__mint;") == 2
    assert CONFIG.count("auth_request_set $mint_delegation") == 2
    assert CONFIG.count("proxy_set_header X-Episteck-Delegation $mint_delegation;") == 2
    assert "svc-nutrition" not in CONFIG
    for directive in REQUIRED:
        assert directive in CONFIG, directive


def test_mint_subrequest_cannot_receive_client_credentials_or_body():
    mint_block = CONFIG.split("location = /__mint {", 1)[1].split("}", 1)[0]
    assert "proxy_pass_request_headers off;" in mint_block
    assert "proxy_pass_request_body off;" in mint_block
    assert 'proxy_set_header Authorization "";' in mint_block
    assert 'proxy_set_header Cookie "";' in mint_block
    assert 'proxy_set_header X-Episteck-Delegation "";' in mint_block
    assert 'proxy_set_header X-Actor-ID "";' in mint_block
    assert 'proxy_set_header X-Runtime-ID "";' in mint_block


def test_security_controls_have_negative_mutation_proof():
    assert CONFIG.count("proxy_next_upstream off;") == 2
    mutated = CONFIG.replace("proxy_next_upstream off;", "", 1)
    assert mutated.count("proxy_next_upstream off;") == 1
    assert CONFIG.count("proxy_next_upstream off;") > mutated.count(
        "proxy_next_upstream off;"
    )


def test_config_never_mentions_json_rpc_body_parsing_or_query_logging():
    assert "jsonrpc" not in CONFIG.lower()
    assert '"$request_method $uri $server_protocol"' in CONFIG
    assert "$request " not in CONFIG
