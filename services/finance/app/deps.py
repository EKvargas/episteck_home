"""Process wiring for the container entrypoints."""
from __future__ import annotations

from collections.abc import Sequence

from .authz import UNAVAILABLE, BatchDecision, Requirement
from .config import Settings
from .service import FinanceService
from .store.repo import FinanceRepository


class UnconfiguredAuthorizer:
    """Fails closed until the real Home client (Phase B, H2) is wired.

    Home's ``authorize_batch`` does not exist yet, so nothing can be authorised and every
    request is refused as service-unavailable. This is deliberate, not a stub to forget.
    """

    def authorize(self, delegation: str | None,
                  requirements: Sequence[Requirement]) -> BatchDecision:
        return BatchDecision(UNAVAILABLE)


def build_service(settings: Settings | None = None) -> FinanceService:
    settings = settings or Settings.from_env()
    repo = FinanceRepository(settings.db_path, pepper=settings.pepper)
    return FinanceService(repo, UnconfiguredAuthorizer(), settings.workspace_id)
