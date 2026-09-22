"""The ONE logical synthetic Knowledge model both backends realize (correction 9).

This is not a production schema. It is the minimum synthetic structure needed to test
accepted B1-B6 invariants: trusted partition, immutable assertion versions, replacement
lines, complete subjects, required domains, classification revision, lifecycle/control
revision, applicability state, suppression register, derivation/materialization bindings,
source/version references.

Security metadata (partition, subjects, domains, lifecycle state, classification,
suppression, applicability) is modeled SEPARATELY from statement text (`content_text`), so
metadata-only queries never touch content -- this is what H2 requires and what the
metadata-planning phase of every scenario exercises.

`sqlite_backend.py` and `postgres_backend.py` both implement the same operations against
this same logical shape. Only backend-specific storage (FTS5 vs tsvector/GIN for S2) is
allowed to differ, and only where the experiment intentionally targets it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class LifecycleState(str, Enum):
    PROPOSED = "PROPOSED"
    ADMITTED = "ADMITTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    DISPUTED = "DISPUTED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


DOMAINS = frozenset({"NUTRITION", "HEALTH", "CALENDAR", "FINANCE", "HOUSEHOLD", "KNOWLEDGE"})


@dataclass(frozen=True)
class AssertionVersion:
    """One immutable assertion version -- the exact-version unit lifecycle attaches to."""

    version_id: str
    partition_id: str
    line_id: str  # replacement-line grouping; not a global topic identity
    subject_person_ids: tuple[str, ...]
    domains: tuple[str, ...]
    content_text: str  # SENSITIVE. Never read during metadata planning.
    lifecycle_state: LifecycleState
    classification_revision: int
    control_revision: int
    applicable_from: int  # epoch seconds
    applicable_until: int | None
    replaces_version_id: str | None = None
    source_id: str | None = None
    source_version: str | None = None


@dataclass(frozen=True)
class SuppressionRecord:
    """Durable non-use fact. Independent of physical deletion (B4)."""

    target_version_id: str
    partition_id: str
    reason_family: str  # opaque family, no restated content (B4 S10)
    effective_at: int


@dataclass(frozen=True)
class MaterializationBinding:
    """A derived artifact's currency binding (H6) -- checkable without a rebuild."""

    binding_id: str
    partition_id: str
    source_version_id: str
    derivation_family: str
    classification_revision_at_build: int
    control_revision_at_build: int
    suppression_obligation: bool


@dataclass(frozen=True)
class GrantRecord:
    """Synthetic authorization grant the Home stub evaluates against (not real ConsentGrant)."""

    actor_person_id: str
    subject_person_id: str
    domain: str
    action: str  # VIEW / CREATE / UPDATE / MANAGE
    partition_id: str


@dataclass(frozen=True)
class Corpus:
    """A fully generated synthetic corpus, backend-agnostic."""

    seed: int
    size_label: str
    partitions: tuple[str, ...]
    persons: tuple[str, ...]
    circles: tuple[str, ...]
    assertions: tuple[AssertionVersion, ...]
    suppressions: tuple[SuppressionRecord, ...]
    bindings: tuple[MaterializationBinding, ...]
    grants: tuple[GrantRecord, ...] = field(default_factory=tuple)
