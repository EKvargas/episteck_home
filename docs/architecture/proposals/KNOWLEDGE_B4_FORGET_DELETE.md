# Knowledge B4 — Dependency, Forget, Delete, retention, and resurrection safety

Status: ACCEPTED — B4 ARCHITECTURE DECISION

Date: 2026-09-21

Repository: `EKvargas/episteck_home`

Main baseline: `43ea2935c03c65741fd625f844a4be79a6b2e9f2`, verified current `origin/main` after [PR #25](https://github.com/EKvargas/episteck_home/pull/25) merged and made accepted B3 authoritative on `main`.

Branch: `docs/knowledge-b4-forget-delete`

Decision owner: Product Architect

Decision date: 2026-09-21

Disposition: ACCEPTED WITH CLARIFICATIONS — B4 RESOLVED

Gate: [B4 — Dependency / Forget / Delete](KNOWLEDGE_TECHNOLOGY_GATE.md#b4--dependency--forget--delete)

This document records the Product Architect's accepted B4 architecture and future acceptance criteria, including the four clarifications in section 1.1 and the D1–D7 dispositions in section 16. Section 16 records the explicit disposition dated 2026-09-21; acceptance is not inferred from a PR merge. It changes no contract, schema, service, runtime, index, deployment or production system, and selects no storage, retrieval, orchestration, key-management or cleanup technology. B1–B3 remain RESOLVED and unamended; no contradiction requiring any of them to reopen was found. B1–B4 are RESOLVED; B5–B6 and the Knowledge Technology Gate remain OPEN. All scenarios are synthetic.

## 1. Summary of the accepted decision

Adopt **a durable suppression register as the authoritative non-use fact, separated from physical erasure, with bounded recorded derivation families and a mandatory pre-use admission barrier on restore and re-import.**

Four separable commitments:

1. **Non-use is a durable positive record, not the absence of data.** "Forget" commits a suppression entry that survives restore, re-import, reindexing and cleanup failure. Deleting rows is never the mechanism that makes information stop being used.
2. **Erasure is a separate, asynchronous, evidenced obligation** over a bounded derivation family recorded at creation time. It has its own completion state and its own honest latency.
3. **Nothing re-enters usable state without passing admission again.** Restore, import and reindex are re-admission events evaluated against the current suppression register, not trusted resumptions of previous state.
4. **Backups are an expiry commitment, not a deletion commitment.** Existing snapshots are not rewritten; suppression is what makes restored data unusable, and the retention tail is disclosed to the user.

The essential inversion: a deletion architecture that relies on removing data is only as correct as its least reliable cleanup path. One that relies on a durable record of prohibition stays correct even when cleanup is incomplete, delayed, or replayed from an old snapshot.

### 1.1 Accepted clarifications

Four clarifications are part of the accepted decision and are authoritative wherever the rest of this document is less precise.

**C1 — Restore freshness is load-bearing.** Anti-resurrection state must not depend only on the same snapshot that carries the payload being restored. Consider: a T1 backup contains claim X; at T2 the user forgets X; at T3 the system is lost; T1 is restored. If the only available suppression state is also from T1, X resurrects. The accepted invariant:

```text
RESTORED DATA MUST NOT BECOME USABLE UNLESS THE SYSTEM CAN PROVE THAT THE
SUPPRESSION / DELETION CONTROL STATE USED FOR RECONCILIATION IS AT LEAST AS
CURRENT AS THE PAYLOAD BEING RESTORED.
```

Unknown freshness fails closed. The architecture requires a monotonic or otherwise current anti-resurrection authority, or an equivalent freshness proof. **B4 selects no persistence or replication mechanism for it**; B5/B6 and implementation determine that later. Section 12 and Scenarios H and L are authoritative for the consequences.

**C2 — Hashing is not canonicalized.** "Salted one-way digest over normalized proposition" is **not** a B4 architecture decision. Exact hashes cannot reliably identify semantically equivalent paraphrases, and fixing one would prematurely select a mechanism. The technology-neutral requirement replacing it: the anti-resurrection state must contain the minimum non-reconstructable information necessary to identify the prohibited object, source or use and to support bounded re-admission matching, without retaining the forgotten plaintext. It must be non-reconstructable, non-disclosing, partition-bound, sufficient for the approved re-admission policy, and free of forgotten plaintext or embeddings. Future mechanisms may include opaque source identities, policy keys, digests, classification metadata or trusted semantic review; **B4 selects none**.

**C3 — Forget is not a permanent topic ban.** Forget blocks automatic resurrection, re-extraction, stale restore and materially equivalent re-admission for the covered use and applicability. It does not prevent the legitimate authority from later deliberately choosing to remember the information again. Section 9.1 is authoritative.

**C4 — External provider deletion is conditional, not categorically impossible.** Local Forget/Delete cannot *by itself* guarantee deletion of information previously sent to an external provider, but provider-side deletion is not universally unavailable. Section 6.1 is authoritative.

## 2. Repository facts that determine the design

These were independently verified on the baseline. Prior review statements were re-derived rather than assumed.

| Verified fact | Evidence | Consequence for B4 |
|---|---|---|
| **No deletion capability exists anywhere.** No `forget`, `delete`, `erase`, `purge`, `tombstone` or `suppress` symbol exists in `packages/`. | Repository-wide search of all contract sources | B4 designs a capability from zero. No existing artifact constrains the model, and none should be promoted to a requirement merely because it exists. |
| **No `DELETE` statement exists in the persistence layer.** `services/nutrition/app/store/` contains no delete, drop or purge operation. | `store/repository.py`, `store/sqlite_repo.py` | The running system today cannot erase anything. Any completion promise is currently unimplementable; B4 must define it without assuming a delete path exists. |
| **A REVOKED claim is accepted into a ContextBundle with full statement text.** | In-memory probe P1 | Lifecycle status is not an access control. Suppression must be enforced at the use barrier, not inferred from a status enum. |
| **ContextBundle holds claims by value and has no revalidation member.** | Probe P2; [`context.py`](../../../packages/home-contracts/src/episteck_home_contracts/context.py) | An assembled bundle is a detached plaintext copy with no recall hook. In-flight suppression cannot reach it. B4 must treat the bundle as an ephemeral derivative with a pre-disclosure barrier, and B6 must own the mechanism. |
| **`source_episode_id` is a single scalar string; `KnowledgeEpisode` has no reverse index.** | Probe P3; [`knowledge.py`](../../../packages/home-contracts/src/episteck_home_contracts/knowledge.py) | "Delete everything derived from this source" is not answerable from current contracts. Dependency must be recorded at creation, not reconstructed by scanning. |
| **Only `supersedes_claim_id` links claims. No derivation, chunk, embedding, summary or cache artifact type exists.** | Probe P4, exported names | The single existing edge is a *replacement* relation. B3 §4 states a replacement relation is explicitly *not* automatically a derivation edge. B4 cannot reuse it as the dependency model. |
| **`REVOKED → ACTIVE` is correctly blocked by `transition()`.** | Probe P5 | In-place resurrection of a terminal version is already prevented at contract level. This is the one anti-resurrection property that exists. It covers only same-object transitions. |
| **Identical statement text re-admits freely under a new `claim_id` with the same `source_episode_id`.** | Probe P6 | The re-import and re-extraction attack surface is completely open. Nothing consults a prior revocation. This is the decisive gap. |
| **Backups: restic 0.18.1 → Hetzner Storage Box, daily timer, `keep 7d/4w/3m`, client-side encrypted, restore validated.** | [`DEPLOYMENT.md`](../DEPLOYMENT.md) | Deleted content can persist in retained snapshots until the longest retained snapshot covering it expires. Snapshots are immutable and encrypted. Honest completion semantics must disclose this tail rather than claim immediate erasure. Per D1, this is the accepted **current personal-deployment** policy, not a permanent commercial requirement, and no fixed duration is promised. |
| **Nutrition persists `preferences` and `dislikes` as free text in an upserted profile; there is no delete.** | `services/nutrition/app/service.py` | The canned-tuna example genuinely lives in a non-Knowledge store today. A Knowledge-only forget would leave it usable. B4 must require cross-owner suppression propagation; B5 must resolve who executes it. |
| **12 existing contract tests pass on the baseline.** | `pytest packages/home-contracts/tests` | Verifies the inspected baseline only. No test covers deletion, suppression, dependency or restore. These are not future B4 acceptance tests. |

Two prior characterizations are worth correcting from evidence. First, the independent review's framing that "one source episode and one predecessor link cannot establish all evidentiary dependencies" is correct but understates the position: there is no derivation edge *at all*, so this is a greenfield model rather than an insufficient one. Second, the gate's existing illustration places cleanup orchestration prominently; the probes show the controlling risk is not cleanup sequencing but the absent re-admission barrier, which no amount of orchestration fixes.

## 3. The problem as understood

A user saying "forget that" is issuing one of several materially different requests. Conflating them produces either a false promise or an over-broad destruction of other people's records.

The concrete difficulty is that Knowledge fans out. One statement may exist as original source, Episode, evidence span, assertion version, summary, chunk, embedding, index entry, cache, assembled ContextBundle, generated answer, operation receipt, and backup snapshot. Removing the assertion leaves the derivatives usable. Removing derivatives without a durable prohibition leaves them free to regenerate from a source that still exists. Removing everything destroys independent assertions and audit integrity that other people legitimately rely on.

Compounding this, three things are already true and cannot be undone by any architecture: information already disclosed to a human cannot be recalled; information already sent to an external model provider is outside Episteck's control; and existing encrypted backup snapshots cannot be selectively rewritten. An honest architecture must state these plainly rather than imply a stronger promise.

The design target is therefore: **make the prohibition durable and cheap to enforce, make the erasure bounded and evidenced, and make the promise honest about what cannot be reached.**

## 4. Alternatives considered

**A — Cascade deletion over a full dependency graph.** Record every derivation edge; on forget, traverse transitively and physically delete every descendant. Completion means the traversal finished.

*Assessment:* Intuitive and gives the strongest "it is gone" story when it succeeds. But correctness depends entirely on graph completeness, and any unrecorded edge is a silent resurrection path. It offers nothing against re-import or restore, because after successful deletion no record remains to say the content was prohibited — a restored snapshot looks exactly like legitimate data. Cleanup failure is indistinguishable from completion. Deletion latency is bounded by the slowest store. Rejected as a primary model, though its traversal mechanics are retained inside the recommendation for the erasure obligation.

**B — Suppression register with bounded derivation families and re-admission barrier (accepted).** Commit a durable suppression entry naming what is prohibited and for which uses. Record derivation family membership at creation. Erasure runs asynchronously against that family with its own receipts. Every path into usable state — retrieval, restore, import, reindex — consults the register first, against control state proven current per §12.1.

*Assessment:* Correctness does not depend on cleanup completeness, so partial cleanup degrades to "still prohibited, not yet erased" rather than to silent exposure. Survives restore by construction, since the register is itself restored and re-consulted. Honest about backups. Costs a small durable anti-resurrection metadata record while the prohibition remains in force, plus a mandatory check on every use path.

**C — Crypto-shredding.** Encrypt each erasable unit under its own key; forget by destroying the key. Ciphertext may remain anywhere, including old backups.

*Assessment:* The only model that makes existing immutable snapshots genuinely unreadable, which is a real advantage given the backup retention tail. But it requires a full key-management architecture, per-unit key granularity decisions, and key-custody design that does not exist and would constitute significant technology selection. It also does not by itself solve re-extraction from a still-present source, nor re-import. **DEFERRED under D2** — retained as a strong future architecture option, especially for reducing backup exposure in commercial deployments, layerable onto B under the same suppression semantics. It is not a prerequisite for B4, and no key-management technology is selected.

**D — Full erasure including audit and receipts.** Delete everything, including operation history.

*Assessment:* Maximal data minimization, but destroys the anti-resurrection evidence itself and the idempotency cutoff B3 §11.10 requires. Deleting the record that something was prohibited is precisely what enables resurrection. Rejected on correctness grounds, not merely on audit preference.

| Criterion | A: cascade delete | B: suppression register (accepted) | C: crypto-shred | D: full erasure |
|---|---|---|---|---|
| Anti-resurrection | Fails on restore, re-import and any missed edge | Durable prohibition independent of cleanup | Strong for backups; weak for re-extraction | Actively harmful — removes the evidence |
| Correctness under partial failure | Silent exposure | Degrades to prohibited-but-present | Depends on key destruction completeness | Unrecoverable |
| UX honesty | Overpromises "deleted" | Can state stop/erase/expire separately | Honest, but key story is hard to explain | Overpromises |
| Deletion latency | Bounded by slowest store | Non-use immediate; erasure asynchronous | Immediate on key destruction | Bounded by slowest store |
| Backup implications | Unsolved | Disclosed expiry + suppression on restore | Genuinely solved | Unsolved |
| Auditability | Poor — no record survives | Minimal non-sensitive record retained | Good | None |
| Data minimization | Good on payload, no prohibition record | Small durable metadata cost while the prohibition is in force | Good | Maximal |
| B1/B2/B3 fit | Conflicts with B3 §11.10 retention cutoff | Direct fit with B2 immediate ineligibility and B1 non-disclosing withdrawal | Compatible | Conflicts |
| Health/Finance readiness | Weak | Bounded per-domain retention | Strong | Unacceptable |
| Operational complexity | Medium | Medium | High | Low |
| Implementation complexity | Medium | Medium | High | Low |

**B is accepted.** Its decisive property is that safety does not depend on the success of the least reliable cleanup path, which is the exact failure mode the probes demonstrate is currently unguarded. **A** is retained as the internal erasure mechanism. **C** is deferred under D2 as a future layer for the backup boundary, should key management be separately designed. **D** is rejected.

## 5. The operations that should exist

These are distinct commands with distinct authority, effects and promises. They must not be collapsed into one "delete" verb in either the API or the UX.

| Operation | Meaning | Authority (composing B1) | Effect |
|---|---|---|---|
| **STOP USING** | Bar specified uses of an exact version. Content and history retained. | B1 Q(MANAGE) on target, or the B1 §8.3 narrow non-disclosing route for own assertion/subject | Suppression entry, use-scoped. No erasure. Reversible only by the restriction's legitimate authority per B3 §10. |
| **FORGET (durable Knowledge)** | Stop ordinary use of the assertion **and** schedule erasure of its payload and derived family. Source is untouched. | Q(MANAGE) plus the authorized removal process | Suppression entry + erasure obligation over the recorded family. Retains minimal anti-resurrection metadata. |
| **DELETE SOURCE** | Erase the original artifact and Episode payload. | Source-handling authority (B2 §8.2 custody), not Knowledge MANAGE | Source erasure + suppression of re-import by source identity. Derived assertions handled per §9. |
| **DELETE DERIVED ARTIFACTS** | Erase chunks, embeddings, summaries, indexes and caches for a target, retaining the assertion. | Q(MANAGE) on the parent | Family erasure + reindex prohibition until re-admitted. Typically an internal consequence, rarely user-facing. |
| **FORGET SUBJECT/TOPIC** | Prohibit a bounded described class about a subject, spanning independent lines. | The affected Person's own authority (B1 §8.3), or Q(MANAGE) across every affected object | Person-scoped suppression predicate. B1 §8.3 and B2 §181 already require Person-wide restrictions to span independent lineage. |
| **WITHDRAW ASSERTION** | Retract one's own contribution. | Proven assertor self-authority (B1 §8.3) | Suppression of that attributable contribution only. Never touches another person's independent assertion. |
| **REMOVE SHARED USE** | End Circle eligibility; retain personal scope. | Circle MANAGE, or subject objection | Scope-limited suppression. Not erasure. |
| **DELETE PARTITION / ACCOUNT** | Erase all content in one trusted partition. | Separately approved account-closure authority | Whole-partition erasure with a retained partition-level tombstone preventing restore re-admission. |

Two boundaries matter. **STOP USING is not weaker FORGET** — it is the correct answer when the user wants Olin to stop acting on something whose record other people or future audit legitimately need. And **FORGET is not DELETE SOURCE** — forgetting an extracted preference does not entitle the actor to destroy a medical document, which may have independent custody and other dependents.

## 6. What "Forget" promises to a consumer

The product promise must be stated in terms the user can verify, and must not imply reach Olin does not have.

**Immediately, on acknowledgement:**
- Olin stops using the content in answers, recommendations and assembled context.
- It stops appearing in retrieval candidates, including via summaries, chunks and embeddings derived from it.
- Regeneration and re-extraction of the same prohibited content are barred.
- In-flight work that would publish it is fenced (§13).

**Temporarily remaining, then removed:**
- Payload rows, derived artifacts, index and cache entries pending asynchronous cleanup. These are already unusable; their presence is a cleanup state, not an exposure.

**Retained deliberately, disclosed:**
- Minimal non-sensitive anti-resurrection metadata (§10).
- Minimal operation receipts within the B3 §11.10 retry cutoff.
- Existing backup snapshots until retention expiry, derived from the actual retained snapshot schedule (§12).

**Never promised:**
- Recall of anything already shown to a human.
- Retraction of an already exported or shared file.
- Alteration of another person's independent assertion.
- Provider-side deletion that Olin cannot verify (§6.1).

The corresponding user-facing language is deliberately plain: *"Olin has stopped using this. It is being removed from storage, and it will disappear from encrypted backups on the backup schedule. Anything already shared or shown cannot be taken back."* This is longer than "Deleted." It is the honest version, and the gap between them is exactly what this decision is about.

Per D1, the expiry statement should be derived from the actual retained snapshot schedule where the system can determine it, or described approximately where it cannot. No fixed duration is promised to the user as an architectural commitment.

### 6.1 External disclosure and provider-side deletion

Local Forget/Delete cannot **by itself** guarantee deletion of information previously sent to an external provider. This is a statement about the reach of a local command, not a claim that provider-side deletion is universally impossible.

What provider-side retention and deletion actually depend on:

- the approved provider and what its terms commit to
- contractual and data-retention terms in force
- configured retention controls
- provider deletion APIs or capabilities, where they exist

The accepted rule: **Olin must not promise provider-side deletion unless it can actually verify it.** Where a provider offers a verifiable deletion capability and it has been exercised, that may be stated. Where it does not, or where verification is unavailable, Olin states that the information was sent externally and that local use has stopped — without implying external erasure.

This becomes an input to the future LLM Routing / Provider Policy architecture, which should treat verifiable deletion capability as a provider-selection criterion rather than leaving it to per-request judgment. B4 does not select providers or routing policy.

Two things remain outside any architecture's reach and are stated plainly: content already displayed to a human, and files independently exported by a user, cannot be recalled.

## 7. Dependency model

**Bounded recorded derivation families, not a global graph and not reconstruction by scanning.**

At the moment any derivative is created, it records: its trusted partition, its direct inputs by exact version, its family root, its kind, and the classification revision it was built under. This is the B2 §C lineage obligation made operational for erasure — B2 already requires actual-influence lineage, so B4 adds the erasure-reachability requirement rather than a new concept.

| Link type | Erasure/suppression behavior |
|---|---|
| **Derivation** (actual influence: summary, chunk, embedding, index entry, cache) | Inherits suppression immediately; included in the erasure family. |
| **Attestation support** | Suppressing the attestation does not erase the assertion; if admission depended on it, the assertion becomes ineligible (B3 §10). |
| **Replacement** (`supersedes`) | **Not** a derivation edge per B3 §4. Forgetting a predecessor does not erase its successor unless the successor actually derived content from it. |
| **Corroboration / independent assertion** | Never in the family. Separate lineage per B2. Survives §9. |
| **History / receipt** | Not a derivative. Governed by §11 retention. |

Three properties make this tractable. Families are **bounded** — rooted at an admitted version or a source, not spanning the whole partition. They are **recorded at creation**, so nothing depends on later reconstruction from a scalar `source_episode_id` that cannot support it. And **unknown coverage fails closed**: B3 §11 already requires that if the dependency set cannot be safely determined, the affected bounded use path is denied pending reconciliation. B4 adopts that rule unchanged and makes it the response to any family-integrity gap.

A full graph database is not required. Neither is a graph traversal engine. What is required is that every derivative know its parents and its family root at creation time — which is a discipline, not a technology.

## 8. Anti-resurrection model

Resurrection is the primary threat. Each vector gets a specific barrier.

| Vector | Barrier |
|---|---|
| Stale index or cache entry | Family membership carries suppression; entries are ineligible before erasure completes. B2 §J already requires survival in storage not to imply retrieval eligibility. |
| Queued or running job | Commit-time and pre-publication barrier (§13). Jobs carry the control revision they started under and re-check before publishing. |
| Retry / replay | B3 §11.4–11.5 idempotency; a receipt is never authority and must not re-emit claim text. |
| **Restore from backup** | Restored state is not usable until reconciled against the current suppression register (§12). |
| **Re-import of a deleted source** | Source identity suppression. Probe P6 shows this is currently wide open. |
| **Re-extraction while source remains** | Suppression predicate consulted at admission, barring readmission of the prohibited proposition (§9). |
| Regenerated embedding | Regeneration is a creation event; it inherits the parent's suppression and is barred at creation. |
| Duplicate ingestion | B3 §11.6 capture-duplicate binding, extended to check suppression. |
| New ID with same content | B3 §10 already states a new ID never defeats non-use. B4 makes the check concrete at the admission barrier. |
| Independent assertion | **Deliberately not blocked** — see §9. |

The single architectural invariant underlying all of these:

```text
No path into usable state may bypass the suppression register.
Retrieval, restore, import, reindex and regeneration are all admission events.
```

This is what makes the model robust: there is exactly one checkpoint concept to get right, rather than N independent cleanup paths that must each be complete.

## 9. Independent assertions, and the source/claim asymmetry

**Independent assertions survive.** B2 establishes independent lineage as a first-class property, and B1 §8.3 forbids one person's withdrawal from erasing another's evidence. If a medical document says X and Ana separately asserted X herself, deleting the document removes the document-derived path; Ana's own assertion retains its own lineage, its own admission and its own authority. It is not a descendant and must not be collected into the erasure family.

The exception is already fixed by accepted architecture: a **Person-wide** restriction about that Person spans independent lines (B1 §8.3, B2 §181). Independent lineage is not immunity to a subject's own authority over information about themselves.

**When an assertion is forgotten but the source remains,** the suppression entry must bar re-extraction — otherwise the next extraction pass silently restores it. Suppression is therefore scoped to the *proposition and its uses within its partition*, not merely to a row ID. It should not be scoped so broadly that it becomes a permanent topic ban; B3 §9's D4 boundary discipline applies by analogy — materially equivalent content for overlapping applicability is barred, while a genuinely new proposition is evaluated on its own merits.

**When a source is deleted but a derived claim exists,** the default is that the derived claim is suppressed and erased with the family, because B2 §138 states that a source disappearing does not make its former derivative unrestricted, and unresolved dependencies deny pending B4 reconciliation. Three qualified exceptions, each requiring explicit authorization rather than inference:

- The claim is **independently supported** by a separate admitted lineage. Then it survives on that lineage alone — but the derived path is still severed, and the claim must not silently inherit continued life merely because a second source is asserted to exist.
- The claim is an **approved B2 projection** whose approval explicitly addressed source decoupling. B2 §8.2 already requires proof of no residual removed-Person or removed-domain disclosure.
- The user's intent was **source-only removal** ("delete the file, keep what I told you"), expressed explicitly.

Provenance may be retained without content: the fact that a claim derived from a now-erased source, with source identity reduced to an opaque partition-local reference and no title, author, locator or excerpt. This preserves the lineage integrity B2 requires without retaining the sensitive material B4 is meant to remove.

### 9.1 Deliberate reassertion after Forget

A suppression blocks *automatic* return: resurrection, re-extraction, stale restore, and materially equivalent re-admission for the covered use and applicability. It does not remove the legitimate authority's ability to deliberately choose to remember the information again.

The governing example. In 2026 the user says "Forget that I dislike canned tuna." Later they say "Remember again that I dislike canned tuna." The second command:

- **must not reactivate the erased version.** B3 §10 already forbids in-place resurrection of a terminal version, and probe P5 confirms the contract blocks `REVOKED → ACTIVE`. The erased payload stays erased; nothing is restored.
- **may create a new reviewed assertion and control decision**, provided all of: the actor holds current authority; save intent is explicit; B1, B2 and B3 requirements pass; and the prior suppression is **explicitly addressed by the legitimate authority** rather than bypassed.

The last condition carries the weight. The suppression is not silently ignored because new wording arrived — it is explicitly superseded by a new control decision made by an authority entitled to make it. B3 §10 already establishes that an applicable non-use decision cannot be bypassed by a new ID, import, alternate source, attestation or fresh wording, and that only the restriction's legitimate authority can resolve it. B4 adds that this authority genuinely exists and can be exercised deliberately.

The historical suppression decision may remain as minimal anti-resurrection metadata (§10) after being superseded, recording that a prohibition existed and was lifted. **Automatic import or re-extraction must never override it** — only an explicit, authorized, reviewed decision can.

This preserves the bounded-time-and-use principle already accepted in B3 §9's D4 clarification: a suppression must not become an accidental permanent ban on all future similar Knowledge. A materially different later fact, changed circumstances, a non-overlapping period, or a genuinely independent assertion each receive their own current evaluation rather than inheriting the old prohibition. Where equivalence or applicability is uncertain, the candidate's contested use is withheld pending review; uncertainty fails closed.

## 10. Minimum anti-resurrection state

Retaining sensitive content "for safety" is itself a privacy failure. The register entry is deliberately minimal and non-revealing.

**The technology-neutral requirement (C2).** The anti-resurrection state must contain **the minimum non-reconstructable information necessary to identify the prohibited object, source or use and to support bounded re-admission matching, without retaining the forgotten plaintext.** It must be:

- **non-reconstructable** — the forgotten content cannot be recovered from it
- **non-disclosing** — possessing an ID must not become a discovery oracle, matching B1 §8.3
- **partition-bound** — scoped to one trusted partition per B1
- **sufficient** for the approved re-admission policy
- **free of forgotten plaintext or embeddings**

**B4 selects no mechanism for this.** Possible future mechanisms include opaque source identities, policy keys, digests, classification metadata or trusted semantic review. Exact hashing in particular is *not* canonicalized: it cannot reliably identify semantically equivalent paraphrases, so committing to it here would both under-deliver on the matching requirement and prematurely select a mechanism. The matching breadth that the eventual mechanism must achieve is defined by §9.1 and D5, not by any particular representation.

**May be retained:**
- Trusted partition and suppression entry identity
- Target identities: exact version IDs, family root, source identity (opaque, partition-local)
- Anti-resurrection matching state meeting the requirement above
- Use scope, applicability interval, decision timestamp
- Decision kind (stop-using / forget / delete-source / partition-deletion)
- Erasure obligation state and cleanup receipts

**Must not be retained:**
- Claim statement text, source excerpts, titles, authors or locators
- Any embedding or reconstructable representation of the prohibited content
- Free-text reasons that restate the content — a real trap, since "forget that I have condition X" restates X
- Content of other subjects incidentally present in the original

### 10.1 Retention of the anti-resurrection state (D3)

Retention is deliberately differentiated rather than uniformly permanent:

| Element | Retention |
|---|---|
| Forgotten content itself | **Not retained.** |
| Embeddings, excerpts, titles, reconstructable forms | **Not retained.** |
| Anti-resurrection matching state | Retained **as long as required to enforce the prohibition** — which for an ongoing prohibition means the life of the partition, and for a superseded one (§9.1) may be shorter. |
| Actor identity, capacity and decision history | **Does not automatically require lifetime retention.** Minimized independently of the anti-resurrection key, on its own retention basis. |
| Partition tombstone | Minimal marker retained beyond payload deletion so old backups cannot resurrect a deleted partition (§15, Scenario L). |

The separation in the third and fourth rows is the substantive point: enforcing "this must not come back" requires a matching key, but it does not require remembering **who** asked or **when** for all time. Those are distinct retention questions with distinct justifications, and conflating them would retain more personal data than the anti-resurrection purpose needs.

It is therefore **not** asserted that every suppression record including full actor metadata is permanent for all time. The enforceable prohibition persists as long as it is in force; the surrounding audit metadata is minimized on its own schedule.

## 11. Logs, audit history and receipts

| Element | Disposition |
|---|---|
| Operation receipts | Retained only within B3 §11.10's maximum retry window, then removed with a trusted cutoff barring ancient replay. No sensitive payload retained for idempotency. |
| Lifecycle decision history | Retained: version IDs, actor, capacity, decision kind, timestamp, control revision. |
| Claim text in history | **Erased** with the family. B2 §315 already states a lineage record is not a license to retain deleted text forever. |
| Source names, titles, excerpts | Erased on source deletion; reduced to opaque reference. |
| Application/system logs | Must not contain Knowledge payloads. `SECURITY_AND_CONSENT.md` already forbids secrets in logs; B4 extends this to Knowledge content, and the absence of a Knowledge runtime makes this cheap to establish now rather than retrofit. |
| Suppression register | Differentiated retention per §10.1: matching state for as long as the prohibition is in force; actor/decision metadata minimized independently. |

The governing principle: **audit retains that a decision occurred, never what the content said** — and per D3, retaining *who* made it is a separate retention question from retaining the enforceable prohibition, decided on its own basis rather than defaulting to permanent.

## 12. Backup and restore semantics

This is where honesty matters most, and where the verified retention numbers do the work.

**Repository fact:** restic 0.18.1, daily timer, `keep 7d/4w/3m`, client-side encrypted, restore validated. Per D1 this is the accepted **current personal-deployment** policy, not a permanent commercial architecture requirement.

**What "deleted" means while snapshots exist.** Content is prohibited and removed from live stores, while remaining inside encrypted snapshots until the longest retained snapshot covering it expires. This is a real, disclosed gap.

**Backups are not rewritten.** Selectively editing restic snapshots is not proposed. It would be operationally fragile, would break snapshot integrity guarantees, and would scale as deletions × snapshots. More fundamentally it is unnecessary under model B, because suppression — not absence — is what prevents use.

### 12.1 The restore-freshness invariant (C1)

The naive version of "restore the register alongside the payload" is **not sufficient**, and this is the most important correction to the original proposal. If the only suppression state available is the one inside the same snapshot, it is exactly as stale as the payload it is supposed to govern:

```text
T1  backup taken, contains claim X
T2  user forgets X               ← suppression created AFTER the snapshot
T3  system lost
T4  restore T1
```

Reconciling T1 payload against a T1 register would find no prohibition on X, and X resurrects — a correct-looking restore that silently undoes a deletion. The accepted invariant:

```text
RESTORED DATA MUST NOT BECOME USABLE UNLESS THE SYSTEM CAN PROVE THAT THE
SUPPRESSION / DELETION CONTROL STATE USED FOR RECONCILIATION IS AT LEAST AS
CURRENT AS THE PAYLOAD BEING RESTORED.
```

**Unknown freshness fails closed.** The architecture therefore requires a **monotonic or otherwise current anti-resurrection authority, or an equivalent freshness proof** — control state that can be shown to be no older than the data it governs, and that can establish this positively rather than by assumption.

**B4 deliberately selects no mechanism.** Whether this is achieved by separately replicated control state, an append-only authority with a verifiable high-water mark, out-of-band control backup with independent retention, an external attestation of currency, or something else is **not decided here**. B5 (ownership of the authority), B6 (the pre-use barrier consulting it) and implementation determine it. What B4 fixes is the obligation and the failure mode, not the technology.

The corrected reconciliation sequence:

```text
restore snapshot
→ obtain suppression/deletion control state
→ PROVE that control state is at least as current as the restored payload
   └─ cannot prove it? → restored Knowledge stays UNUSABLE; do not admit
→ re-evaluate all restored Knowledge against that control state
→ re-apply suppression and re-queue erasure for anything prohibited since the snapshot
→ only then admit restored data as usable
```

A restore that cannot establish control-state currency must not bring Knowledge into usable state. Partial availability is acceptable — unaffected domains may return while Knowledge stays withheld — but usable Knowledge without a freshness proof is not. This implements B3 §13's requirement to "reconcile restored state before use," strengthened so that reconciliation cannot be satisfied by stale evidence.

**What can honestly be promised:** immediate non-use; live erasure on the cleanup schedule; backup expiry on the actual retained snapshot schedule; no resurrection through restore, including restores that predate the deletion. What cannot: immediate erasure from existing snapshots, absent the deferred crypto-shredding option (D2).

**Retention-policy implications.** Shortening retention shrinks the exposure tail but weakens recovery. D1 accepts the current personal-deployment policy and leaves commercial retention to a later commercialization decision. Legal and regulatory characterization is deferred under D6 and is not claimed either way here.

## 13. In-flight and queued work

| Situation | Semantics |
|---|---|
| Embedding or summarization job running | Job carries the control revision it started under; re-checks before publishing. Output is discarded, not published, if suppression intervened. |
| Workflow awaiting approval | Pending basis invalidated; approval cannot commit against a suppressed target (B3 §11.8 commit-time barrier). |
| Cache warming | Treated as derivative creation; barred at creation. |
| Import retrying | Re-checked against the register on each attempt, since retries are re-admission events. |
| ContextBundle already assembled | Suppression applies at the pre-disclosure barrier. Already-disclosed content cannot be recalled. Probe P2 shows there is no revalidation hook today — B6 must supply it. |
| Answer already generated and shown | Out of reach. Stated plainly, never implied otherwise. |

The ordering rule follows B3 §11.8 unchanged: if suppression is accepted before a commit, the commit is denied; if the commit ordered first, suppression bars all future covered use. Unknown ordering fails closed.

## 14. Completion states

Four distinct states, each independently observable, with no state implying the others:

| State | Meaning | When claimable |
|---|---|---|
| **SUPPRESSED** | Olin has stopped using this. | Immediately on commit. This is the promise the user actually cares about. |
| **ERASURE PENDING** | Payload and family removal in progress. | After suppression, before receipts complete. |
| **ERASED (live stores)** | Required stores have returned cleanup receipts. | Only with evidence from every required store. Partial coverage is not completion. |
| **BACKUP EXPIRY PENDING → EXPIRED** | Snapshot residency until retention boundary. | Disclosed from the actual retained snapshot schedule where determinable, otherwise approximately; expired when the boundary passes. |

Olin may say "I have stopped using this" immediately. It may say "deletion is complete" only when live-store erasure is evidenced **and** the user has been told about the backup tail. Workflow-step completion is never evidence of erasure — the existing gate illustration already warns about this, and it remains correct.

Per D7, ERASURE PENDING and BACKUP EXPIRY PENDING are internal states that **may** be surfaced when useful but need not become primary user actions. The primary user-facing operations are defined in §14.1.

### 14.1 User-facing operation semantics (D7)

Three distinct concepts are preserved in the product surface. They must not collapse into one "delete" verb.

| User-facing operation | Promise | Explicitly not promised |
|---|---|---|
| **STOP USING** | Immediate non-use. The record may remain. | No physical deletion promise of any kind. |
| **FORGET / DELETE MEMORY** | Immediate suppression; live payload and derivative cleanup; anti-resurrection state retained; backup tail disclosed. | Not erasure from existing snapshots; not recall of prior disclosure. |
| **DELETE SOURCE** | A separate operation, offered in the source/document context rather than the memory context. | Not implied by forgetting a memory derived from that source. |

Placing DELETE SOURCE in the document context rather than alongside FORGET is deliberate: it carries different authority (source custody, not Knowledge MANAGE per §5) and different blast radius, and presenting it as a variant of "forget" would invite users to destroy documents while intending to remove a preference.

## 15. Scenarios A–M

Accepted architecture outcomes and future acceptance specifications, not implemented tests. Every operation assumes complete current B1/B2 authority. Scenario M was added by the accepted C3 clarification.

| Case | Outcome |
|---|---|
| **A — Forget one preference** ("I dislike canned tuna" → "Forget that") | Suppression on the exact version, immediate. Erasure of the assertion and its family. Re-extraction barred by predicate. **Because the dislike is also persisted in the Nutrition profile as verified free text with no delete path, suppression must propagate to that owner or the promise is false.** B5 must assign the executor. |
| **B — Delete source, keep independent assertion** | Source and its derived family erased. Ana's independent assertion survives on its own lineage. It is not a family member. Unless a Person-wide restriction about Ana applies, which spans independent lines. |
| **C — Source with only derived Knowledge** (source → summary → claim → embedding) | Entire family suppressed and erased: summary, claim, embedding, index entries. Opaque provenance stub may remain, with no title, author, locator or excerpt. |
| **D — Forget claim, source remains** | Claim suppressed and erased. Source untouched. Suppression predicate bars re-extraction of the same proposition — the case the current contracts fail outright per probe P6. |
| **E — Re-import attack** | Import is an admission event. Source identity suppression blocks re-entry; content predicate catches a renamed re-upload. A materially new proposition from a legitimately re-supplied source is evaluated on its own merits, per the D4 boundary discipline. |
| **F — Stale queued job** | Job re-checks control revision before publishing; output discarded. No partial publication. |
| **G — Cache/index resurrection** | Family membership makes entries ineligible immediately, before physical removal. Survival in storage never implies eligibility (B2 §J). |
| **H — Backup restore** | Restored data is not usable until reconciled **against control state proven at least as current as the restored payload** (§12.1). The T1-backup / T2-forget / T4-restore case must not resurrect X: a T1-era register is not acceptable evidence for T1 payload, because it predates the T2 deletion. Prohibited content is re-suppressed and re-queued for erasure. **Unknown control-state freshness fails closed — restored Knowledge stays unusable**, even if the restore itself succeeded. |
| **I — Shared Circle assertion** (Erick asserted a shared routine; Ana requests removal of information about herself) | Ana's subject authority suppresses uses revealing her, via the B1 §8.3 non-disclosing route. Erick's assertion is not rewritten and not deleted. If the statement is inseparable, the whole claim is suppressed for the covered use rather than silently redacted — B1 §248 already forbids removing the subject label while retaining revealing text. |
| **J — Independent multiple assertions** | Deleting one leaves the other intact, with separate lineage. No content-similarity merging (B3 §11.6). A Person-wide restriction would still span both. |
| **K — Already disclosed answer** | Local non-use and erasure proceed. Content already displayed to a human is not recalled. For an external model provider, Olin states that the information was sent and that local use has stopped; it claims provider-side deletion **only** where the provider offers a verifiable capability that has been exercised (§6.1). No false promise in either direction. |
| **L — Whole-partition deletion** | All partition content erased; a **minimal partition tombstone** is retained beyond payload deletion so an old snapshot cannot resurrect the deleted partition (§10.1). That tombstone is itself subject to §12.1: restoring a pre-deletion snapshot must prove control-state currency, or the restored partition stays unusable. Completion evidenced per §14 with the backup tail disclosed. Commercial account-closure terms are a separate commercialization decision. |
| **M — Deliberate reassertion after Forget** | "Forget that I dislike canned tuna," later "Remember again that I dislike canned tuna." The erased version is **not** reactivated. A new reviewed assertion may be admitted when the actor has current authority, save intent is explicit, B1/B2/B3 pass, and the prior suppression is explicitly addressed by the legitimate authority. Automatic import or re-extraction can never achieve this (§9.1). |

## 16. Product Architect disposition

Decision owner: Product Architect

Decision date: 2026-09-21

Disposition: ACCEPTED WITH CLARIFICATIONS — B4 RESOLVED

The core model is accepted: durable suppression as authoritative non-use state; physical erasure separate from suppression; bounded recorded derivation families; a mandatory re-admission/use barrier; immediate non-use before asynchronous cleanup; independent lineage surviving source-specific deletion; no resurrection through stale jobs, indexes, caches or restores; honest backup-tail semantics; and orchestration — Flowable included — never being canonical Knowledge truth.

| Decision | Disposition | Accepted meaning |
|---|---|---|
| **D1 — Backup retention** | ACCEPT WITH SCOPE CLARIFICATION | The current personal-deployment policy `restic keep 7 daily / 4 weekly / 3 monthly` is accepted. It is **not** a permanent commercial architecture requirement, and no fixed duration such as "90 days" is promised. User-facing expiry is derived from the actual retained snapshot schedule where possible, or described approximately. Commercial retention is a later commercialization decision. |
| **D2 — Crypto-shredding** | DEFER | Retained as a strong future architecture option, especially for reducing backup exposure in commercial deployments. **Not** a prerequisite for B4 resolution. No key-management technology is selected. |
| **D3 — Suppression / anti-resurrection retention** | ACCEPT WITH CLARIFICATION | Minimal durable anti-resurrection metadata accepted. Forgotten content, embeddings, excerpts, titles and reconstructable forms are not retained. Anti-resurrection control state persists as long as required to enforce the prohibition. Audit identity and capacity metadata do **not** automatically require lifetime retention and are minimized independently of the anti-resurrection key. Whole-partition deletion may require a minimal partition tombstone beyond payload deletion. It is not asserted that every suppression record including full actor metadata is permanent for all time. §10.1 is authoritative. |
| **D4 — Source deletion default** | ACCEPT | Source-derived assertions and artifacts depending only on the deleted source are suppressed and erased with that dependency family. They survive only through independently admitted lineage, an approved B2 projection that already established source decoupling, or explicit authorized source-only deletion semantics where retained Knowledge has a valid independent basis. Deleting a source must never weaken restrictions. |
| **D5 — Re-admission breadth** | ACCEPT WITH CLARIFICATION | Block automatic and materially equivalent resurrection for the covered proposition, use and applicability/context. Do **not** create a permanent global topic ban. Later materially different facts, changed circumstances, non-overlapping periods and genuinely independent assertions receive their own evaluation. Explicit legitimate reassertion may address and supersede the suppression through a new reviewed control decision. Uncertainty fails closed or requires review. §9.1 is authoritative. |
| **D6 — Legal characterization** | DEFER | B4 defines technical and product semantics only. No claim of GDPR or right-to-erasure compliance **or** non-compliance is made. Legal and regulatory characterization requires separate counsel and commercialization policy. |
| **D7 — User-facing vocabulary** | ACCEPT | Distinct concepts preserved for STOP USING, FORGET / DELETE MEMORY and DELETE SOURCE, with the promises in §14.1. Internal states such as ERASURE PENDING and BACKUP EXPIRY PENDING may be shown when useful but need not become primary user actions. |

Four clarifications recorded in §1.1 are part of this acceptance: restore freshness is load-bearing (C1, §12.1); hashing is not canonicalized (C2, §10); Forget is not a permanent topic ban (C3, §9.1); and external-provider deletion is conditional rather than categorically impossible (C4, §6.1).

Scenarios A–M and the clarification boundary cases are accepted architecture outcomes and future acceptance specifications, not implemented enforcement. B1, B2 and B3 remain unchanged and RESOLVED. B5–B6 and the Knowledge Technology Gate remain OPEN. This disposition authorizes no contracts, schemas, database, suppression registry, deletion executor, key management, crypto-shredding, Flowable process, backup change, runtime, technology selection, deployment or production change, and does not resolve B5 or B6.

## 17. Boundaries for B5 and B6

**B4 requires from B5 (ownership):**
- One accountable command boundary owning suppression commit and the register.
- **Ownership of the anti-resurrection authority and its freshness proof (C1)** — who holds the monotonic or current control state, and how its currency is established relative to restored payload. B4 fixes the obligation; B5 assigns the owner.
- A named executor for cross-owner suppression propagation — **required by Scenario A**, since Nutrition holds preference text with no delete path, verified.
- Custody authority for source erasure, distinct from Knowledge MANAGE.
- A partition-bound, non-disclosing cleanup mandate, which B1 §109 already requires be separately approved.
- Retention ownership for the differentiated elements in §10.1, since matching state and actor metadata expire on different bases.

**B4 requires from B6 (retrieval):**
- Suppression check before sensitive candidate selection **and** again before disclosure.
- A revalidation hook on assembled context — probe P2 verified none exists.
- Family-aware index and cache invalidation.
- Restore reconciliation before restored Knowledge enters retrieval, **including the §12.1 freshness proof**; an unproven control state must leave Knowledge unusable rather than merely stale.
- A concrete re-admission matching mechanism meeting §10's non-reconstructable requirement at the breadth D5 defines — B4 selects none.

**On orchestration:** cleanup is a multi-store, retryable, receipt-collecting obligation that may legitimately span days, which is a real long-running-process shape. But it is **not** canonical Knowledge truth. Suppression must commit synchronously in the domain and must never wait on an orchestrator. If orchestration is later adopted for cleanup, the register remains authoritative and the orchestrator holds opaque IDs only. **No orchestration technology is selected here, and Flowable is not selected.**

## 18. Verification

Only this accepted decision and the B4 gate entry change. B1/B2/B3 decisions, canonical architecture, ADRs, contracts and runtime are untouched.

```json
{
  "task": "knowledge_b4_architecture_decision",
  "baseline_main_sha": "43ea2935c03c65741fd625f844a4be79a6b2e9f2",
  "pr_25": "MERGED",
  "baseline_worktree_clean": true,
  "accepted_model": "durable suppression register with bounded derivation families and pre-use re-admission barrier",
  "restore_freshness_invariant": "control state must be provably at least as current as restored payload; unknown freshness fails closed",
  "anti_resurrection_state": "minimum non-reconstructable, non-disclosing, partition-bound matching information; no mechanism selected",
  "existing_contract_tests_passed": 12,
  "probes": "in-memory only; no repository files written",
  "scenarios": "A-M: accepted architecture outcomes, not implemented tests",
  "b1": "RESOLVED",
  "b2": "RESOLVED",
  "b3": "RESOLVED",
  "b4": "RESOLVED — PRODUCT ARCHITECT DECISION, 2026-09-21",
  "b5_b6": "OPEN",
  "knowledge_technology_gate": "OPEN",
  "technology_selected": false,
  "flowable_selected": false,
  "crypto_shredding_selected": false,
  "key_management_selected": false,
  "contracts_or_schemas_changed": false,
  "knowledge_runtime_implemented": false,
  "suppression_registry_implemented": false,
  "deletion_executor_implemented": false,
  "backup_changed": false,
  "production_changed": false
}
```

Verify the docs-only change:

```powershell
git diff --check origin/main...HEAD
git diff --name-only origin/main...HEAD
git status --short --branch
```

Expected changed paths: `docs/architecture/proposals/KNOWLEDGE_B4_FORGET_DELETE.md` and `docs/architecture/proposals/KNOWLEDGE_TECHNOLOGY_GATE.md`.

Reproduce the baseline contract check without writing cache files:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'packages/home-contracts/src')
$env:PYTHONDONTWRITEBYTECODE = '1'
python -m pytest packages/home-contracts/tests -q -p no:cacheprovider
```

Passing these verifies the inspected baseline only, not enforcement of this decision.

**B1–B4 RESOLVED BY PRODUCT ARCHITECT DECISION**

**B5–B6 REMAIN OPEN**

**KNOWLEDGE TECHNOLOGY GATE REMAINS OPEN**

**NO TECHNOLOGY SELECTED**

**NO KNOWLEDGE RUNTIME IMPLEMENTED**

**NO PRODUCTION CHANGE**
