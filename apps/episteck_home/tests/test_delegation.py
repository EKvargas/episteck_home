"""Pure adversarial tests for delegated human context verification (G1.6)."""
from __future__ import annotations

import pytest

from episteck_home.identity.delegation import (
    CLOCK_SKEW_SECONDS,
    MAX_LIFETIME_SECONDS,
    sign,
    verify,
)

SECRET = "delegation-secret-for-tests"
ISSUER = "episteck-home-bff"
AUDIENCE = "home-control-plane"
NOW = 1_700_000_000


def _claims(**overrides):
    base = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": NOW,
        "exp": NOW + 120,
        "jti": "tok-1",
        "sid": "sess-abc",
    }
    base.update(overrides)
    return base


def _verify(token, *, now=NOW, audience=AUDIENCE, secret=SECRET, seen=None):
    return verify(
        token,
        secret=secret,
        expected_issuer=ISSUER,
        expected_audience=audience,
        now=now,
        seen_token_ids=seen,
    )


def test_valid_token_yields_session_not_person():
    result = _verify(sign(_claims(), SECRET))
    assert result.valid is True
    assert result.context.session_id == "sess-abc"
    # The token must never be able to name a Person.
    assert not hasattr(result.context, "person_id")
    assert not hasattr(result.context, "actor_person_id")


def test_person_id_claim_is_ignored_and_never_surfaces():
    """Even if an attacker stuffs a Person id in, it cannot become the actor."""
    token = sign(_claims(actor_person_id="PSN-00001", person_id="PSN-00001"), SECRET)
    result = _verify(token)
    assert result.valid is True
    assert result.context.session_id == "sess-abc"
    assert "PSN-00001" not in str(result.context)


def test_tampered_payload_is_rejected():
    token = sign(_claims(), SECRET)
    body, _, signature = token.partition(".")
    forged = sign(_claims(sid="sess-victim"), "attacker-secret").partition(".")[0]
    assert not _verify(f"{forged}.{signature}").valid


def test_wrong_secret_is_rejected():
    assert not _verify(sign(_claims(), "other-secret")).valid


def test_wrong_issuer_is_rejected():
    assert not _verify(sign(_claims(iss="evil-issuer"), SECRET)).valid


def test_audience_binding_prevents_cross_service_replay():
    """A token minted for Nutrition must not work at the Control Plane."""
    token = sign(_claims(aud="svc-nutrition"), SECRET)
    assert not _verify(token, audience="home-control-plane").valid


def test_expired_token_is_rejected():
    token = sign(_claims(iat=NOW - 300, exp=NOW - 1), SECRET)
    assert not _verify(token, now=NOW).valid


def test_token_valid_until_the_instant_it_expires():
    token = sign(_claims(iat=NOW, exp=NOW + 60), SECRET)
    assert _verify(token, now=NOW + 59).valid is True
    assert not _verify(token, now=NOW + 60).valid


def test_future_token_beyond_skew_is_rejected():
    token = sign(_claims(iat=NOW + 600, exp=NOW + 700), SECRET)
    assert not _verify(token, now=NOW).valid


def test_small_clock_skew_is_tolerated():
    token = sign(_claims(iat=NOW + CLOCK_SKEW_SECONDS - 5, exp=NOW + 120), SECRET)
    assert _verify(token, now=NOW).valid is True


def test_overlong_lifetime_is_rejected():
    """A misconfigured issuer must not be able to widen the replay window."""
    token = sign(_claims(iat=NOW, exp=NOW + MAX_LIFETIME_SECONDS + 1), SECRET)
    assert not _verify(token, now=NOW).valid


def test_replayed_token_id_is_rejected():
    token = sign(_claims(jti="tok-replay"), SECRET)
    assert _verify(token, seen=set()).valid is True
    assert not _verify(token, seen={"tok-replay"}).valid


@pytest.mark.parametrize("claim", ["iss", "aud", "iat", "exp", "jti", "sid"])
def test_missing_required_claim_is_rejected(claim):
    payload = _claims()
    payload.pop(claim)
    assert not _verify(sign(payload, SECRET)).valid


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_session_is_rejected(blank):
    assert not _verify(sign(_claims(sid=blank), SECRET)).valid


@pytest.mark.parametrize(
    "token", [None, "", "garbage", "no-dot", "a.b.c", ".", "x."]
)
def test_malformed_tokens_are_rejected_without_raising(token):
    assert not _verify(token).valid


def test_missing_secret_fails_closed():
    assert not _verify(sign(_claims(), SECRET), secret=None).valid


def test_non_integer_validity_is_rejected():
    assert not _verify(sign(_claims(exp="soon"), SECRET)).valid
    assert not _verify(sign(_claims(iat=True, exp=False), SECRET)).valid


def test_inverted_window_is_rejected():
    assert not _verify(sign(_claims(iat=NOW, exp=NOW - 10), SECRET)).valid
