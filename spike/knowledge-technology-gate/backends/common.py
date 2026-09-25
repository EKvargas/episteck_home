"""Shared backend interface: the authorized-set execution barrier (Phase-1 SS9.2, SS16.6.1).

Every backend (SQLite, PostgreSQL) implements this exact protocol so scenarios run
identically against both:

    plan_metadata(...)   -> PlannedMetadata   # security metadata ONLY, never content_text
    authorized_ids(...)  -> tuple[str, ...]   # exact authorized version IDs
    fetch_content(...)   -> ContentAccessLog  # content, ONLY for those IDs, fully logged

The ContentAccessLog is the PRIMARY, MANDATORY evidence layer (methodological correction
1.A): every logical content ID actually requested is recorded, and callers assert
`requested_ids <= authorized_ids`. Backend query-plan capture (correction 1.B) is
corroboration only and lives in `instrumentation.py`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Correction 13 (Product Architect directive, PR #33 review): the original per-candidate
# N+1 query pattern in plan_metadata() (one subject query + one domain query PER candidate)
# was the dominant cost at C-large (20,201 SQL statements for 10,100 candidates) and the
# dominant cost in P13's C-medium read phase (1,723 statements for 861 candidates) -- not
# index absence, not corpus-size-driven storage cost, and not a fundamental SQLite-vs-
# PostgreSQL difference. Both backends now batch subject/domain lookups using this SAME
# fixed batch size so the comparison stays fair (requirement: identical batching strategy
# on both realizations, not independently tuned).
METADATA_BATCH_SIZE = 500


def chunk_ids(ids: tuple[str, ...], size: int = METADATA_BATCH_SIZE) -> list[tuple[str, ...]]:
    """Split `ids` into fixed-size batches, preserving order. A conservative fixed size
    (500) is used rather than relying on either backend's maximum parameter count, so the
    same chunking logic and batch count apply identically to SQLite and PostgreSQL."""
    return [ids[i : i + size] for i in range(0, len(ids), size)]


@dataclass(frozen=True)
class CandidateRequirement:
    """The COMPLETE security-metadata requirement for one candidate version -- CORRECTION
    1 (Product Architect review of PR #33): a candidate with subjects {P1, P2} and
    domains {NUTRITION, HEALTH} must expose ALL FOUR subject/domain pairs, not just one,
    so the orchestration layer can compile the true union requirement set before ever
    asking Home for a decision. NEVER carries content_text."""

    version_id: str
    subject_person_ids: tuple[str, ...]
    domains: tuple[str, ...]


@dataclass(frozen=True)
class PlannedMetadata:
    """Result of protected security-metadata planning -- NEVER carries content_text.

    CORRECTION 9 (terminology, Product Architect review of PR #33): `rows_returned` (was
    misleadingly named `rows_inspected`) is the count of CANDIDATE ROWS THE QUERY
    RETURNED -- a logical metric, not a claim about physical rows/pages the backend
    touched internally. The physical-access-style metric
    (`security_metadata_rows_inspected`, per Phase-1 SS16.6.1) requires backend-internal
    instrumentation this spike's application layer cannot itself produce with certainty;
    see `backends/instrumentation.py` for the corroboration-only Layer B evidence, which
    may legitimately report UNKNOWN rather than a false-precision number.
    """

    partition_id: str
    candidate_version_ids: tuple[str, ...]  # eligible before suppression/authorization filter
    candidate_requirements: tuple[CandidateRequirement, ...]  # complete per-candidate subject/domain sets
    rows_returned: int  # metadata_candidate_rows_produced -- logical count, NOT a physical-access claim

    def union_requirement_pairs(self) -> tuple[tuple[str, str], ...]:
        """The complete union of (subject, domain) pairs across every surviving
        candidate -- what a compound Knowledge authorization operation must request."""
        pairs: list[tuple[str, str]] = []
        for req in self.candidate_requirements:
            for s in req.subject_person_ids:
                for d in req.domains:
                    pairs.append((s, d))
        return tuple(dict.fromkeys(pairs))


@dataclass(frozen=True)
class AuthorizedSet:
    """The exact authorized version-ID set produced by the barrier (H3 anchor)."""

    version_ids: tuple[str, ...]  # authorized_versions_produced == len(version_ids)


@dataclass
class ContentAccessLog:
    """Mandatory application-boundary evidence: every logical content ID requested."""

    requested_ids: list[str] = field(default_factory=list)
    authorized_ids_at_request_time: tuple[str, ...] = ()

    def record(self, version_id: str) -> None:
        self.requested_ids.append(version_id)

    @property
    def unauthorized_logical_content_ids_requested(self) -> int:
        authorized = set(self.authorized_ids_at_request_time)
        return sum(1 for vid in self.requested_ids if vid not in authorized)

    @property
    def content_records_examined_after_barrier(self) -> int:
        return len(self.requested_ids)


class KnowledgeBackend:
    """Abstract shape both realizations implement. Not a production interface."""

    name: str

    def load_corpus(self, corpus) -> None:
        raise NotImplementedError

    def plan_metadata(
        self, *, partition_id: str, subject_person_ids: tuple[str, ...], domains: tuple[str, ...],
        as_of: int,
    ) -> PlannedMetadata:
        raise NotImplementedError

    def authorize(
        self, planned: PlannedMetadata, *, granted_version_ids: frozenset[str],
    ) -> AuthorizedSet:
        """Intersect candidate set with what Home's grant decision allows. Local, no I/O."""
        allowed = tuple(v for v in planned.candidate_version_ids if v in granted_version_ids)
        return AuthorizedSet(version_ids=allowed)

    def fetch_content(
        self, authorized: AuthorizedSet, *, log: ContentAccessLog,
    ) -> list[dict]:
        raise NotImplementedError

    def fetch_content_fulltext(
        self, authorized: AuthorizedSet, *, query: str, log: ContentAccessLog,
    ) -> list[dict]:
        """S2 barrier: full-text matching ONLY over the bounded authorized set."""
        raise NotImplementedError

    def resolve_source_expansion(
        self, *, partition_id: str, surviving_version_ids: tuple[str, ...],
    ) -> tuple[CandidateRequirement, ...]:
        """CORRECTION 3: the lazy source-expansion step. Follow each surviving candidate's
        derivation reference (`replaces_version_id`) to its predecessor "source version"
        and return that predecessor's COMPLETE subject/domain requirement (never
        content_text). The orchestrator authorizes the expansion as an INDEPENDENT
        operation -- a separate Home crossing, not a free extension of the base grant.
        Returns () when nothing is reachable (expansion stays lazy by construction)."""
        raise NotImplementedError

    def suppressed_version_ids(self, partition_id: str) -> frozenset[str]:
        raise NotImplementedError

    def materialization_binding_current(self, binding_id: str) -> bool | None:
        """True/False if determinable; None if binding is unknown (fails closed by caller)."""
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError
