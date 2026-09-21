# Knowledge Technology Gate

Status: OPEN

Phase: PROCESS / ARCHITECTURE

Runtime implementation: NOT APPROVED

Technology selection: NOT APPROVED

Date opened: 2026-09-19

Repository: EKvargas/episteck_home

Creation baseline: `b256c47d00f45aca6ff3bc28dfca39687c74994f` — current `main` after [PR #17](https://github.com/EKvargas/episteck_home/pull/17) merged and closed G1.6.

## Goal and authority

Define the Knowledge processes and invariants required before selecting persistence, retrieval, parsing, graph, workflow, or memory technology.

The governing sequence is:

```text
PROCESS
→ DOMAIN MODEL
→ SERVICES / APIs
→ AGENT TOOLS
→ UI
```

Technology must not dictate the Knowledge model.

This is a working decision register, NOT the final Knowledge architecture. The [independent architecture review](../reviews/2026-09-19-knowledge-independent-architecture-review.md) is historical review input, not canonical architecture. Its reviewed baseline was `ddebab6439c9d68487d180dec6995fc546d3cf68`; the G1.6 closeout was merged subsequently. Its findings were initially recorded without disposition. B1–B4 are now resolved by the explicit Product Architect decisions below; B5–B6 remain OPEN.

Canonical architecture remains in [ARCHITECTURE.md](../ARCHITECTURE.md), [KNOWLEDGE.md](../KNOWLEDGE.md), accepted ADRs, and approved architecture proposals. The accepted [B1 security/scope decision](KNOWLEDGE_B1_SECURITY_SCOPE.md) governs B1 where older Knowledge documentation is less precise, until later consolidation. The existing [Roadmap](../ROADMAP.md) identifies the Knowledge gate. Other canonical documents are not rewritten here, and no runtime approval is granted.

Only explicit Product Architect decisions may accept, modify, or reject review recommendations. For each disposition, record the decision owner, date, exact accepted/modified/rejected finding, reasoning, acceptance scenarios, and references to approved architecture changes. **B1 is RESOLVED** by Product Architect acceptance with amendments on **2026-09-19**. **B2 is RESOLVED** by Product Architect acceptance with clarification on **2026-09-20**. **B3 is RESOLVED** by Product Architect acceptance with D2/D4 clarifications on **2026-09-21**. **B4 is RESOLVED** by Product Architect acceptance with C1–C4 clarifications on **2026-09-21**. B5–B6 remain **OPEN / NOT DECIDED**. The Knowledge Technology Gate remains **OPEN**. A reviewer recommendation or this document's eventual merge does not itself select technology or authorize runtime implementation.

## Current five-layer model

| Layer | Meaning and ownership boundary |
|---|---|
| 1. Structured domain truth | Canonical records and calculations owned by domain services: Nutrition intake/targets, future Health measurements/clinical data, Finance transactions, Calendar events. |
| 2. Relationship / control truth | Person, Circle, CircleMembership, CareRelationship, ConsentGrant, trusted identity and authorization remain Home Control Plane responsibilities. |
| 3. Durable contextual Knowledge | Reusable contextual assertions such as preferences, goals, routines, constraints, decisions and rationale, with provenance and lifecycle. Exact admission and ownership details remain open. |
| 4. Source evidence / originals | Conversations, documents, imports, photos, professional material and other originals. Sources are not the same objects as extracted claims. |
| 5. Agent working memory | Hermes/agent session and execution context. It is not canonical durable personal/family Knowledge. |

Knowledge is NOT:

- a shadow Health DB
- a shadow Finance DB
- a universal domain database
- Hermes working memory
- a vector database abstraction

This distinction preserves the current conceptual direction; it does not resolve contested ownership fields such as reusable Nutrition preferences.

## Security partition — accepted B1 invariant

Status: ACCEPTED — PRODUCT ARCHITECT B1 DECISION, 2026-09-19 (B6 OPEN)

**Every durable Knowledge object and every derivative belongs to exactly one trusted security partition.**

The commercial Tenant object does NOT need to be implemented yet.

- **Security partition** = isolation boundary.
- **PERSON/CIRCLE scope** = semantic context.

Accepted B1 coverage includes partition-bound identifiers and references, originals, claims, chunks, embeddings, summaries, caches, indexes, queued jobs, exports and workflow metadata. Effective identity conceptually includes `(partition, resource_type, local_id)`. Actor and partition come from trusted server/runtime context, never authoritative model/tool/user payload fields. Partition is distinct from Person, Circle, membership, semantic scope and a commercial Tenant object. Initial cross-partition references, joins, Knowledge sharing, sensitive deduplication and retrieval are forbidden. See the [accepted B1 decision](KNOWLEDGE_B1_SECURITY_SCOPE.md).

Avoid:

- global cross-tenant vector namespaces
- cross-tenant deduplication of sensitive content
- unpartitioned caches/indexes/jobs
- global search followed by application post-filtering

The B1 logical boundary and pre-retrieval invariant are accepted. Concrete enforcement, physical isolation, key ownership and future commercial representation remain deferred. This decision does not approve a Tenant implementation, database layout, encryption system or technology.

## B1 — Tenant / Person / Circle / multi-subject authorization

Status: RESOLVED — PRODUCT ARCHITECT DECISION

Decision owner: Product Architect

Decision date: 2026-09-19

Product Architect disposition: ACCEPTED WITH AMENDMENTS

Authoritative decision: [Knowledge B1 — Security partition, scope, and subject authorization](KNOWLEDGE_B1_SECURITY_SCOPE.md), including section 13's Product Architect disposition and acceptance scenarios A–H.

Accepted decisions:

- Partition is trusted isolation; scope is semantic placement; subjects are Persons whose information is revealed. PERSON scope includes its Person; genuinely Circle-only assertions may have empty subjects.
- Reusable/shared Knowledge requires scope AND every subject AND every required content-domain authorization. Self-access covers only the actor's own Person requirement. Membership, care, authorship, majority agreement, Circle MANAGE and generic KNOWLEDGE relabeling cannot bypass Person restrictions. B2 may relax the conservative intersection only through an explicit approved projection/declassification model.
- Accept the structure closest to alternative A: one Home authority and one bounded Authorization Grant family/evaluation model with PERSON/CIRCLE targets and separate issuer rules. PERSON represents consent/access authority; CIRCLE represents handling/stewardship authority, not personal consent. Existing ConsentGrant naming may remain; eventual persisted naming is an implementation/migration decision. No arbitrary-resource model, generic policy language or service-local ACL is adopted.
- Authorized authenticated Circle creation may atomically create the Circle, record the creator's acceptance of initial stewardship and establish bounded Circle MANAGE. Normal consumer onboarding does not require manual system administration. Imported/pre-existing Circles require trusted designation/recovery. Membership/role/AI inference grants nothing; ordinary recipients cannot redelegate, recursive MANAGE delegation is not approved, and root replacement/recovery requires a protected Home process.
- Actor, assertor, subject, attestor and viewer remain distinct. Stewardship endorsement permits shared Circle use, not everyone's agreement; no family-consensus state. Retain VIEW/CREATE/UPDATE/MANAGE; domain operations compose these with trusted context and operation predicates. Detailed lifecycle effects remain B3/B4.
- Narrow non-disclosing own-assertion retraction and own-information objection/non-use do not confer VIEW, rewrite others' words or automatically erase independent sources. B4 owns physical erasure and cleanup.
- Joining grants nothing; exit/removal invalidates Circle-derived grants before completion; rejoining revives none. Dissolution stops ordinary Circle use without Person-scope migration. Authorship gives no perpetual VIEW; independent Person grants are not automatically destroyed by exit. No permanent guardian/representative access is inferred.
- Trusted partition and authorization constrain the eligible candidate space before sensitive direct/keyword/vector retrieval, chunks, embeddings, summaries, caches, source expansion and reranking. B6 retains concrete protocol, freshness and revalidation decisions.

Explicit amendment/deferral: **PRIVATE THIRD-PARTY ASSERTIONS = DEFERRED PRODUCT/PRIVACY MODEL**, outside the initial Knowledge runtime. “Erick privately says Ana likes blue” is intentionally not solved by B1. It cannot enter active shared Knowledge without normal Ana subject restrictions; this does not permanently prohibit a future separately designed private-personal-assertion model.

Reasoning: the bounded model preserves Home's single authority and fail-closed Person restrictions while supporting genuine subjectless Circle context. The amendments distinguish Circle handling from personal consent, permit explicit consumer stewardship bootstrap, and preserve future private-note design without creating an authorization bypass. Scenarios A–H remain architecture acceptance specifications, not runtime tests; the added private-third-party scenario records a deferral.

Baseline implementation gap remains: current Person-based authorization cannot target a Circle, and simply allowing empty subjects would remove the bundle's subject checks. Resolving B1 defines the required architecture; it does not modify those contracts or authorize implementation. B2, B3 and B4 are resolved by the decisions below; B5–B6 and the Knowledge Technology Gate remain OPEN. No technology is selected.

## B2 — Sensitivity inheritance

Status: B2 — RESOLVED — PRODUCT ARCHITECT DECISION

Decision owner: Product Architect

Decision date: 2026-09-20

Product Architect disposition: ACCEPTED WITH CLARIFICATION

Authoritative decision: [Knowledge B2 — Sensitivity inheritance](KNOWLEDGE_B2_SENSITIVITY_INHERITANCE.md), including section 14's Product Architect disposition and scenarios A–J.

Accepted decisions:

- Every information artifact carries complete conjunctive requirements and actual-influence lineage. Ordinary transformations never weaken protection; AI cannot declassify. Independent assertions retain separate lineage.
- Sources and mixed-source derivatives inherit source/container requirements by default. Approved projections are new, exact, version- and use-bound outputs. Provenance disclosures are separately authorized.
- Person/content-sensitivity relaxation requires explicit affected-Person authority. Circle stewardship, uploader status, MANAGE, document custody, administrator status, professional title and AI review do not substitute for that Person's authority. Future legal representation remains separate policy.
- Source/container decoupling for an exact projection does not automatically require every Person whose information occurs elsewhere in the original. It requires source-handling authority, trusted projection approval, proof that removed Person/domain sensitivity is absent from the output, exact version/use binding and preservation of every remaining restriction. If the output still reveals protected content, affected-Person authority is required. Source custody cannot remove Person protection; Person consent cannot disclose unrelated protected source material.
- Reclassification makes stale derivatives immediately ineligible. Current authorization constrains the candidate space before sensitive retrieval. No technology or runtime is selected or approved.

Scenarios A–J are accepted conceptual outcomes and future acceptance specifications, not runtime tests. B2 resolution changes no schema, contract, service, database, index, workflow, deployment or production system. B3 and B4 are resolved below; B5–B6 remain OPEN.

## B3 — Confirmation and lifecycle

Status: B3 — RESOLVED — PRODUCT ARCHITECT DECISION

Decision owner: Product Architect

Decision date: 2026-09-21

Product Architect disposition: ACCEPTED WITH CLARIFICATIONS — D1 ACCEPT; D2 ACCEPT WITH CLARIFICATION; D3 ACCEPT; D4 ACCEPT WITH CLARIFICATION; D5 ACCEPT; D6 ACCEPT; D7 ACCEPT.

Authoritative decision: [Knowledge B3 — Confirmation, admission, and lifecycle](KNOWLEDGE_B3_LIFECYCLE.md), including section 14's disposition, scenarios A–J and D2/D4 boundary cases.

Accepted decisions:

- Lifecycle attaches to exact immutable assertion versions; explicit replacement lines are not global topic identities, and Episodes are evidence. PROPOSED/ADMITTED/REJECTED record admission; current selection, supersession, dispute, revocation, expiry and holds remain distinct facts. ACTIVE is derived readiness, never objective truth, universal agreement or authorization for every viewer.
- **D2 clarification:** direct admission requires trusted explicit save intent, an explicitly approved admission class, passed canonical-domain routing and B1/B2 checks, and no applicable suppression. Faithful wording in the approved initial preference class may be admitted atomically without redundant confirmation when every gate passes. An LLM cannot decide that material is “low risk” and thereby approve a new class. Unknown ownership/classification, incidental conversation, ambiguous inference and unapproved consequential domains must not auto-admit. Future source/domain-specific auto-admission policies require explicit architecture approval; B5 ownership remains open.
- Confirmation of an AI-origin proposal creates a distinct admitted successor and atomically closes the proposal while retaining AI/source lineage and B2 restrictions. Further attestation to unchanged admitted wording does not clone it. Circle endorsement, personal agreement and disclosure permission remain distinct.
- **D4 clarification:** challenges bind exact version, disputed proposition/use, applicable interval/context, actor/authority and their own control revision. Unresolved relevant disputes suppress contested ordinary use without majority truth or steward override. Carryover requires materially preserved contested meaning for overlapping applicability/use; cosmetic replacements cannot bypass it. Later non-overlapping periods, materially changed circumstances and genuinely independent lines receive their own current B1/B2/B3 evaluation. Historical disagreement is not a permanent Person-level veto; uncertain equivalence may require review.
- Correction records an earlier misrepresentation; change records later changed circumstances. Preserve recorded and applicable time, scheduled changes and distinct review reminders/hard expiry. No in-place resurrection of REJECTED/REVOKED/EXPIRED; fresh reviewed assertions require continuing restrictions to permit them.
- Exact-version preconditions, CAS-equivalent checks, atomic successor/replacement outcomes and partition/actor/operation-bound business idempotency are required. No content-only semantic deduplication, stale-receipt authorization or reused transport delegation. Commit-time authorization needs an enforceable barrier; immediate non-use precedes asynchronous cleanup.

Reasoning: the accepted model separates admission, attribution, temporal meaning and use controls without an expanding exclusive state machine. The clarifications prevent model-created admission authority and unbounded dispute carryover while preserving B1/B2.

Scenarios and invariants are accepted architecture requirements, not implemented behavior. The current confirmation helper and ContextBundle gaps remain until separately approved implementation. B1 and B2 remain unchanged and RESOLVED; B4 is resolved below; B5–B6 and the Knowledge Technology Gate remain OPEN. No technology, contract/schema change or runtime implementation is approved.

## B4 — Dependency / Forget / Delete

Status: B4 — RESOLVED — PRODUCT ARCHITECT DECISION

Authoritative decision: [Knowledge B4 — Dependency, Forget, Delete, retention, and resurrection safety](KNOWLEDGE_B4_FORGET_DELETE.md), including section 16's disposition, the section 1.1 clarifications and scenarios A–M.

Accepted model: a durable suppression register as the authoritative non-use fact, separated from physical erasure, with bounded recorded derivation families and a mandatory pre-use re-admission barrier on retrieval, restore, import and reindex. Non-use commits immediately; erasure is an asynchronous evidenced obligation; existing encrypted backup snapshots are not rewritten. Independent lineage survives source-specific deletion. Orchestration, Flowable included, is never canonical Knowledge truth and suppression never waits on it. Distinct operations (stop using, forget, delete source, delete derived artifacts, forget subject, withdraw assertion, remove shared use, delete partition) carry distinct authority and promises.

- **C1 — restore freshness is load-bearing:** restored data must not become usable unless the system can prove the suppression/deletion control state used for reconciliation is at least as current as the payload being restored. Unknown freshness fails closed. A monotonic or otherwise current anti-resurrection authority, or an equivalent freshness proof, is required; **B4 selects no persistence or replication mechanism for it**, and B5/B6/implementation determine that later.
- **C2 — hashing is not canonicalized:** the anti-resurrection state must hold the minimum non-reconstructable, non-disclosing, partition-bound information sufficient for the approved re-admission policy, with no forgotten plaintext or embeddings. Opaque source identities, policy keys, digests, classification metadata and trusted semantic review are possible future mechanisms; **B4 selects none**.
- **C3 — Forget is not a permanent topic ban:** the legitimate authority may later deliberately reassert. A reassertion never reactivates the erased version; it may create a new reviewed assertion when current authority, explicit save intent, B1/B2/B3 checks and explicit treatment of the prior suppression all hold. Automatic import or re-extraction can never override a suppression.
- **C4 — external provider deletion is conditional:** local Forget/Delete cannot by itself guarantee provider-side deletion, which depends on the approved provider, contractual retention terms, configured controls and available deletion APIs. Olin must not promise provider-side deletion unless it can verify it. This is an input to the future LLM Routing / Provider Policy architecture. Already displayed output and independently exported files cannot be recalled.

D1 ACCEPT WITH SCOPE CLARIFICATION (current personal-deployment `restic keep 7d/4w/3m` accepted; not a permanent commercial requirement; no fixed duration promised) · D2 DEFER (crypto-shredding retained as a future option, not a B4 prerequisite; no key-management technology selected) · D3 ACCEPT WITH CLARIFICATION (minimal anti-resurrection state; actor/audit metadata minimized independently and not automatically permanent; partition tombstone for whole-partition deletion) · D4 ACCEPT (source-only dependents suppressed and erased with the family; deletion never weakens restrictions) · D5 ACCEPT WITH CLARIFICATION (bounded to covered proposition/use/applicability; no global topic ban; uncertainty fails closed) · D6 DEFER (technical semantics only; no GDPR/right-to-erasure claim either way) · D7 ACCEPT (STOP USING, FORGET / DELETE MEMORY and DELETE SOURCE remain distinct; internal cleanup states need not be primary user actions).

Scenarios A–M and the clarification boundary cases are accepted architecture outcomes and future acceptance specifications, not implemented enforcement. B4 resolution changes no contract, schema, service, database, suppression registry, deletion executor, key management, index, workflow, backup, deployment or production system. B1–B3 remain unchanged and RESOLVED. B5–B6 and the Knowledge Technology Gate remain OPEN. No technology is selected; Flowable is not selected.

## B5 — Ownership boundaries

Status: OPEN — DISPOSITIONS RECORDED, AWAITING FINAL ARCHITECTURE BOARD MERGE REVIEW

Product Architect disposition: **ACCEPTED IN DIRECTION WITH FIVE REQUIRED CORRECTIONS — NOT YET CLOSED**

Proposal under review: [Knowledge B5 — Ownership boundaries](KNOWLEDGE_B5_OWNERSHIP_BOUNDARIES.md), including its section 7 responsibility matrix, the section 8 domain-fact rule, and the section 18 dispositions. **B5 is not resolved by this entry.** It closes only when the Architecture Board approves merge and this status is changed to RESOLVED.

Accepted core direction:

> **Home decides → Knowledge remembers → Domains own structured operational truth.**

PA dispositions recorded: **PA-1** ACCEPT Model D, subject to the projection clarification · **PA-2** ACCEPT leaving physical deployment/runtime/storage open, with the **logical Knowledge ownership boundary now fixed** — the Technology Gate may choose placement and co-location but may not silently collapse canonical Knowledge ownership into ordinary Home Control Plane persistence or DocTypes · **PA-3** ACCEPT restore-freshness authority under the Knowledge owner, fail-closed when currency cannot be proven · **PA-4** ACCEPT the bounded cleanup **obligation** concept with revised authority wording — an obligation is required work, not a permission, and no concrete authorization-token mechanism is approved · **PA-5** ACCEPT eventual retirement/reconciliation of the dormant Home Nutrition schema and the divergent Care Journey provenance vocabulary through separately approved implementation work · **PA-6** ACCEPT intolerance/allergy-shaped fields as outside B5, deferred to future Health architecture, with ambiguous legacy values not silently reclassified · **PA-7** ACCEPT Nutrition re-capture / explicit review-and-confirm rather than fabricating provenance for existing blob text · **PA-8** ACCEPT the domain-fact-vs-contextual-Knowledge rule after incorporating the process/provenance clarification · **PA-9** ACCEPT reconciliation of canonical documentation when B5 closes.

Five required corrections were issued and incorporated: **(1)** trusted partition binding — Home resolves the partition, Knowledge records it as immutable canonical security metadata; **(2)** a cleanup obligation is not authorization issuance, and KN gains no grant, disclosure or access authority by recording one; **(3)** projection semantic ownership is separated from physical hosting, with no implication that Knowledge writes domain databases and no credential topology implied; **(4)** ownership follows the producing process rather than natural-language wording, so a domain-derived analytic stays domain-owned however it is phrased; **(5)** the logical ownership boundary is fixed even though physical placement stays open. See section 18.1 of the proposal.

No correction demonstrated a contradiction requiring the selected model to change or requiring B1–B4 to reopen.

Canonical documentation reconciliation (PA-9) is deferred and itemized as D-1 … D-7 in section 17.2 of the proposal, following the precedent of accepted B1–B4. **D-1 (the ROADMAP prerequisite placing Knowledge governance implementation "in the Home Control Plane") is the one active contradiction with the accepted ownership boundary and must be corrected when B5 closes.**

Questions to resolve:

- Who owns reusable Nutrition preferences?
- How should current Nutrition preference storage and the proposed duplicate Knowledge storage be reconciled? **Corrected by the B5 investigation:** preference-shaped fields exist in **two** stores today — svc-nutrition's live profile blob, and a dormant `Nutrition Profile` DocType in the Home Control Plane carrying `preferences`/`dislikes`/`explicit_intolerances` with System Manager CRUD and no application code referencing it. The second is unused, not un-installed, so this is a latent dual-canonical hazard rather than only a risk to avoid. The earlier wording here understated it.
- Who is the canonical Knowledge persistence owner?
- Which responsibilities stay in the Home Control Plane?
- Does Knowledge become its own service, and what decision justifies that service boundary?
- How would migration avoid dual canonical ownership and independently editable copies?

Evidence: the existing [Nutrition profile fields/write path](https://github.com/EKvargas/episteck_home/blob/ddebab6439c9d68487d180dec6995fc546d3cf68/services/nutrition/app/main.py#L43) stores preferences/dislikes. The B5 investigation additionally verified that this applies to the **general** profile endpoint and not only the pregnancy path; that the profile is a single opaque JSON document per person, so an individual preference has no version, provenance or delete path; and that `Care Journey Item` carries a separate `knowledge_status` provenance vocabulary divergent from `KnowledgeProvenance`. The current Roadmap and ownership documents also need an explicit interpretation of governance-in-Home versus Knowledge persistence ownership; that contradiction remains unresolved on `main`. No Nutrition migration, new service, DocType retirement, or ownership transfer is approved here.

## B6 — Trusted retrieval and ContextBundle

Status: OPEN

Product Architect disposition: NOT DECIDED

Questions to resolve:

- How does trusted actor resolution bind each request?
- How does the security partition constrain every retrieval stage?
- How is authorization enforced before retrieval, including candidate search space?
- How does discoverability prevent unauthorized resource enumeration?
- How is authorization freshness maintained across the request and any caches?
- Which current lifecycle states and validity intervals are eligible?
- How are source and canonical-domain retrieval independently authorized?
- What final disclosure revalidation is needed if access or content changes during assembly?
- How is ContextBundle bounded to the current task?
- How is a persisted universal cross-domain bundle prevented?

Review concern: the bundle's structural validation does not prove that supplied authorization was trusted, current, or checked before retrieval. Its accepted content is broader than normal active/current retrieval. No revised contract, service or retrieval mechanism is approved here.

## Process register

Status: OPEN — PROCESS SPECIFICATIONS NOT YET APPROVED

B3's lifecycle/admission semantics and B4's forget/delete semantics are accepted by the decisions above. The checklist below tracks complete operational process specifications and remaining B5–B6 integration; its OPEN entries do not reopen B1–B4 or authorize runtime work.

- [ ] OPEN — Admission / domain routing
- [ ] OPEN — Capture
- [ ] OPEN — Confirmation
- [ ] OPEN — Correction
- [ ] OPEN — Change
- [ ] OPEN — Supersession
- [ ] OPEN — Dispute
- [ ] OPEN — Rejection
- [ ] OPEN — Expiration
- [ ] OPEN — Sharing / reclassification
- [ ] OPEN — Forget / delete
- [ ] OPEN — Dependency invalidation
- [ ] OPEN — Retrieval
- [ ] OPEN — Source traceability
- [ ] OPEN — Domain reconciliation
- [ ] OPEN — Consent revocation
- [ ] OPEN — Capture idempotency / retry
- [ ] OPEN — Export/import with provenance
- [ ] OPEN — Membership/household transitions
- [ ] OPEN — Restore/reindex reconciliation
- [ ] OPEN — Working-memory invalidation
- [ ] OPEN — Tenant deletion

Each future process specification must state:

- initiator
- required authorization
- inputs
- canonical owner
- state transitions
- dependent artifacts
- failure behavior
- user-visible result
- audit expectations

This persistence task records the work to be decided. It does not fully specify these processes, select a workflow engine, or authorize their implementation.

## Proposed minimal first Knowledge use case

Status: PROPOSED — NOT APPROVED FOR IMPLEMENTATION

PERSON-scoped reusable food preference:

> “Remember that I prefer Mediterranean/Latin food and I dislike canned tuna.”

The proposed vertical exercises:

1. Capture explicit preferences with source attribution.
2. Retrieve authorized active preferences.
3. Combine them with current authorized Nutrition structured truth.
4. Explain the source of the preference.
5. Correct/change a preference, distinguishing those two processes.
6. Forget a preference according to the future approved policy.
7. Verify a denied Person cannot retrieve it.

Use synthetic data first. Nutrition preference ownership remains **B5 OPEN**; this example does not create another canonical preference store.

The historical review notes that “Fresh tuna is fine; I dislike canned tuna” does not contradict a correctly captured canned-tuna dislike. Future acceptance scenarios should separately test an actual mistaken generalization and a preference changing over time; no automatic supersession policy is selected here.

Explicitly excluded from this first vertical:

- allergy
- diagnosis
- pregnancy restriction
- medical contraindication
- Finance
- autonomous extraction from all conversations

## Technology candidates — not approved

All entries are **UNSELECTED**. The hypotheses below preserve review input; they are not approved architecture decisions or installation instructions.

| Candidate | Status | Current review hypothesis |
|---|---|---|
| Plain Postgres | UNSELECTED | Leading minimal baseline after architecture blockers close; bounded authorized preference retrieval may require no semantic search. |
| Postgres + pgvector | UNSELECTED | Add only if measured semantic retrieval needs justify it, with candidate isolation verified rather than assumed. |
| Mem0 OSS | UNSELECTED | May later be evaluated as a proposal/extraction helper, never the canonical authority. |
| Docling | UNSELECTED | Relevant later for document ingestion; unnecessary for the initial conversational preference vertical. |
| Graphiti | UNSELECTED | Requires a demonstrated graph/multi-hop workload that warrants added infrastructure. |
| RAGFlow | UNSELECTED | Currently likely too heavy for the first Knowledge vertical. |

The historical review contains the supporting technology analysis and primary-source references. Existing accepted decisions, including the rejection of adopting a turnkey RAG stack now, are not reversed by keeping candidates visible in this register. Any later selection requires explicit Product Architect disposition and version-specific verification.

## Workflow Orchestration / Flowable

Status: OPEN — NOT SELECTED

**Reviewer recommendation: USE FLOWABLE ONLY FOR EXCEPTIONAL/LONG-RUNNING PROCESSES.**

This is an assessment for Product Architect consideration, not an approved selection or a resolution of B1–B6. Flowable already operates in the broader Episteck environment according to the task context; its existing deployment, edition, version, capacity, security controls and suitability for Olin have not been inspected in this task.

Default safety principle: **Flowable must never become the canonical Knowledge database.** If used, Knowledge/domain state remains canonical and Flowable orchestrates a process around that state. Sensitive payloads should be minimized in workflow variables.

### Evidence and limits of this assessment

Flowable supports human user tasks, timers, persisted waits, asynchronous continuations and failed-job retry configuration. These capabilities can support durable orchestration; they do not decide Olin's ownership, approval or consent rules. [Flowable BPMN constructs](https://www.flowable.com/open-source/docs/bpmn/ch07b-BPMN-Constructs).

Flowable OSS tenant identifiers support scoping/querying, but its documentation explicitly leaves tenant access enforcement to the calling layer. The same documentation describes retries and dead-letter jobs. [Flowable advanced documentation](https://www.flowable.com/open-source/docs/bpmn/ch18-Advanced).

Process variables and submitted form values can enter history. The documented default history level is audit; historical data is retained indefinitely unless cleanup is configured, and automatic history cleaning is disabled by default. Ending a process is therefore not evidence of erasure. [Flowable history](https://www.flowable.com/open-source/docs/bpmn/ch10-History).

The REST API permits remote integration. Its existence does not establish Olin actor identity, Circle consent or security-partition enforcement. [Flowable REST API](https://www.flowable.com/open-source/docs/bpmn/ch14-REST).

Sources were consulted on 2026-09-19. These are upstream capabilities and defaults, not verified properties of Episteck's current engine. The following recommendations are architectural judgments requiring approval.

### 1. Which Knowledge processes genuinely benefit from BPMN?

Consider BPMN where an approved process waits for people or external systems, has deadlines/escalations, independently failing steps, or operational case tracking. Potential candidates are:

- Shared household claims requiring another person's approval.
- Dispute-resolution workflow and professional review.
- Sensitive reclassification approval.
- Long-running document review.
- Tenant deletion and large export requests.
- Future support/break-glass approval.
- Forget/Delete cleanup spanning several stores and verification steps.

A single approval, ordinary export, or small background cleanup job does not automatically justify BPMN. First compare the actual process against domain state plus a simple durable job mechanism. None of these processes is specified or approved by this assessment.

### 2. Which processes would BPMN unnecessarily complicate?

The current hypothesis is that saving a preference, activating a claim, atomic supersession, revoking a claim, retrieving active claims, and ordinary expiration eligibility remain deterministic transactional domain operations. They should not require BPMN, one workflow instance per claim, or consultation of workflow state to establish whether a claim is active.

Immediate suppression belongs to the domain safety boundary even if subsequent deletion cleanup is orchestrated. B3's lifecycle/non-use semantics and B4's suppression/cleanup separation are accepted; the concrete runtime/orchestration boundary remains OPEN and no orchestration technology is selected.

### 3. Does Flowable create an undesirable basic CRUD dependency?

Yes, if placed on the mandatory path for all Knowledge operations. It adds availability and consistency coupling without a demonstrated benefit for basic CRUD. Recommend that permitted basic operations and immediate suppression remain possible when an optional workflow engine is unavailable.

An operation that genuinely requires human approval must remain pending during an orchestration outage. Independence from Flowable must not become a way to bypass the required approval.

### 4. How should transactional Knowledge state relate to workflow state?

Proposed boundary: Knowledge/domain state records accepted assertions, lifecycle, authorization-relevant status and durable operation outcomes. Flowable records orchestration progress such as waiting, retrying or completed. Workflow tasks call authorized domain commands rather than directly updating claim tables.

Engine transactions do not by themselves make remote Knowledge commands atomic with workflow progress. A future integration needs a durable, recoverable handoff for an accepted process request. An outbox or equivalent mechanism is an option to evaluate, not a selected implementation. The failure window between a domain commit and orchestration notification must be explicit.

### 5. What is canonical if Flowable and Knowledge disagree?

Knowledge/domain state remains canonical. A completed process flag cannot activate an uncommitted claim or prove that all deletion obligations have finished. Reconcile workflow progress against current domain state and operation receipts; do not overwrite newer domain state to match an old workflow.

If a domain commit succeeds but acknowledgement is lost, recovery should discover the existing result. If the workflow advances without a successful domain command, the domain operation remains incomplete. B3's atomic outcome and idempotency requirements and B4's cleanup/anti-resurrection obligations are accepted; the concrete reconciliation, cleanup and freshness **mechanisms** remain B5–B6 OPEN.

### 6. How should retry and idempotency work?

Treat delivery of external commands as potentially repeated. The proposal is to bind stable operation/step identifiers to the security partition, target and intended object version, and deduplicate at the canonical command boundary. Version/precondition checks should prevent delayed approval from activating corrected, revoked or superseded content.

Retryable technical failure is different from business rejection or revoked authorization. Exhausted retries need visible operational handling. Cleanup should tolerate an artifact already being absent. Compensation must not recreate forgotten content. These are criteria for the future process specifications, not a selected queue or implementation.

### 7. Should instances contain sensitive content or only opaque IDs?

Prefer opaque request/object identifiers, versions and minimal operational status. Avoid claim text, originals, medical/financial values, ContextBundles, bearer material or credentials in workflow variables, task titles, form fields, comments, attachments and exception messages. Fetch required content through a currently authorized service when needed.

Opaque identifiers and metadata remain protected data. Workflow runtime records, history, logs, backups and exports must participate in retention and deletion rules. Merely choosing IDs does not eliminate the need for tenant isolation or restricted support access. B2's accepted sensitivity rules and B4's accepted retention/anti-resurrection rules apply.

### 8. How does consent revocation affect an active workflow?

A prior assignment or approval request is not continuing permission. Recommend current authorization checks on task display, completion, content fetch and domain mutation. Revocation should suppress access immediately and invalidate or re-evaluate affected tasks/cached views according to the eventual process policy.

Revocation events may accelerate cleanup but cannot replace authoritative checks if event processing is delayed. An authorized erasure process may need to finish under narrowly scoped system authority after user read access ends; whether and how that authority exists is explicitly a B1/B4 decision, and B4 requires a partition-bound, non-disclosing cleanup mandate whose owner B5 must assign. No durable impersonation or blanket service authority is approved.

### 9. How is tenant/security-partition context bound into execution?

The trusted Olin integration should bind actor and partition from authenticated context, not from arbitrary model/client `tenantId` values. Bind that partition to the request, instance, task, job, callback and domain command, and reject mismatches or unpartitioned execution.

Task assignment, Flowable authentication and a machine credential must not stand in for current Home authorization. Any future integration must cover direct-ID access, history, administration and background execution as well as filtered queries. Flowable's tenant metadata alone does not close B1 or B6.

### 10. Must Flowable run on Nuremberg?

No BPMN requirement places it on the Nuremberg service node. A future workflow adapter/service could call a suitably isolated existing engine remotely through its API. This avoids assuming another deployment is necessary, but does not approve reuse of the current Episteck engine.

A later assessment must verify its edition/version, trust boundary, network access, credentials, tenancy enforcement, operational ownership, retention, residency and outage behavior. Existing availability is not authorization to send sensitive Olin content. No placement, remote connection, deployment or replication is selected here.

### 11. What concrete trigger justifies adoption or another deployment?

Reconsider Flowable when a Product Architect-approved process demonstrates durable human waits/escalations or independently retryable multi-service steps, a simpler domain-state/job approach is insufficient, and there is an accountable operator with defined recovery requirements. Evaluate that bounded process against simpler alternatives and record an explicit accepted decision, including authorization and retention evidence.

Deploy or replicate an engine for Knowledge only if an approved existing remote engine cannot meet the required isolation, availability, latency or operational constraints. The initial synthetic food-preference vertical does not currently establish that trigger.

### Candidate Forget/Delete orchestration boundary

The following is an assessment illustration, not a complete process specification. B4's semantics are now accepted (see the B4 entry above); the orchestration boundary itself remains OPEN and unselected:

```text
Domain commits immediate suppression and a durable deletion request
→ optional orchestration deletes covered derivatives/chunks/embeddings
→ invalidates covered caches and fences stale queued work
→ collects cleanup receipts and verifies required stores
→ domain records completion only when required evidence exists
→ orchestration closes; approved backup/retention obligations still apply
```

Immediate suppression must not wait for Flowable. Completion of workflow steps must not be mistaken for physical erasure of every backup or previously disclosed model context. The eventual deletion policy determines what completion means.

### Assessment disposition

Product Architect decision: NOT DECIDED

B1: RESOLVED — PRODUCT ARCHITECT DECISION, 2026-09-19 ([accepted decision](KNOWLEDGE_B1_SECURITY_SCOPE.md))

B2: RESOLVED — PRODUCT ARCHITECT DECISION, 2026-09-20 ([accepted decision](KNOWLEDGE_B2_SENSITIVITY_INHERITANCE.md))

B3: RESOLVED — PRODUCT ARCHITECT DECISION, 2026-09-21 ([accepted decision](KNOWLEDGE_B3_LIFECYCLE.md))

B4: RESOLVED — PRODUCT ARCHITECT DECISION, 2026-09-21 ([accepted decision](KNOWLEDGE_B4_FORGET_DELETE.md))

B5: OPEN — [proposal](KNOWLEDGE_B5_OWNERSHIP_BOUNDARIES.md) accepted in direction with five required corrections incorporated; PA-1 … PA-9 recorded 2026-09-21; **NOT YET CLOSED** pending Architecture Board merge review

B6: OPEN

Flowable selection: NOT APPROVED. B4 confirms orchestration is never canonical Knowledge truth and that immediate suppression must not wait on it.

No installation, deployment, replication, configuration, process triggering, or core Knowledge dependency is authorized by this document.

## Gate completion and change boundary

The next work is Architecture Board merge review of the [B5 ownership proposal](KNOWLEDGE_B5_OWNERSHIP_BOUNDARIES.md) — whose PA-1 … PA-9 dispositions are recorded and whose five required corrections are incorporated, but which is NOT YET CLOSED — followed by explicit disposition of B6 and the remaining process requirements. B6 has no proposal. B1–B4 are resolved by the accepted decisions above; the Knowledge Technology Gate remains OPEN and is not complete. Agreed acceptance scenarios must precede technology selection. Technology selection and runtime implementation require their own approval; B1/B2/B3/B4 acceptance supplies neither.

The original gate-opening task changed only the independent review artifact and this gate register. The B1 follow-up changes only [KNOWLEDGE_B1_SECURITY_SCOPE.md](KNOWLEDGE_B1_SECURITY_SCOPE.md) and B1 status/references in this register. It does not modify canonical architecture documents, existing ADRs, `packages/home-contracts/`, `services/`, `deploy/`, or production configuration.

**NO KNOWLEDGE TECHNOLOGY SELECTED**

**NO KNOWLEDGE RUNTIME IMPLEMENTED**

**NO PRODUCTION CHANGE**
