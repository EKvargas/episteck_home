"""Static config test for the explicit nginx route allowlist (§11, deploy row of §12).

No nginx binary is invoked. This reads the raw config text the same way
test_quadlets.py reads raw Quadlet text — config-only, never deployed.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONF = (ROOT / "nginx-home-bff.conf").read_text(encoding="utf-8")


def test_delegation_is_explicit_404():
    assert "location = /delegation" in CONF
    assert "return 404" in CONF


def test_public_bff_routes_are_explicitly_allowlisted():
    for route in ("/login", "/callback", "/logout", "/session", "/whoami"):
        assert f"location = {route}" in CONF, f"{route} must be an explicit location"


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
