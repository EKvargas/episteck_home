# Independent Architecture Review — Knowledge

Date: 2026-09-19

Status: REVIEW INPUT — NOT CANONICAL ARCHITECTURE

Repository: EKvargas/episteck_home

Review baseline: `ddebab6439c9d68487d180dec6995fc546d3cf68` (approved GitHub `main` at the time of review).

G1.6 subsequently closed through [PR #17](https://github.com/EKvargas/episteck_home/pull/17), merged on 2026-09-19 at `b256c47d00f45aca6ff3bc28dfca39687c74994f`. This historical review is preserved on that later baseline without changing its findings to match subsequent decisions. Statements below about PR #17 being open describe the original review time, not its current state.

## Purpose and authority

This document preserves an independent architecture review of the proposed Olin Knowledge architecture.

Its findings and recommendations are NOT automatically accepted decisions.

Canonical architecture remains in:

- [docs/architecture/ARCHITECTURE.md](../ARCHITECTURE.md)
- [docs/architecture/KNOWLEDGE.md](../KNOWLEDGE.md)
- [accepted ADRs](../adr/)
- [approved architecture proposals](../proposals/)

Accepted/rejected findings must be resolved explicitly by the Product Architect. The [Knowledge Technology Gate](../proposals/KNOWLEDGE_TECHNOLOGY_GATE.md) records unresolved decisions; opening that register does not accept this review.

## Preservation note

The original review follows. Formatting has been adapted for a repository document; findings, B1–B6 blockers, reasoning, technology analysis, and recommendations are preserved. Test/probe results and upstream technology observations are historical evidence from the review, not new runtime validation performed while persisting this document. Examples are synthetic or conceptual, not personal medical or financial records.

## Original independent review

**Verdict: NOT READY for Knowledge technology selection.** The conceptual foundation is sound, but several authorization, ownership, and lifecycle decisions remain unresolved. Preserve the existing architecture; close those decisions before approving persistence or retrieval technology.

```json
{
  "review_type": "independent_architecture_review",
  "repository": "EKvargas/episteck_home",
  "approved_baseline": "ddebab6439c9d68487d180dec6995fc546d3cf68",
  "local_checkout": "detached HEAD at d7d3b2dfb9917f1d5c87d16d7d78dc4e17e0601b",
  "pr_17": {
    "state": "OPEN",
    "head": "3f557ae43b095fd8744bf480b47b8cd756735bc0",
    "treatment": "inspected as pending closeout evidence; untouched"
  },
  "validation": {
    "existing_contract_test_functions_passed": 12,
    "method": "evaluated directly from origin/main in memory",
    "production_validation_performed": false
  },
  "files_created_or_modified": [],
  "verdict": "NOT READY"
}
```

I fetched `origin`, verified GitHub `main`, read all six requested architecture documents completely, both contracts and their tests, and ADRs 0001–0009. Additional inspection covered the consent policy, Circle/Consent schemas, and Nutrition preference persistence.

[PR #17](https://github.com/EKvargas/episteck_home/pull/17) reports the completed G1.6 cutover from the approved SHA. Its latest diff includes the documentation corrections concerning authentication metadata and deferred OIDC `sub` remediation. These remain pending changes; I neither adopted them as merged architecture nor independently verified production. The Knowledge findings below do not depend on its merge.

### 1. Current architecture as understood

The five-layer distinction is coherent:

| Layer | Responsibility |
|---|---|
| Structured domain truth | Domain services own authoritative records and calculations. |
| Relationship/control truth | Home Control Plane owns identity, relationships, consent, and policy decisions. |
| Durable contextual Knowledge | Stores reusable assertions, preferences, rationale, and context with provenance and lifecycle. |
| Sources/originals | Preserve what was actually said, received, or captured. Extraction produces separate claims. |
| Working memory | Supports agent execution and conversation continuity without becoming canonical Knowledge. |

Knowledge is currently **a contract model, not a runtime**. `ContextBundle` is a composition contract. Neither implements storage, authorization calls, retrieval, or erasure.

The approved foundations remain appropriate: independent domain ownership, centralized consent, trusted actor binding, and separation of privileged infrastructure operations from the user-facing agent. [Architecture](https://github.com/EKvargas/episteck_home/blob/ddebab6439c9d68487d180dec6995fc546d3cf68/docs/architecture/ARCHITECTURE.md), [Knowledge](https://github.com/EKvargas/episteck_home/blob/ddebab6439c9d68487d180dec6995fc546d3cf68/docs/architecture/KNOWLEDGE.md).

### 2. What is already strong

- **Knowledge is explicitly prevented from replacing domain services.** This is the most important boundary to preserve.
- **Membership and care relationships do not imply access.** That supports overlapping families and care networks.
- **Actor identity comes from trusted authentication.** Knowledge should inherit this boundary unchanged.
- **Confirmation creates a new assertion.** Preserving the distinction between an AI inference and a human assertion is correct.
- **Validity and lifecycle are explicit.** These are necessary even without graph infrastructure.
- **Technology is deferred.** Dependency-free contracts provide room to resolve semantics before inheriting a vendor’s memory model.

These decisions can survive Health, Finance, Documents, Family, and AI. Their operational interpretation needs strengthening.

### 3. Critical flaws and blockers

These are blockers to architecture approval for technology selection, **not claims of an existing production Knowledge vulnerability**.

| ID | Finding and evidence | Required decision to close |
|---|---|---|
| **B1** | **Scope, tenant, and authorization resources do not align.** The policy authorizes a Person; Circle claims have no independent Circle authorization rule. `ContextBundle` does not inspect claim scope or validate Circle inclusion. | Define tenant binding, Person/Circle resource authorization, and how permissions combine for claims about several people. |
| **B2** | **Content can lose its security classification.** Claims and excerpts have one domain; source references have no subject/domain authorization checks. A document can contain several domains and people. | Define inherited restrictions for claims, excerpts, sources, and derived content; prevent relabeling sensitive material as generic Knowledge. |
| **B3** | **Confirmation and lifecycle guarantees are incomplete.** A revoked hypothesis can be confirmed; the “new” ID may equal the original; confirmation does not itself supersede the original. `AI_SUMMARY` and `DERIVED` can be constructed ACTIVE without confirmation. | Define authorized transitions, confirmation evidence, atomic replacement, and which generated outputs may become active. |
| **B4** | **Deletion and derivation lack a governing model.** One source episode and one predecessor link cannot establish all evidentiary dependencies or deletion obligations. | Define source/claim dependencies, immediate suppression, durable erasure, reindex protection, and backup/restore behavior. |
| **B5** | **The proposed first vertical already overlaps existing domain ownership.** Nutrition persists `preferences` and `dislikes`. Separately, Roadmap places Knowledge governance implementation in Home while other docs describe an independent Knowledge owner. | Decide the canonical owner of reusable food preferences and the responsibility boundary between Home and Knowledge. |
| **B6** | **A bundle validates supplied metadata, not trusted authorization or disclosure timing.** It accepts inactive/expired claims and has no authorization freshness or revocation semantics. | Define the trusted assembly boundary, current-state eligibility, revalidation points, and session/cache invalidation. |

Concrete probes against approved contracts accepted:

- A Circle claim without that Circle appearing in the bundle.
- A source reference with no authorization records.
- REVOKED, SUPERSEDED, and EXPIRED claims.
- An ACTIVE claim whose validity had ended.
- Confirmation of a revoked hypothesis using its original ID.
- A PERSON scope referring to someone absent from its subjects.
- Document evidence without a DOCUMENTS grant when its single domain was NUTRITION.

The document case exposes an **unresolved policy choice**; the others demonstrate missing contract guards. Existing tests passing does not establish these broader guarantees. [Knowledge contract](https://github.com/EKvargas/episteck_home/blob/ddebab6439c9d68487d180dec6995fc546d3cf68/packages/home-contracts/src/episteck_home_contracts/knowledge.py#L114), [Context contract](https://github.com/EKvargas/episteck_home/blob/ddebab6439c9d68487d180dec6995fc546d3cf68/packages/home-contracts/src/episteck_home_contracts/context.py#L103).

### 4. Important but non-blocking improvements

Specify these before implementing the relevant feature:

- UTC-aware timestamps, interval boundary rules, and the meaning of unknown validity.
- Source locators precise enough to identify a message, page, table, or passage.
- Idempotent capture and optimistic concurrency for competing corrections.
- Explicit “not available,” “not authorized,” and “not known” handling without leaking resource existence.
- A bounded retrieval evaluation set covering relevance, negation, corrections, abstention, and unauthorized distractors.
- A documented limit on claims, excerpts, and token volume per request.

Avoid treating keyword detection as a secrets guarantee. The current five-marker check is useful hygiene but cannot establish that arbitrary statements contain no credentials. [Secret validation](https://github.com/EKvargas/episteck_home/blob/ddebab6439c9d68487d180dec6995fc546d3cf68/packages/home-contracts/src/episteck_home_contracts/knowledge.py#L65).

### 5. Missing Knowledge processes

The proposed process list is necessary but incomplete.

| Additional process | Why it matters |
|---|---|
| **Admission and domain routing** | Distinguishes “remember this preference” from “record this measurement” before persistence. |
| **Sharing and reclassification** | Making private Knowledge shared, adding subjects, or changing its sensitivity changes access requirements. |
| **Dependency invalidation/recomputation** | A corrected or withdrawn source must affect dependent summaries and claims. |
| **Dispute resolution and rejection** | DISPUTED needs an outcome and responsible decision-maker; rejected proposals need a retention policy. |
| **Capture deduplication and retry recovery** | Replayed messages and imports must not create contradictory duplicate claims. |
| **Export/import with provenance** | Portability must preserve attribution and lineage without silently importing permissions. |
| **Membership and household transitions** | Joining, leaving, household separation, and dependent-to-adult transitions affect access and stewardship. |
| **Restore and reindex reconciliation** | Old backups or queued jobs must not resurrect forgotten information. |
| **Working-memory invalidation** | Revocation must affect future agent use, not just the next database query. |

Each process needs a small specification: initiator, authorization, input, state change, dependent artifacts, failure behavior, and user-visible result. This does not require a workflow engine.

### 6. Review of Scope, Episode, and Claim

**Episode → Claim is a useful capture abstraction, but not a complete evidence model.**

An Episode should represent a capture or assertion event. It should reference an original or exact source location. A PDF, a conversation, and the event of importing either are not interchangeable.

One Episode may produce several claims; one claim may depend on several Episodes or other claims. Keep the initial capture episode, but permit additional evidence/dependency links when needed. Ordinary relational links are sufficient.

**Claim is an appropriate durable unit if it is independently correctable.**

“Prefers Mediterranean food and dislikes canned tuna” should not be one indivisible claim. Its clauses can change independently. Conversely, avoid atomizing every sentence into a universal subject–predicate–object ontology.

A claim should retain meaningful qualifiers:

- Who or what it concerns.
- Context of applicability.
- Negation.
- Validity.
- Attribution.

For PERSON scope, the scope Person must be among the subjects. Additional subjects introduce additional access requirements. For CIRCLE scope, an empty Person-subject set can be legitimate.

Scope expresses contextual placement; it must not silently mean ownership, audience, or authorization.

### 7. Review of proposed ClaimKind

**The separation from provenance is sound.** Semantic kind and how something was learned answer different questions.

However, adopt a small vocabulary with clear retrieval consequences:

| Kind | Recommendation |
|---|---|
| PREFERENCE | Keep; includes likes and dislikes with explicit polarity. |
| GOAL | Keep when contextual; canonical plans and numeric targets still belong to their owner. |
| CONSTRAINT | Keep carefully; distinguish a personal limitation from a clinical contraindication or security rule. |
| DECISION | Keep; should identify whose decision and its applicability. |
| RATIONALE | Prefer a relationship to the decision/goal it explains; standalone only when independently reusable. |
| ROUTINE | Keep; a habitual pattern is not a Calendar event. |
| CONTEXT_FACT | Consider CONTEXT_ASSERTION: “fact” can overstate an unverified assertion. |
| INSTRUCTION | Defer as a generic kind. Narrowly scoped user directives may be useful, but must never become executable authority. |

Kinds must not grant permissions, establish truth, or determine canonical ownership by themselves. A claim labeled CONSTRAINT cannot override Health or authorization policy.

Only PREFERENCE needs to be implemented for the first vertical.

### 8. Review of provenance and lifecycle

The provenance enum is useful for display but mixes three dimensions:

- Origin: user, professional, imported source, system.
- Transformation: extraction, summary, derivation.
- Attestation: explicit assertion or confirmation.

An AI summary of a professional document has all three. One enum cannot preserve the complete explanation.

Keep the enum initially, supplemented by source/producer identity, processing lineage where applicable, and explicit confirmation events.

| Dimension | Needed? |
|---|---|
| Claim kind | Yes. |
| Source authority | Evidence of identity, role, verification, and context where relevant; no universal authority score. |
| Confidence | Optional and explicitly defined, such as extraction confidence. Never authorization or truth. |
| Certainty | Preserve meaningful uncertainty in the assertion; defer a separate numeric scale. |
| Freshness | Yes, through timestamps, validity, and review policy; no generic freshness score needed. |

**Recommend a hybrid persistence model:** immutable assertion content/provenance, transactional lifecycle state, and a small transition history. Do not introduce full event sourcing. Do not retain sensitive payload forever merely because it once appeared in an event.

Distinguish:

- **Correction:** the previous assertion was wrong.
- **Change:** it was previously valid and is different now.
- **Dispute:** its validity is contested.
- **Supersession:** a successor replaces it for a defined purpose.

“Newest wins” is unsafe for professional observations, conflicting family accounts, and financial evidence. A higher confidence score is not a conflict-resolution policy.

Confirmation must validate authority, current status, distinct identity, and the exact reviewed content, then atomically activate the successor and retire the predecessor. [Current confirmation behavior](https://github.com/EKvargas/episteck_home/blob/ddebab6439c9d68487d180dec6995fc546d3cf68/packages/home-contracts/src/episteck_home_contracts/knowledge.py#L151).

### 9. Circle-scoped Knowledge recommendation

Approve the proposed semantic correction:

- PERSON scope requires Person subjects.
- CIRCLE scope may have no Person subjects.

**Do not approve it as an isolated validator change.** The present authorization loop would execute zero checks for an empty subject set.

A Circle claim needs:

1. Tenant access.
2. Explicit access to that Circle’s Knowledge resource.
3. Applicable domain restrictions.
4. Additional Person restrictions for any people the content concerns.

Access must come from an explicit policy/grant, not membership alone. The current Person-based ConsentGrant cannot express this directly. [Consent schema](https://github.com/EKvargas/episteck_home/blob/ddebab6439c9d68487d180dec6995fc546d3cf68/apps/episteck_home/episteck_home/episteck_home/doctype/consent_grant/consent_grant.json).

“Our household usually eats at 19:00” can have no Person subjects. “We eat early because Alice has condition X” cannot avoid Alice’s restrictions by being stored under the household.

Also decide who may assert, correct, dispute, and remove shared claims. One member’s statement must not automatically become family consensus.

Until that policy exists, a PERSON-only runtime is a reasonable explicit limitation.

### 10. Tenant-isolation implications

**Yes: introduce a first-class tenant/security-partition concept distinct from Circle.** Naming it Tenant avoids conflating a commercial boundary with a HOUSEHOLD-type Circle.

A Person may participate in overlapping social and care Circles. That does not imply a shared storage or encryption boundary.

Decisions needed now:

- Bind tenant identity through trusted infrastructure.
- Give all content and derivatives an unambiguous tenant association.
- Scope references, uniqueness, caches, jobs, exports, and indexes to that tenant.
- Reject cross-tenant references unless a later explicit sharing mechanism authorizes them.
- Permit tenant data to be located and removed without scanning unrelated customer content.
- Keep application access separate from support and infrastructure privileges.

The proposed preauthorization invariant is necessary but insufficient: it must cover query rewriting, embeddings, chunk expansion, reranking, source lookup, caches, and final model disclosure.

Preserve the option of separate databases/storage and keys. Avoid global cross-tenant deduplication, shared sensitive summaries, or shared vector namespaces that make independent deletion difficult.

Per-tenant encryption keys do not automatically protect data from a running service that can decrypt it. Ordinary vector search also needs usable vectors inside its execution boundary.

Support access should eventually be exceptional, tenant-scoped, time-limited, purpose-recorded, and audited. Full commercial provisioning and key management can remain deferred.

### 11. ContextBundle review

**Keep ContextBundle as an assembly result. It is not the authorization authority.**

A constructor receiving `AuthorizedDomain` objects cannot prove that:

- Home issued the authorization.
- It applies to this actor and tenant.
- It remains current.
- It preceded retrieval.

Those guarantees belong to trusted service orchestration and enforcing repositories/providers. The bundle validator is an additional consistency check.

Recommended pipeline refinements:

- Resolve tenant and actor first.
- Discover only resources the actor may discover.
- Establish resource/domain permissions before content retrieval.
- Retrieve eligible claims and authorized evidence.
- Fetch current domain projections from their canonical owners.
- Revalidate relevant authorization/state before disclosure.
- Assemble only what the task requires.

Record request-local provenance such as policy decision/version, assembly time, and source/domain version or observation time. Such metadata must not become a reusable bearer permission.

A bundle may contain **ephemeral domain values** needed to answer the question. Referencing canonical ownership does not require an LLM to reason from record IDs alone. The prohibition is against turning fetched values into another durable authoritative store.

Prevent DTO growth through optional bounded sections. Avoid embedding every domain’s full record schema or persisting assembled bundles as a convenient Knowledge cache.

### 12. Source/document architecture review

Originals, extracted text, chunks, and claims need distinct identities and lifecycles.

- Originals belong to an explicitly designated source/document custodian.
- Parsed text, chunks, embeddings, and summaries are derived artifacts.
- Claims point to evidence with original/version and message/page/span locators.
- A source pointer does not grant access to its target.
- A user may be allowed to see a claim without being allowed to open its full source.

The same physical database may initially hold claim and source metadata. That does not require identical authorization or retention. Large original files can use separate storage later without changing conceptual ownership.

A document’s container label DOCUMENTS does not fully describe its sensitivity. A medical letter or bank statement may require HEALTH or FINANCE restrictions, and may discuss several people.

Treat document text as untrusted data. Parsing success does not make its instructions trustworthy. Parser workers need bounded resources and restricted access; extracted “instructions” must not mutate consent, change actors, or trigger tool execution.

For “why do you know that?”, return the authorized evidence and attribution available to the actor. Do not expose a private document title or excerpt merely to explain an accessible claim.

### 13. AI persistence and confirmation model

**An LLM may propose a write through a constrained application operation. It must not choose authoritative persistence metadata or write directly to storage.**

The application controls tenant, actor, authorization, source binding, provenance eligibility, and state transitions.

| Operation | Recommended confirmation rule |
|---|---|
| “Remember that I dislike canned tuna” about oneself | The authenticated command is explicit intent; no redundant confirmation is necessary for faithful, low-risk capture. Show what was saved. |
| Ambiguous extraction or changed meaning | Present the proposed wording for confirmation. |
| Inferred preference or sensitive hypothesis | Remain PROPOSED until valid confirmation. |
| Imported/professional assertion | Preserve attribution; import does not equal user agreement or verified professional authority. |
| Shared claim about other people | Require authorization and the agreed shared-assertion policy. |
| Sharing expansion, consequential directive, or canonical-domain mutation | Separate explicit authorization and confirmation through the owning process. |
| Clear request to forget a specific personal preference | Execute the agreed forget semantics; clarify only ambiguous targets or materially broader consequences. |

The general architectural statement that AI output remains a proposal conflicts with the narrower contract guard covering only `AI_HYPOTHESIS`. Resolve this deliberately.

Future automatic summaries may be usable as labeled, authorized derivatives under an explicit policy. They must never acquire human or professional authority simply by changing provenance labels.

### 14. Deletion, revocation, and index-removal model

Separate four operations:

| Operation | Meaning |
|---|---|
| Revoke access | This actor loses permission; the underlying record may remain valid. |
| Withdraw/revoke a claim | The assertion stops participating in ordinary use; restricted history may remain. |
| Supersede/expire | The assertion is historical or outside its validity period. |
| Delete/erase | Remove content and covered derivatives according to the retention promise. |

“Forget” needs a product definition. My recommendation: stop use immediately and remove the selected durable memory plus dependent retrieval artifacts. Clearly disclose whether the original conversation/document remains. Do not silently promise erasure when only a status changed.

A minimal reliable sequence is:

1. Commit authoritative suppression and a new content/deletion version.
2. Deny subsequent use through every retrieval path immediately.
3. Remove covered vectors, chunks, summaries, caches, and other derivatives.
4. Prevent stale jobs from publishing against an obsolete version.
5. Verify removal and report cleanup completion separately from immediate suppression.
6. Reapply deletions before a restored backup becomes accessible.

**Embeddings must be treated as sensitive derivatives.** Deleting their source text does not delete the vectors or other artifacts containing its influence. Database deletion also does not imply immediate physical removal of old row versions. [PostgreSQL storage reclamation](https://www.postgresql.org/docs/current/routine-vacuuming.html).

Dependency links need meaning. A historical “supersedes” link is not necessarily an evidentiary dependency. Otherwise deleting an old hypothesis could incorrectly invalidate a newly independent human assertion.

Dependent outputs should become unusable when required evidence is withdrawn, then be recomputed or reviewed. Access revocation must constrain dependent outputs without requiring deletion of the source for everyone.

Backups require a defined retention/expiry policy and restore discipline. Minimal tombstones should avoid retaining deleted statements. Tenant deletion must include originals, indexes, exports, queues, caches, histories, and encryption-key copies where applicable.

Finally, information already disclosed to an LLM cannot be retroactively undisclosed. Stop future disclosure, invalidate reusable sessions/caches where supported, and minimize initial exposure.

### 15. Technology assessment

| Candidate | Assessment |
|---|---|
| **Plain Postgres** | Strongest initial candidate after blockers close. Transactional claims, evidence links, lifecycle state, and authorized structured selection fit naturally. Food preferences may need no text search. RLS is useful defense in depth, but owners normally bypass it and superusers/BYPASSRLS roles bypass it; runtime privilege design matters. [PostgreSQL RLS](https://www.postgresql.org/docs/17/ddl-rowsecurity.html). |
| **pgvector** | Optional later retrieval projection. Upstream documents that approximate-index filtering occurs after index scanning, and shared tenant indexes affect recall/speed. Database WHERE/RLS is different from application post-filtering, but shared ANN does not establish the stronger candidate-isolation requirement. Exact ranking over an authorized candidate set is a simpler starting point. Tenant partitioning alone does not solve Person/Circle isolation within a tenant. [pgvector filtering and multitenancy](https://github.com/pgvector/pgvector#filtering). |
| **Mem0 OSS** | Defer. Its persistence/update semantics would need adaptation to Olin’s lifecycle. Current source records previous memory text in deletion history, so its delete operation is not an erasure guarantee. If later useful, evaluate it as a proposal-producing extraction helper against a direct structured extraction call. Application-supplied user identifiers are not authorization. [Mem0 source](https://github.com/mem0ai/mem0/blob/main/mem0/memory/main.py). |
| **Docling** | Credible later document-parser candidate. Its conversion/OCR options do not supply consent, ownership, confirmation, or safe document execution. Evaluate page/span fidelity and representative documents when a Documents vertical exists. Unnecessary for conversational preferences. [Docling pipeline options](https://docling-project.github.io/docling/reference/pipeline_options/). |
| **Graphiti** | Defer. Temporal validity and relational evidence do not themselves require a graph database. Its temporal extraction/invalidation capabilities must not substitute for Olin’s authority-aware dispute rules. Require a concrete multi-hop query workload before considering its operational cost. [Graphiti](https://github.com/getzep/graphiti). |
| **RAGFlow** | Poor initial fit. The integrated platform adds substantial machinery; upstream lists at least 16 GB RAM and a multi-service deployment. Its capabilities do not establish compatibility with Olin’s consent and erasure requirements. Revisit only for a demonstrated document-heavy workload. [RAGFlow](https://github.com/infiniflow/ragflow). |

This is a candidate ranking, not technology approval. Upstream evidence is current documentation/source, not a validated pinned deployment.

### 16. Recommended minimal first Knowledge use case

The preference vertical is appropriate, **after resolving existing Nutrition ownership**.

Nutrition already accepts and persists preferences/dislikes through its profile API. [Profile fields and write path](https://github.com/EKvargas/episteck_home/blob/ddebab6439c9d68487d180dec6995fc546d3cf68/services/nutrition/app/main.py#L43).

My preferred future boundary is:

- Knowledge owns reusable taste assertions.
- Nutrition owns targets, intake, calculations, and other structured Nutrition state.
- Nutrition consumes authorized preferences without maintaining another independently editable canonical copy.

That is a proposed ownership decision, not an instruction to modify Nutrition now.

The first vertical should cover:

1. Explicitly capture separate cuisine preferences and canned-tuna dislike.
2. Retrieve only authorized, active, applicable preferences.
3. Combine them with current authorized Nutrition data for dinner suggestions.
4. Explain the saved assertions through their source messages.
5. Exercise actual correction, expiration, forgetting, and access denial.

**The supplied correction example does not necessarily require supersession.** “Fresh tuna is fine; I dislike canned tuna” is compatible with an accurately captured canned-tuna dislike. Add clarification without retiring the valid dislike.

To test genuine supersession, include a separately mistaken broad “dislikes all tuna” claim, or an explicit change of preference. Distinguish correction of history from a preference changing today.

Use synthetic data first, and include a second Person/tenant as negative authorization cases. Exclude allergy, pregnancy, diagnosis, and clinical dietary restrictions from this vertical.

### 17. What not to build yet

- Generic graph infrastructure or a universal semantic ontology.
- Autonomous background memory extraction from every conversation.
- Broad INSTRUCTION execution.
- Medical or financial inference persistence.
- Full document ingestion and parsing.
- Global vector search across households.
- A giant cross-domain ContextBundle schema.
- Full event sourcing.
- Multiple numeric confidence/authority/certainty scores.
- Complete commercial provisioning, billing, or customer support infrastructure.

Do define the boundaries that would make those additions safe later.

### 18. Proposed architecture changes

These are corrections to the existing design:

1. Clarify Episode as capture/assertion evidence referencing originals.
2. Define claims as independently correctable assertions.
3. Add tenant partitioning independently of semantic scope.
4. Specify Circle authorization before permitting subjectless Circle claims.
5. Define inherited domain/subject restrictions and typed evidence dependencies.
6. Specify hybrid lifecycle persistence, atomic confirmation/supersession, and deletion behavior.
7. Clarify ContextBundle as trusted request-local composition, with ephemeral domain projections allowed.
8. Resolve Nutrition preference ownership and Knowledge/Home runtime responsibility.

The Roadmap currently requires governance implementation “in the Home Control Plane,” while ownership documents describe a Knowledge service. Home should remain the policy authority; the physical owner of Episodes/Claims must be explicit before storage selection. [Roadmap gate](https://github.com/EKvargas/episteck_home/blob/ddebab6439c9d68487d180dec6995fc546d3cf68/docs/architecture/ROADMAP.md), [Data ownership](https://github.com/EKvargas/episteck_home/blob/ddebab6439c9d68487d180dec6995fc546d3cf68/docs/architecture/DATA_OWNERSHIP.md).

Also separate **process approval → technology selection → runtime approval**. Requiring a persistence implementation before selecting persistence technology would make the gate circular.

### 19. Questions requiring Product Architect decision

| Decision | Reviewer recommendation |
|---|---|
| Who owns reusable food preferences? | Knowledge, with an explicit transition from existing Nutrition fields; no dual ownership. |
| What does PERSON scope mean when several subjects appear? | The scope Person must be included; every affected subject contributes restrictions. |
| Who speaks for a Circle? | Explicit authority and attribution; membership alone is insufficient. |
| What does “forget” promise about retained conversations/documents? | Immediate non-use plus clearly stated erasure scope. |
| Does confirmation independently attest content or merely acknowledge reading it? | Record the distinction; acknowledgement must not create truth or wider sharing. |
| How do DOCUMENTS and content-domain permissions combine? | Preserve both resource access and sensitive-content restrictions, with explicit approved projections if needed. |
| What happens when Knowledge contradicts canonical state? | Use the canonical owner for its structured field; flag discrepancies and route corrections there. Preserve attributed historical evidence where appropriate. |
| Can AI summaries become active automatically? | Defer initially; later permit only under explicit derivation and inherited-access rules. |
| What is the commercial partition? | Tenant, distinct from Circle; cross-tenant sharing deferred. |
| Where are Episodes/Claims persisted? | Explicit Knowledge ownership; Home continues to own identity and authorization. |

For cross-domain survival, the key rule is **field-specific authority**. A diagnosis, transaction, appointment, or current balance must not become an editable Knowledge “fact.” Conversely, a person’s goal, explanation, or disagreement should not disappear merely because it is not canonical domain state.

### 20. Final verdict and exact blockers

**NOT READY.**

Close these six architecture decisions before approving technology:

- **B1:** Tenant, Person, Circle, and multi-subject authorization semantics.
- **B2:** Source/claim/excerpt sensitivity inheritance and disclosure permissions.
- **B3:** Confirmation, correction, dispute, and atomic lifecycle rules.
- **B4:** Dependency invalidation, forgetting, index removal, and restore semantics.
- **B5:** Nutrition preference ownership and Knowledge persistence responsibility.
- **B6:** Trusted retrieval/assembly, authorization freshness, and working-memory revocation.

Closure requires agreed process rules and acceptance scenarios—not a complete commercial design or an implemented runtime.

After closure, **plain relational persistence with bounded authorized retrieval** is the leading baseline. Add vectors only if measured retrieval requirements justify them.

No files, contracts, production systems, or PRs were changed during the original independent review.
