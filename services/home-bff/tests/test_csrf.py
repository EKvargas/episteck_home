"""CSRF guard and runtime settings (H5)."""
from __future__ import annotations

import pytest

from home_bff import csrf
from home_bff.config import ConfigError, Settings

SECRET = "delegation-secret"
ORIGIN = "https://bff.home.episteck.com"


def _verify(**overrides):
    args = dict(
        session_id="sess-1",
        secret=SECRET,
        presented=csrf.token_for("sess-1", SECRET),
        origin=ORIGIN,
        sec_fetch_site=None,
        expected_origin=ORIGIN,
    )
    args.update(overrides)
    return csrf.verify(**args)


def test_valid_token_and_same_origin_passes():
    assert _verify() is True


def test_missing_origin_requires_same_origin_fetch_site():
    assert _verify(origin=None, sec_fetch_site="same-origin") is True
    assert _verify(origin=None, sec_fetch_site="cross-site") is False
    assert _verify(origin=None, sec_fetch_site="same-site") is False


def test_no_origin_and_no_fetch_site_fails():
    assert _verify(origin=None, sec_fetch_site=None) is False


@pytest.mark.parametrize("origin", ["https://evil.example", "null", "http://bff.home.episteck.com", ""])
def test_cross_site_origin_with_valid_token_fails(origin):
    assert _verify(origin=origin) is False


def test_same_origin_with_wrong_or_missing_token_fails():
    assert _verify(presented="0" * 64) is False
    assert _verify(presented=None) is False
    assert _verify(presented="") is False


def test_token_is_bound_to_session_and_secret():
    assert csrf.token_for("sess-1", SECRET) != csrf.token_for("sess-2", SECRET)
    assert csrf.token_for("sess-1", SECRET) != csrf.token_for("sess-1", "other")
    assert _verify(session_id="sess-2") is False


def test_origin_of_extracts_scheme_and_host():
    assert csrf.origin_of("https://bff.home.episteck.com/callback") == ORIGIN


BASE_ENV = {
    "BFF_REDIRECT_URI": "https://bff.home.episteck.com/callback",
    "HOME_BASE_URL": "https://home.example",
    "BFF_CLIENT_ID": "c", "BFF_CLIENT_SECRET": "s",
    "HOME_DELEGATION_SECRET": "d", "BFF_MINT_SOCKET_PATH": "/tmp/m.sock",
}


def _settings(monkeypatch, **extra):
    for key, value in {**BASE_ENV, **extra}.items():
        monkeypatch.setenv(key, value)
    return Settings.from_env()


def test_defaults(monkeypatch):
    monkeypatch.delenv("RUNTIME_LEGACY_BINDING", raising=False)
    monkeypatch.delenv("BFF_RUNTIME_GRANT_DAYS", raising=False)
    settings = _settings(monkeypatch)
    assert settings.runtime_legacy_binding is True
    assert settings.runtime_grant_days == 90


@pytest.mark.parametrize("raw,expected", [("on", True), ("TRUE", True), ("1", True),
                                          ("off", False), ("false", False), ("0", False)])
def test_legacy_flag_parsing(monkeypatch, raw, expected):
    assert _settings(monkeypatch, RUNTIME_LEGACY_BINDING=raw).runtime_legacy_binding is expected


def test_legacy_flag_rejects_garbage(monkeypatch):
    with pytest.raises(ConfigError):
        _settings(monkeypatch, RUNTIME_LEGACY_BINDING="maybe")


@pytest.mark.parametrize("raw", ["0", "91", "-1", "abc"])
def test_grant_days_bounds(monkeypatch, raw):
    with pytest.raises(ConfigError):
        _settings(monkeypatch, BFF_RUNTIME_GRANT_DAYS=raw)


def test_grant_days_accepts_30(monkeypatch):
    assert _settings(monkeypatch, BFF_RUNTIME_GRANT_DAYS="30").runtime_grant_days == 30


# Review fix C1: under Referrer-Policy no-referrer a real browser sends "Origin: null"
# on a same-origin form POST, together with Sec-Fetch-Site: same-origin.


def test_origin_null_with_same_origin_fetch_site_passes():
    assert _verify(origin="null", sec_fetch_site="same-origin") is True


def test_origin_null_without_fetch_metadata_fails():
    assert _verify(origin="null", sec_fetch_site=None) is False


@pytest.mark.parametrize("site", ["cross-site", "same-site", "none"])
def test_matching_origin_but_non_same_origin_fetch_site_fails(site):
    assert _verify(origin=ORIGIN, sec_fetch_site=site) is False


def test_foreign_origin_fails_even_if_fetch_site_claims_same_origin():
    assert _verify(origin="https://evil.example", sec_fetch_site="same-origin") is False
