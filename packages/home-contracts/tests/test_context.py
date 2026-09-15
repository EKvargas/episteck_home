from __future__ import annotations

import pytest

from episteck_home_contracts import (
    AuthorizedDomain,
    ContextBundle,
    DocumentEvidence,
    KnowledgeClaim,
    KnowledgeProvenance,
    KnowledgeScope,
    KnowledgeScopeType,
    KnowledgeStatus,
    SourceReference,
    StructuredDomainReference,
)


def _claim() -> KnowledgeClaim:
    return KnowledgeClaim(
        claim_id="claim-1",
        scope=KnowledgeScope(KnowledgeScopeType.PERSON, "PSN-B"),
        subject_person_ids=("PSN-B",),
        domain="NUTRITION",
        statement="Synthetic confirmed preference",
        provenance=KnowledgeProvenance.USER_CONFIRMED,
        author_person_id="PSN-B",
        source_episode_id="episode-confirmation",
        status=KnowledgeStatus.ACTIVE,
    )


def test_structured_truth_is_referenced_by_owner_and_record_id():
    reference = StructuredDomainReference(
        "PSN-B", "NUTRITION", "svc-nutrition", "profile", "PSN-B"
    )
    assert reference.owner_service == "svc-nutrition"
    assert reference.record_id == "PSN-B"


def test_context_bundle_rejects_unauthorized_structured_context():
    context = StructuredDomainReference(
        "PSN-B", "NUTRITION", "svc-nutrition", "profile", "PSN-B"
    )
    with pytest.raises(ValueError, match="authorization"):
        ContextBundle(
            actor_person_id="PSN-A",
            subject_person_ids=("PSN-B",),
            structured_domain_context=(context,),
        )


def test_context_bundle_rejects_knowledge_without_knowledge_view():
    with pytest.raises(ValueError, match="KNOWLEDGE/VIEW"):
        ContextBundle(
            actor_person_id="PSN-A",
            subject_person_ids=("PSN-B",),
            knowledge_claims=(_claim(),),
            authorized_domains=(
                AuthorizedDomain("PSN-B", "NUTRITION", frozenset({"VIEW"})),
            ),
        )


def test_context_bundle_rejects_unauthorized_document_evidence():
    evidence = DocumentEvidence(
        "evidence-1", "PSN-B", "DOCUMENTS", "source-document", "Synthetic excerpt"
    )
    with pytest.raises(ValueError, match="DOCUMENTS/VIEW"):
        ContextBundle(
            actor_person_id="PSN-A",
            subject_person_ids=("PSN-B",),
            document_evidence=(evidence,),
        )


def test_authorized_context_bundle_preserves_all_contract_sections():
    structured = StructuredDomainReference(
        "PSN-B", "NUTRITION", "svc-nutrition", "profile", "PSN-B"
    )
    document = DocumentEvidence(
        "evidence-1", "PSN-B", "DOCUMENTS", "source-document", "Synthetic excerpt"
    )
    source = SourceReference(
        "source-document", "DOCUMENT", "document:synthetic-1", KnowledgeProvenance.IMPORTED_SOURCE
    )
    bundle = ContextBundle(
        actor_person_id="PSN-A",
        subject_person_ids=("PSN-B",),
        circle_ids=("CIR-HOME",),
        authorized_domains=(
            AuthorizedDomain("PSN-B", "KNOWLEDGE", frozenset({"VIEW"})),
            AuthorizedDomain("PSN-B", "DOCUMENTS", frozenset({"VIEW"})),
            AuthorizedDomain("PSN-B", "NUTRITION", frozenset({"VIEW"})),
        ),
        knowledge_claims=(_claim(),),
        document_evidence=(document,),
        structured_domain_context=(structured,),
        sources=(source,),
    )
    assert bundle.actor_person_id == "PSN-A"
    assert bundle.subject_person_ids == ("PSN-B",)
    assert bundle.circle_ids == ("CIR-HOME",)
    assert bundle.structured_domain_context == (structured,)
