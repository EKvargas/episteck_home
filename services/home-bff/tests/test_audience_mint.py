"""/internal/mint optional ?audience= selection (Olin Finance B4)."""
from __future__ import annotations

import base64
import json

import pytest

from home_bff import sessions
from home_bff.runtime import RUNTIME_ID
from tests.test_runtime_grant_mint import AUDIENCES, DAY, build, clock  # noqa: F401


def _claims(response) -> dict:
    body = response.headers["X-Episteck-Delegation"].split(".")[0]
    return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))


def _granted(tmp_path, clock, audiences=AUDIENCES):  # noqa: F811
    http, store = build(tmp_path, clock, runtime_legacy_binding=False)
    store.put_runtime_grant(RUNTIME_ID, "HDS-GRANT", audiences, ttl_seconds=DAY)
    return http, store


def test_svc_finance_is_a_known_audience():
    assert "svc-finance" in sessions.KNOWN_AUDIENCES
    assert sessions.AUDIENCE_FINANCE == "svc-finance"


@pytest.mark.parametrize("audience", sorted(AUDIENCES))
def test_each_known_audience_mints_exactly_that_one_audience(
    tmp_path, clock, audience  # noqa: F811
):
    http, _ = _granted(tmp_path, clock)
    response = http.post(f"/internal/mint?audience={audience}")
    assert response.status_code == 204
    claims = _claims(response)
    assert claims["aud"] == audience
    assert isinstance(claims["aud"], str)
    assert claims["sid"] == "HDS-GRANT"


def test_default_audience_is_unchanged_without_the_parameter(tmp_path, clock):  # noqa: F811
    http, _ = _granted(tmp_path, clock)
    assert _claims(http.post("/internal/mint"))["aud"] == "home-control-plane"


def test_audience_not_in_grant_is_refused_without_a_token(tmp_path, clock):  # noqa: F811
    http, _ = _granted(tmp_path, clock, frozenset({"home-control-plane"}))
    response = http.post("/internal/mint?audience=svc-finance")
    assert response.status_code == 401
    assert "X-Episteck-Delegation" not in response.headers
    assert "svc-finance" not in response.text


def test_default_still_requires_control_plane_in_grant(tmp_path, clock):  # noqa: F811
    http, _ = _granted(tmp_path, clock, frozenset({"svc-finance"}))
    assert http.post("/internal/mint").status_code == 401
    assert http.post("/internal/mint?audience=svc-finance").status_code == 204


@pytest.mark.parametrize(
    "query",
    [
        "audience=svc-unknown",
        "audience=",
        "audience=SVC-FINANCE",
        "audience=Svc-Finance",
        "audience=%20svc-finance",
        "audience=svc-finance%20",
        "audience=svc-finance%0a",
        "audience=svc-finance,svc-nutrition",
        "audience=svc-finance%20svc-nutrition",
        "audience=svc-finance&audience=svc-nutrition",
        "audience=home-control-plane&audience=svc-finance",
        "audience=svc-finance&audience=svc-finance",
        "audience=*",
        "audience=svc-*",
    ],
)
def test_malformed_or_unknown_audience_is_refused_generically(tmp_path, clock, query):  # noqa: F811
    http, _ = _granted(tmp_path, clock)
    response = http.post(f"/internal/mint?{query}")
    assert response.status_code == 401
    assert "X-Episteck-Delegation" not in response.headers
    assert response.json() == {"detail": "no active runtime grant"}


def test_unknown_audience_is_not_echoed_or_logged(tmp_path, clock, caplog):  # noqa: F811
    http, _ = _granted(tmp_path, clock)
    response = http.post("/internal/mint?audience=svc-secret-probe")
    assert response.status_code == 401
    assert "svc-secret-probe" not in response.text
    assert "svc-secret-probe" not in caplog.text


def test_legacy_binding_can_only_mint_the_default_audience(tmp_path, clock):  # noqa: F811
    from tests.test_runtime_grant_mint import _browser_binding

    http, store = build(tmp_path, clock)
    _browser_binding(store)
    assert http.post("/internal/mint").status_code == 204
    assert http.post("/internal/mint?audience=svc-finance").status_code == 401
    assert http.post("/internal/mint?audience=svc-nutrition").status_code == 401


def test_expired_grant_refuses_every_audience(tmp_path, clock):  # noqa: F811
    http, _ = _granted(tmp_path, clock)
    clock.now += DAY
    for suffix in ("", "?audience=svc-finance"):
        assert http.post(f"/internal/mint{suffix}").status_code == 401


def test_revoked_grant_refuses_finance(tmp_path, clock):  # noqa: F811
    http, store = _granted(tmp_path, clock)
    assert http.post("/internal/mint?audience=svc-finance").status_code == 204
    store.delete_runtime_grant(RUNTIME_ID)
    assert http.post("/internal/mint?audience=svc-finance").status_code == 401
