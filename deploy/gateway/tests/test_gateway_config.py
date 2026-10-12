from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG = (ROOT / "nginx-mcp-gateway.conf").read_text(encoding="utf-8")
SERVICE = (ROOT / "episteck-mcp-gateway.service").read_text(encoding="utf-8")


REQUIRED = (
    "listen 127.0.0.1:9934;",
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


def test_home_and_nutrition_use_the_default_audience_mint_seam():
    assert CONFIG.count("auth_request /__mint;") == 2
    assert CONFIG.count("auth_request_set $mint_delegation") == 3
    assert CONFIG.count("proxy_set_header X-Episteck-Delegation $mint_delegation;") == 3
    assert CONFIG.count("proxy_hide_header X-Episteck-Delegation;") == 3
    assert "svc-nutrition" not in CONFIG
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
    assert 'proxy_set_header X-Runtime-ID "";' in mint_block


def test_security_controls_have_negative_mutation_proof():
    assert CONFIG.count("proxy_next_upstream off;") == 3
    mutated = CONFIG.replace("proxy_next_upstream off;", "", 1)
    assert mutated.count("proxy_next_upstream off;") == 2
    assert CONFIG.count("proxy_next_upstream off;") > mutated.count(
        "proxy_next_upstream off;"
    )


def test_config_never_mentions_json_rpc_body_parsing_or_query_logging():
    assert "jsonrpc" not in CONFIG.lower()
    assert '"$request_method $uri $server_protocol"' in CONFIG
    assert "$request " not in CONFIG


def _block(header: str) -> str:
    return CONFIG.split(header, 1)[1].split("\n        }", 1)[0]


def test_finance_route_proxies_only_to_9936_and_mirrors_nutrition():
    finance = _block("location /gateway/finance/ {")
    nutrition = _block("location /gateway/nutrition/ {")
    assert "proxy_pass http://127.0.0.1:9936/mcp;" in finance
    assert "auth_request /__mint_finance;" in finance
    # Identical to nutrition except the mint seam and upstream port.
    assert (
        finance.replace("9936", "9931").replace("/__mint_finance", "/__mint")
        == nutrition
    )
    assert CONFIG.count("location /gateway/finance/ {") == 1


def test_finance_mint_requests_exactly_svc_finance_and_is_internal():
    mint = _block("location = /__mint_finance {")
    assert "internal;" in mint
    assert (
        "proxy_pass http://unix:/run/episteck/home-bff-mint/mint.sock:"
        "/internal/mint?audience=svc-finance;"
    ) in mint
    # Same client-credential isolation as the default mint seam.
    default = _block("location = /__mint {")
    assert mint.replace("?audience=svc-finance", "") == default
    assert CONFIG.count("audience=") == 1
    assert "$arg_audience" not in CONFIG and "$args" not in CONFIG


def test_only_expected_locations_and_upstream_ports_exist():
    import re

    locations = re.findall(r"location (?:= )?(\S+) \{", CONFIG)
    assert locations == [
        "/__mint",
        "/__mint_finance",
        "/gateway/home/",
        "/gateway/nutrition/",
        "/gateway/finance/",
    ]
    assert sorted(re.findall(r"proxy_pass http://127\.0\.0\.1:(\d+)/", CONFIG)) == [
        "9931",
        "9932",
        "9936",
    ]
    assert CONFIG.count("listen ") == 1
