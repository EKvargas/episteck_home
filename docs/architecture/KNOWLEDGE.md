# Knowledge Architecture (CONTRACTS ONLY — nothing installed)

Episteck **Knowledge** is a governance layer for durable, reusable, contextual
personal/family knowledge — with ownership, provenance, consent, sharing, and
correction/deletion. It is **not** a duplicate store for structured domain facts
(those stay in their owning services) and **not** the Hermes working memory.

> This stage defines **contracts** so Person/Circle/Consent are ready for a future
> Knowledge service. **No** Mem0 / Graphiti / RAGFlow / Postgres+pgvector / Docling
> is installed now.

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

## Knowledge vs domain truth (examples)
weight → Device Gateway · diagnosis → FHIR · nutrition intake → svc-nutrition ·
calendar event → Calendar · Person/Circle → Home Control Plane. Knowledge references
these; it does not replace them.

## Future ContextBundle contract (define, do NOT implement)
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
**ContextBundle** (conceptual): `actor`, `subjects`, `circles`, `authorized_domains`,
`knowledge_claims`, `document_evidence`, `structured_domain_context`,
`sources/provenance`.

## Candidate technology (documented, NOT selected/installed)
- **Episteck Knowledge governance layer** — always Episteck-owned (Person/Circle/Consent).
- **Mem0 (OSS)** — candidate for conversational memory extraction/search.
- **Docling** — candidate for document parsing.
- **Postgres + pgvector** — candidate for hybrid document/context retrieval.
- **Graphiti** — deferred candidate for temporal/relational context if later justified.
- **RAGFlow** — **not selected** (heavier deployment; Episteck needs custom
  Person/Circle/Consent governance a turnkey RAG stack won't provide).

Decision is deferred to the **Knowledge Technology Gate** (see ROADMAP).
