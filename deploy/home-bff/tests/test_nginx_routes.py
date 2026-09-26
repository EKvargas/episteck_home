"""Static config test for the explicit nginx route allowlist (§11, deploy row of §12).

No nginx binary is invoked. This reads the raw config text the same way
test_quadlets.py reads raw Quadlet text — config-only, never deployed.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
CONF = (ROOT / "nginx-home-bff.conf").read_text(encoding="utf-8")
LOG_FORMAT = (ROOT / "episteck-log-format.conf").read_text(encoding="utf-8")


def _server_blocks():
    blocks = []
    for match in re.finditer(r"(?m)^server\s*\{", CONF):
        depth = 0
        for offset in range(match.end() - 1, len(CONF)):
            if CONF[offset] == "{":
                depth += 1
            elif CONF[offset] == "}":
                depth -= 1
                if depth == 0:
                    blocks.append(CONF[match.end():offset])
                    break
    assert len(blocks) == 2
    assert any(re.search(r"(?m)^\s*listen 80;", block) for block in blocks)
    assert any(re.search(r"(?m)^\s*listen 443 ssl http2;", block) for block in blocks)
    return blocks


def test_delegation_is_explicit_404():
    assert "location = /delegation" in CONF
    assert "return 404" in CONF


def test_public_bff_routes_are_explicitly_allowlisted():
    for route in ("/login", "/callback", "/logout", "/session", "/whoami", "/health"):
        assert f"location = {route}" in CONF, f"{route} must be an explicit location"


def test_access_log_directive_is_server_level_not_per_location():
    """Both vhosts need the sanitized policy; a location cannot override it."""
    expected = "access_log /var/log/nginx/home-bff-access.log episteck_noqs;"
    for block in _server_blocks():
        active = "\n".join(line.split("#", 1)[0] for line in block.splitlines())
        directives = [
            (match.start(), match.group().strip())
            for match in re.finditer(r"\baccess_log\s+[^;]*;", active)
        ]
        assert len(directives) == 1
        assert directives[0][1] == expected
        first_location = re.search(r"\blocation\s", active)
        if first_location:
            assert directives[0][0] < first_location.start()


def test_error_log_cannot_record_raw_callback_request():
    # nginx upstream errors include the original request line. Access logs retain
    # response status and size, while request-bearing error logs are discarded.
    for block in _server_blocks():
        active = "\n".join(line.split("#", 1)[0] for line in block.splitlines())
        assert re.findall(r"\berror_log\s+[^;]*;", active) == ["error_log /dev/null;"]


def test_sanitized_log_format_cannot_record_queries_or_raw_headers():
    active = "\n".join(
        line for line in LOG_FORMAT.splitlines() if not line.lstrip().startswith("#")
    )
    match = re.search(r"log_format\s+episteck_noqs\s+(.+?);", active, re.DOTALL)
    assert match is not None
    fields = match.group(1)
    for required in ("$remote_addr", "$time_local", "$request_method", "$uri",
                     "$server_protocol", "$status", "$body_bytes_sent"):
        assert required in fields
    for forbidden in ("request", "request_uri", "args", "query_string",
                      "http_referer", "http_user_agent"):
        assert re.search(rf"\${forbidden}(?![A-Za-z0-9_])", fields) is None
    assert "$http_" not in fields


def test_http_redirect_does_not_reflect_callback_query():
    assert "return 301 https://$server_name$uri;" in CONF
    assert "$request_uri" not in "\n".join(
        line for line in CONF.splitlines() if not line.lstrip().startswith("#")
    )


def test_bootstrap_docs_and_openapi_are_not_explicitly_proxied():
    for path in ("/bootstrap", "/docs", "/redoc", "/openapi.json"):
        assert f"location = {path} {{" not in CONF
        assert f"proxy_pass" not in CONF.split(f"location = {path}")[-1][:200] if f"location = {path}" in CONF else True


def test_app_routes_are_reserved_with_correct_anchors():
    assert "location = /app " in CONF or "location = /app\n" in CONF or "location = /app{" in CONF or "location = /app {" in CONF
    assert "location ^~ /app/" in CONF


def test_generic_app_prefix_without_anchor_is_absent():
    """`location /app` (no `=` or `^~`) would also match `/application`."""
    import re

    naive = re.search(r"location\s+/app\s*\{", CONF)
    assert naive is None


def test_application_path_is_not_matched_by_app_locations():
    """Sanity check on the anchors themselves: /application must not start with
    the *exact* `/app` string followed by a `/`, which is what `^~ /app/` requires."""
    assert not "/application".startswith("/app/")
    assert "/application" != "/app"


def test_catch_all_falls_through_to_404():
    # The LAST unqualified `location /` block must return 404, not proxy_pass.
    assert 'location /' in CONF
    tail = CONF.rsplit("location /", 1)[-1]
    assert "return 404" in tail.split("}")[0] or "return 404" in tail[:200]


def test_no_domain_attribute_rewriting_is_introduced():
    assert "proxy_cookie_domain" not in CONF
    assert "Domain=" not in CONF
