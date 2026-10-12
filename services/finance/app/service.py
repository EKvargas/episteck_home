"""FinanceService: authorize first, read second. Nothing else reads the repository.

* The caller supplies only an opaque delegation (from transport) and, optionally, a
  valuation currency. No actor, workspace or SQL: the workspace is service configuration
  and the actor is whatever Home resolves from the delegation.
* ONE Home request per operation. Anything but a complete, positive answer reads nothing
  and is not retried. There is no decision cache.
* The single read allowed before Home answers is ``workspace_scope`` (owner ids and a
  status) because the requirements are built from the owners.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone

from . import domain
from .authz import (
    ANSWERED, MAX_REQUIREMENTS, SELF, SESSION_INVALID, Authorizer, Requirement,
)
from .overview import compute_overview, observation_kind
from .store.repo import FinanceRepository

logger = logging.getLogger("finance.service")


class SessionInvalid(Exception):
    """No usable human session (missing or rejected delegation)."""


class AccessDenied(Exception):
    """Home answered and the actor may not read this."""


class PolicyUnavailable(Exception):
    """Home could not give a complete, trustworthy answer."""


class FeatureOff(Exception):
    """Finance is switched off for this workspace."""


class UnsupportedValuation(Exception):
    """A valuation currency other than EUR was requested."""


class FinanceService:
    def __init__(self, repo: FinanceRepository, authorizer: Authorizer, workspace_id: str,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self._repo = repo
        self._authorizer = authorizer
        self._workspace_id = workspace_id
        self._clock = clock

    def overview(self, delegation: str | None, valuation_currency: str | None = None) -> dict:
        if not delegation:
            raise SessionInvalid()
        scope = self._repo.workspace_scope(self._workspace_id)
        owners = scope.owner_person_ids if scope else ()
        requirements = [Requirement(SELF, "VIEW")] + [Requirement(o, "VIEW") for o in owners]
        if len(requirements) > MAX_REQUIREMENTS:
            logger.warning("finance authorization not possible: too many owners")
            raise PolicyUnavailable()
        try:
            batch = self._authorizer.authorize(delegation, requirements)
        except Exception:
            logger.warning("finance authorization not granted: authorizer_error")
            raise PolicyUnavailable() from None
        if batch.outcome == SESSION_INVALID:
            raise SessionInvalid()
        if batch.outcome != ANSWERED:
            raise PolicyUnavailable()
        if not batch.is_allowed(SELF):
            raise AccessDenied()
        actor = batch.actor_person_id
        if not actor or not self._repo.is_member(self._workspace_id, actor):
            raise AccessDenied()
        if scope is None or scope.status is not domain.WorkspaceStatus.ACTIVE:
            raise FeatureOff()
        if valuation_currency not in (None, "EUR"):
            raise UnsupportedValuation()

        def owner_allowed(owner: str) -> bool:
            return (owner == actor and batch.is_allowed(SELF)) or batch.is_allowed(owner)

        accounts = self._repo.list_accounts(self._workspace_id)
        visible = [a for a in accounts if all(owner_allowed(o) for o in a.owner_person_ids)]
        observations = {}
        for account in visible:
            kind = observation_kind(account)
            observations[account.id] = (
                self._repo.latest_balance(self._workspace_id, account.id, kind) if kind else None
            )
        connections = {c.id: c for c in self._repo.list_connections(self._workspace_id)}
        rates = self._repo.latest_fx_rates() if valuation_currency else None
        result = compute_overview(visible, observations, connections, self._clock(),
                                  rates, valuation_currency)
        result["hidden_accounts"] = len(accounts) - len(visible)
        return result
