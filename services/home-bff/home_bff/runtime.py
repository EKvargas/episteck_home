"""Fixed runtime identity and binding outcomes."""
from __future__ import annotations

from enum import StrEnum


RUNTIME_ID = "home-agent-primary"


class BindResult(StrEnum):
    BOUND = "bound"
    ALREADY_BOUND = "already_bound"
    REPLACED_STALE = "replaced_stale"
    SAME_SESSION = "same_session"
