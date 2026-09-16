"""Home BFF: PKCE, session, and delegation minting (G1.6).

These tests also prove round-trip compatibility with the Control Plane verifier: a
token minted here must verify there, and must fail there under every adversarial
condition.
"""
from __future__ import annotations

import base64
import hashlib
import sys
from pathlib import Path

import pytest

from home_bff import oauth, sessions

# Verify against the REAL Control Plane verifier, not a copy of it.
sys.path.insert(
    0, str(Path(__file__).resolve().parents[3] / "apps" / "episteck_home")
)
from episteck_home.identity.delegation import verify  # noqa: E402

SECRET = "shared-delegation-secret"


# --------------------------------------------------------------------------
# PKCE
# --------------------------------------------------------------------------


def test_pkce_pair_is_s256_and_matches_frappe_computation():
    pair = oauth.new_pkce_pair()
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(pair.verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    assert pair.challenge == expected
    assert pair.method == "S256"
    # Frappe's stored method is lowercased; padding must be stripped.
    assert "=" not in pair.challenge


def test_pkce_pairs_are_unique():
    pairs = {oauth.new_pkce_pair().verifier for _ in range(20)}
    assert len(pairs) == 20


def test_authorization_request_always_carries_s256_pkce():
    """The downgrade Frappe permits must be unreachable from this client."""
    params = oauth.authorization_params(
        "client-1", "https://home.invalid/cb", oauth.new_pkce_pair(), oauth.new_state()
    )
    assert params["code_challenge_method"] == "S256"
    assert params["code_challenge"]
    assert params["response_type"] == "code"
    assert "code_challenge_method" in params and params["code_challenge_method"] != "plain"


def test_token_request_is_confidential_and_sends_the_verifier():
    params = oauth.token_request_params(
        "client-1", "top-secret", "the-code", "https://home.invalid/cb", "the-verifier"
    )
    assert params["client_secret"] == "top-secret"
    assert params["code_verifier"] == "the-verifier"
    assert params["grant_type"] == "authorization_code"


def test_wrong_verifier_produces_a_different_challenge():
    """The property Frappe checks: a mismatched verifier must not validate."""
    pair = oauth.new_pkce_pair()
    assert oauth.compute_challenge("some-other-verifier") != pair.challenge
    assert oauth.compute_challenge(pair.verifier) == pair.challenge


# --------------------------------------------------------------------------
# Sessions and cookie policy
# --------------------------------------------------------------------------


def test_session_ids_are_opaque_and_unique():
    ids = {sessions.new_session_id() for _ in range(50)}
    assert len(ids) == 50
    assert all(len(value) > 20 for value in ids)


def test_browser_cookie_is_httponly_secure_samesite():
    """Amendment A2: the browser holds no token material."""
    assert sessions.COOKIE_FLAGS["httponly"] is True
    assert sessions.COOKIE_FLAGS["secure"] is True
    assert sessions.COOKIE_FLAGS["samesite"] in {"lax", "strict"}


def test_redaction_never_reveals_credential_material():
    assert sessions.redact("super-secret-token") == "<redacted:18 chars>"
    assert "super-secret" not in sessions.redact("super-secret-token")
    assert sessions.redact(None) == "<none>"


# --------------------------------------------------------------------------
# Delegation minting -> Control Plane verification (round trip)
# --------------------------------------------------------------------------


def _verify(token, audience=sessions.AUDIENCE_CONTROL_PLANE, now=None, seen=None):
    return verify(
        token,
        secret=SECRET,
        expected_issuer=sessions.ISSUER,
        expected_audience=audience,
        now=now if now is not None else 1_700_000_000,
        seen_token_ids=seen,
    )


def test_minted_delegation_verifies_at_the_control_plane():
    minted = sessions.mint_delegation(
        "sess-1", sessions.AUDIENCE_CONTROL_PLANE, SECRET, now=1_700_000_000
    )
    result = _verify(minted.token)
    assert result.valid is True
    assert result.context.session_id == "sess-1"


def test_delegation_carries_no_person_identity():
    """The BFF cannot assert who the human is; only the Control Plane decides."""
    minted = sessions.mint_delegation(
        "sess-1", sessions.AUDIENCE_CONTROL_PLANE, SECRET, now=1_700_000_000
    )
    body = minted.token.partition(".")[0]
    padding = "=" * (-len(body) % 4)
    decoded = base64.urlsafe_b64decode(body + padding).decode()
    assert "PSN-" not in decoded
    assert "person" not in decoded.lower()


def test_audience_binding_blocks_cross_service_replay():
    """A Nutrition delegation must not work at the Control Plane, and vice versa."""
    for minted_for, presented_to in (
        (sessions.AUDIENCE_NUTRITION, sessions.AUDIENCE_CONTROL_PLANE),
        (sessions.AUDIENCE_CONTROL_PLANE, sessions.AUDIENCE_NUTRITION),
    ):
        minted = sessions.mint_delegation(
            "sess-1", minted_for, SECRET, now=1_700_000_000
        )
        assert not _verify(minted.token, audience=presented_to).valid


def test_unknown_audience_is_refused_at_mint_time():
    with pytest.raises(sessions.UnknownAudienceError):
        sessions.mint_delegation("sess-1", "svc-attacker", SECRET)


def test_delegation_expires_within_its_short_ttl():
    minted = sessions.mint_delegation(
        "sess-1", sessions.AUDIENCE_CONTROL_PLANE, SECRET, now=1_700_000_000
    )
    assert minted.expires_at == 1_700_000_000 + sessions.DELEGATION_TTL_SECONDS
    assert _verify(minted.token, now=minted.expires_at - 1).valid is True
    assert not _verify(minted.token, now=minted.expires_at).valid


def test_ttl_is_a_single_turn_not_a_session():
    assert sessions.DELEGATION_TTL_SECONDS <= 300


def test_token_ids_are_unique_so_replay_is_detectable():
    minted = [
        sessions.mint_delegation("sess-1", sessions.AUDIENCE_CONTROL_PLANE, SECRET)
        for _ in range(20)
    ]
    assert len({token.token_id for token in minted}) == 20


def test_replayed_delegation_is_rejected_by_the_control_plane():
    minted = sessions.mint_delegation(
        "sess-1", sessions.AUDIENCE_CONTROL_PLANE, SECRET, now=1_700_000_000
    )
    seen: set[str] = set()
    assert _verify(minted.token, seen=seen).valid is True
    seen.add(minted.token_id)
    assert not _verify(minted.token, seen=seen).valid


def test_a_forged_delegation_from_another_secret_is_rejected():
    minted = sessions.mint_delegation(
        "sess-victim", sessions.AUDIENCE_CONTROL_PLANE, "attacker-secret",
        now=1_700_000_000,
    )
    assert not _verify(minted.token).valid


def test_missing_inputs_are_refused_at_mint_time():
    with pytest.raises(ValueError):
        sessions.mint_delegation("", sessions.AUDIENCE_CONTROL_PLANE, SECRET)
    with pytest.raises(ValueError):
        sessions.mint_delegation("sess-1", sessions.AUDIENCE_CONTROL_PLANE, "")
