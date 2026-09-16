"""Integration tests for the delegation composition (G1.6).

WHY THESE EXIST
---------------
Every piece of the delegated path had unit coverage and every piece passed, yet the
live service-mediated request failed 100% of the time. The unit tests each supplied
their own clock, so none of them could see that the hook derived ``now`` from
site-local time while the BFF minted ``exp`` in epoch UTC. On a ``Europe/Berlin``
site that is a 7200 s skew against a 120 s token lifetime, so every delegation
arrived "expired".

These tests exercise the COMPOSITION — mint the way the BFF mints, verify the way the
hook verifies, through ``frappe.auth.validate_auth``'s real ordering — so a clock,
config, or ordering regression fails the build instead of production.
"""
from __future__ import annotations

import importlib
import json
import sys
import time
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

# Mint with the real BFF implementation, not a copy of it.
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "services" / "home-bff"))
from home_bff import sessions as bff_sessions  # noqa: E402

SECRET = "integration-delegation-secret"
ISSUER = "episteck-home-bff"
SESSION_ID = "HDS-INTEGRATION"
MACHINE = "home-mcp-service@example.invalid"
HUMAN = "syn-lowpriv@example.invalid"
PERSON = "PSN-00002"

# The skew that caused the live failure: a site two hours ahead of UTC.
BERLIN_OFFSET_SECONDS = 7200


class _PermissionError(Exception):
    pass


def _make_fake_frappe(*, site_offset: int = 0, session_user: str = MACHINE):
    """A frappe double whose site clock can be offset from UTC, as a real site's is."""
    fake = types.ModuleType("frappe")
    fake.session = SimpleNamespace(user=session_user)
    fake.local = SimpleNamespace()
    fake.PermissionError = _PermissionError
    fake.conf = {
        "home_delegation_secret": SECRET,
        "home_delegation_issuer": ISSUER,
    }
    fake.request_headers = {}
    fake.logged = []

    fake.get_request_header = lambda key, default=None: fake.request_headers.get(
        key, default
    )
    fake.log_error = lambda message, title=None: fake.logged.append((title, message))

    def throw(message, exc=Exception):
        raise exc(message)

    def whitelist(*args, **kwargs):
        def decorate(fn):
            return fn

        return decorate

    fake.throw = throw
    fake.whitelist = whitelist

    fake.sessions = {
        SESSION_ID: {"user": HUMAN, "status": "Active", "expires_at": None},
    }
    fake.people = {HUMAN: [PERSON]}
    fake.enabled_users = {HUMAN: True, MACHINE: True}

    def get_all(doctype, filters=None, fields=None, **kwargs):
        filters = filters or {}
        if doctype == "Home Delegated Session":
            row = fake.sessions.get(filters.get("name"))
            if not row or row["status"] != filters.get("status", row["status"]):
                return []
            return [dict(row)]
        if doctype == "Person":
            return [{"name": p} for p in fake.people.get(filters.get("linked_user"), [])]
        return []

    fake.get_all = get_all

    class DB:
        @staticmethod
        def get_value(doctype, name, field):
            if doctype == "User" and field == "enabled":
                return 1 if fake.enabled_users.get(name) else 0
            return None

    fake.db = DB()

    utils = types.ModuleType("frappe.utils")
    # now_datetime() is NAIVE site-local: this is exactly the trap.
    utils.now_datetime = lambda: _naive_site_now(site_offset)
    utils.now = lambda: _naive_site_now(site_offset).strftime("%Y-%m-%d %H:%M:%S.%f")
    fake.utils = utils
    return fake


def _naive_site_now(offset_seconds: int):
    from datetime import datetime

    return datetime.utcfromtimestamp(time.time() + offset_seconds)


@pytest.fixture
def harness(monkeypatch):
    """Load the hook and actor against a frappe double with a given site offset."""

    def build(*, site_offset: int = 0, session_user: str = MACHINE):
        fake = _make_fake_frappe(site_offset=site_offset, session_user=session_user)
        monkeypatch.setitem(sys.modules, "frappe", fake)
        monkeypatch.setitem(sys.modules, "frappe.utils", fake.utils)
        hook = importlib.reload(
            importlib.import_module("episteck_home.identity.auth_hook")
        )
        actor = importlib.reload(
            importlib.import_module("episteck_home.identity.actor")
        )
        return fake, hook, actor

    yield build
    sys.modules.pop("frappe", None)
    sys.modules.pop("frappe.utils", None)


