# Knowledge B3 — Confirmation, admission, and lifecycle

Status: ACCEPTED — B3 ARCHITECTURE DECISION

Date: 2026-09-20

Final verification: 2026-09-21; `origin/main` remains at the investigation baseline below.

Repository: `EKvargas/episteck_home`

Main baseline: `0a6fc2eb15f805299d732a3b7cdf8f1719a0e902`, verified current `origin/main` after [PR #24](https://github.com/EKvargas/episteck_home/pull/24) merged.

Branch: `docs/knowledge-b3-lifecycle`

Decision owner: Product Architect

Decision date: 2026-09-21

Disposition: ACCEPTED WITH CLARIFICATIONS — B3 RESOLVED

Gate: [B3 — Confirmation and lifecycle](KNOWLEDGE_TECHNOLOGY_GATE.md#b3--confirmation-and-lifecycle)

## 1. Accepted decision and authority

Adopt **immutable assertion versions, explicit admission, version-bound attestations, typed replacement relations, and independent use controls**, with an atomic current-state view and a minimal decision history. Lifecycle belongs to an exact assertion version. An assertion line groups explicit replacements; it is not a global identity for everything said about a topic. An Episode records capture/confirmation evidence, not the lifecycle of everything extracted from it.

Do not persist one status that must simultaneously answer whether content was admitted, whether someone agrees, whether it has a successor, whether it is contested, whether it is within its applicable time, and whether this viewer can use it. In particular, ACTIVE must not mean true, universally confirmed, or authorized. Section 5 defines the small admission state machine and the other independent lifecycle facets; the familiar status words are derived descriptions of those facts.

Preserve [accepted B1](KNOWLEDGE_B1_SECURITY_SCOPE.md) and [accepted B2](KNOWLEDGE_B2_SENSITIVITY_INHERITANCE.md) without amendment. No contradiction requiring either to reopen was found. Trusted actor/partition, conjunctive scope/subject/domain authorization, actual-influence lineage, no ordinary sensitivity weakening, independent assertion lines, and immediate ineligibility remain mandatory. AI is never release or declassification authority.

This document records the Product Architect's accepted B3 architecture and future acceptance criteria, including the D2 and D4 clarifications in sections 6 and 9. Section 14 records the explicit disposition dated 2026-09-21; acceptance is not inferred from a PR merge. This decision governs B3 where older documentation is less precise, pending later consolidation. It changes no contract, schema, enum, runtime, or production system; it selects no storage, retrieval, indexing, or workflow technology. B1–B3 are RESOLVED; B4–B6 and the Knowledge Technology Gate remain OPEN. All scenarios are synthetic.

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

A direct explicit assertion in an approved admission class can be captured and admitted in one atomic operation when every section 6 gate passes; no externally visible proposal stage is required. A fulfilled AI proposal remains an unadmitted historical proposal linked to its admitted successor and closed to further decisions. Its derived label is SUPERSEDED, not REJECTED. No proposed version can remain an actionable confirmation target after replacement, revocation, expiry or rejection.

Rejecting a shared proposal's admission requires exact proposal VIEW plus B1 Q(UPDATE), with all inherited restrictions and the current decision revision. A person who lacks that authority may decline their own requested attestation without rejecting the proposal for everyone; B1's narrow own-contribution withdrawal and own-subject objection remain available. A pending request's cancellation or technical failure is not a factual rejection and creates no attestation. The model cannot supply a human rejection or clear a pending approval on its own.

### 5.2 Independent lifecycle facets and familiar labels

| Label/facet | Precise meaning and use effect |
|---|---|
| **CURRENT** | Selected for this line's defined purpose and requested applicable time. There may be historical and scheduled versions, but no two effective successors for the same predecessor/purpose/overlapping interval. Independent lines may coexist and conflict. CURRENT alone conveys no admission or permission. |
| **SUPERSEDED** | An explicit successor replaces this version for the stated purpose/interval. The old version is excluded from ordinary current use for that interval; its capture, attestations and replacement reason remain protected history. Future-effective change does not suppress the old version before its effective boundary. |
| **DISPUTED** | At least one authorized, unresolved challenge contests this exact version and proposition for the relevant use/interval/context. It can coexist with ADMITTED, SUPERSEDED or REVOKED. Ordinary use excludes the contested content within that bounded scope. Carryover follows section 9; a challenge is not a permanent Person-level veto, rejection, deletion, or proof of falsity. |
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

**D2 clarification — approved admission classes.** Direct admission requires an explicitly architecture-approved admission class; “low risk” is not an LLM/model judgment or an admission authority. The model may propose classification and routing, but cannot create or approve an admission class. The direct-admission condition is:

```text
trusted explicit save intent
AND approved admission class
AND canonical-domain routing passed
AND B1 authorization passed
AND B2 classification/lineage passed
AND no applicable suppression
→ may admit directly
```

For the approved initial preference class, an authenticated “Remember that I dislike canned tuna” may admit faithful reusable wording atomically without redundant confirmation, once all these gates pass. Class approval does not settle B5 ownership or authorize runtime: unknown canonical ownership means routing has not passed. Incidental conversation, ambiguous inference, an unapproved information class, uncertain B2 classification, or Health/Finance and other consequential domains without approved policy must not be auto-admitted on a model's assessment of risk. Such material remains PROPOSED under authorized protected capture, is routed to its canonical domain process, or is withheld from durable Knowledge as appropriate. Future source/domain-specific auto-admission policies require explicit architecture approval.

| Origin/operation | Accepted admission policy |
|---|---|
| Authenticated “Remember that I dislike canned tuna” | Within the approved initial preference admission class, explicit first-person assertion and save intent may admit faithful wording atomically only when canonical routing, B1, B2 and suppression checks pass. Show exactly what was saved. No redundant “yes” is required. Separate independently changing clauses. |
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

An authorized challenge binds the exact challenged assertion/version, disputed proposition/use, applicable interval/context, challenge actor and authority, and its own lifecycle/control revision. It also records separately classified evidence where supplied. “I disagree” need not create an opposite factual claim. If Ana supplies a replacement proposition, capture it as her separately attributed assertion with its own admission/authorization, and link it as a challenge where authorized. Never edit Erick's words to become Ana's words.

Under B1, a viewer may challenge when also authorized to CREATE that challenge under its complete requirements. A subject/assertor has B1's narrower non-disclosing objection/retraction route even without joint-content VIEW; a guessed identifier must not reveal existence. A challenge reason that reveals more sensitive information receives its own B2 restrictions. Even the existence or author of a dispute can be protected metadata.

Accepted default: an accepted unresolved relevant challenge excludes the targeted content from ordinary recommendations/answers for the contested use and applicability. It stays available only in authorized, explicitly requested review/history with attribution and uncertainty, subject to non-use and B4 retention. If challenge detail is inaccessible, return a neutral unavailable result, not a revealing “Ana disputed your health claim.” Do not substitute the disputed value or use it indirectly through an old summary.

**D4 clarification — bounded dispute scope.** A challenge is not a permanent Person-level veto. It may carry to a replacement only when that replacement materially preserves the contested proposition for the same overlapping applicability/use. Determine equivalence conservatively; uncertainty may require review and temporary withholding of that candidate's contested use. Similar words, topic or Person identity alone do not establish carryover. A new assertion about a later non-overlapping period, materially changed circumstances, or a genuinely independent assertion line must be evaluated under its own current B1/B2/B3 requirements. The historical challenge remains attributable history and does not automatically suppress that new proposition. A cosmetic new ID, wording change or falsely claimed independence cannot evade an applicable dispute.

For example, Ana's challenge to “Our household eats at 19:00” in 2026 prevents a cosmetic replacement from restoring the same contested 2026 assertion. It does not automatically block a separately supported 2027 assertion, “Our household now usually eats at 18:30.” The 2027 assertion needs its own admission, Circle endorsement, authorization, classification and lineage checks; acknowledgement of the old challenge is not a prerequisite for this distinct proposition. This boundary does not weaken independently applicable B1 subject non-use or B2 source restrictions, which retain their own scopes.

Resolution is bounded, not a vote:

- The challenger may withdraw their own challenge through a version-checked, attributable decision. Re-enabling ordinary use requires all remaining checks and no other challenge.
- The original assertor may retract their assertion or accept an authorized correction. The target is retired for ordinary use; the challenge remains a recorded historical disagreement, not a rewritten vote.
- A replacement that remains within the challenge's bounded proposition/use and overlapping applicability does not automatically clear it. Mark that challenge addressed only with explicit challenger acknowledgement tied to the reviewed successor; otherwise the applicable contested use remains withheld. A new proposition outside that scope is evaluated separately and needs no acknowledgement of the historical challenge. Carrying or resolving the control cannot drop the challenge's protection.
- A Circle steward may retire shared use and endorse separately attributed new content, but cannot clear another person's unresolved objection by authority, majority, timestamp, or renaming the claim. A materially equivalent successor within the same overlapping applicability/use cannot bypass that dispute. If equivalence or applicability is uncertain, withhold the candidate's contested use pending review; do not expand the old challenge into a blanket veto on future family Knowledge.

No general steward override or adjudication engine is adopted. With unresolved relevant disagreement, Olin may abstain or, in an explicitly authorized comparison, report attributed positions. Mere detection of contradictory independent claims is grounds to withhold a confident combined answer and request clarification; it does not manufacture a person's challenge, merge their assertions, or automatically carry an old challenge to an independent line. The Product Architect accepted this conservative policy with the bounded-scope clarification above.

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

These are accepted architecture outcomes and future acceptance specifications, not implemented B3 tests. Every permitted operation assumes complete current B1/B2 authority; failure means no usable publication and no unauthorized disclosure.

| Case | Accepted outcome |
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

Additional required later tests: dispute and supersession coexist; one attestor withdraws while another remains; hidden challenge metadata is not disclosed; expiry at the exact boundary without a timer; scheduled and retroactive changes; rejection racing with confirmation; classification changes after review but before commit; restriction after content retrieval; two independent equal-text assertions; receipt removal followed by an ancient retry; an unresolved challenge carried only to materially equivalent successor wording for overlapping applicability/use; no automatic carryover to a separately supported non-overlapping 2027 routine after a 2026 dispute; materially changed circumstances and genuinely independent lines evaluated on their own requirements; unapproved classes and uncertain ownership/classification cannot auto-admit despite a model's risk assessment; no reactivation through source import or restore.

## 13. Boundaries for B4, B5, and B6

| Blocker | B3 requires | Still open |
|---|---|---|
| **B4 — Dependency / Forget / Delete** | Distinguish actual derivation, attestation support, history and replacement; immediate non-use precedes cleanup; source-specific invalidation does not erase independent lines, while Person-wide restrictions still apply. Immutable content is removable under retention policy. Preserve minimal anti-resurrection/idempotency evidence and reconcile restored state before use. | Physical deletion scope, retention of proposals/episodes/content/decisions, deletion versus withdrawal UX, dependency representation, cleanup executors and authority, indexes/caches/jobs, backup retention/restore, erasure verification. No promise to retain full history forever. |
| **B5 — Ownership boundaries** | One accountable canonical command boundary must own atomic lifecycle decisions and receipts while Home remains grant/operation-policy authority. Domain facts remain with their owners; source handling and admission authority must be explicit. | Which service owns Knowledge persistence, Nutrition preferences and migration, source/episode custody, distributed responsibility and implementation placement. B3 appoints no new service and moves no data. |
| **B6 — Trusted retrieval / ContextBundle** | Separate ordinary use from proposal/history/dispute review. Enforce current lifecycle/time/authority/dependency predicates before sensitive candidates, carry exact versions, revalidate before disclosure and honor immediate invalidation across retained context. Demonstrate commit/disclosure freshness consistent with G1.6. | Concrete bounded multi-resource protocol, authority fences, provider/repository interfaces, search/ranking, cache/index invalidation, context reset, task limits and disclosure mechanisms. B3 specifies outcomes, not a retrieval technology or protocol. |

B4–B6 are not resolved by assigning these obligations. Accepted B3 semantics do not authorize Knowledge runtime or technology selection; the remaining gate decisions and separately approved implementation work are still required.

## 14. Product Architect disposition

Decision owner: Product Architect

Decision date: 2026-09-21

Disposition: ACCEPTED WITH CLARIFICATIONS — B3 RESOLVED

| Decision | Disposition | Accepted meaning |
|---|---|---|
| **D1 — Lifecycle unit/model** | ACCEPT | Exact immutable assertion versions, explicit replacement lines and separate lifecycle facts (option B). Episodes are evidence. ACTIVE is derived readiness only, never objective truth, universal agreement or authorization for every viewer. |
| **D2 — Initial admission** | ACCEPT WITH CLARIFICATION | Direct admission requires trusted explicit save intent, an architecture-approved admission class, passed canonical routing and B1/B2 checks, and no applicable suppression. The approved initial preference class avoids redundant confirmation when these conditions hold. Model risk judgments cannot authorize new classes; future source/domain-specific auto-admission policies require explicit architecture approval. Section 6 is authoritative. |
| **D3 — Confirmation object semantics** | ACCEPT | Exact human confirmation of an eligible AI-origin proposal creates a distinct admitted successor and atomically closes the proposal, preserving AI/source lineage and restrictions. Additional attestations to unchanged admitted wording do not clone content. Circle endorsement, personal agreement and disclosure permission remain separate. |
| **D4 — Circle use and disagreement** | ACCEPT WITH CLARIFICATION | Preserve attribution and suppress unresolved relevant contested use without majority truth or steward override. Challenges bind exact version, proposition/use, interval/context, actor/authority and control revision. Carryover requires materially preserved contested meaning and overlapping applicability/use. Cosmetic replacements cannot bypass disputes; later periods, changed circumstances and genuinely independent lines receive their own current evaluation, not a permanent Person-level veto. Section 9 is authoritative. |
| **D5 — Temporal meaning** | ACCEPT | Correction repairs an earlier misrepresentation; change records later changed circumstances. Preserve recorded and applicable time, half-open intervals, unknown precision and scheduled changes. Separate review reminders from hard deadlines; no universal preference TTL. |
| **D6 — Terminal versions and renewed use** | ACCEPT | No in-place resurrection of REJECTED, REVOKED or EXPIRED versions. Fresh reviewed assertions/renewals require all continuing restrictions to permit them. |
| **D7 — Commit and retry invariants** | ACCEPT | Exact-version preconditions, CAS-equivalent checks, atomic successor/replacement outcomes, partition/actor/operation-bound idempotency, no content-only semantic deduplication, fresh delegated authentication for retries, no stale receipt as authorization, commit-time authorization barrier and immediate non-use before asynchronous cleanup. B5/B6 must establish the mechanisms. |

The clarifications preserve explicit admission authority and dispute integrity without making an LLM an admission-policy authority or creating a permanent veto over future family Knowledge. Scenarios A–J and the D2/D4 boundary cases are accepted architecture outcomes and future acceptance specifications, not implemented enforcement. B1 and B2 remain unchanged and RESOLVED. B4–B6 and the Knowledge Technology Gate remain OPEN. This disposition authorizes no contracts, schemas, runtime, technology selection, deployment or production changes; PR #25 remains unmerged by this task.

## 15. Verification and structured investigation result

Only this accepted decision and B3 status/disposition references in the gate register change. B1/B2 decisions remain unchanged and RESOLVED; B3 is RESOLVED by the disposition above. B4–B6 and the Knowledge Technology Gate remain OPEN. Canonical architecture files, ADRs and all contracts/runtime remain untouched.

```json
{
  "task": "knowledge_b3_architecture_decision",
  "baseline_main_sha": "0a6fc2eb15f805299d732a3b7cdf8f1719a0e902",
  "baseline_worktree_clean": true,
  "pr_24": "MERGED",
  "accepted_model": "immutable assertion versions with explicit admission, attestations, replacement and use controls",
  "existing_contract_tests_passed": 12,
  "scenarios": "A-J and D2/D4 boundary cases: accepted architecture criteria, not implemented runtime tests",
  "b1": "RESOLVED",
  "b2": "RESOLVED",
  "b3": "RESOLVED — PRODUCT ARCHITECT DECISION, 2026-09-21",
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

**B1–B3 RESOLVED BY PRODUCT ARCHITECT DECISION**

**B4–B6 REMAIN OPEN**

**KNOWLEDGE TECHNOLOGY GATE REMAINS OPEN**

**NO TECHNOLOGY SELECTED**

**NO KNOWLEDGE RUNTIME IMPLEMENTED**

**NO PRODUCTION CHANGE**
