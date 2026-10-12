"""HomeAuthorizer: one delegated authorize_batch request per operation (H1 client)."""
from __future__ import annotations

import inspect
import json
import logging

import httpx
import pytest

from app.authz import ANSWERED, SESSION_INVALID, UNAVAILABLE, Requirement
from app.home_control.client import HomeAuthorizer

DELEGATION = "delegation-token-SECRET"
ACTOR = "PSN-00001"
SELF_REQ = Requirement("SELF", "VIEW")
PSN_REQ = Requirement("PSN-00002", "VIEW")


def _client(handler) -> HomeAuthorizer:
    return HomeAuthorizer(
        httpx.Client(base_url="https://home.invalid", transport=httpx.MockTransport(handler))
    )


def _ok(requirements, actor=ACTOR) -> httpx.Response:
    decisions = [
        {"subject": r.subject, "domain": r.domain, "action": r.action,
         "allow": True, "reason": "self-access" if r.subject == "SELF" else "grant"}
        for r in requirements
    ]
    return httpx.Response(200, json={"message": {"actor_person_id": actor, "decisions": decisions}})


def test_issues_exactly_one_request_to_authorize_batch():
    calls = []

    def handler(req):
        calls.append(req)
        return _ok([SELF_REQ, PSN_REQ])

    _client(handler).authorize(DELEGATION, [SELF_REQ, PSN_REQ])
    assert len(calls) == 1
    assert calls[0].url.path == "/api/method/episteck_home.api.authorize_batch"
    assert json.loads(calls[0].content) == {"requirements": [
        {"subject": "SELF", "domain": "FINANCE", "action": "VIEW"},
        {"subject": "PSN-00002", "domain": "FINANCE", "action": "VIEW"},
    ]}


def test_sends_delegation_header():
    seen = {}

    def handler(req):
        seen.update(req.headers)
        return _ok([SELF_REQ])

    _client(handler).authorize(DELEGATION, [SELF_REQ])
    assert seen["x-episteck-delegation"] == DELEGATION


def test_answered_exposes_actor_and_decisions_in_order():
    result = _client(lambda r: _ok([SELF_REQ, PSN_REQ])).authorize(DELEGATION, [SELF_REQ, PSN_REQ])
    assert result.outcome == ANSWERED
    assert result.actor_person_id == ACTOR
    assert [d.subject for d in result.decisions] == ["SELF", "PSN-00002"]


@pytest.mark.parametrize("status", [401, 403])
def test_credential_or_session_rejection_is_session_invalid(status):
    assert _client(lambda r: httpx.Response(status)).authorize(DELEGATION, [SELF_REQ]).outcome == SESSION_INVALID


def test_no_delegation_is_session_invalid_and_sends_nothing():
    calls = []
    result = _client(lambda r: calls.append(r) or _ok([SELF_REQ])).authorize(None, [SELF_REQ])
    assert result.outcome == SESSION_INVALID
    assert calls == []


@pytest.mark.parametrize("status", [404, 429, 500, 503])
def test_other_statuses_are_unavailable(status):
    assert _client(lambda r: httpx.Response(status)).authorize(DELEGATION, [SELF_REQ]).outcome == UNAVAILABLE


def test_network_error_is_unavailable():
    def handler(req):
        raise httpx.ConnectError("down")

    assert _client(handler).authorize(DELEGATION, [SELF_REQ]).outcome == UNAVAILABLE


def test_unusable_delegation_header_is_session_invalid():
    assert _client(lambda r: _ok([SELF_REQ])).authorize("tökén☃", [SELF_REQ]).outcome == SESSION_INVALID


@pytest.mark.parametrize("body", [b"not json", b"[]", b'{"message": null}', b'{}'])
def test_malformed_body_is_unavailable(body):
    result = _client(lambda r: httpx.Response(200, content=body)).authorize(DELEGATION, [SELF_REQ])
    assert result.outcome == UNAVAILABLE


def test_decisions_length_mismatch_goes_through_validate_batch():
    def handler(req):
        return httpx.Response(200, json={"message": {"actor_person_id": ACTOR, "decisions": [
            {"subject": "SELF", "domain": "FINANCE", "action": "VIEW", "allow": True, "reason": "x"}]}})

    assert _client(handler).authorize(DELEGATION, [SELF_REQ, PSN_REQ]).outcome == UNAVAILABLE


def test_home_refusal_with_empty_decisions_is_unavailable():
    """Home refuses a malformed batch with 200 + empty decisions + no actor."""
    body = {"message": {"actor_person_id": None, "decisions": [], "reason": "x (fail closed)"}}
    assert _client(lambda r: httpx.Response(200, json=body)).authorize(DELEGATION, [SELF_REQ]).outcome == UNAVAILABLE


def test_no_actor_parameter():
    assert list(inspect.signature(HomeAuthorizer.authorize).parameters) == [
        "self", "delegation", "requirements"]


def test_logs_never_contain_the_delegation_or_actor(caplog):
    caplog.set_level(logging.DEBUG)
    _client(lambda r: httpx.Response(500)).authorize(DELEGATION, [SELF_REQ])
    _client(lambda r: httpx.Response(401)).authorize(DELEGATION, [SELF_REQ])
    _client(lambda r: _ok([SELF_REQ])).authorize(DELEGATION, [SELF_REQ])
    assert DELEGATION not in caplog.text and ACTOR not in caplog.text
