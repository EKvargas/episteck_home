"""Production replay enforcement for delegation tokens (G1.6).

WHY A SEPARATE SUITE
--------------------
`delegation.verify()` has always *supported* replay rejection via an injected
`seen_token_ids` set, and the threat matrix claimed T-18 on that basis. But the
production hook never passed one, so nothing enforced single use: live validation
presented the same `jti` twice and both succeeded.

An in-process set could not have fixed it either — four gunicorn workers means four
sets, and a replay simply lands on a different worker. These tests therefore exercise
the **shared, atomic** claim the hook actually makes, including the cross-worker and
concurrency cases that a pure-function test cannot express.
"""
from __future__ import annotations

import base64
import hashlib
import hmac as _hmac
import json
import time

import pytest

from tests.test_delegation_integration import (  # noqa: F401  (harness is a fixture)
    HUMAN,
    ISSUER,
    MACHINE,
    PERSON,
    SECRET,
    SESSION_ID,
    SITE_DB_NAME,
    _PermissionError,
    harness,
)

AUDIENCE_CONTROL_PLANE = "home-control-plane"
AUDIENCE_NUTRITION = "svc-nutrition"


def _sign(claims: dict) -> str:
    body = (
        base64.urlsafe_b64encode(
            json.dumps(claims, sort_keys=True, separators=(",", ":")).encode()
        )
        .decode()
        .rstrip("=")
    )
    sig = _hmac.new(SECRET.encode(), body.encode(), hashlib.sha256).digest()
    return body + "." + base64.urlsafe_b64encode(sig).decode().rstrip("=")


def mint(jti: str, *, audience: str = AUDIENCE_CONTROL_PLANE, age: int = 0) -> str:
    """Mint with an EXACT jti, so a captured-token replay is byte-reproducible."""
    now = int(time.time())
    return _sign(
        {
            "iss": ISSUER,
            "aud": audience,
            "iat": now - age,
            "exp": now - age + 120,
            "jti": jti,
            "sid": SESSION_ID,
        }
    )


# ----------------------------------------------------------------- first use


def test_first_presentation_succeeds(harness):
    fake, hook, _ = harness()
    fake.request_headers[hook.DELEGATION_HEADER] = mint("JTI-ONE")

    hook.establish_delegated_context()

    assert fake.local.episteck_delegated_user == HUMAN
    assert fake.local.episteck_delegation_stage == hook.STAGE_BOUND


def test_distinct_jtis_all_succeed(harness):
    fake, hook, _ = harness()
    for jti in ("JTI-A", "JTI-B", "JTI-C"):
        fake.request_headers[hook.DELEGATION_HEADER] = mint(jti)
        hook.establish_delegated_context()
        assert fake.local.episteck_delegated_user == HUMAN, jti


# -------------------------------------------------------------------- replay


def test_second_presentation_of_same_jti_is_denied(harness):
    """THE REGRESSION: this exact sequence was accepted twice in production."""
    fake, hook, actor = harness()
    token = mint("JTI-REPLAY")

    fake.request_headers[hook.DELEGATION_HEADER] = token
    hook.establish_delegated_context()
    assert fake.local.episteck_delegated_user == HUMAN

    fake.request_headers[hook.DELEGATION_HEADER] = token
    hook.establish_delegated_context()

    assert fake.local.episteck_delegated_user is None
    assert fake.local.episteck_delegation_stage == hook.STAGE_REPLAY_DETECTED
    with pytest.raises(_PermissionError):
        actor.resolve_principals()


def test_replay_denied_across_separate_workers(harness):
    """A second worker must observe the first worker's claim.

    This is the case an in-process set cannot cover, and the reason the live
    system accepted a replay despite `verify()` supporting rejection.
    """
    fake_a, hook_a, _ = harness()
    token = mint("JTI-CROSS-WORKER")
    fake_a.request_headers[hook_a.DELEGATION_HEADER] = token
    hook_a.establish_delegated_context()
    assert fake_a.local.episteck_delegated_user == HUMAN

    shared = fake_a.cache_store
    fake_b, hook_b, _ = harness()
    fake_b.cache_store = shared
    fake_b.cache = lambda: shared  # same Redis, different worker

    fake_b.request_headers[hook_b.DELEGATION_HEADER] = token
    hook_b.establish_delegated_context()

    assert fake_b.local.episteck_delegated_user is None
    assert fake_b.local.episteck_delegation_stage == hook_b.STAGE_REPLAY_DETECTED


