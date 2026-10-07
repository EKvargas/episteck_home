# Knowledge Architecture (PURE CONTRACTS IMPLEMENTED — no runtime installed)

Episteck **Knowledge** is a governance layer for durable, reusable, contextual
personal/family knowledge — with ownership, provenance, consent, sharing, and
correction/deletion. It is **not** a duplicate store for structured domain facts
(those stay in their owning services) and **not** the Hermes working memory.

> The pure Python contracts live in `packages/home-contracts`. They provide no
> storage, extraction, indexing, retrieval, embeddings, or service runtime. **No**
> Knowledge store is installed: not SQLite, Mem0, Graphiti, RAGFlow, Postgres/pgvector
> or Docling.

## Concepts

### KnowledgeScope
- Scope types: **PERSON**, **CIRCLE**.
- A claim is scoped to a Person or a Circle; visibility still runs through
  `can_access` on the KNOWLEDGE domain (and the relevant subject).

### KnowledgeEpisode (source material)
Represents where knowledge came from: conversation, document, form, import, domain
event, professional note. Carries `episode_id`, `type`, `captured_at`, `source_ref`.

### KnowledgeClaim (a reusable piece of contextual knowledge)
| field | meaning |
| --- | --- |
| claim_id | stable id |
| scope | PERSON or CIRCLE (+ scope ref) |
| subject_person_ids | who the claim is about |
| domain | NUTRITION/HEALTH/…/KNOWLEDGE |
| statement | the contextual knowledge (natural language or structured) |
| provenance | see below |
| author_person_id | who asserted it (or system) |
| source_episode_id | the Episode it was extracted from |
| valid_from / valid_until | temporal validity |
| status | lifecycle (see below) |
| confidence | where appropriate |

### Provenance (source of a claim)
USER_EXPLICIT, USER_CONFIRMED, IMPORTED_SOURCE, PROFESSIONAL_PROVIDED,
SYSTEM_OBSERVED, AI_HYPOTHESIS, AI_SUMMARY, DERIVED.

### Lifecycle (status)
PROPOSED → ACTIVE → (SUPERSEDED | DISPUTED | REVOKED | EXPIRED).

### Hard rules
- **AI_HYPOTHESIS must never silently become USER_CONFIRMED.** Promotion requires an
  explicit human confirmation event (which itself becomes provenance).
- Knowledge preserves source/provenance always.
- Never store credentials/secrets as Knowledge.

The contract represents confirmation by creating a new `USER_CONFIRMED` claim with
an explicit confirmation Episode and a `supersedes_claim_id`; it never rewrites an
AI hypothesis in place. Lifecycle transitions preserve provenance and source.

## Knowledge vs domain truth (examples)
weight → Device Gateway · diagnosis → FHIR · nutrition intake → svc-nutrition ·
calendar event → Calendar · Person/Circle → Home Control Plane. Knowledge references
these; it does not replace them.

## ContextBundle contract (implemented; retrieval is not)
Pipeline (authorization BEFORE any sensitive retrieval):
```
query
 → resolve actor
 → resolve subjects/circles
 → authorization (can_access per subject+domain)
 → determine allowed scopes/domains
 → retrieve Knowledge (allowed only)
 → retrieve documents (allowed only)
 → retrieve current structured domain state (allowed only)
 → rerank
 → assemble ContextBundle
 → Home Agent
```
`ContextBundle` formalizes `actor_person_id`, `subject_person_ids`, `circle_ids`,
`authorized_domains`, `knowledge_claims`, `document_evidence`,
`structured_domain_context`, and `sources`. Its constructor rejects Knowledge,
document evidence, or structured-domain references without prior matching
subject/domain VIEW authorization. Structured domain truth is represented by
`StructuredDomainReference(owner_service, record_type, record_id)`, not copied into
durable Knowledge.

The module also formalizes `KnowledgeScopeType`, `KnowledgeScope`,
`KnowledgeEpisode`, `KnowledgeClaim`, `KnowledgeProvenance`, `KnowledgeStatus`,
`AuthorizedDomain`, `DocumentEvidence`, and `SourceReference`.

