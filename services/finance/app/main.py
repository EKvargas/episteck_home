"""Container entrypoint: ``uvicorn app.main:app``. Tests use ``app.api.create_app`` instead."""
from __future__ import annotations

from .api import create_app
from .config import Settings
from .deps import build_callback, build_receivables_service, build_service
from .receivables.service import API_CALLER

_settings = Settings.from_env()
app = create_app(
    build_service(_settings), callback=build_callback(_settings),
    receivables=build_receivables_service(_settings, caller=API_CALLER))