def test_concurrent_claims_admit_exactly_one(harness):
    """Racing requests with one token: exactly one may proceed."""
    harness()
    from episteck_home.identity import replay as R

    now = int(time.time())
    ttl = R.ttl_for(now + 120, now)
    outcomes = [
        R.claim(ISSUER, AUDIENCE_CONTROL_PLANE, "JTI-RACE", ttl_seconds=ttl)
        for _ in range(8)
    ]
    assert outcomes.count(True) == 1, outcomes
    assert outcomes.count(False) == 7


# --------------------------------------------------- store unavailable = deny


def test_store_unavailable_denies(harness):
    """An outage denies; it never degrades to replay-protection-off."""
    fake, hook, actor = harness()
    fake.cache_store.fail = True
    fake.request_headers[hook.DELEGATION_HEADER] = mint("JTI-OUTAGE")

    hook.establish_delegated_context()

    assert fake.local.episteck_delegated_user is None
    assert fake.local.episteck_delegation_stage == hook.STAGE_REPLAY_UNAVAILABLE
    assert fake.logged, "an outage should leave a sanitized diagnostic"
    with pytest.raises(_PermissionError):
        actor.resolve_principals()


def test_indeterminate_result_denies(harness):
    """An unrecognised reply is not evidence of first use."""
    fake, hook, _ = harness()
    fake.cache_store.weird_return = True
    fake.request_headers[hook.DELEGATION_HEADER] = mint("JTI-WEIRD")

    hook.establish_delegated_context()

    assert fake.local.episteck_delegated_user is None
    assert fake.local.episteck_delegation_stage == hook.STAGE_REPLAY_UNAVAILABLE


def test_outage_diagnostic_leaks_nothing(harness):
    fake, hook, _ = harness()
    fake.cache_store.fail = True
    fake.request_headers[hook.DELEGATION_HEADER] = mint("JTI-QUIET")

    hook.establish_delegated_context()

    blob = str(fake.local.episteck_delegation_stage) + str(fake.logged)
    for forbidden in (SECRET, SESSION_ID, HUMAN, MACHINE, PERSON, "JTI-QUIET", "redis"):
        assert forbidden not in blob, forbidden


# ------------------------------------------------------------------- expiry


def test_claim_keys_expire(harness):
    """Claims must not accumulate without bound."""
    fake, hook, _ = harness()
    fake.request_headers[hook.DELEGATION_HEADER] = mint("JTI-TTL")
    hook.establish_delegated_context()
    assert fake.cache_store.store, "a claim key should exist"

    fake.cache_store.advance(120 + 60 + 5)  # past exp + skew buffer
    assert not fake.cache_store.store, "claim keys must expire"


def test_ttl_covers_acceptance_window_plus_skew():
    from episteck_home.identity import replay as R

    now = 1_000_000
    assert R.ttl_for(now + 120, now) == 120 + R.SKEW_BUFFER_SECONDS
    # Never zero or negative, even for a token that is already expired.
    assert R.ttl_for(now - 500, now) >= R.MIN_TTL_SECONDS


# --------------------------------- invalid tokens must not burn a legitimate jti


def test_forged_token_does_not_burn_a_jti(harness):
    fake, hook, _ = harness()
    good = mint("JTI-PRECIOUS")
    forged = good.rsplit(".", 1)[0] + ".xxxxx"

    fake.request_headers[hook.DELEGATION_HEADER] = forged
    hook.establish_delegated_context()
    assert fake.local.episteck_delegated_user is None
    assert not fake.cache_store.store, "a forged token must not claim a jti"

    fake.request_headers[hook.DELEGATION_HEADER] = good
    hook.establish_delegated_context()
    assert fake.local.episteck_delegated_user == HUMAN


def test_expired_token_does_not_burn_a_jti(harness):
    fake, hook, _ = harness()
    fake.request_headers[hook.DELEGATION_HEADER] = mint("JTI-EXPIRED", age=600)
    hook.establish_delegated_context()
    assert not fake.cache_store.store


