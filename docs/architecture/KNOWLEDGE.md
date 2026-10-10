# Knowledge Architecture (PURE CONTRACTS IMPLEMENTED — no runtime installed)

## KAP delivery state (draft consolidation, 2026-10-10)

KAP-1 wire contracts are architecturally accepted but remain unmerged. KAP-2 is open:
the typed evaluator, default-closed transactional witness gateway and procedure-only
PERSON foundation are disconnected disposable candidates. The fresh-incarnation
recovery amendment is **proposed and Board ratification is pending**. The request-time
GCS Candidate A was rejected. KAP-3–10 remain ahead. See the
[consolidation handoff](proposals/KNOWLEDGE_KAP2_CONSOLIDATION_HANDOFF.md) for exact
PR/worktree disposition, validation and deployment implications.

Episteck **Knowledge** is a governance layer for durable, reusable, contextual
personal/family knowledge — with ownership, provenance, consent, sharing, and
correction/deletion. It is **not** a duplicate store for structured domain facts
(those stay in their owning services) and **not** the Hermes working memory.

> The pure contracts live in `packages/home-contracts`. They provide no
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
