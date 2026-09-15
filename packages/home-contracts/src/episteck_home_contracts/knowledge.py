"""Dependency-free governance contracts for durable Episteck Knowledge."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum


class KnowledgeScopeType(str, Enum):
    PERSON = "PERSON"
    CIRCLE = "CIRCLE"


class KnowledgeProvenance(str, Enum):
    USER_EXPLICIT = "USER_EXPLICIT"
    USER_CONFIRMED = "USER_CONFIRMED"
    IMPORTED_SOURCE = "IMPORTED_SOURCE"
    PROFESSIONAL_PROVIDED = "PROFESSIONAL_PROVIDED"
    SYSTEM_OBSERVED = "SYSTEM_OBSERVED"
    AI_HYPOTHESIS = "AI_HYPOTHESIS"
    AI_SUMMARY = "AI_SUMMARY"
    DERIVED = "DERIVED"


class KnowledgeStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    DISPUTED = "DISPUTED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


_ALLOWED_TRANSITIONS = {
    KnowledgeStatus.PROPOSED: frozenset(
        {
            KnowledgeStatus.ACTIVE,
            KnowledgeStatus.SUPERSEDED,
            KnowledgeStatus.DISPUTED,
            KnowledgeStatus.REVOKED,
            KnowledgeStatus.EXPIRED,
        }
    ),
    KnowledgeStatus.ACTIVE: frozenset(
        {
            KnowledgeStatus.SUPERSEDED,
            KnowledgeStatus.DISPUTED,
            KnowledgeStatus.REVOKED,
            KnowledgeStatus.EXPIRED,
        }
    ),
    KnowledgeStatus.DISPUTED: frozenset(
        {
            KnowledgeStatus.ACTIVE,
            KnowledgeStatus.SUPERSEDED,
            KnowledgeStatus.REVOKED,
            KnowledgeStatus.EXPIRED,
        }
    ),
    KnowledgeStatus.SUPERSEDED: frozenset(),
    KnowledgeStatus.REVOKED: frozenset(),
    KnowledgeStatus.EXPIRED: frozenset(),
}

_SECRET_MARKERS = (
    "password=",
    "api_key=",
    "api-key=",
    "authorization: bearer",
    "-----begin private key-----",
)


@dataclass(frozen=True)
class KnowledgeScope:
    scope_type: KnowledgeScopeType
    scope_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.scope_type, KnowledgeScopeType) or not self.scope_id:
            raise ValueError("KnowledgeScope requires a valid type and scope id")


@dataclass(frozen=True)
class KnowledgeEpisode:
    episode_id: str
    episode_type: str
    captured_at: datetime
    source_ref: str

    def __post_init__(self) -> None:
        if not all((self.episode_id, self.episode_type, self.source_ref)):
            raise ValueError("KnowledgeEpisode requires identity, type, and source")
        if not isinstance(self.captured_at, datetime):
            raise TypeError("captured_at must be a datetime")


@dataclass(frozen=True)
class KnowledgeClaim:
    claim_id: str
    scope: KnowledgeScope
    subject_person_ids: tuple[str, ...]
    domain: str
    statement: str
    provenance: KnowledgeProvenance
    author_person_id: str | None
    source_episode_id: str
    status: KnowledgeStatus = KnowledgeStatus.PROPOSED
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    confidence: float | None = None
    supersedes_claim_id: str | None = None

    def __post_init__(self) -> None:
        if not all(
            (
                self.claim_id,
                self.scope,
                self.subject_person_ids,
                self.domain,
                self.statement,
                self.source_episode_id,
            )
        ):
            raise ValueError("KnowledgeClaim requires identity, scope, subjects, domain, statement, and source")
        if any(not subject for subject in self.subject_person_ids):
            raise ValueError("subject Person ids must be non-empty")
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise ValueError("valid_until cannot precede valid_from")
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        if (
            self.provenance is KnowledgeProvenance.AI_HYPOTHESIS
            and self.status is KnowledgeStatus.ACTIVE
        ):
            raise ValueError("AI_HYPOTHESIS must remain PROPOSED until confirmed")
        if (
            self.provenance is KnowledgeProvenance.USER_CONFIRMED
            and not self.author_person_id
        ):
            raise ValueError("USER_CONFIRMED requires the confirming Person")
        lowered = self.statement.lower()
        if any(marker in lowered for marker in _SECRET_MARKERS):
            raise ValueError("credentials and secrets are never Knowledge")

    def transition(self, status: KnowledgeStatus) -> "KnowledgeClaim":
        if status not in _ALLOWED_TRANSITIONS[self.status]:
            raise ValueError(f"invalid Knowledge lifecycle transition: {self.status.value} -> {status.value}")
        return replace(self, status=status)

    def confirm(
        self,
        new_claim_id: str,
        confirmation_episode_id: str,
        confirming_person_id: str,
    ) -> "KnowledgeClaim":
        """Create a new human-confirmed claim; never mutate AI provenance in place."""
        if self.provenance is not KnowledgeProvenance.AI_HYPOTHESIS:
            raise ValueError("only an AI_HYPOTHESIS uses explicit hypothesis confirmation")
        if not confirmation_episode_id:
            raise ValueError("confirmation episode is required")
        if not new_claim_id or not confirming_person_id:
            raise ValueError("confirmed claim id and confirming Person are required")
        return KnowledgeClaim(
            claim_id=new_claim_id,
            scope=self.scope,
            subject_person_ids=self.subject_person_ids,
            domain=self.domain,
            statement=self.statement,
            provenance=KnowledgeProvenance.USER_CONFIRMED,
            author_person_id=confirming_person_id,
            source_episode_id=confirmation_episode_id,
            status=KnowledgeStatus.ACTIVE,
            valid_from=self.valid_from,
            valid_until=self.valid_until,
            confidence=self.confidence,
            supersedes_claim_id=self.claim_id,
        )
