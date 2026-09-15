"""Authorization-carrying ContextBundle contract; retrieval is deliberately absent."""
from __future__ import annotations

from dataclasses import dataclass

from .knowledge import KnowledgeClaim, KnowledgeProvenance


VALID_DOMAINS = frozenset(
    {
        "NUTRITION",
        "HEALTH",
        "CALENDAR",
        "DOCUMENTS",
        "FINANCE",
        "MIND",
        "HOUSEHOLD",
        "KNOWLEDGE",
    }
)
VALID_ACTIONS = frozenset({"VIEW", "CREATE", "UPDATE", "MANAGE"})


@dataclass(frozen=True)
class AuthorizedDomain:
    subject_person_id: str
    domain: str
    actions: frozenset[str]

    def __post_init__(self) -> None:
        if not self.subject_person_id or self.domain not in VALID_DOMAINS:
            raise ValueError("AuthorizedDomain requires a subject and known domain")
        if not self.actions or not self.actions <= VALID_ACTIONS:
            raise ValueError("AuthorizedDomain requires known actions")

    def allows(self, action: str) -> bool:
        return action in self.actions or "MANAGE" in self.actions


@dataclass(frozen=True)
class SourceReference:
    source_id: str
    source_type: str
    source_ref: str
    provenance: KnowledgeProvenance

    def __post_init__(self) -> None:
        if not all((self.source_id, self.source_type, self.source_ref)):
            raise ValueError("SourceReference requires identity, type, and reference")


@dataclass(frozen=True)
class DocumentEvidence:
    evidence_id: str
    subject_person_id: str
    domain: str
    source_id: str
    excerpt: str

    def __post_init__(self) -> None:
        if not all(
            (
                self.evidence_id,
                self.subject_person_id,
                self.source_id,
                self.excerpt,
            )
        ) or self.domain not in VALID_DOMAINS:
            raise ValueError("DocumentEvidence requires identity, subject, domain, source, and excerpt")


@dataclass(frozen=True)
class StructuredDomainReference:
    subject_person_id: str
    domain: str
    owner_service: str
    record_type: str
    record_id: str

    def __post_init__(self) -> None:
        if not all(
            (
                self.subject_person_id,
                self.owner_service,
                self.record_type,
                self.record_id,
            )
        ) or self.domain not in VALID_DOMAINS:
            raise ValueError("StructuredDomainReference requires a canonical owner and record identity")


@dataclass(frozen=True)
class ContextBundle:
    actor_person_id: str
    subject_person_ids: tuple[str, ...]
    circle_ids: tuple[str, ...] = ()
    authorized_domains: tuple[AuthorizedDomain, ...] = ()
    knowledge_claims: tuple[KnowledgeClaim, ...] = ()
    document_evidence: tuple[DocumentEvidence, ...] = ()
    structured_domain_context: tuple[StructuredDomainReference, ...] = ()
    sources: tuple[SourceReference, ...] = ()

    def __post_init__(self) -> None:
        if not self.actor_person_id:
            raise ValueError("ContextBundle requires an actor Person")
        subjects = set(self.subject_person_ids)
        if any(not subject for subject in subjects):
            raise ValueError("ContextBundle subject Person ids must be non-empty")
        for authorization in self.authorized_domains:
            if authorization.subject_person_id not in subjects:
                raise ValueError("authorization subject is outside the ContextBundle")
        for claim in self.knowledge_claims:
            for subject in claim.subject_person_ids:
                self._require(subjects, subject, "KNOWLEDGE", "VIEW")
                if claim.domain != "KNOWLEDGE":
                    self._require(subjects, subject, claim.domain, "VIEW")
        for evidence in self.document_evidence:
            self._require(subjects, evidence.subject_person_id, evidence.domain, "VIEW")
        for reference in self.structured_domain_context:
            self._require(subjects, reference.subject_person_id, reference.domain, "VIEW")

    def _require(
        self,
        subjects: set[str],
        subject_person_id: str,
        domain: str,
        action: str,
    ) -> None:
        if subject_person_id not in subjects:
            raise ValueError("sensitive context subject is outside the ContextBundle")
        if not any(
            authorization.subject_person_id == subject_person_id
            and authorization.domain == domain
            and authorization.allows(action)
            for authorization in self.authorized_domains
        ):
            raise ValueError(
                f"authorization required before retrieving {domain}/{action} context"
            )