def mint(audience: str = bff_sessions.AUDIENCE_CONTROL_PLANE) -> str:
    """Mint exactly as the deployed BFF does — epoch UTC, 120 s lifetime."""
    return bff_sessions.mint_delegation(SESSION_ID, audience, SECRET).token


# ======================================================================
# The regression: a site whose timezone is not UTC
# ======================================================================


@pytest.mark.parametrize(
    "offset",
    [0, BERLIN_OFFSET_SECONDS, -BERLIN_OFFSET_SECONDS, 5 * 3600, -8 * 3600],
    ids=["utc", "berlin_+2", "behind_-2", "asia_+5", "us_-8"],
)
def test_delegation_binds_regardless_of_site_timezone(harness, offset):
    """THE REGRESSION. A BFF-minted token must verify on a site at ANY offset.

    Before the fix this passed only at offset 0; every real site failed.
    """
    fake, hook, actor = harness(site_offset=offset)
    fake.request_headers[hook.DELEGATION_HEADER] = mint()

    hook.establish_delegated_context()

    assert fake.local.episteck_delegated_user == HUMAN, (
        f"site offset {offset}s broke binding; stage="
        f"{getattr(fake.local, 'episteck_delegation_stage', None)}"
    )
    assert fake.local.episteck_delegation_stage == hook.STAGE_BOUND


def test_hook_clock_is_utc_and_ignores_the_site_offset(harness):
    """The hook's clock is epoch UTC and does not move with the site timezone.

    Asserted as invariance rather than by comparing against the double's own naive
    datetime: `.timestamp()` on a naive value re-applies the *runner's* local offset,
    which cancels out on a UTC CI box and would make such a comparison vacuous there.
    """
    baseline = None
    for offset in (0, BERLIN_OFFSET_SECONDS, -8 * 3600):
        _, hook, _ = harness(site_offset=offset)
        now = hook._now()
        assert abs(now - int(time.time())) <= 2, f"offset {offset} leaked into the clock"
        if baseline is not None:
            assert abs(now - baseline) <= 2, "clock moved with the site timezone"
        baseline = now


# ======================================================================
# Required composition cases
# ======================================================================


def test_machine_plus_valid_delegation_yields_both_principals(harness):
    fake, hook, actor = harness()
    fake.request_headers[hook.DELEGATION_HEADER] = mint()

    hook.establish_delegated_context()
    principals = actor.resolve_principals()

    assert principals.human_actor == PERSON
    assert principals.machine_caller == MACHINE
    assert principals.is_delegated is True


def test_machine_plus_invalid_delegation_fails_closed(harness):
    fake, hook, actor = harness()
    fake.request_headers[hook.DELEGATION_HEADER] = mint()[:-4] + "xxxx"

    hook.establish_delegated_context()

    assert fake.local.episteck_delegated_user is None
    assert fake.local.episteck_delegation_stage.startswith(hook.STAGE_VERIFY_INVALID)
    with pytest.raises(_PermissionError):
        actor.resolve_principals()


def test_machine_plus_missing_session_fails_closed(harness):
    fake, hook, actor = harness()
    fake.sessions.clear()
    fake.request_headers[hook.DELEGATION_HEADER] = mint()

    hook.establish_delegated_context()

    assert fake.local.episteck_delegated_user is None
    assert fake.local.episteck_delegation_stage == hook.STAGE_SESSION_MISSING
    with pytest.raises(_PermissionError):
        actor.resolve_principals()


def test_anonymous_plus_valid_delegation_fails_closed(harness):
    """A delegation may never bootstrap identity without an authenticated machine."""
    fake, hook, actor = harness(session_user="Guest")
    fake.request_headers[hook.DELEGATION_HEADER] = mint()

    hook.establish_delegated_context()

    assert fake.local.episteck_delegated_user is None
    assert fake.local.episteck_delegation_stage == hook.STAGE_MACHINE_GUEST


def test_unexpected_exception_fails_closed_and_is_diagnosable(harness):
    fake, hook, actor = harness()
    fake.request_headers[hook.DELEGATION_HEADER] = mint()

    def boom(*args, **kwargs):
        raise RuntimeError("synthetic failure")

    fake.get_all = boom

    hook.establish_delegated_context()  # must not raise

    assert fake.local.episteck_delegated_user is None
    assert fake.local.episteck_delegation_stage.startswith(hook.STAGE_EXCEPTION)
    assert "RuntimeError" in fake.local.episteck_delegation_stage
    assert fake.logged, "an unexpected exception must leave a diagnostic signal"


