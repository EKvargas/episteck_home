import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG = (ROOT / "nginx-mcp-gateway.conf").read_text(encoding="utf-8")
SERVICE = (ROOT / "episteck-mcp-gateway.service").read_text(encoding="utf-8")


_SERVERS = CONFIG.split("server {")[1:]
assert len(_SERVERS) == 2
PRIMARY_SERVER, ANA_SERVER = _SERVERS

REQUIRED = (
    "listen 127.0.0.1:9934;",
    "listen 127.0.0.1:9937;",
    "pid /run/episteck-mcp-gateway/nginx.pid;",
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

RUNTIME_PATHS = (
    "client_body_temp_path /run/episteck-mcp-gateway/client_body;",
    "proxy_temp_path /run/episteck-mcp-gateway/proxy;",
    "fastcgi_temp_path /run/episteck-mcp-gateway/fastcgi;",
    "uwsgi_temp_path /run/episteck-mcp-gateway/uwsgi;",
    "scgi_temp_path /run/episteck-mcp-gateway/scgi;",
)


def test_standalone_gateway_identity_and_listener():
    assert "User=svc-home-gateway" in SERVICE
    assert "Group=svc-home-gateway" in SERVICE
    assert "SupplementaryGroups=episteck-gw" in SERVICE
    assert "sites-enabled" not in SERVICE
    assert "listen 127.0.0.1:9934;" in CONFIG
    assert "listen 0.0.0.0:9934;" not in CONFIG


def test_all_paths_require_mint_and_use_the_fixed_audience_mint_seam():
    assert CONFIG.count("auth_request /__mint;") == 4
    assert CONFIG.count("auth_request /__mint_finance;") == 1
    assert CONFIG.count("auth_request_set $mint_delegation") == 5
    assert CONFIG.count("proxy_set_header X-Episteck-Delegation $mint_delegation;") == 5
    assert CONFIG.count("proxy_hide_header X-Episteck-Delegation;") == 5
    assert "svc-nutrition" not in CONFIG
    assert "svc-finance" not in CONFIG
    for directive in REQUIRED:
        assert directive in CONFIG, directive


def test_all_nginx_runtime_state_uses_the_dedicated_service_directories():
    assert "RuntimeDirectory=episteck-mcp-gateway" in SERVICE
    assert "StateDirectory=episteck-mcp-gateway" in SERVICE
    for directive in RUNTIME_PATHS:
        assert directive in CONFIG, directive
    assert "logs/nginx.pid" not in CONFIG


def test_mint_subrequest_cannot_receive_client_credentials_or_body():
    mint_block = CONFIG.split("location = /__mint {", 1)[1].split("}", 1)[0]
    assert "proxy_pass_request_headers off;" in mint_block
    assert "proxy_pass_request_body off;" in mint_block
    assert 'proxy_set_header Authorization "";' in mint_block
    assert 'proxy_set_header Cookie "";' in mint_block
    assert 'proxy_set_header X-Episteck-Delegation "";' in mint_block
    assert 'proxy_set_header X-Actor-ID "";' in mint_block
    assert 'proxy_set_header X-Runtime-ID "home-agent-primary";' in mint_block
    ana_block = ANA_SERVER.split("location = /__mint {", 1)[1].split("}", 1)[0]
    assert 'proxy_set_header X-Runtime-ID "home-agent-ana";' in ana_block
    assert 'proxy_set_header X-Runtime-ID ""' not in CONFIG


def test_security_controls_have_negative_mutation_proof():
    assert CONFIG.count("proxy_next_upstream off;") == 5
    mutated = CONFIG.replace("proxy_next_upstream off;", "", 1)
    assert mutated.count("proxy_next_upstream off;") == 4
    assert CONFIG.count("proxy_next_upstream off;") > mutated.count(
        "proxy_next_upstream off;"
    )


def test_config_never_mentions_json_rpc_body_parsing_or_query_logging():
    assert "jsonrpc" not in CONFIG.lower()
    assert '"$request_method $uri $server_protocol"' in CONFIG
    assert "$request " not in CONFIG


def test_finance_route_uses_only_the_finance_mint_and_finance_upstream():
    block = CONFIG.split("location /gateway/finance/ {", 1)[1].split(chr(10) + "        }", 1)[0]
    assert "auth_request /__mint_finance;" in block
    assert "auth_request /__mint;" not in block
    assert "proxy_pass http://127.0.0.1:9936/mcp;" in block
    assert "proxy_hide_header X-Episteck-Delegation;" in block
    assert 'proxy_set_header Authorization "";' in block
    assert 'proxy_set_header Cookie "";' in block


def test_other_routes_never_use_the_finance_mint():
    for route in ("/gateway/home/", "/gateway/nutrition/"):
        block = CONFIG.split(f"location {route} {{", 1)[1].split(chr(10) + "        }", 1)[0]
        assert "__mint_finance" not in block


def test_finance_mint_subrequest_cannot_receive_client_credentials_or_body():
    block = CONFIG.split("location = /__mint_finance {", 1)[1].split("}", 1)[0]
    assert "internal;" in block
    assert "proxy_pass http://unix:/run/episteck/home-bff-mint/mint.sock:/internal/mint_finance;" in block
    assert "proxy_pass_request_headers off;" in block
    assert "proxy_pass_request_body off;" in block
    for header in ("Authorization", "Cookie", "X-Episteck-Delegation", "X-Actor-ID"):
        assert f'proxy_set_header {header} "";' in block
    assert 'proxy_set_header X-Runtime-ID "home-agent-primary";' in block


def test_each_server_stamps_its_own_runtime_on_the_mint():
    assert "listen 127.0.0.1:9934;" in PRIMARY_SERVER
    assert PRIMARY_SERVER.count('X-Runtime-ID "home-agent-primary"') == 2
    assert "home-agent-ana" not in PRIMARY_SERVER
    assert "listen 127.0.0.1:9937;" in ANA_SERVER
    assert ANA_SERVER.count('X-Runtime-ID "home-agent-ana"') == 1
    assert "home-agent-primary" not in ANA_SERVER


def test_ana_server_has_no_finance_route_or_mint():
    assert "finance" not in ANA_SERVER.lower()
    assert "9936" not in ANA_SERVER
    assert "/gateway/home/" in ANA_SERVER
    assert "/gateway/nutrition/" in ANA_SERVER


def test_every_mint_block_drops_client_headers():
    blocks = re.findall(r"location = /__mint(?:_finance)? \{(.*?)\}", CONFIG, re.S)
    assert len(blocks) == 3
    for block in blocks:
        assert "proxy_pass_request_headers off;" in block
        assert "proxy_pass_request_body off;" in block


def test_listeners_are_loopback_only():
    # [^;]+ captures any listen options too, so an extra listener or flag is caught.
    assert re.findall(r"^\s*listen\s+([^;]+);", CONFIG, re.M) == [
        "127.0.0.1:9934",
        "127.0.0.1:9937",
    ]
    assert "0.0.0.0" not in CONFIG


def _location_body(server: str, spec: str) -> str:
    """The body of exactly one location block (location blocks hold no nested braces)."""
    found = re.findall(r"location\s+" + re.escape(spec) + r"\s*\{(.*?)\}", server, re.S)
    assert len(found) == 1, spec
    return found[0]


def test_ana_server_blocks_equal_primary_blocks():
    """9937 is 9934 minus Finance: same mint and routes, only the stamped runtime differs."""
    for spec in ("= /__mint", "/gateway/home/", "/gateway/nutrition/"):
        primary = _location_body(PRIMARY_SERVER, spec)
        ana = _location_body(ANA_SERVER, spec)
        assert ana == primary.replace('"home-agent-primary"', '"home-agent-ana"'), spec


# The empty-header clears every 9934 mint block carries today.
MINT_CLEARED_HEADERS = {
    "Content-Length",
    "Authorization",
    "Cookie",
    "X-Episteck-Delegation",
    "X-Actor-ID",
}


def test_every_mint_block_is_internal_and_clears_credentials():
    blocks = [
        _location_body(server, spec)
        for server in (PRIMARY_SERVER, ANA_SERVER)
        for spec in ("= /__mint", "= /__mint_finance")
        if re.search(r"location\s+" + re.escape(spec) + r"\s*\{", server)
    ]
    assert len(blocks) == 3  # 9934: mint + finance mint; 9937: mint only
    for block in blocks:
        assert "internal;" in block
        cleared = set(re.findall(r'proxy_set_header\s+(\S+)\s+"";', block))
        assert cleared == MINT_CLEARED_HEADERS
        for header in MINT_CLEARED_HEADERS:
            assert f'proxy_set_header {header} "";' in block