def test_wrong_audience_does_not_burn_a_jti(harness):
    fake, hook, _ = harness()
    fake.request_headers[hook.DELEGATION_HEADER] = mint(
        "JTI-AUD", audience=AUDIENCE_NUTRITION
    )
    hook.establish_delegated_context()
    assert not fake.cache_store.store


def test_valid_token_is_spent_even_when_session_lookup_fails(harness):
    """A cryptographically valid token is consumed regardless of what follows.

    A legitimate request that fails later can mint a fresh delegation; it must not
    be able to retry the old one.
    """
    fake, hook, _ = harness()
    fake.sessions.clear()
    token = mint("JTI-SPENT")

    fake.request_headers[hook.DELEGATION_HEADER] = token
    hook.establish_delegated_context()
    assert fake.local.episteck_delegation_stage == hook.STAGE_SESSION_MISSING
    assert fake.cache_store.store, "claim happens before session lookup"

    fake.sessions[SESSION_ID] = {"user": HUMAN, "status": "Active", "expires_at": None}
    fake.request_headers[hook.DELEGATION_HEADER] = token
    hook.establish_delegated_context()
    assert fake.local.episteck_delegation_stage == hook.STAGE_REPLAY_DETECTED


# --------------------------------------------------------------- key hygiene


def test_key_contains_no_identity_or_credential(harness):
    harness()
    from episteck_home.identity import replay as R

    key = R.replay_key(ISSUER, AUDIENCE_CONTROL_PLANE, "JTI-SECRETISH")
    for forbidden in (SESSION_ID, HUMAN, MACHINE, PERSON, SECRET, "JTI-SECRETISH"):
        assert forbidden not in key, forbidden
    assert key.startswith(R.KEY_PREFIX)


def test_key_is_site_scoped(harness):
    """Redis is shared across sites on this bench; keys must not collide."""
    harness()
    from episteck_home.identity import replay as R

    assert SITE_DB_NAME in R.replay_key(ISSUER, AUDIENCE_CONTROL_PLANE, "JTI-SITE")


def test_key_is_stable_and_collision_resistant(harness):
    harness()
    from episteck_home.identity import replay as R

    a = R.replay_key(ISSUER, AUDIENCE_CONTROL_PLANE, "J1")
    b = R.replay_key(ISSUER, AUDIENCE_CONTROL_PLANE, "J1")
    c = R.replay_key(ISSUER, AUDIENCE_NUTRITION, "J1")
    d = R.replay_key("other-issuer", AUDIENCE_CONTROL_PLANE, "J1")
    assert a == b, "the same delegation must map to the same key"
    assert len({a, c, d}) == 3, "issuer and audience must both affect the key"


def test_claim_rejects_incomplete_identity(harness):
    harness()
    from episteck_home.identity import replay as R

    for args in (("", "aud", "jti"), ("iss", "", "jti"), ("iss", "aud", "")):
        with pytest.raises(R.ReplayStoreUnavailable):
            R.claim(*args, ttl_seconds=60)


# -------------------------------------------------- guard against regressing


def test_old_implementation_would_have_allowed_the_replay():
    """Prove the PREVIOUS behaviour was genuinely broken, not assumed so.

    The old hook passed no replay store, so `verify()` had nothing to check against
    and accepted the same token twice. Asserting that here keeps the fix honest.
    """
    from episteck_home.identity.delegation import verify as pure_verify

    token = mint("JTI-OLDWAY")
    now = int(time.time())
    kwargs = dict(
        secret=SECRET,
        expected_issuer=ISSUER,
        expected_audience=AUDIENCE_CONTROL_PLANE,
        now=now,
    )

    # Old production path: no store -> a replay verifies fine.
    assert pure_verify(token, **kwargs).valid
    assert pure_verify(token, **kwargs).valid, "the old path accepted replays"

    # The injected-set seam still works for isolated testing.
    seen: set[str] = set()
    first = pure_verify(token, seen_token_ids=seen, **kwargs)
    seen.add(first.context.token_id)
    assert not pure_verify(token, seen_token_ids=seen, **kwargs).valid
