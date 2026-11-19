"""Fixed runtime identity and binding outcomes."""
from __future__ import annotations

import re
from enum import StrEnum


PRIMARY_RUNTIME_ID = "home-agent-primary"
# Kept so existing imports keep meaning "the owner's agent".
RUNTIME_ID = PRIMARY_RUNTIME_ID
RUNTIME_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")

PRIMARY_GRANT_AUDIENCES = frozenset({"home-control-plane", "svc-nutrition", "svc-finance"})
_OTHER_GRANT_AUDIENCES = frozenset({"home-control-plane"})


def grant_audiences_for(runtime_id: str) -> frozenset[str]:
    """Only the owner's agent may hold Finance; every other runtime gets Home only."""
    if runtime_id == PRIMARY_RUNTIME_ID:
        return PRIMARY_GRANT_AUDIENCES
    return _OTHER_GRANT_AUDIENCES


class BindResult(StrEnum):
    BOUND = "bound"
    ALREADY_BOUND = "already_bound"
    REPLACED_STALE = "replaced_stale"
    SAME_SESSION = "same_session"
