# Knowledge B4 — Dependency, Forget, Delete, retention, and resurrection safety

Status: PROPOSED — AWAITING PRODUCT ARCHITECT DECISION

Date: 2026-09-21

Repository: `EKvargas/episteck_home`

Main baseline: `43ea2935c03c65741fd625f844a4be79a6b2e9f2`, verified current `origin/main` after [PR #25](https://github.com/EKvargas/episteck_home/pull/25) merged and made accepted B3 authoritative on `main`.

Branch: `docs/knowledge-b4-forget-delete`

Gate: [B4 — Dependency / Forget / Delete](KNOWLEDGE_TECHNOLOGY_GATE.md#b4--dependency--forget--delete)

This is an independent architecture investigation. It changes no contract, schema, service, runtime, index, deployment or production system, and selects no storage, retrieval, orchestration or cleanup technology. B1–B3 remain RESOLVED and unamended. B4 is PROPOSED only; B5–B6 and the Knowledge Technology Gate remain OPEN. All scenarios are synthetic.

## 1. Summary of the proposed decision

Adopt **a durable suppression register as the authoritative non-use fact, separated from physical erasure, with bounded recorded derivation families and a mandatory pre-use admission barrier on restore and re-import.**

Four separable commitments:

1. **Non-use is a durable positive record, not the absence of data.** "Forget" commits a suppression entry that survives restore, re-import, reindexing and cleanup failure. Deleting rows is never the mechanism that makes information stop being used.
2. **Erasure is a separate, asynchronous, evidenced obligation** over a bounded derivation family recorded at creation time. It has its own completion state and its own honest latency.
3. **Nothing re-enters usable state without passing admission again.** Restore, import and reindex are re-admission events evaluated against the current suppression register, not trusted resumptions of previous state.
4. **Backups are an expiry commitment, not a deletion commitment.** Existing snapshots are not rewritten; suppression is what makes restored data unusable, and the retention tail is disclosed to the user.

The essential inversion: a deletion architecture that relies on removing data is only as correct as its least reliable cleanup path. One that relies on a durable record of prohibition stays correct even when cleanup is incomplete, delayed, or replayed from an old snapshot.

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
| **Backups: restic 0.18.1 → Hetzner Storage Box, daily timer, `keep 7d/4w/3m`, client-side encrypted, restore validated.** | [`DEPLOYMENT.md`](../DEPLOYMENT.md) | Worst-case residency of deleted content in snapshots is roughly 90+ days. Snapshots are immutable and encrypted. Honest completion semantics must disclose this tail rather than claim immediate erasure. |
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

**B — Suppression register with bounded derivation families and re-admission barrier (recommended).** Commit a durable suppression entry naming what is prohibited and for which uses. Record derivation family membership at creation. Erasure runs asynchronously against that family with its own receipts. Every path into usable state — retrieval, restore, import, reindex — consults the register first.

*Assessment:* Correctness does not depend on cleanup completeness, so partial cleanup degrades to "still prohibited, not yet erased" rather than to silent exposure. Survives restore by construction, since the register is itself restored and re-consulted. Honest about backups. Costs a permanent small metadata record per suppression and a mandatory check on every use path.

**C — Crypto-shredding.** Encrypt each erasable unit under its own key; forget by destroying the key. Ciphertext may remain anywhere, including old backups.

*Assessment:* The only model that makes existing immutable snapshots genuinely unreadable, which is a real advantage given the 90-day restic tail. But it requires a full key-management architecture, per-unit key granularity decisions, and key-custody design that does not exist and would constitute significant technology selection. It also does not by itself solve re-extraction from a still-present source, nor re-import. Not selected now, but explicitly preserved as the recommended future strengthening of the backup boundary, layerable onto B under the same suppression semantics.

**D — Full erasure including audit and receipts.** Delete everything, including operation history.

*Assessment:* Maximal data minimization, but destroys the anti-resurrection evidence itself and the idempotency cutoff B3 §11.10 requires. Deleting the record that something was prohibited is precisely what enables resurrection. Rejected on correctness grounds, not merely on audit preference.

| Criterion | A: cascade delete | B: suppression register (recommended) | C: crypto-shred | D: full erasure |
|---|---|---|---|---|
| Anti-resurrection | Fails on restore, re-import and any missed edge | Durable prohibition independent of cleanup | Strong for backups; weak for re-extraction | Actively harmful — removes the evidence |
| Correctness under partial failure | Silent exposure | Degrades to prohibited-but-present | Depends on key destruction completeness | Unrecoverable |
| UX honesty | Overpromises "deleted" | Can state stop/erase/expire separately | Honest, but key story is hard to explain | Overpromises |
| Deletion latency | Bounded by slowest store | Non-use immediate; erasure asynchronous | Immediate on key destruction | Bounded by slowest store |
| Backup implications | Unsolved | Disclosed expiry + suppression on restore | Genuinely solved | Unsolved |
| Auditability | Poor — no record survives | Minimal non-sensitive record retained | Good | None |
| Data minimization | Good on payload, no prohibition record | Small permanent metadata cost | Good | Maximal |
| B1/B2/B3 fit | Conflicts with B3 §11.10 retention cutoff | Direct fit with B2 immediate ineligibility and B1 non-disclosing withdrawal | Compatible | Conflicts |
| Health/Finance readiness | Weak | Bounded per-domain retention | Strong | Unacceptable |
| Operational complexity | Medium | Medium | High | Low |
| Implementation complexity | Medium | Medium | High | Low |

Choose **B**. Its decisive property is that safety does not depend on the success of the least reliable cleanup path, which is the exact failure mode the probes demonstrate is currently unguarded. **A** is retained as the internal erasure mechanism. **C** is the recommended future layer for the backup boundary once key management is separately designed. **D** is rejected.

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
- Existing backup snapshots until retention expiry — roughly 90 days at current `keep 7d/4w/3m`.

**Never promised:**
- Recall of anything already shown to a human.
- Deletion from an external model provider's systems.
- Retraction of an already exported or shared file.
- Alteration of another person's independent assertion.

The corresponding user-facing language is deliberately plain: *"Olin has stopped using this. It is being removed from storage, and it will disappear from encrypted backups within about three months. Anything already shared or shown cannot be taken back."* This is longer than "Deleted." It is the honest version, and the gap between them is exactly what this decision is about.

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

## 10. Minimum anti-resurrection state

Retaining sensitive content "for safety" is itself a privacy failure. The register entry is deliberately minimal and non-revealing.

**May be retained:**
- Trusted partition and suppression entry identity
- Target identities: exact version IDs, family root, source identity (opaque, partition-local)
- Suppression predicate covering re-admission — expressed as salted one-way digests over normalized propositions, never recoverable plaintext
- Use scope, applicability interval, decision timestamp
- Deciding actor and capacity, and the control revision
- Decision kind (stop-using / forget / delete-source / partition-deletion)
- Erasure obligation state and cleanup receipts

**Must not be retained:**
- Claim statement text, source excerpts, titles, authors or locators
- Any embedding or reconstructable representation of the prohibited content
- Free-text reasons that restate the content — which is a real trap, since "forget that I have condition X" restates X
- Content of other subjects incidentally present in the original

Two derived requirements follow. The register entry must be **non-disclosing**: possessing an ID must not become a discovery oracle, matching B1 §8.3's existing rule. And the digest approach is a *semantic* statement of intent, not a technology choice — the requirement is "sufficient to recognize re-admission of the same proposition, insufficient to reconstruct it," and the concrete mechanism belongs to implementation.

Register entries are retained for the life of the partition, because their whole purpose is to outlive the data. This is a genuine, disclosed data-minimization trade: a small permanent metadata record is the price of a durable prohibition.

## 11. Logs, audit history and receipts

| Element | Disposition |
|---|---|
| Operation receipts | Retained only within B3 §11.10's maximum retry window, then removed with a trusted cutoff barring ancient replay. No sensitive payload retained for idempotency. |
| Lifecycle decision history | Retained: version IDs, actor, capacity, decision kind, timestamp, control revision. |
| Claim text in history | **Erased** with the family. B2 §315 already states a lineage record is not a license to retain deleted text forever. |
| Source names, titles, excerpts | Erased on source deletion; reduced to opaque reference. |
| Application/system logs | Must not contain Knowledge payloads. `SECURITY_AND_CONSENT.md` already forbids secrets in logs; B4 extends this to Knowledge content, and the absence of a Knowledge runtime makes this cheap to establish now rather than retrofit. |
| Suppression register | Retained for partition life (§10). |

The governing principle: **audit retains that a decision occurred and who made it, never what the content said.**

## 12. Backup and restore semantics

This is where honesty matters most, and where the verified retention numbers do the work.

**Repository fact:** restic 0.18.1, daily timer, `keep 7d/4w/3m`, client-side encrypted, restore validated.

**What "deleted" means while snapshots exist.** Content is prohibited and removed from live stores, while remaining inside encrypted snapshots until retention expiry. This is a real, disclosed gap of roughly 90+ days at current policy.

**Backups are not rewritten.** Selectively editing restic snapshots is not proposed. It would be operationally fragile, would break snapshot integrity guarantees, and would scale as deletions × snapshots. More fundamentally it is unnecessary under model B, because suppression — not absence — is what prevents use.

**Restore must reconcile before data becomes usable.** This is the load-bearing requirement:

```text
restore snapshot
→ restore or reconstruct the suppression register (register is itself backed up)
→ if the register is older than the restored data, treat the gap as unknown and fail closed
→ re-evaluate all restored Knowledge against the current register
→ re-apply suppression and re-queue erasure for anything prohibited since the snapshot
→ only then admit restored data as usable
```

A restore that cannot establish register currency must not bring Knowledge into usable state. This directly implements B3 §13's requirement to "reconcile restored state before use." Because the register is part of the backup set and outlives payloads, a restored snapshot carries its own prohibitions forward.

**What can honestly be promised:** immediate non-use; live erasure on the cleanup schedule; backup expiry on the disclosed retention schedule; no resurrection through restore. What cannot: immediate erasure from existing snapshots, absent the future crypto-shredding layer (Alternative C), which remains the recommended path to strengthen precisely this boundary.

**Retention-policy implications.** Shortening retention shrinks the exposure tail but weakens recovery. This is a genuine Product Architect trade (§16), not a technical conclusion. Legal and regulatory characterization — whether this satisfies any particular erasure obligation — is explicitly flagged as a policy decision outside this technical proposal.

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
| **BACKUP EXPIRY PENDING → EXPIRED** | Snapshot residency until retention boundary. | Disclosed with an approximate date; expired when the boundary passes. |

Olin may say "I have stopped using this" immediately. It may say "deletion is complete" only when live-store erasure is evidenced **and** the user has been told about the backup tail. Workflow-step completion is never evidence of erasure — the existing gate illustration already warns about this, and it remains correct.

## 15. Scenarios A–L

Accepted-outcome specifications, not implemented tests. Every operation assumes complete current B1/B2 authority.

| Case | Outcome |
|---|---|
| **A — Forget one preference** ("I dislike canned tuna" → "Forget that") | Suppression on the exact version, immediate. Erasure of the assertion and its family. Re-extraction barred by predicate. **Because the dislike is also persisted in the Nutrition profile as verified free text with no delete path, suppression must propagate to that owner or the promise is false.** B5 must assign the executor. |
| **B — Delete source, keep independent assertion** | Source and its derived family erased. Ana's independent assertion survives on its own lineage. It is not a family member. Unless a Person-wide restriction about Ana applies, which spans independent lines. |
| **C — Source with only derived Knowledge** (source → summary → claim → embedding) | Entire family suppressed and erased: summary, claim, embedding, index entries. Opaque provenance stub may remain, with no title, author, locator or excerpt. |
| **D — Forget claim, source remains** | Claim suppressed and erased. Source untouched. Suppression predicate bars re-extraction of the same proposition — the case the current contracts fail outright per probe P6. |
| **E — Re-import attack** | Import is an admission event. Source identity suppression blocks re-entry; content predicate catches a renamed re-upload. A materially new proposition from a legitimately re-supplied source is evaluated on its own merits, per the D4 boundary discipline. |
| **F — Stale queued job** | Job re-checks control revision before publishing; output discarded. No partial publication. |
| **G — Cache/index resurrection** | Family membership makes entries ineligible immediately, before physical removal. Survival in storage never implies eligibility (B2 §J). |
| **H — Backup restore** | Restored data is not usable until reconciled. Register re-applied; prohibited content re-suppressed and re-queued for erasure. Unknown register currency fails closed. |
| **I — Shared Circle assertion** (Erick asserted a shared routine; Ana requests removal of information about herself) | Ana's subject authority suppresses uses revealing her, via the B1 §8.3 non-disclosing route. Erick's assertion is not rewritten and not deleted. If the statement is inseparable, the whole claim is suppressed for the covered use rather than silently redacted — B1 §248 already forbids removing the subject label while retaining revealing text. |
| **J — Independent multiple assertions** | Deleting one leaves the other intact, with separate lineage. No content-similarity merging (B3 §11.6). A Person-wide restriction would still span both. |
| **K — Already disclosed answer** | Local non-use and erasure proceed. Prior disclosure to a human or external model is **not** recalled, and Olin says so. No false promise. |
| **L — Whole-partition deletion** | All partition content erased; partition-level tombstone retained to prevent restore re-admission. Completion evidenced per §14, with the backup tail disclosed. Commercial account-closure terms are a separate policy decision. |

## 16. Product Architect decisions required

These are genuine choices that evidence does not settle:

1. **Backup retention versus exposure tail.** Keep `7d/4w/3m` (~90-day tail, stronger recovery), or shorten it. Trade-off, not a technical conclusion.
2. **Crypto-shredding adoption and timing.** Accept the disclosed backup tail now, or commission the key-management design that would close it. Recommended as a later layer, not now.
3. **Suppression register permanence.** Confirm that a small permanent non-sensitive metadata record per suppression is an acceptable price for durable anti-resurrection.
4. **Default on source deletion with derived claims.** This proposal recommends suppress-and-erase by default. Confirm, or choose a prompt-the-user default.
5. **Re-admission predicate breadth.** How aggressively should a suppressed proposition block similar future content? Recommended conservative, following B3 §9's D4 discipline against permanent topic bans.
6. **Legal characterization.** Whether these technical semantics satisfy any specific regulatory erasure obligation is deliberately unanswered here and needs separate counsel.
7. **User-facing vocabulary.** Whether the product exposes "stop using" and "delete" as distinct user actions, or presents one action with an explained outcome.

## 17. Boundaries for B5 and B6

**B4 requires from B5 (ownership):**
- One accountable command boundary owning suppression commit and the register.
- A named executor for cross-owner suppression propagation — **required by Scenario A**, since Nutrition holds preference text with no delete path, verified.
- Custody authority for source erasure, distinct from Knowledge MANAGE.
- A partition-bound, non-disclosing cleanup mandate, which B1 §109 already requires be separately approved.

**B4 requires from B6 (retrieval):**
- Suppression check before sensitive candidate selection **and** again before disclosure.
- A revalidation hook on assembled context — probe P2 verified none exists.
- Family-aware index and cache invalidation.
- Restore reconciliation before restored Knowledge enters retrieval.

**On orchestration:** cleanup is a multi-store, retryable, receipt-collecting obligation that may legitimately span days, which is a real long-running-process shape. But it is **not** canonical Knowledge truth. Suppression must commit synchronously in the domain and must never wait on an orchestrator. If orchestration is later adopted for cleanup, the register remains authoritative and the orchestrator holds opaque IDs only. **No orchestration technology is selected here, and Flowable is not selected.**

## 18. Verification

Only this proposal and the B4 gate entry change. B1/B2/B3 decisions, canonical architecture, ADRs, contracts and runtime are untouched.

```json
{
  "task": "knowledge_b4_architecture_investigation",
  "baseline_main_sha": "43ea2935c03c65741fd625f844a4be79a6b2e9f2",
  "pr_25": "MERGED",
  "baseline_worktree_clean": true,
  "recommended_model": "durable suppression register with bounded derivation families and pre-use re-admission barrier",
  "existing_contract_tests_passed": 12,
  "probes": "in-memory only; no repository files written",
  "scenarios": "A-L: proposed architecture outcomes, not implemented tests",
  "b1": "RESOLVED",
  "b2": "RESOLVED",
  "b3": "RESOLVED",
  "b4": "PROPOSED — AWAITING PRODUCT ARCHITECT DECISION",
  "b5_b6": "OPEN",
  "knowledge_technology_gate": "OPEN",
  "technology_selected": false,
  "flowable_selected": false,
  "contracts_or_schemas_changed": false,
  "knowledge_runtime_implemented": false,
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

Passing these verifies the inspected baseline only, not enforcement of this proposal.

**B4 PROPOSED — NOT RESOLVED**

**B1–B3 REMAIN RESOLVED**

**B5–B6 REMAIN OPEN**

**KNOWLEDGE TECHNOLOGY GATE REMAINS OPEN**

**NO TECHNOLOGY SELECTED**

**NO KNOWLEDGE RUNTIME IMPLEMENTED**

**NO PRODUCTION CHANGE**
