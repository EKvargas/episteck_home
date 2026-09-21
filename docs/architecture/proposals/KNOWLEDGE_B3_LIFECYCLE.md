# Knowledge B3 — Confirmation, admission, and lifecycle

Status: PROPOSED — AWAITING PRODUCT ARCHITECT DECISION

Date: 2026-09-20

Final verification: 2026-09-21; `origin/main` remains at the investigation baseline below.

Repository: `EKvargas/episteck_home`

Main baseline: `0a6fc2eb15f805299d732a3b7cdf8f1719a0e902`, verified current `origin/main` after [PR #24](https://github.com/EKvargas/episteck_home/pull/24) merged.

Branch: `docs/knowledge-b3-lifecycle`

Decision owner: Product Architect

Disposition: NOT DECIDED

Gate: [B3 — Confirmation and lifecycle](KNOWLEDGE_TECHNOLOGY_GATE.md#b3--confirmation-and-lifecycle)

## 1. Recommendation and authority

Recommend **immutable assertion versions, explicit admission, version-bound attestations, typed replacement relations, and independent use controls**, with an atomic current-state view and a minimal decision history. Lifecycle belongs to an exact assertion version. An assertion line groups explicit replacements; it is not a global identity for everything said about a topic. An Episode records capture/confirmation evidence, not the lifecycle of everything extracted from it.

Do not persist one status that must simultaneously answer whether content was admitted, whether someone agrees, whether it has a successor, whether it is contested, whether it is within its applicable time, and whether this viewer can use it. In particular, ACTIVE must not mean true, universally confirmed, or authorized. Section 5 defines the small admission state machine and the other independent lifecycle facets; the familiar status words are derived descriptions of those facts.

Preserve [accepted B1](KNOWLEDGE_B1_SECURITY_SCOPE.md) and [accepted B2](KNOWLEDGE_B2_SENSITIVITY_INHERITANCE.md) without amendment. No contradiction requiring either to reopen was found. Trusted actor/partition, conjunctive scope/subject/domain authorization, actual-influence lineage, no ordinary sensitivity weakening, independent assertion lines, and immediate ineligibility remain mandatory. AI is never release or declassification authority.

This document proposes architecture and future acceptance criteria. It changes no contract, schema, enum, runtime, or production system; it selects no storage, retrieval, indexing, or workflow technology. Merge is not acceptance. B3 remains unresolved until explicit Product Architect disposition. All scenarios are synthetic.

## 2. Repository facts that determine the design

The existing detached checkout contained untracked `apps/home-hub/` and `docs/ref/`; it was preserved. A fresh worktree on this branch had empty `git status --porcelain=v1` and HEAD equal to the baseline before edits. PR #24's merge commit equals that baseline.

Sources read include [KNOWLEDGE](../KNOWLEDGE.md), the [gate](KNOWLEDGE_TECHNOLOGY_GATE.md), both accepted decisions, the [independent review](../reviews/2026-09-19-knowledge-independent-architecture-review.md), [data ownership](../DATA_OWNERSHIP.md), and relevant ADRs [0001](../adr/0001-home-control-plane-is-frappe.md), [0002](../adr/0002-independent-domain-services.md), [0004](../adr/0004-svc-nutrition-source-of-truth.md), [0006](../adr/0006-family-care-graph.md), [0007](../adr/0007-knowledge-architecture.md), [0008](../adr/0008-consent-fail-closed.md), and [0009](../adr/0009-trusted-actor-binding.md). The implementation was inspected independently; historical review recommendations are not treated as accepted decisions.

| Ground truth at the baseline | Consequence for B3 |
|---|---|
| [Knowledge contracts](../../../packages/home-contracts/src/episteck_home_contracts/knowledge.py) are frozen dataclasses. `transition()` returns a replacement object with the same claim ID. There is no persisted version, lifecycle revision, command receipt, or transaction. | Python immutability does not establish durable version identity, atomic replacement, or concurrency safety. These must be defined before implementation. |
| `KnowledgeEpisode` has an ID, free-form type, capture timestamp and source reference. Claims have one source episode, one provenance enum, an optional predecessor, and optional validity times. | An Episode is evidence of an event. It cannot alone represent multiple inputs, human attestation capacity, replacement intent, or source versions. |
| The six statuses are PROPOSED, ACTIVE, SUPERSEDED, DISPUTED, REVOKED, EXPIRED. PROPOSED may transition to any other state; DISPUTED may become ACTIVE. SUPERSEDED/REVOKED/EXPIRED have no outgoing `transition()` edges. There is no REJECTED. | Rejection is missing, dispute overwrites another lifecycle fact, and constructor/helper paths can evade the intended terminal-state story. The existing enum is evidence, not a constraint on the recommendation. |
| Only `AI_HYPOTHESIS` plus ACTIVE is prohibited by construction. `AI_SUMMARY` and `DERIVED` may be constructed ACTIVE. | The broader architectural rule that AI output is a proposal until confirmed is not fully represented by contracts. Admission must govern all generated assertions. |
| `confirm()` checks hypothesis provenance and nonempty supplied IDs, then returns a USER_CONFIRMED ACTIVE claim. It does not validate predecessor status, a distinct new ID, a real confirmation Episode, actor authority, or current validity. It copies statement, scope, subjects, domain, confidence and validity. | Confirmation needs exact version/content binding, trusted evidence, authority and concurrency checks. Copying confidence is not human verification; retaining an elapsed deadline is not renewal. |
| The new claim points to the confirmation Episode and predecessor; the original remains unchanged. Original source ancestry survives only if the caller preserves and resolves that predecessor. | A link called `supersedes` must not carry all evidentiary, security and historical semantics. Confirmation publication and proposal closure need one atomic outcome. |
| [ContextBundle](../../../packages/home-contracts/src/episteck_home_contracts/context.py) checks caller-supplied subject/domain VIEW tuples. It does not check lifecycle status, time, Circle scope, trusted issuance, freshness, or separately authorize source references. | ADMITTED/ACTIVE and bundle construction are insufficient for retrieval. B6 must enforce current use eligibility before sensitive candidates and again before disclosure. |
| [Knowledge tests](../../../packages/home-contracts/tests/test_knowledge.py) check exact enum sets, hypothesis ACTIVE rejection, confirmation evidence presence/new-object behavior, provenance preservation and obvious secret markers. [Context tests](../../../packages/home-contracts/tests/test_context.py) check limited authorization consistency. | Existing tests do not demonstrate state race handling, idempotency, current authorization, rejection, or temporal semantics. They should not be described as future B3 acceptance tests. |
| Independent local verification passed all 12 existing contract tests. In-memory probes reproduced confirmation from REVOKED, EXPIRED, SUPERSEDED and DISPUTED; equal old/new IDs; elapsed validity; and bundle acceptance of all six statuses. | Review concerns are reproducible on current main, not merely inherited opinions. These are contract gaps, not observed production Knowledge failures. |
| ADR-0009 requires trusted session-derived identity and replay-resistant delegation. B1/B2 specify broader authority requirements than current Person-only contracts implement. | Business retries must use fresh authentication/delegation; business idempotency must not disable transport replay protection. No model-supplied actor, local ACL, or stale grant snapshot can authorize commit. |
| Nutrition already persists preferences/dislikes; ADR-0004 gives it structured domain authority. Knowledge has no service/runtime here. | Examples define lifecycle semantics, not a new preference owner or duplicate canonical store. B5 must resolve that ownership before implementation. |

The independent review's immutable-content/transactional-state direction is supported by these facts. Its generic rule to activate a successor and retire the predecessor on confirmation needs qualification: additional attestations to already admitted wording need no new content version; Circle endorsement is not personal agreement; and future-effective replacement does not retire the predecessor early. This proposal also separates dispute and expiry from an exclusive status enum. No technology ranking from the review is adopted.

## 3. Alternatives considered

**A — Versioned claims with one exclusive lifecycle state.** Use immutable versions, explicit confirmation records, CAS and an expanded PROPOSED/ACTIVE/REJECTED/SUPERSEDED/DISPUTED/REVOKED/EXPIRED machine. This is viable if transition history retains displaced states and every operation consults the relevant history. A mutable statement on one ID without protected historical versions is not viable: confirmation and races would target moving content.

**B — Immutable versions with orthogonal lifecycle facts (recommended).** Keep admission small, preserve exact attestations and typed replacement edges, and evaluate disputes, non-use and time independently. Maintain the current authoritative view atomically with a minimal transition/decision history. This is a domain model, not a choice of persistence layout or full event sourcing.

**C — Event-ledger lifecycle.** Record all capture, admission, attestation, replacement and restriction events; derive current state from ordered events and projections. Viable with strong per-line concurrency, current projection guarantees and erasable protected payloads. An eventually updated projection alone cannot establish safe eligibility.

| Criterion | A: one state per version | B: separate lifecycle facts | C: event-ledger model |
|---|---|---|---|
| Correctness | Straight paths are simple; simultaneous supersession, dispute and revocation require history lookups or compound states. | Represents coexisting facts directly; explicit invariants constrain combinations. | Precise ordered history; projection lag and cross-line ordering require careful control. |
| Simplicity | Small UI; growing transition matrix and hidden qualifiers. | Small admission machine, several bounded concepts; eligibility predicate must be explicit. | Most machinery, replay semantics and recovery obligations. |
| Auditability | Requires separate audit to explain overwritten statuses. | Exact content, actor/capacity, reason and version-bound decisions. | Excellent sequence reconstruction if event completeness is enforced. |
| UX | One badge hides why a claim is unavailable. | Can show “previous preference,” “contested,” or “withdrawn” together; raw facets need not appear in UI. | Similar UX to B after building trustworthy projections. |
| B1/B2 | Compatible only with independent authorization/lineage and restriction checks anyway. | Fits separate attribution, inherited restrictions and immediate non-use. | Compatible; replay must never restore outdated permissions or classification. |
| Ask Olin | ACTIVE needs many additional checks; enum alone is unsafe. | Explicit ordinary-use predicate and separately bounded history/review modes. | Needs a current, authorized projection before retrieval. |
| Shared disagreement | DISPUTED obscures whether content was admitted or superseded. | Separate attributed challenges and attestations; no vote aggregation. | Rich event history, but no inherent answer to who can resolve disagreement. |
| Future Health/Finance | A single “confirmed” state risks implying domain truth. | Attestation capacity and canonical domain authority remain distinct. | Can model rich evidence, with significant audit/privacy burden. |
| B4 deletion | Historical payload copies still need erasure policy. | Immutable-for-edit does not mean retain forever; minimal decision records can outlive removable content only under B4. | An append-only payload ledger conflicts with erasure unless payload/history retention is deliberately separated. |
| Implementation complexity | Low initially, medium/high as exceptions accumulate. | Moderate and bounded; no universal ontology or family-consensus engine. | Highest; not justified by the first preference use case. |

Choose B because it represents the demonstrated combinations without an expanding status matrix or a replay-dependent eligibility system. A remains viable for a tightly bounded first release, but its required side records already approach B. C offers no required user outcome that offsets its additional complexity here.

## 4. Lifecycle unit and identity

| Concept | Exact meaning |
|---|---|
| Assertion version | An independently correctable, immutable proposition with qualifiers, attribution, stated temporal applicability, capture evidence and known derivation bindings. Lifecycle decisions target this exact identity. Changing meaning or claimed applicability creates a new version. |
| Assertion line | An explicit replacement chain for a bounded assertion and purpose in one partition. It groups versions without merging independent speakers/sources or every claim on the same topic. Its revision protects replacement selection. |
| Episode | Evidence of capture, original assertion, confirmation or another interaction, referencing an exact available source. One Episode may yield several versions; rejecting one does not reject the entire Episode. |
| Attestation | An identified human's statement about an exact version, with declared capacity, meaning, time and relevant authority evidence. Attestors do not overwrite assertors or each other. |
| Replacement relation | A directed, acyclic, exact predecessor/successor relation with a reason and effective applicability. Confirmation, correction and real change are different reasons. It is not automatically a derivation edge. |
| Lifecycle/control revision | Revision of admission, attestations, challenges, replacement selection and use restrictions. Distinct from content identity; a dispute need not edit text. |

These are conceptual responsibilities, not proposed schema fields or a required new entity for each row. Existing `claim_id` could later identify an immutable version; migration and naming require separately approved contract design.

Immutable content includes the wording actually reviewed and its qualifiers. Security classification and use restrictions remain independently revisable and may strengthen immediately; immutability cannot freeze an obsolete access rule. Material scope/audience changes use B1 SHARE/RECLASSIFY and B2 approval rules, not ordinary correction. Preserve original provenance plus later events rather than relabeling the original AI producer as a human author.

Only an explicit replacement command selects a predecessor. Similarity, a newer timestamp, same text, higher confidence or majority opinion does not create a line or supersession. A correction authored by a different authorized actor preserves both identities. An independent assertion remains a separate line even if it supports the same conclusion; known derivation is never relabeled independent.

## 5. Exact state and eligibility semantics

### 5.1 Admission states

| State | Meaning | Allowed admission transition |
|---|---|---|
| **PROPOSED** | Captured candidate, with no authority for ordinary durable Knowledge use. It may be displayed only in an authorized proposal/review operation. Capture itself requires authorization and protected handling. | ADMITTED after complete admission checks, or REJECTED by an authorized rejection. Confirmation of generated wording uses the successor process in section 7 instead of rewriting its origin. |
| **ADMITTED** | Accepted into durable contextual Knowledge under a recorded admission policy and attribution. This records admission, not truth, present validity, human unanimity or permission for any viewer. | No reversal of the historical admission fact. Subsequent supersession, dispute, revocation and expiry are separate facts. |
| **REJECTED** | This unadmitted candidate was explicitly declined for admission, for a recorded reason. “Incorrect suggestion” is a reason, not an assertion of the opposite proposition. | Terminal for that candidate. Reconsideration requires a new reviewed version/request linked to the rejected proposal; never a silent retry. |

A direct explicit assertion can be captured and admitted in one atomic operation; no externally visible proposal stage is required. A fulfilled AI proposal remains an unadmitted historical proposal linked to its admitted successor and closed to further decisions. Its derived label is SUPERSEDED, not REJECTED. No proposed version can remain an actionable confirmation target after replacement, revocation, expiry or rejection.

Rejecting a shared proposal's admission requires exact proposal VIEW plus B1 Q(UPDATE), with all inherited restrictions and the current decision revision. A person who lacks that authority may decline their own requested attestation without rejecting the proposal for everyone; B1's narrow own-contribution withdrawal and own-subject objection remain available. A pending request's cancellation or technical failure is not a factual rejection and creates no attestation. The model cannot supply a human rejection or clear a pending approval on its own.

### 5.2 Independent lifecycle facets and familiar labels

| Label/facet | Precise meaning and use effect |
|---|---|
| **CURRENT** | Selected for this line's defined purpose and requested applicable time. There may be historical and scheduled versions, but no two effective successors for the same predecessor/purpose/overlapping interval. Independent lines may coexist and conflict. CURRENT alone conveys no admission or permission. |
| **SUPERSEDED** | An explicit successor replaces this version for the stated purpose/interval. The old version is excluded from ordinary current use for that interval; its capture, attestations and replacement reason remain protected history. Future-effective change does not suppress the old version before its effective boundary. |
| **DISPUTED** | At least one authorized, unresolved challenge contests this exact version for the relevant use/interval. It can coexist with ADMITTED, SUPERSEDED or REVOKED. Default ordinary use excludes the contested content. Dispute is not rejection, deletion, or proof of falsity. |
| **REVOKED** | An authorized durable withdrawal/non-use decision bars the specified version/use. It can coexist with any admission/replacement state. It does not claim the proposition was false and does not erase it. The covered use cannot be restored on that same version; section 10 governs a fresh assertion. |
| **EXPIRED** | A hard use deadline or the end of applicable validity has been reached for the requested ordinary use. This is evaluated from authoritative time and metadata, even if no timer job has run. It does not imply falsity or erasure. |
| **HELD / ineligible pending review** | A temporary fail-closed control for uncertain classification, dependencies or required authority. This is distinct from deliberate revocation. A trusted review may clear only the hold it resolves, with version checks; other restrictions remain. |
| **ACTIVE** | Optional derived product label: ADMITTED and current/applicable for the requested ordinary use, with required attestations/endorsement, no unresolved relevant dispute, no covering non-use or hold, unexpired and with current valid dependencies/classification. It is not a persisted truth/permission bit. |

There is no exclusive priority ordering that erases other facets. If the UI shows one headline badge, protected detail must retain all reasons. An admitted, superseded, disputed, revoked version is a valid historical combination, not an illegal enum state.

For ordinary Ask Olin use, the complete condition is:

```text
trusted actor and partition
AND exact admitted version selected for purpose and applicable time
AND required version-bound admission/attestation/endorsement evidence
AND no relevant unresolved challenge, non-use, hold or hard expiry
AND current classification and dependency/release validity
AND B1 scope AND every subject AND every required domain authorization
AND B2 inherited source/use restrictions
```

Authorize the candidate space before sensitive retrieval. A missing/unknown fact fails closed. A previously ACTIVE badge, a source pointer, a bundle, or an old operation receipt supplies no permission. Grant loss can make a claim unusable for one viewer without changing its admission for everyone.

History and dispute review are separate, explicitly requested uses with current full authorization and their own applicable non-use rules. Rejected/proposed material must never leak into ordinary answers as supporting Knowledge. Superseded/expired content can be shown as attributed history when allowed, not quietly used as current guidance. A revoked version is available only if its non-use/retention policy explicitly permits the review use; do not invent an audit bypass. B4 decides retention and deletion, not this proposal.

## 6. Capture and admission

Capture does not mean durable admission. A conversation message can exist as source evidence without producing any usable Knowledge. An authorized command should first determine whether the input is reusable context or belongs to a canonical domain process. Measurements, diagnoses, transactions and appointments go through their domain owners; a contextual assertion may reference them but cannot replace them.

For initial admission, require trusted identity/partition, B1 CREATE+VIEW for complete proposed content, separately authorized source use, complete B2 classification and lineage, bounded reusable wording, explicit applicability, the required admission evidence, and no applicable suppression. Unknown authority/classification means no usable admission; any retained proposal still needs protected capture authority. Credentials/secrets are excluded; the current keyword checks are not a complete detector.

| Origin/operation | Proposed admission policy |
|---|---|
| Authenticated “Remember that I dislike canned tuna” | Explicit first-person assertion and save intent may admit faithful low-risk wording atomically. Show exactly what was saved. No redundant “yes” is required. Separate independently changing clauses. |
| Incidental conversation or ambiguous extraction | Source capture is not consent to remember. Present exact candidate wording and save intent; remain PROPOSED until accepted. No autonomous extraction from every conversation. |
| AI_HYPOTHESIS, AI_SUMMARY, AI-generated DERIVED content | No automatic ordinary use as durable Knowledge initially. Human confirmation of exact content may produce an admitted successor; required authority/classification still applies. Preserve AI origin and input lineage. |
| Imported/professional/system-origin content | Provenance label alone cannot admit it. A later explicitly approved source-specific admission policy must prove source identity, bounded use, authority and canonical-domain routing. Initially propose/review or route to its owner; no blanket auto-admission. |
| Circle assertion | An authorized contributor may propose an attributed assertion. Shared ordinary use additionally needs exact-version stewardship endorsement with B1's required Circle MANAGE and full subject restrictions. The assertor may also endorse only when independently proven steward authority exists. |

Transient request-local summaries are not a back door into durable ADMITTED Knowledge. Any future use of generated material as an ephemeral answer/derivative remains labeled, subject to B2/B6, and does not establish new durable authority. Deterministic retrieval representations likewise inherit eligibility from inputs; they cannot invent an admitted assertion.

This policy deliberately restricts the initial reusable preference use case. Health/Finance need explicit domain-specific admission and consequential-action rules before extension. Confirming a dietary statement does not establish a clinical diagnosis, professional verification, or authority to execute an instruction.

## 7. Confirmation and attestation

The word “confirm” must name what the person is doing:

| Human act | Recorded meaning | Does not imply |
|---|---|---|
| Said it originally | Direct assertion by the authenticated speaker, with original source evidence and explicit save intent where required. | Verified truth, another subject's agreement, or permission to share. |
| Confirms AI wording | “This exact statement accurately expresses my assertion” in the recorded capacity/applicability. | Independent lineage, declassification, professional verification or universal truth. |
| Endorses Circle use | Steward authorizes this exact version for bounded shared contextual use. | Every member agrees; consent for other Persons; truth verification. |
| Attests truth/accuracy | A person's explicit agreement with a proposition, with capacity and limitations preserved. | A universal verified flag. Professional authority requires a separately validated domain process. |
| Allows disclosure | Separate B1 grant/share operation and, where needed, B2 projection approvals. | Agreement with the statement. Confirmation alone never widens audience. |
| Acknowledges reading | Receipt/acknowledgement only. | Attestation, admission or sharing. |

Bind confirmation to an exact version, wording/qualifiers, requested meaning, applicable time, and current classification/lineage revision. A stale UI “yes,” unbound chat response, checkbox from another session, imported Episode ID, or model-authored “user confirmed” is insufficient. Presentation must make the attestation meaning and save intent clear. If wording changes after review, require a new review. A classification/authority change invalidates the pending approval basis even if text is unchanged.

For an eligible AI proposal, confirmation atomically records the human event/attestation, creates a **distinct immutable successor**, records the human's assertion capacity while retaining AI transformation ancestry, admits it if all gates pass, and closes the exact proposal through a confirmation replacement relation. The successor is the admitted contextual assertion; it is not canonical objective truth. The hypothesis remains unadmitted protected history. Neither object receives a weaker classification merely because a human agrees. Never use a self-referential predecessor ID.

For already admitted unchanged wording, another person's agreement creates a separate version-bound attestation, not duplicate content or reassignment of the original author. It cannot remove another person's challenge, revoke a restriction, extend validity, or reactivate a retired version. Confirmation without permission to replace cannot secretly perform correction. A proposal about another person needs complete B1 authority; the confirming actor is not impersonating that subject.

Apply B1 operation predicates: exact old VIEW and UPDATE for confirmation, replacement CREATE+VIEW when a successor is created, and all B2 inherited restrictions. Steward endorsement also requires Circle MANAGE in every required domain. Personal attestations use the attesting Person's own trusted actor; no proxy absent separately approved representation. B2 projection approval is a separate exact-output, version/use-bound decision with all required human capacities, never a confirmation side effect. The initial preference vertical has no downgrade feature.

## 8. Correction, change over time, and supersession

**Correction** means the old assertion misrepresented the relevant circumstances. Create a separately attributed replacement with a correction reason, exact target and corrected applicability. Preserve the old statement as “previously recorded, later corrected,” not as known true before the correction date. Record when the correction was received separately from the period it corrects.

**Change over time** means a previously applicable assertion is different from an effective time onward. Create a new version and a CHANGE replacement relation with that effective boundary. Do not brand the prior preference as wrong. Record both when the system learned of the change and when the user says it took effect.

Both may use supersession, but supersession is a replacement mechanism, not the reason. Confirmation is a third replacement reason. A clarification compatible with existing content may be an additional assertion without supersession. Corrections cannot silently remove scope/source restrictions; potential weakening goes through B1/B2 review even when the wording sounds less sensitive.

Use aware UTC instants for ordering and half-open applicability intervals `[from, until)`. Preserve original local/date precision where relevant; do not invent midnight or an exact onset when the speaker supplied none. Unknown onset is unknown, not capture time and not “true forever.” For ordinary preferences, “from now on” may explicitly establish the receipt-time boundary; ambiguous “actually” needs clarification before destructive semantic replacement. Unknown required temporal applicability excludes use where that uncertainty matters.

Keep stated original validity immutable. A later CHANGE relation can end the old version's **effective selection** at T without editing its originally recorded assertion. For a future T, the old version remains selected before T and the successor after T, subject to all other checks. A retroactive correction alters the present understanding of the earlier period while preserving what the system believed at its earlier recorded time. No full bitemporal query engine is required, but both times and replacement reason must survive.

Only one effective successor per predecessor/purpose/overlapping interval may commit. This does not require one universally true assertion per Person/topic. Independently attributed conflicting lines remain separate and require the dispute policy. A broad similarity match cannot authorize retiring several assertions; each target/version and replacement scope must be explicit and authorized.

## 9. Dispute without a consensus engine

An authorized challenge records its actor, exact target/version, stated issue, affected applicability, and separately classified evidence. “I disagree” need not create an opposite factual claim. If Ana supplies a replacement proposition, capture it as her separately attributed assertion with its own admission/authorization, and link it as a challenge where authorized. Never edit Erick's words to become Ana's words.

Under B1, a viewer may challenge when also authorized to CREATE that challenge under its complete requirements. A subject/assertor has B1's narrower non-disclosing objection/retraction route even without joint-content VIEW; a guessed identifier must not reveal existence. A challenge reason that reveals more sensitive information receives its own B2 restrictions. Even the existence or author of a dispute can be protected metadata.

Recommended default: an accepted unresolved challenge excludes the targeted content from ordinary recommendations/answers for the contested use. It stays available only in authorized, explicitly requested review/history with attribution and uncertainty, subject to non-use and B4 retention. If challenge detail is inaccessible, return a neutral unavailable result, not a revealing “Ana disputed your health claim.” Do not substitute the disputed value or use it indirectly through an old summary.

Resolution is bounded, not a vote:

- The challenger may withdraw their own challenge through a version-checked, attributable decision. Re-enabling ordinary use requires all remaining checks and no other challenge.
- The original assertor may retract their assertion or accept an authorized correction. The target is retired for ordinary use; the challenge remains a recorded historical disagreement, not a rewritten vote.
- A replacement may address the issue, but does not automatically clear it. Mark relevant challenges addressed only with explicit challenger acknowledgement tied to the reviewed successor. Otherwise the replacement stays withheld for the contested use. Carrying or resolving the control cannot drop the challenge's protection.
- A Circle steward may retire shared use and endorse separately attributed new content, but cannot clear another person's unresolved objection by authority, majority, timestamp, or renaming the claim. A materially equivalent successor cannot bypass that dispute. If its relationship to an unresolved challenge is uncertain, withhold ordinary shared use pending review.

No general steward override or adjudication engine is proposed. With unresolved disagreement, Olin may abstain or, in an explicitly authorized comparison, report attributed positions. Mere detection of contradictory independent claims is grounds to withhold a confident combined answer and request clarification; it does not manufacture a person's challenge or merge their assertions. This conservative policy has an availability/UX cost, explicitly for Product Architect decision.

## 10. Revocation, non-use, expiry, and renewed assertions

Distinguish the causes and affected scope:

| Event | Lifecycle consequence |
|---|---|
| Viewer loses authorization | Deny that viewer's covered uses immediately. Do not label the proposition false or globally revoke it. Other viewers still need their own complete current checks. |
| Author retracts assertion | Withdraw that attributable contribution/version from ordinary use. Retain attribution only as permitted by B4. Do not retract another person's independent assertion or source. |
| Person withdraws an attestation | Retire only their endorsement/attestation. If admission/shared use depended on it, that use becomes ineligible; unrelated valid attestation is not erased. |
| Authorized whole-claim non-use | Apply the requested use restriction under B1 MANAGE/removal predicates. Record reason and target; no physical erasure promise. |
| Subject objects to use | Apply B1's accepted restriction to the inseparable claim and dependent covered uses immediately, without granting joint VIEW. A Person-wide restriction also applies across independent lines. |
| Assertion is believed wrong | Correction or dispute, not a vague access-revocation flag. Withdrawal may be added when the actor also requests non-use. |

Deliberate version revocation is irreversible on that version under this recommendation. A rejected, revoked or expired version cannot be confirmed back into current use. A new deliberate reassertion/renewal may create a distinct reviewed version with new evidence, current authority and explicit applicability, provided the old restriction was version-limited and all continuing line/subject/source restrictions permit the new use. A still-applicable non-use decision cannot be bypassed by a new ID, import, alternate source, attestation or fresh wording. An explicit change by the restriction's legitimate authority must resolve that restriction first; AI and mere claim UPDATE cannot do so.

If renewed content was formulated from the old content, preserve its actual dependencies and requirements. Only a genuinely independent capture under B2 has separate source lineage; independent capture still cannot bypass Person-wide non-use. A renewal is not a deletion restore. B4 defines retained minimal suppression evidence and anti-resurrection coverage.

Expiry serves two distinct needs: the proposition's applicability ends (for example a temporary routine), or the permission to rely on an unreviewed assertion ends at a hard freshness/use deadline. A **review reminder** is different: it prompts review but does not silently expire the content. Deadline type, reason, authority and applicable use must be explicit; no universal TTL or guessed dietary expiry.

At the hard boundary, ordinary eligibility changes automatically by evaluating trusted time. A job may update a display/index later, but cannot extend use until it runs. Expired content may remain valid as a historical account of its earlier period; a hard use deadline may instead bar that use too according to its recorded scope. Renewal creates a new version/deadline and fresh review, never edits the old deadline to make a stale approval valid. Expiry of a pending proposal closes its actionable confirmation window; it does not assert that the proposed statement is false.

## 11. Atomicity, concurrency, idempotency, and authority races

These are technology-neutral obligations on the eventual canonical command boundary, not a database or distributed-transaction selection.

1. **Exact preconditions.** Every decision binds trusted partition/actor, command identity, target content version, expected lifecycle/control revision, expected replacement-line revision, intended effect and relevant source/classification/authority revisions. Protected metadata must be resolved before sensitive reads; untrusted IDs are not authority.
2. **CAS-equivalent commit.** Validate expected revisions and commit only if unchanged. A mismatch returns a conflict requiring an authorized refresh and a new deliberate decision. Never automatically retarget confirmation/correction to the newest version, supersede a different predecessor, or overwrite another person's attestation.
3. **One atomic domain outcome.** When a command publishes a successor, its content/evidence binding, admission decision, confirmation event, predecessor closure/effective replacement, required challenge/non-use effects, decision history, invalidation obligation and durable operation result must agree. No observable interval may expose a new current version while leaving a conflicting old one current. Failed approval leaves no admitted successor; any authorized draft remains non-usable.
4. **Business idempotency.** Scope a stable operation key to trusted partition, actor and operation kind; bind it to exact intent/payload and targets. Same key/same intent returns the original outcome without new claims, attestations or transitions. Same key/different intent is rejected. Reserve/check it atomically with commit. A lost acknowledgement is recovered by inspecting the original receipt, not running the mutation again.
5. **No replay disclosure.** A receipt records what committed then, not current validity or permission. After access loss, a replay may return only a permitted minimal non-disclosing outcome; it must not re-emit old claim text. A failed authorization/conflict is not automatically retried into success after later state changes; a revised deliberate command uses a new operation identity. Transport retries use fresh authenticated delegation; never reuse a consumed G1.6 token.
6. **Capture duplicates.** Bind repeated delivery/import to partition-local source identity/version and capture intent (including separately captured item identity when one episode yields several claims). Same source event and intent yields the same result. Different independent messages with similar text are not merged by content hash or semantic similarity. Reuse of bytes cannot merge lineage or permissions. If the source lacks stable identity, require a stable capture request key; content-only deduplication is not a correctness substitute.
7. **Transition races.** Competing confirmation, correction, rejection, challenge, revocation and expiry must be ordered at the authoritative boundary. A commit must validate every affected revision, not only the text. Restrictions/challenges accepted before another commit must be observed by it. If admission commits first, a subsequent valid restriction immediately bars the covered use; it need not undo history. Stale drafts/jobs cannot republish the old view.
8. **Commit-time authorization barrier.** Revalidate the session, complete B1 operation requirements, B2 source/use constraints, all required human approval capacities and exact approval applicability at commit. A separate earlier ALLOW followed by an unchecked write is insufficient: revocation and commit must have an enforceable ordering/fence. If relevant revocation is accepted before commit, deny/abort; if commit orders first, subsequent revocation bars future covered use. Unknown order, unavailable Home or unprovable freshness means no commit. B5/B6 must demonstrate a mechanism across authority/owner boundaries before implementation approval.
9. **No stale disclosure/publication.** Completion of a task, queued approval, cache hit or workflow status is not authority. Recheck at protected task display, command completion and final response/disclosure. If already retrieved context becomes ineligible, withhold and regenerate from eligible inputs where possible; previously disclosed information cannot be recalled. B6 defines the concrete retrieval/context protocol.
10. **Finite retention, durable correctness.** B4 must define idempotency/receipt retention and a maximum supported retry window, with a trusted cutoff preventing ancient commands from executing as new after receipts are removed. Retain no sensitive payload merely for idempotency. Unknown commit outcome remains recoverable/pending, never reported as an unqualified failure inviting a duplicate write. No unbounded event log is required.

For A correcting an old version while B confirms it: if correction commits first, confirmation's expected version/control/line revisions fail and no successor/attestation is published by that command. If confirmation commits first, correction based on the old revisions fails, or must be deliberately refreshed against the new state before committing. Both may ultimately appear in ordered history, but the stale command must never resurrect the replaced version. Addition of a challenge also changes the control revision; it cannot be lost behind a concurrent confirmation.

Suppression/invalidation must become authoritative as part of the domain outcome even when derivative cleanup is asynchronous. If the dependency set cannot be safely determined, deny the affected bounded use path pending reconciliation. This preserves B2's immediate ineligibility without choosing B4's cleanup or B6's freshness mechanism.

## 12. Scenarios A–J and expected outcomes

These are proposed acceptance specifications, not implemented B3 tests. Every permitted operation assumes complete current B1/B2 authority; failure means no usable publication and no unauthorized disclosure.

| Case | Proposed outcome |
|---|---|
| **A — Vegetarian dinner hypothesis confirmed** | Hypothesis H is PROPOSED. The user reviews exact wording and confirms it as their preference. One atomic command creates distinct admitted V with the human attestation and all H ancestry, closes H with a confirmation replacement edge, and records the result. V is authoritative only as that admitted attributed contextual assertion. H never becomes a user-origin assertion or ordinary usable hypothesis. |
| **B — “No, that is wrong” to AI suggestion** | Reject the exact unadmitted proposal and record the user's rejection event; do not dispute an admitted claim that does not exist or infer “I prefer meat.” No new positive claim without explicit content. If the target had already been admitted, use an attributed challenge/correction/withdrawal as appropriate; the UI must bind which version was rejected. |
| **C — “I dislike all tuna” → “Actually, only canned tuna”** | When the user means the earlier broad assertion was wrong, create a correction successor with narrower asserted meaning and a correction relation covering the mistaken scope. Preserve the original as a corrected record, not a formerly true dislike of all tuna. Do not infer unrelated positive preferences. Inherited restrictions remain unless separately released. If the old assertion already said canned tuna, this may only be compatible clarification; do not auto-supersede. |
| **D — “I avoid fish” → “I eat fish now”** | If an actual change, create a CHANGE successor with an explicit effective time; preserve the old preference for its earlier interval. Capture time and effective time are distinct. If “eat” versus “avoid” could mean an exception rather than a changed preference, clarify before replacement. |
| **E — Confirmation of protected derived wording** | Admit a new confirmed version only when authorized; retain source/AI lineage, full inherited sensitivity, source-use restrictions and B1 checks. The user's confirmation is new evidence about agreement, not independent origin or release authority. Wider sharing needs the separate approved B1/B2 process. |
| **F — Already REVOKED or EXPIRED** | Reject ordinary confirmation/reactivation of that version. A deliberate new assertion/renewal may be proposed under current authority and applicability only if continuing restrictions allow it. Known derivation remains inherited; new IDs never defeat non-use. Historical visibility is separately authorized and retention-dependent. |
| **G — Correction versus stale confirmation** | CAS-equivalent checks permit an ordered outcome, not last-write-wins. The stale operation conflicts and must refresh deliberately. No self-supersession, two overlapping current successors, confirmation of replaced text, or silent retargeting. See section 11 for both commit orders. |
| **H — Capture/confirmation retry** | Same actor/partition/operation key and intent returns the original permitted receipt/result. No duplicate claim or attestation; altered intent conflicts. Lost response does not cause another transition. Current authorization controls result disclosure; fresh transport delegation preserves anti-replay. |
| **I — Erick asserts 19:00; Ana disagrees** | Erick's attributed Circle assertion needs authorized stewardship endorsement for ordinary shared use. Ana's authorized challenge targets its exact version; the unresolved challenge suppresses ordinary use but does not rewrite Erick. Authorized review may show both positions. A separately asserted alternative has Ana's attribution and own admission/lineage. No majority, inferred family agreement or steward truth override. |
| **J — Authorization revoked while pending** | Invalidate the pending basis and revalidate at commit under an enforceable ordering with revocation. Revocation accepted first prevents confirmation/share/update commit; old approval/workflow state does not override it. If commit occurred first, the later revocation bars future covered use and result disclosure. No automatic retry, relabeling or private-scope fallback. Narrow authorized non-disclosing withdrawal remains available under B1. |

Additional required later tests: dispute and supersession coexist; one attestor withdraws while another remains; hidden challenge metadata is not disclosed; expiry at the exact boundary without a timer; scheduled and retroactive changes; rejection racing with confirmation; classification changes after review but before commit; restriction after content retrieval; two independent equal-text assertions; receipt removal followed by an ancient retry; an unresolved challenge carried to equivalent successor wording; no reactivation through source import or restore.

## 13. Boundaries for B4, B5, and B6

| Blocker | B3 requires | Still open |
|---|---|---|
| **B4 — Dependency / Forget / Delete** | Distinguish actual derivation, attestation support, history and replacement; immediate non-use precedes cleanup; source-specific invalidation does not erase independent lines, while Person-wide restrictions still apply. Immutable content is removable under retention policy. Preserve minimal anti-resurrection/idempotency evidence and reconcile restored state before use. | Physical deletion scope, retention of proposals/episodes/content/decisions, deletion versus withdrawal UX, dependency representation, cleanup executors and authority, indexes/caches/jobs, backup retention/restore, erasure verification. No promise to retain full history forever. |
| **B5 — Ownership boundaries** | One accountable canonical command boundary must own atomic lifecycle decisions and receipts while Home remains grant/operation-policy authority. Domain facts remain with their owners; source handling and admission authority must be explicit. | Which service owns Knowledge persistence, Nutrition preferences and migration, source/episode custody, distributed responsibility and implementation placement. B3 appoints no new service and moves no data. |
| **B6 — Trusted retrieval / ContextBundle** | Separate ordinary use from proposal/history/dispute review. Enforce current lifecycle/time/authority/dependency predicates before sensitive candidates, carry exact versions, revalidate before disclosure and honor immediate invalidation across retained context. Demonstrate commit/disclosure freshness consistent with G1.6. | Concrete bounded multi-resource protocol, authority fences, provider/repository interfaces, search/ranking, cache/index invalidation, context reset, task limits and disclosure mechanisms. B3 specifies outcomes, not a retrieval technology or protocol. |

B4–B6 are not resolved by assigning these obligations. Until their enforcement is designed and the gate closes, even accepted B3 semantics would not authorize Knowledge runtime or technology selection.

## 14. Genuine Product Architect decisions requested

| Decision | Recommendation and tradeoff |
|---|---|
| **D1 — Lifecycle unit/model** | Accept exact immutable assertion versions plus explicit replacement lines and separate lifecycle facts (option B). More concepts than one status, but simultaneous dispute/supersession/non-use remain expressible. ACTIVE is derived readiness, not truth or permission. |
| **D2 — Initial admission** | Allow explicit faithful first-person low-risk save commands without redundant confirmation. All AI-origin durable assertions require exact human confirmation; no blanket imported/professional/system auto-admission. Future source-specific policies require separate approval. This trades automation for explicit authority. |
| **D3 — Confirmation object semantics** | Confirming an eligible AI proposal creates a distinct admitted successor and atomically closes the proposal; additional attestations to admitted unchanged content do not clone it. Confirmation preserves all lineage/restrictions and never doubles as disclosure permission. |
| **D4 — Circle use and disagreement** | Require exact-version stewardship endorsement for shared ordinary use. An authorized unresolved challenge suppresses the contested use; no steward/majority adjudication override. Equivalent successors cannot bypass it. This may reduce availability during disagreement; accept explicitly or request a separately specified resolution policy. |
| **D5 — Temporal meaning** | Distinguish correction from real change using reason, capture time and applicable time; use half-open intervals and explicit unknown precision. Permit scheduled changes without retiring current content early. No universal preference TTL; separate soft reminders from hard use deadlines. |
| **D6 — Terminal versions and renewed use** | No in-place resurrection of rejected, revoked or expired versions. Permit only fresh reviewed assertions/renewals that satisfy continuing restrictions. This adds a visible renewal step and preserves an auditable distinction. |
| **D7 — Commit and retry invariants** | Accept exact-version CAS-equivalent checks, atomic replacement/receipts, partition/actor-bound idempotency and enforceable authorization ordering at commit. B5/B6 must prove a mechanism; an earlier ALLOW alone is insufficient. |

These decisions concern B3 product semantics, not permission to modify contracts or deploy. B1/B2 authority and non-weakening rules are already accepted, not presented for another vote. There is no recorded Product Architect acceptance of D1–D7 in this proposal.

## 15. Verification and structured investigation result

Only this proposal and the B3 entry of the gate register are changed. General gate text still calls B3 open because it remains unresolved; the B3 entry records the more precise proposed/awaiting-decision status. B1/B2 and B4–B6 entries, canonical architecture, ADRs and all contracts/runtime remain untouched.

```json
{
  "task": "knowledge_b3_architecture_proposal",
  "baseline_main_sha": "0a6fc2eb15f805299d732a3b7cdf8f1719a0e902",
  "baseline_worktree_clean": true,
  "pr_24": "MERGED",
  "recommended_model": "immutable assertion versions with explicit admission, attestations, replacement and use controls",
  "existing_contract_tests_passed": 12,
  "scenarios": "A-J: proposed architecture acceptance criteria, not implemented runtime tests",
  "b1": "RESOLVED",
  "b2": "RESOLVED",
  "b3": "PROPOSED — AWAITING PRODUCT ARCHITECT DECISION",
  "b4_b5_b6": "OPEN",
  "knowledge_technology_gate": "OPEN",
  "technology_selected": false,
  "contracts_or_schemas_changed": false,
  "knowledge_runtime_implemented": false,
  "production_changed": false
}
```

Verify the docs-only change after commit:

```powershell
git diff --check origin/main...HEAD
git diff --name-only origin/main...HEAD
git diff origin/main...HEAD -- docs/architecture/proposals/KNOWLEDGE_TECHNOLOGY_GATE.md
git status --short --branch
```

Expected changed paths: `docs/architecture/proposals/KNOWLEDGE_B3_LIFECYCLE.md` and `docs/architecture/proposals/KNOWLEDGE_TECHNOLOGY_GATE.md`. Passing existing contract tests verifies the inspected baseline only, not enforcement of this proposal.

Reproduce the existing contract test check without creating repository cache files:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'packages/home-contracts/src')
$env:PYTHONDONTWRITEBYTECODE = '1'
python -m pytest packages/home-contracts/tests -q -p no:cacheprovider
```

**B3 PROPOSED — NOT RESOLVED**

**B1–B2 REMAIN RESOLVED**

**B4–B6 REMAIN OPEN**

**NO TECHNOLOGY SELECTED**

**NO KNOWLEDGE RUNTIME IMPLEMENTED**

**NO PRODUCTION CHANGE**
