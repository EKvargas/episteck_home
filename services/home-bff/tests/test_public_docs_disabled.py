"""BFF-19: the public app never exposes its own API surface inventory."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from home_bff.app import create_app
from home_bff.store import SessionStore

from tests.test_app import FakeClient, make_settings  # noqa: E402


@pytest.fixture
def ctx(tmp_path):
    store = SessionStore(str(tmp_path / "bff.sqlite"))
    client = FakeClient()
    app = create_app(make_settings(), store=store, client=client)
    with TestClient(app, base_url="https://bff.invalid") as http:
        yield http


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_public_docs_routes_are_404(ctx, path):
    response = ctx.get(path)
    assert response.status_code == 404
