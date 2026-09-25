"""Login-binding cookie primitives (F2a-BFF, B3 / §9)."""
from __future__ import annotations

from home_bff import sessions


def test_login_binding_cookie_name_uses_host_prefix():
    assert sessions.LOGIN_BINDING_COOKIE_NAME == "__Host-episteck_home_login"


def test_login_binding_cookie_flags_have_no_domain():
    flags = sessions.LOGIN_BINDING_COOKIE_FLAGS
    assert flags["httponly"] is True
    assert flags["secure"] is True
    assert flags["samesite"] == "lax"
    assert flags["path"] == "/"
    assert "domain" not in flags


def test_login_binding_max_age_is_ten_minutes():
    assert sessions.LOGIN_BINDING_MAX_AGE_SECONDS == 600


def test_new_login_binding_is_random_and_unique():
    values = {sessions.new_login_binding() for _ in range(10)}
    assert len(values) == 10
    assert all(len(v) >= 32 for v in values)


def test_hash_login_binding_is_sha256_hex():
    import hashlib

    value = "some-binding-value"
    expected = hashlib.sha256(value.encode()).hexdigest()
    assert sessions.hash_login_binding(value) == expected


def test_hash_login_binding_is_deterministic():
    value = sessions.new_login_binding()
    assert sessions.hash_login_binding(value) == sessions.hash_login_binding(value)


def test_different_bindings_hash_differently():
    a, b = sessions.new_login_binding(), sessions.new_login_binding()
    assert sessions.hash_login_binding(a) != sessions.hash_login_binding(b)
