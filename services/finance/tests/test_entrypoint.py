"""Until the real Home client exists (Phase B) the deployed entrypoint must refuse everything."""
from __future__ import annotations

import importlib
import os
import sys

from fastapi.testclient import TestClient


def test_entrypoint_fails_closed_without_a_home_client(tmp_path, monkeypatch):
    pepper = tmp_path / "pepper"
    pepper.write_text("entrypoint-test-pepper")
    if sys.platform != "win32":
        os.chmod(pepper, 0o600)
    monkeypatch.setenv("FINANCE_DB", str(tmp_path / "f.sqlite"))
    monkeypatch.setenv("FINANCE_WORKSPACE_ID", "ws-1")
    monkeypatch.setenv("FINANCE_PEPPER_FILE", str(pepper))
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    client = TestClient(main.app)
    assert client.get("/health").status_code == 200
    response = client.get("/overview", headers={"X-Episteck-Delegation": "tok"})
    assert response.status_code == 503
    assert response.json() == {"detail": "SERVICE_UNAVAILABLE"}
    # The PSD2 callback is wired to the same database: an unknown state is refused, not 404.
    callback = client.get("/connect/callback", params={"state": "U" * 43, "code": "c"})
    assert callback.status_code == 400
    sys.modules.pop("app.main", None)
