from __future__ import annotations

import httpx

from finance_pilot.home_auth import HomeFinanceAuthorizer


def test_home_authorizer_asks_exact_finance_permission_without_actor():
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(200, json={"message": {"allow": True, "reason": "owner"}})

    auth = HomeFinanceAuthorizer("https://home.invalid", "machine-key", "machine-secret", transport=httpx.MockTransport(handle))
    decision = auth.check_access("PSN-OLIN", "FINANCE", "CREATE", "delegation-1")
    assert decision.allow is True
    assert len(seen) == 1
    assert seen[0].headers["x-episteck-delegation"] == "delegation-1"
    assert dict(seen[0].url.params) == {"subject_person_id": "PSN-OLIN", "domain": "FINANCE", "action": "CREATE"}
    assert "actor" not in str(seen[0].url)


def test_home_authorizer_fails_closed_on_missing_session_and_bad_response():
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json={"message": {"allow": "true"}})

    auth = HomeFinanceAuthorizer("https://home.invalid", "key", "secret", transport=httpx.MockTransport(handle))
    assert auth.check_access("PSN-OLIN", "FINANCE", "VIEW", None).allow is False
    assert calls == []
    assert auth.check_access("PSN-OLIN", "FINANCE", "VIEW", "token").allow is False
    assert len(calls) == 1
