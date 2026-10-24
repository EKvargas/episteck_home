"""Process wiring for the container entrypoints."""
from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from datetime import datetime, timezone

from .authz import UNAVAILABLE, BatchDecision, Requirement
from .config import Settings
from .connectors.eb_auth import receive_callback
from .home_control.client import HomeAuthorizer
from .service import FinanceService
from .store.repo import FinanceRepository


class UnconfiguredAuthorizer:
    """Fails closed when no Home variables are set: every request is service-unavailable.

    This is deliberate, not a stub to forget. A PARTIAL configuration is different: it is
    a deployment mistake and ``build_service`` refuses to start rather than hide it.
    """

    def authorize(self, delegation: str | None,
                  requirements: Sequence[Requirement]) -> BatchDecision:
        return BatchDecision(UNAVAILABLE)


_HOME_VARS = ("HOME_CONTROL_PLANE_URL", "HOME_API_KEY", "HOME_API_SECRET")


def _build_authorizer() -> HomeAuthorizer | UnconfiguredAuthorizer:
    """Same variable names as svc-nutrition. None set -> unconfigured; some set -> error."""
    values = {name: os.environ.get(name, "").strip() for name in _HOME_VARS}
    if not any(values.values()):
        return UnconfiguredAuthorizer()
    if not all(values.values()):
        # Names only: never echo a value.
        missing = ", ".join(name for name, value in values.items() if not value)
        raise ValueError(f"incomplete Home configuration, missing: {missing}")
    return HomeAuthorizer.from_credentials(
        values["HOME_CONTROL_PLANE_URL"],
        values["HOME_API_KEY"],
        values["HOME_API_SECRET"],
        timeout_seconds=float(os.environ.get("HOME_API_TIMEOUT_SECONDS", "3")),
    )


def build_service(settings: Settings | None = None) -> FinanceService:
    settings = settings or Settings.from_env()
    repo = FinanceRepository(settings.db_path, pepper=settings.pepper)
    return FinanceService(repo, _build_authorizer(), settings.workspace_id)


def build_callback(settings: Settings | None = None) -> Callable[..., bool]:
    """The PSD2 redirect handler. It needs the database only: no Home, no provider secret."""
    settings = settings or Settings.from_env()
    repo = FinanceRepository(settings.db_path, pepper=settings.pepper)

    def handle(state: str | None, code: str | None, error: str | None) -> bool:
        return receive_callback(repo, state, code=code, error=error,
                                now=datetime.now(timezone.utc))

    return handle