## Technology direction (selected by the Knowledge Technology Gate; NOT installed)
The [Knowledge Technology Gate](proposals/KNOWLEDGE_TECHNOLOGY_GATE.md) is **CLOSED —
SELECTION COMPLETE** (2026-09-25). See the
[closure record](proposals/KNOWLEDGE_TECHNOLOGY_GATE_SPIKE_REPORT.md#27-technology-gate-closure-record-2026-09-25).

- **Selected:** S1 — relational canonical owner with structured retrieval, realized
  on **SQLite 3.41.2**. The **Episteck Knowledge governance layer** stays
  Episteck-owned (Person/Circle/Consent).
- **Pre-runtime obligations** (all six must be resolved before runtime
  implementation approval):
  1. **CLOSED** — production SQLite durability mode/mechanism satisfying B4,
     [Board disposition 2026-09-27](proposals/KNOWLEDGE_SQLITE_DURABILITY.md).
  2. **OPEN** — direct warm/cold end-to-end latency confirmation.
  3. **OPEN** — timing side-channel closure.
  4. **CLOSED** — [production R13 mechanism](proposals/KNOWLEDGE_R13_PRODUCTION_MECHANISM.md),
     Board disposition 2026-09-27; provisioning and rollout are separate gates.
  5. **OPEN** — real R14 / domain measurement (the spike used a synthetic 10 ms injection).
  6. **CLOSED** — [restore-freshness realization](proposals/KNOWLEDGE_RESTORE_FRESHNESS.md),
     Board disposition 2026-09-26.
- **Not authorized:** selection authorizes no implementation, migration, schema
  deployment or runtime.

Candidates evaluated and **not selected**:
- **PostgreSQL** (with or without pgvector): spiked as S1-PostgreSQL and not selected.
  pgvector stays deferred until a measured semantic-retrieval need exists.
- **Mem0 / RAGFlow:** hard-eliminated as canonical owner.
- **Graphiti:** not shortlisted.
- **Docling:** deferred to document ingestion.

## Knowledge Authorization Plan implementation progress

**Updated:** 2026-10-06. The accepted runtime contract is
[`KNOWLEDGE_AUTHORIZATION_PLAN_RUNTIME_CONTRACT.md`](proposals/KNOWLEDGE_AUTHORIZATION_PLAN_RUNTIME_CONTRACT.md).
The Board accepted that contract in PR #56; PR #56 remains open. Its acceptance
does not authorize production endpoints, credentials, certificates, deployment,
or data migration. KAP-1 is being reviewed as a contract-only package change on a
draft branch based on PR #56.

| Item | Accepted scope and prerequisite | Current evidence / unmet acceptance |
| --- | --- | --- |
| KAP-1 | Versioned strict wire/domain contracts and test vectors; first. | Architecturally accepted at PR #58 head `e5b2e4ff47245d7d1af4d74873e7eaabc57e7718` (37 local tests); still unmerged, no live use. |
| KAP-2 | Home typed PERSON/CIRCLE policy, trusted partition binding, durable rollback-safe authorization revision; needs KAP-1. | PR #59 at `8d9e3f904eae6015872cf4dc2178972ab4e03579` accepted as **candidate for integration validation**, not complete or approved for production. This branch adds only a pure disconnected typed evaluator and policy/isolation unit tests. The trusted snapshot loader, database guard, independent GCS witness, restore proof and live race tests remain. |
| KAP-3 | Dedicated `olin-runtime` machine identity and Home-owned bounded one-use request context; needs KAP-2. | Not implemented. Provisioning is separately gated; no credential exists for this path. |
| KAP-4 | Complete RT#1 Authorization Plan evaluation; needs KAP-3. | Not implemented. No Home endpoint or integration tests exist. |
| KAP-5 | Home R13 signer and trusted service/SPKI registration; needs KAP-4. | Not implemented. No key provisioning, trust registration, or issuance tests exist. |
| KAP-6 | Persistent Home client and protected metadata planner; needs KAP-1 and KAP-4. | Not implemented. No runtime client or content-planning path exists. |
| KAP-7 | Direct domain mTLS adapter, R13 verifier, replay store, and repository guard; needs KAP-5 and KAP-6. | Not implemented. No production domain route or live peer verification exists. |
| KAP-8 | Fresh RT#2 evaluation and disclosure ordering; needs KAP-2, KAP-3, and KAP-4. | Not implemented. No endpoint, ordering fence, or revocation-race tests exist. |
| KAP-9 | Constrained exact-version retrieval, Knowledge control fence, and ContextBundle release; needs KAP-6, KAP-7, and KAP-8. | Not implemented. SQLite selection is not an installed store; restore freshness and suppression remain runtime gates. |
| KAP-10 | Adversarial end-to-end tests, two-crossing proof, latency/timing gates, and real R14/domain measurement; needs all prior items. | Not implemented or live-verified. Obligations #2, #3, and #5 remain open. |

“Implemented locally” and “unit-tested” do not mean merged, deployed, or live
verified. Track each state separately in the KAP draft PRs and update this table
after each accepted review.