def test_missing_secret_is_diagnosable_and_fails_closed(harness):
    fake, hook, _ = harness()
    fake.conf["home_delegation_secret"] = None
    fake.request_headers[hook.DELEGATION_HEADER] = mint()

    hook.establish_delegated_context()

    assert fake.local.episteck_delegated_user is None
    assert fake.local.episteck_delegation_stage == hook.STAGE_NOT_CONFIGURED
    assert fake.logged


# ======================================================================
# Invariants that must survive the fix
# ======================================================================


def test_machine_credential_alone_is_never_a_human(harness):
    fake, hook, actor = harness()  # no delegation header at all

    hook.establish_delegated_context()

    assert fake.local.episteck_delegation_stage == hook.STAGE_NO_TOKEN
    with pytest.raises(_PermissionError):
        actor.resolve_principals()
    assert fake.local.episteck_denial_category == "actor.no_delegated_user"


def test_wrong_audience_still_denied_after_the_clock_fix(harness):
    fake, hook, _ = harness(site_offset=BERLIN_OFFSET_SECONDS)
    fake.request_headers[hook.DELEGATION_HEADER] = mint(
        bff_sessions.AUDIENCE_NUTRITION
    )

    hook.establish_delegated_context()

    assert fake.local.episteck_delegated_user is None
    assert fake.local.episteck_delegation_stage.startswith(hook.STAGE_VERIFY_INVALID)


def test_genuinely_expired_token_still_denied(harness):
    """The fix must not become a blanket acceptance of stale tokens."""
    fake, hook, _ = harness()
    expired = bff_sessions.mint_delegation(
        SESSION_ID,
        bff_sessions.AUDIENCE_CONTROL_PLANE,
        SECRET,
        now=int(time.time()) - 600,
    ).token
    fake.request_headers[hook.DELEGATION_HEADER] = expired

    hook.establish_delegated_context()

    assert fake.local.episteck_delegated_user is None
    assert "expired" in fake.local.episteck_delegation_stage


def test_disabled_user_denied_even_with_live_session(harness):
    fake, hook, _ = harness()
    fake.enabled_users[HUMAN] = False
    fake.request_headers[hook.DELEGATION_HEADER] = mint()

    hook.establish_delegated_context()

    assert fake.local.episteck_delegated_user is None
    assert fake.local.episteck_delegation_stage == hook.STAGE_SESSION_MISSING


def test_ambiguous_person_binding_is_diagnosable(harness):
    """Two Persons for one User: deny, and say WHICH failure it was."""
    fake, hook, actor = harness()
    fake.people[HUMAN] = [PERSON, "PSN-00003"]
    fake.request_headers[hook.DELEGATION_HEADER] = mint()

    hook.establish_delegated_context()
    assert fake.local.episteck_delegated_user == HUMAN  # the hook bound fine

    with pytest.raises(_PermissionError):
        actor.resolve_principals()
    # The distinction that matters: the hook worked, the Person mapping did not.
    assert fake.local.episteck_denial_category == "actor.no_person_for_delegated_user"


# ======================================================================
# Diagnostics must never leak
# ======================================================================


def test_stage_codes_never_contain_identities_or_secrets(harness):
    """Whatever path is taken, the stage code must be safe to log."""
    forbidden = [SECRET, SESSION_ID, HUMAN, MACHINE, PERSON]

    scenarios = [
        ("bound", lambda f, h: f.request_headers.__setitem__(h.DELEGATION_HEADER, mint())),
        ("no_token", lambda f, h: None),
        ("invalid", lambda f, h: f.request_headers.__setitem__(h.DELEGATION_HEADER, "garbage")),
        ("missing_session", lambda f, h: (f.sessions.clear(), f.request_headers.__setitem__(h.DELEGATION_HEADER, mint()))),
    ]
    for name, setup in scenarios:
        fake, hook, _ = harness()
        setup(fake, hook)
        hook.establish_delegated_context()
        stage = fake.local.episteck_delegation_stage or ""
        for value in forbidden:
            assert value not in stage, f"{name}: leaked into stage code"
        for title, message in fake.logged:
            for value in forbidden:
                assert value not in str(message), f"{name}: leaked into log"


def test_token_never_appears_in_any_diagnostic(harness):
    fake, hook, _ = harness()
    token = mint()
    fake.request_headers[hook.DELEGATION_HEADER] = token

    hook.establish_delegated_context()

    assert token not in (fake.local.episteck_delegation_stage or "")
    assert all(token not in str(m) for _, m in fake.logged)
