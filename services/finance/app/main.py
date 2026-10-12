"""Container entrypoint: ``uvicorn app.main:app``. Tests use ``app.api.create_app`` instead."""
from __future__ import annotations

from .api import create_app
from .deps import build_service

app = create_app(build_service())
