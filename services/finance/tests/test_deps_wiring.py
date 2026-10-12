"""deps.py wiring: HomeAuthorizer when configured, fail-closed otherwise."""
from __future__ import annotations

import pytest

from app.authz import UNAVAILABLE, Requirement
from app.config import Settings
from app.deps import UnconfiguredAuthorizer, build_service
from app.home_control.client import HomeAuthorizer

HOME_VARS = ("HOME_CONTROL_PLANE_URL", "HOME_API_KEY", "HOME_API_SECRET", "HOME_API_TIMEOUT_SECONDS")


@pytest.fixture
def settings(tmp_path):
    return Settings(db_path=str(tmp_path / "f.sqlite"), workspace_id="ws-1", pepper=b"p" * 16)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in HOME_VARS:
        monkeypatch.delenv(name, raising=False)


def test_unconfigured_when_no_home_variables(settings):
    svc = build_service(settings)
    assert isinstance(svc._authorizer, UnconfiguredAuthorizer)
    assert svc._authorizer.authorize("tok", [Requirement("SELF", "VIEW")]).outcome == UNAVAILABLE


def test_home_authorizer_when_fully_configured(settings, monkeypatch):
    monkeypatch.setenv("HOME_CONTROL_PLANE_URL", "https://home.invalid")
    monkeypatch.setenv("HOME_API_KEY", "key")
    monkeypatch.setenv("HOME_API_SECRET", "secret")
    assert isinstance(build_service(settings)._authorizer, HomeAuthorizer)


@pytest.mark.parametrize("missing", ["HOME_CONTROL_PLANE_URL", "HOME_API_KEY", "HOME_API_SECRET"])
def test_partial_configuration_fails_fast(settings, monkeypatch, missing):
    values = {"HOME_CONTROL_PLANE_URL": "https://home.invalid", "HOME_API_KEY": "k", "HOME_API_SECRET": "s"}
    del values[missing]
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(ValueError) as err:
        build_service(settings)
    assert "secret" not in str(err.value)


def test_invalid_timeout_fails_fast(settings, monkeypatch):
    monkeypatch.setenv("HOME_CONTROL_PLANE_URL", "https://home.invalid")
    monkeypatch.setenv("HOME_API_KEY", "k")
    monkeypatch.setenv("HOME_API_SECRET", "s")
    monkeypatch.setenv("HOME_API_TIMEOUT_SECONDS", "soon")
    with pytest.raises(ValueError):
        build_service(settings)
