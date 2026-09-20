# Knowledge B2 — Sensitivity inheritance

Status: PROPOSED — AWAITING PRODUCT ARCHITECT DECISION

Date: 2026-09-20

Repository: `EKvargas/episteck_home`

Main baseline: `cf34771e6770acc4c91bbd46475f24917a7365fc` — current fetched `origin/main`, the merge commit of [PR #20](https://github.com/EKvargas/episteck_home/pull/20).

Branch: `docs/knowledge-b2-sensitivity`

Decision owner: Product Architect

Disposition: NOT DECIDED. Merging this proposal would not accept it or resolve B2.

Gate: [B2 — Sensitivity inheritance](KNOWLEDGE_TECHNOLOGY_GATE.md#b2--sensitivity-inheritance)

## 1. Recommendation and authority

Adopt **conjunctive access requirements on each information artifact, with explicit derivation lineage and separately approved projections**. A transformation inherits the requirements of everything that influenced it. It may add protection, never remove protection. A new independent assertion has its own lineage; similar wording does not merge permissions. An approved projection is a separate, version-bound output whose narrower requirements have been explicitly justified and authorized.

Preserve [accepted B1](KNOWLEDGE_B1_SECURITY_SCOPE.md) in full: one trusted partition per object and derivative; trusted actor; PERSON/CIRCLE resources only; scope AND every Person subject AND every required content domain; Home as the sole grant/operation-policy authority; preauthorized candidates. No B1 contradiction was found that makes B2 impossible. B1 expressly leaves source disclosure and approved projections to B2. This proposal does not introduce sparse subject/domain checks as an ordinary shortcut to B1's conservative intersection.

The problem is information flow, not naming. A HEALTH statement does not become less protected when its representation changes from document to text, summary, claim, vector or answer. At the same time, an unrelated private document must not contaminate an independently asserted preference forever merely because the text matches.

All examples are synthetic. Requirements below are proposed architecture, **not behavior implemented by today's contracts**. B3–B6 remain OPEN. No storage, retrieval, parsing, workflow or model technology is selected; no schema, contract, runtime or production change is authorized.

## 2. Repository evidence that affects the design

The investigation started with a fetch and verification that PR #20 was merged. The existing detached checkout had untracked `apps/home-hub/` and `docs/ref/`; it was preserved. A fresh worktree on the requested branch had empty porcelain status and HEAD equal to the baseline above before editing.

Read together: [KNOWLEDGE](../KNOWLEDGE.md), [SECURITY_AND_CONSENT](../SECURITY_AND_CONSENT.md), [DATA_OWNERSHIP](../DATA_OWNERSHIP.md), [ARCHITECTURE](../ARCHITECTURE.md), the [technology gate](KNOWLEDGE_TECHNOLOGY_GATE.md), accepted B1 and the [independent review](../reviews/2026-09-19-knowledge-independent-architecture-review.md). Relevant accepted decisions are [ADR-0001](../adr/0001-home-control-plane-is-frappe.md), [0002](../adr/0002-independent-domain-services.md), [0004](../adr/0004-svc-nutrition-source-of-truth.md), [0006](../adr/0006-family-care-graph.md), [0007](../adr/0007-knowledge-architecture.md), [0008](../adr/0008-consent-fail-closed.md) and [0009](../adr/0009-trusted-actor-binding.md).

| Repository fact at the baseline | Design consequence |
|---|---|
| [KnowledgeClaim](../../../packages/home-contracts/src/episteck_home_contracts/knowledge.py) has one `domain: str`, one `source_episode_id`, subjects, scope and one provenance enum. Domain is only checked for nonemptiness there. No partition, compound requirements, source versions or derivation set exists. | One field cannot preserve mixed-domain or multi-input restrictions. This is an architectural gap in contracts, not an observed production Knowledge leak: there is no Knowledge runtime. |
| `KnowledgeEpisode` carries ID, free-form episode type, capture time and `source_ref`. It is not a document authority or evidence-span registry. | Distinguish capture event, original, evidence location and derived output conceptually before later contract work. |
| [ContextBundle](../../../packages/home-contracts/src/episteck_home_contracts/context.py) checks KNOWLEDGE plus the claim's one domain for each subject. It does not check Circle scope, source permissions, authorization issuer/freshness, or lifecycle eligibility. `AuthorizedDomain` is caller-constructed. | Retain it as composition/consistency checking, never treat it as a trusted permission or inheritance engine. Accepted B1 already governs future scope checks. |
| `DocumentEvidence` has one subject/domain, a source ID and excerpt; no source version or page/span. `SourceReference` has identity/type/reference/provenance but no authorization checks. `StructuredDomainReference` identifies an owning service and record. [Tests](../../../packages/home-contracts/tests/test_context.py) exercise these limited contracts. | Every excerpt and provenance disclosure needs its own complete requirements. A pointer is neither permission nor proof that only an authorized passage was used. Canonical references must remain independently gated. |
| Searches of production code under `apps/`, `packages/` and `services/` found no implemented Documents service or durable source-sensitivity/approved-projection abstraction beyond these contracts. Nutrition source/provenance labels describe origin or calculation authority. | Do not present source custody, span authorization or release records as already implemented; provenance labels are not access controls. |
| [Consent Grant schema](../../../apps/episteck_home/episteck_home/episteck_home/doctype/consent_grant/consent_grant.json) targets Person only and one domain. [Policy](../../../apps/episteck_home/episteck_home/policy/access.py) uses eight domains and VIEW/CREATE/UPDATE/MANAGE. Self-access covers own Person; MANAGE implies other actions only in that domain. Matching grants are alternatives inside one tuple. | Keep AND between required tuples and Home authority. B1's bounded PERSON/CIRCLE direction is accepted architecture, not current schema. Do not invent DOCUMENT grant targets or service-local ACLs to solve B2. |
| [Home API](../../../apps/episteck_home/episteck_home/api.py) resolves actor internally; `check_access_many` covers at most eight domain/action requirements for one Person. [Actor](../../../apps/episteck_home/episteck_home/identity/actor.py) and [auth hook](../../../apps/episteck_home/episteck_home/identity/auth_hook.py) bind human/machine context through verified delegation. | Required sets can exceed today's endpoint. Never truncate them or reuse a single-use delegation across a loop. B6 must supply a complete bounded trusted decision protocol. |
| [Nutrition authorization client](../../../services/nutrition/app/home_control/client.py) makes a single delegated Home authorization call per operation; [service](../../../services/nutrition/app/service.py) authorizes before repository reads/writes. There is no separate `whoami` pre-call in this path. | Preserve actual trusted actor behavior; high-level prose saying “resolve, then check” is not an instruction to add another delegated call. |
| [Nutrition API](../../../services/nutrition/app/main.py) already accepts `preferences` and `dislikes` in profiles. ADR-0004 assigns Nutrition its structured truth. | Scenario A determines protection, not a migration or duplicate preference store. B5 must decide canonical preference ownership. HEALTH/FINANCE protection similarly cannot confer clinical/accounting authority on Knowledge. |
| The same Nutrition API accepts intolerances and pregnancy profile data; its service currently gates profile operations through NUTRITION permissions. | Current service routing is not proof of complete future content sensitivity. This B2 proposal neither certifies that classification nor changes Nutrition's runtime authorization; any later cross-domain alignment needs explicit follow-up. |
| `confirm()` creates a new USER_CONFIRMED claim referring to a confirmation episode and predecessor. Only AI_HYPOTHESIS is expressly barred from ACTIVE construction; AI_SUMMARY/DERIVED are not. | Confirmation/provenance labels do not establish independence or remove security dependencies. B3 must resolve activation and lifecycle; B2's inheritance rule applies to every provenance/status. |

The earlier review correctly identified single-domain and unchecked-source gaps. This proposal does **not** adopt all its implications automatically: mandatory DOCUMENTS permission forever is too coarse; a generic policy graph is unnecessary; and a historical supersession link is not necessarily evidence dependence. Conversely, “any accessible supporting source” is unsafe if a materialized output actually used restricted input. These distinctions drive the recommendation.

## 3. Alternatives considered

Three serious alternatives can preserve B1 if implemented with the qualifications below. A single “highest sensitivity” label and freely choosing the least restrictive source are not viable: HEALTH and FINANCE are independent permissions, not ranks.

**A — Whole-ancestry conjunction.** Every derivative carries the union of the entire source objects' subjects, domains and access conditions permanently. Independent captures remain separate, but no narrower derived release exists. This is a viable restrictive first release; it does not satisfy the longer-term projection need.

**B — Live evidence-policy evaluation.** Keep requirements mainly on evidence/originals and traverse a dependency graph at read time. AND covers necessary inputs; separate fully independent proofs may be alternatives. To be safe, an output must be generated only from the chosen authorized proof, and B1's own content requirements always apply. Arbitrary policy expressions/resource types would exceed accepted B1; a bounded evaluator could avoid that, with substantial complexity.

**C — Artifact requirements plus typed lineage and approved projections (recommended).** Each disclosed/materialized version has a complete conjunction, bound to its evidence and classification versions. Ordinary derivation unions requirements. Independent assertions are separate objects. A smaller output requires an explicit approved projection, followed by generation from that approved input. Current policy/eligibility remains authoritative; a materialized requirement set is not a cached ALLOW.

| Dimension | A: whole ancestry | B: live evidence evaluation | C: requirements + controlled projection |
|---|---|---|---|
| Security | Conservative if ancestry is complete; denies many safe uses. | Can be precise; OR selection, traversal races and accidental reuse of jointly influenced output are hard to secure. | Conservative default; one explicit narrowing boundary to audit. Misclassification remains a risk in every model. |
| Explainability | Easy “all ancestors”; poor explanation of irrelevant inherited restrictions. | Full dependency reasoning can be difficult to explain and protect. | Explain direct content requirements, inherited restrictions and any release decision separately. |
| Implementation complexity | Lowest initial complexity; growing overrestriction and duplicate captures. | Highest; bounded graph evaluation, proof selection, cycle handling and freshness. | Moderate; conjunctions, versioned dependency information and a constrained approval process. |
| Accepted B1 | Compatible, often stricter. | Compatible only if every proof satisfies full B1 and graph rules introduce no new grant family. | Preserves exact B1 composition; narrowing requires the projection model B1 explicitly permits. |
| Future Health | Medical restriction cannot escape; unrelated passages also blocked. | Fine granularity possible; sensitive inference needs proof provenance. | HEALTH retained for residual clinical disclosure; safe authorized projections separately reviewable. |
| Future Finance | Bank data safely restricted but mixed documents hard to use. | Handles independent transaction/support paths at high complexity. | FINANCE follows account/financial disclosure; safe logistics can be separately released. No ledger ownership transfer. |
| Documents | Whole document is the minimum unit. | Span-level evidence natural, but original/locator authorization remains separate. | Whole document default; versioned spans become narrower only through reviewed classification/projection. |
| Ask Olin | Frequent refusal despite usable benign information. | May dynamically find alternate proofs; greater risk of hidden restricted influence. | Uses eligible variants/projections; answer inherits all input influence. No global source hunt. |
| Deletion/reclassification | All descendants affected, including semantically unrelated outputs. | Requires current transitive dependency evaluation and proof retirement. | Version/dependency invalidation; independent lines isolated, subject-wide restrictions still span them. |
| Retrieval/index | Large conjunctive sets; safe but restrictive candidate space. | Needs authorization-compatible graph/proof planning before sensitive search. | Complete artifact requirements constrain candidates; stale versions unusable. No index technology assumed. |
| UX/provenance | Users may be unable to share harmless logistics without recapture. | Rich “why” but difficult hidden-source handling and unstable explanations. | Clear distinction between assertion, supporting evidence and released explanation; approvals add friction only at narrowing. |

Choose C. Use A's default when classification or release evidence is insufficient. Avoid B's dynamic OR/proof machinery initially: keep independently supported assertions separate and choose an already eligible assertion before generation. C still needs dependency tracking; it does not require a universal graph, policy language, or one workflow instance per claim.

## 4. What carries sensitivity

Sensitivity describes what an information unit reveals, including inference and identification in its context. **Access requirements** are the enforceable consequence: bounded Home resource/domain/action checks and current source/subject use restrictions. They are neither truth/confidence nor a single public/private score.

| Information unit | Required protection |
|---|---|
| Original/source version, conversation/message and capture episode | Protect content and revealing metadata. A source has an access boundary; an episode is not a weaker alias for it. |
| Evidence span/excerpt | Exact original version and locator, complete content classification and applicable source-use restrictions. No automatic lower protection for a smaller byte range. |
| Claim/assertion version | Its own B1 scope/subjects/content domains plus inherited requirements from actual influencing inputs. Reuse outside the original context cannot erase them. |
| Evidence relation | The link itself may reveal private source existence, treatment, authorship or corroboration. Gate its disclosure separately. Classify whether it is a derivation dependency, a protected corroborating reference, or history. |
| Extraction, chunk, summary, embedding and other derivative | Same mandatory inherited requirements as the material used to produce it, plus requirements introduced by its output. Non-readable representations remain protected. |
| Index entry, cached answer, reranked candidate, retained bundle/export/job payload | Protect content, identifiers and metadata that reveal it; bind requirements and dependency versions. Partition-bound routing metadata must not become a discovery channel. |
| Ask Olin response and explanation | Protect all sensitive influence, including retrieved context, user-provided context and conversation history. Later storage, forwarding, reuse or re-embedding is another derivation/disclosure. |

A Person contributes a subject restriction; a domain names an independent permission category; neither replaces the artifact's complete requirements. Pure operational metadata can be minimized and separately classified, but omission of text does not prove that metadata is safe.

Minimum conceptual metadata for a usable artifact: trusted partition; stable identity and content version; complete requirements and authoritative classification revision; relevant scope and subjects; exact dependency identities/versions and relation meanings; current eligibility/invalidation binding; producer/capture provenance; and any approved projection decision with its applicability. This is a semantic minimum, **not proposed schema field names or a requirement to duplicate every ancestor row onto every vector**. Protected references may represent the information if they can establish complete current constraints before content access. Unknown/unresolvable metadata means ineligible.

## 5. Requirements and derivation rules

### 5.1 Keep bounded Home tuples and the B1 intersection

Let `H(P,a,r,d,x)` denote B1's conceptual current Home decision for trusted partition P, actor a, typed PERSON/CIRCLE resource r, domain d and action x. This is not an implemented API.

For a claim c, retain B1 exactly:

```text
R(c) = {scope(c)} UNION {PERSON/s for every actual subject s}
D(c) = complete nonempty content-domain set
Q(c,x) = AND H(P,a,r,d,x) for every r in R(c), d in {KNOWLEDGE} UNION D(c)

Disclosure(c) = trusted context and local references
                AND Q(c,VIEW)
                AND all inherited VIEW/use requirements
                AND current classification, dependency and eligibility checks
```

Sets are conjunctive, normalized and deduplicated. KNOWLEDGE never substitutes for HEALTH, FINANCE, DOCUMENTS or another applicable domain. More authority on one tuple does not compensate for another denied tuple. Existing same-tuple grant alternatives and same-domain MANAGE implication remain Home's concern.

Inherited requirements can include a source's PERSON/CIRCLE resource different from the output's semantic scope. Do not fabricate semantic subjects merely to carry source permissions. An ordinary derivative cannot escape its original Circle's handling restrictions by being copied into PERSON scope. An approved projection may establish a narrower, explicitly authorized release boundary as described below.

Preserve B1's conservative resource × content-domain product even if protected classification records explain that one passage concerns Ana's HEALTH and another concerns Erick's FINANCE. Sparse pairings may help review/classification evidence, but do not authorize a jointly disclosed claim under a weaker predicate. Split outputs only with a justified independent capture or approved projection.

Policy references are useful for current non-use restrictions, source-use dependencies and classification revisions. They must resolve to bounded Home requirements/operation decisions and trusted eligibility state; they are not bearer capabilities, arbitrary expressions, new resource grant types or another authority. No local “source allowlist” can override Home. If a source condition cannot be represented/enforced within that boundary, deny that use pending a separate design.

### 5.2 Ordinary derivation is monotone

For an output o produced from actual influencing inputs I:

```text
Requirements(o) includes its own content/governance requirements
                AND every inherited requirement from I
                AND applicable current source/subject use restrictions
```

“Inputs” includes passages, summaries, prompt/history context and information used to select or formulate an assertion, not just the citations that the AI chose to emit. A citation list cannot certify absence of influence. Default to the entire input's requirements when narrower influence is not established by a trusted process.

Extraction, OCR, chunking, paraphrase, translation, summarization, inference, copying, confirmation and embedding do not lower requirements. Combining two inputs conjoins them and may add new subjects/domains if the combination reveals something new. A low confidence value, generic wording, omitted name or AI-generated provenance is no exception. If new classification is uncertain, withhold usable admission rather than pick the least restrictive label.

Content domains supported by ordinary influencing inputs remain mandatory. Requirements for source access (for example PERSON/A DOCUMENTS/VIEW) also propagate by default even though DOCUMENTS is a container/access domain rather than clinical meaning. Other source-use conditions survive detachment. A source pointer disappearing, expiring or being deleted does not turn its former derivative into unrestricted information; unresolved dependencies deny pending B4 reconciliation.

Authorized extraction workers may inspect a source for the approved capture/classification operation. That does not authorize ordinary Ask Olin retrieval of unclassified content. Actor, partition, source binding and mandatory policy metadata come from the trusted boundary, never the document, model or tool arguments. A classifier may recommend extra restrictions or quarantine; it cannot authorize weakening. Any future automated classifier needs a separately approved completeness/validation policy before its outputs establish usable eligibility.

### 5.3 Reading is not publishing

Use B1's operation table without inventing additional grant actions. CREATE requires Q(new,CREATE) and Q(new,VIEW), independent authorization to read inputs, and all applicable source-use conditions. Reading a document is not permission to create shared assertions about its subjects. UPDATE/confirmation cannot shed restrictions. A release/reclassification uses B1's SHARE/RECLASSIFY predicates and the approval evidence in section 8.

An inherited source VIEW requirement does not mean creating a derivative requires CREATE on the original document itself. It is a continuing use/disclosure condition; creation authority is evaluated on the proposed Knowledge content according to B1. No blind or unauthorized third-party reusable assertion is admitted, even if the actor can personally read its evidence.

## 6. Mixed sources and precise evidence

Default: a mixed document's full extraction, whole-document summary and embedding inherit the conjunction of the entire document. A filename, page boundary, heading or model-selected quote is insufficient to narrow it.

Narrower evidence can exist through an approved projection of an exact source version/span. The review must establish what the selected information reveals when combined with headings, table keys, nearby context, identifiers and the recipient's authorized context. It must distinguish:

- Restrictions caused by unrelated omitted content.
- Restrictions on the selected content itself.
- Source-wide use/confidentiality restrictions that still apply even to a harmless-looking passage.

For a document containing Ana's condition, a household routine and delivery instructions:

- Full source/extraction: HEALTH + HOUSEHOLD and all source access requirements, including DOCUMENTS as applicable.
- Medical passage: retains Ana, HEALTH and applicable source requirements; a KNOWLEDGE wrapper adds governance, not weaker protection.
- Logistics passage: may get a narrower approved version if it neither reveals Ana's condition nor remains covered by an unreleased source-wide restriction. “Deliver to oncology at 07:00” is not nonsensitive logistics merely because it describes a time/place.
- An embedding made from the whole document cannot be relabeled as the logistics embedding. Generate a new embedding from the approved logistics input only, in an execution context without other restricted influence.

Until that projection is approved, every fragment uses the conservative full-source requirements. After approval, downstream transformations inherit the approved fragment's requirements and its release dependencies, not an unrestricted license to expand back into the document. Approval is version-specific; moving page offsets or a revised original require revalidation.

## 7. Several sources and independent assertions

Distinguish **actual derivation**, **independent corroboration** and **historical relation**. These are security meanings for later dependency design, not new persisted enums here.

1. If a claim or summary was formed from both a private medical document and Ana's message, it inherits both. Reading only the message later does not clean the existing materialized output.
2. If authenticated Ana independently asserts the same content from her own knowledge, create a separately attributed assertion with its own capture evidence and classification. It retains Ana's HEALTH requirements but does not inherit the unrelated document's DOCUMENTS/source-container restrictions merely because the statements match.
3. If Olin shows Ana a sensitive AI summary and she clicks “correct,” that is confirmation of that derived content, not automatically an independent source. Preserve its dependencies unless the explicit release process authorizes a new output.
4. A user pasting, reading aloud or restating a restricted source is still derivation. An authenticated, explicit first-person assertion may be independent when the capture process records that capacity and does not use restricted source/model context to construct its content. Do not attempt to prove human mental independence; do require an accountable assertion and preserve known dependencies. Ambiguous restatements stay restricted or require projection review.
5. A separately authorized user can assert public/general information from an independent source; classification still checks what its application to a particular Person reveals. A stranger's reassertion about Ana cannot bypass her requirements or B1's deferred private-third-party model.

Do not merge two assertions into one record with “any source grants access.” Eligible independent assertions can support the same answer, but only after each is authorized in full. A merged statement, combined confidence, source count or “corroborated by medical records” indicator uses additional information and is protected accordingly. A hidden source cannot improve the displayed confidence or the chosen wording of an otherwise accessible assertion.

Keep equality/deduplication links protected and partition-local. Neither linking nor content deduplication transfers permission; an unauthorized search for matching restricted claims is forbidden. Technical reuse of bytes must preserve separate logical requirements and invalidation obligations, not create a shared permission record.

A historical predecessor link alone need not invalidate an independently supported new assertion on source withdrawal. Conversely, labeling a true derivation “history” does not remove dependence. B4 must retain those meanings. Source-specific withdrawal affects its dependent path; an applicable **Person-wide** HEALTH denial/non-use still constrains every independently sourced assertion about that Person. Independent lineage is not a way around subject authority.

## 8. Can protection ever decrease?

Yes, but only for a **new approved output** through a deliberate SHARE/RECLASSIFY projection process. Ordinary transformation never decreases protection. This section proposes that process's security semantics; B3 owns workflow/state transactions and B4/B6 the enforcement mechanisms.

### 8.1 Three distinct operations

| Operation | Example | Rule |
|---|---|---|
| Broaden authorized audience while content remains sensitive | Ana permits another adult to see her HEALTH context. | Keep HEALTH and Ana's subject requirements. Proper Home grant issuance changes who satisfies them; classification is not falsified. |
| Release a bounded projection from source/container restrictions | Authorized summary of one passage, with no access to unrelated source pages. | Explicitly approve which inherited source requirements the new output replaces/removes, and which remain. Full source and its metadata keep their own protections. |
| Correct overclassification or genuinely generalize/de-identify | Release a general dinner guideline without any identifiable individual's condition. | Evidence must establish absence of the removed sensitive disclosure in the actual target context. Removing names is not enough. If the output still conveys Ana's health, keep Ana + HEALTH and use grants instead. |

Within B1 this is a same-partition approved projection, not a public publishing or cross-partition transfer system. A genuinely subjectless Circle projection still needs its Circle requirements. PERSON scope still requires its Person. No generic “public” escape value is proposed.

### 8.2 Authority and evidence required

The initiating actor must satisfy B1's old VIEW and Q(old,MANAGE), and proposed new Q(CREATE), Q(VIEW), Q(MANAGE), including applicable inherited restrictions. They must have current access to all source material needed to review the proposed removal and the relevant bounded management authority over each affected source resource/domain. A source custodian means the authority proven by Home for that source's PERSON/CIRCLE handling context, not an uploader, technical administrator or an invented DOCUMENT grant target.

Management permission is necessary, **not sufficient**, to waive another Person's protection. Every affected Person whose protection or audience is relaxed must explicitly authorize that release through their own authenticated authority, or separately proven representation if such a model is later approved. Relevant Circle stewardship and source-use authority must also explicitly approve the changes they control. One actor may fill several roles when proven. A Circle steward, a cross-Person MANAGE grantee, document owner, professional title, or system administrator cannot consent for another adult. Missing or unrepresentable authority means the proposed decrease is unavailable.

Record, under protection:

- Exact input and proposed output identities/versions; partition; precise spans where relevant.
- Before/after subjects, domains, source-use requirements and intended audience/use boundary; the exact requirement changes, not “approved” alone.
- Reason and classification evidence: what was removed, residual inference/linkability assessment, known identifying context and why the output does not disclose the information whose restriction is removed. For deliberate sharing of still-sensitive content, record consent while retaining its classification.
- Each approving human's trusted identity/capacity, authority checked, decision time, applicable validity and policy/classification revision. The AI may draft; it cannot be the approver or evidence of its own safety.
- Source-to-output lineage and the release decision as a continuing dependency, with source revision, withdrawal and invalidation coverage. Keep minimal audit provenance under B4 retention rules, not source text forever.

Only an exact approved output may acquire the narrower requirements. Regenerate later artifacts from it; do not strip labels from old chunks, vectors, summaries or cached responses. A model invocation that also saw unreleased source context cannot certify a narrower answer just by citing the approved output. Recompute with only approved inputs or review that exact additional output as a new projection.

An unsupported anonymity claim, unresolved inference risk, changed audience/context, changed source version or stale approval fails closed. No anonymization algorithm, automatic release category or standing AI declassifier is approved here. For the first preference vertical, recommend **no runtime downgrade feature**; define the boundary now and enable specific release processes only with later approval and evidence.

### 8.3 Current authority and later changes

Projection approval authorizes a specific requirement change; it is not a perpetual viewer permission. Every read still needs current Home decisions and current release eligibility. Revocation of the approval or a source restriction applicable to the release suppresses its dependents. A new restriction on an original requires revalidation of affected projections; do not automatically broaden or perpetually preserve them. Narrower source classification also does not automatically relax existing derivatives: reassess and publish a new valid version.

The continuing source lineage does not reimpose deliberately released whole-document read requirements on every view of the approved projection. The exact approved substitutions define the release boundary. Other use restrictions, source-change invalidation and Person authority remain live. If that distinction cannot be proved from trusted metadata, deny. This is how claim-access/full-source-denial can be safe without abandoning provenance.

## 9. “Why does Olin know this?”

Authorize **each disclosure**, including the evidence relation. Claim permission alone is insufficient to reveal a source title, filename, document type, author/professional name, excerpt, page number, date, external URL, source ID, number of supporting records or even that a medical record exists.

Safe forms are:

- An authorized independent assertion can be explained using its own permitted capture/attribution. Do not mention hidden corroboration.
- An approved projection can have a separately approved minimal explanation, with only the provenance facts covered by its requirements. A medical-sounding source title is not harmless decoration.
- If no provenance detail is authorized, use a generic response such as “I can't provide further provenance details.” Use equivalent wording for absent, unavailable and inaccessible detail; do not confirm existence of an additional hidden source. Do not invent an alternative provenance story.

Excerpt permission is not whole-source permission. Opening the original, following a locator, expanding surrounding text or fetching a canonical domain record requires independent current authorization. No unchecked URL or source ID is a fetch capability. Even when attribution is unavailable to the viewer, protected provenance remains available to properly authorized review under retention rules.

This permits a user to see a claim but not its original only when the claim comes from an independently authorized assertion or an explicitly approved narrower projection. An ordinary derived claim with unmet inherited source requirements remains denied; a hidden-source link alone does not justify disclosure.

## 10. AI, retrieval artifacts and reclassification

### 10.1 AI is a producer, never a release authority

AI_HYPOTHESIS, AI_SUMMARY and DERIVED all obey the same information-flow rules. Changing provenance or obtaining wording confirmation does not change protection. AI may propose classifications, spans, subjects and projections; trusted processes validate them. AI cannot select authoritative actor/partition, rewrite requirements, issue grants, declare independent human evidence, approve de-identification, or suppress inconvenient source dependencies.

Adding a new inference can make an answer **more** sensitive than its inputs. For example, combining individually innocuous clues may identify a condition or reveal a financial problem. The trusted output/admission boundary must assess the result and its intended recipients; uncertainty withholds disclosure/admission. This is a classification obligation, not a claim that today's contracts or a generic model can prove semantic safety.

### 10.2 Every retrieval representation is protected

Chunks, embeddings, summaries, index entries and caches are protected derivatives. Reranking candidates, cached snippets, similarity scores, counts, identifiers and error differences must not reveal unauthorized content. An index does not make sensitive inputs anonymous. Shared index metadata/statistics derived from sensitive content must either preserve the combined requirements or have a justified approved projection; this rule does not select an indexing structure.

Bind all retained artifacts to the partition, complete requirements, input/output versions and current invalidation state. For an aggregate cache/index artifact, preserve item-level boundaries where enforced; otherwise it requires the conjunction for its entire sensitive payload. A label such as “for Circle H,” a previous actor's cached ALLOW, or matching query text is not sufficient authorization.

B1 preauthorization covers sensitive candidate space, query expansion using stored material, keyword/vector ranking, chunk expansion, reranking, source lookup and caches. Perform only protected, partition-bound minimal security-metadata work to establish eligibility before sensitive search. Do not retrieve broad vectors and post-filter them in the application. A denied actor must not receive top-k matches, scores, titles or source counts influenced by hidden records.

Ask Olin output inherits all restricted inputs used to produce it. A response authorized for one viewer cannot be reused for a broader Circle or later session by merely caching the final text. Revalidate current requirements on reuse. Restricted context already supplied to a model cannot be “unseen”; future generation must isolate/restart context where necessary, or deny, according to B6. No promise of retroactive undisclosure is made.

### 10.3 Immediate effect of stronger classification

Suppose HOUSEHOLD knowledge is credibly identified as HEALTH information. At the authoritative acceptance of that finding, the old classification must cease to authorize use. If exact new classification cannot yet be established, make the object and affected dependent uses ineligible pending review. Strengthening/quarantine must not wait for completion of a release workflow or background reindex.

Required security semantics:

1. Establish a newer authoritative classification/invalidation state; the previous revision is no longer a valid retrieval/disclosure basis.
2. Deny affected old claims, chunks, vectors, summaries, cached answers, bundles and provenance views before sensitive candidate use. Source and approved-projection dependencies participate, including outputs whose wording no longer mentions the sensitive domain.
3. A stale job cannot publish derivatives against the obsolete revision; reject or require fresh classification and authority. Restored/reindexed content cannot become eligible merely because its old label says HOUSEHOLD.
4. Revalidate in-flight work before final disclosure. If it cannot exclude influence from now-ineligible context, withhold/discard and regenerate from eligible inputs. Already delivered data cannot be recalled.
5. Rebuild or remove affected artifacts later under B4; cleanup completion is separate from immediate non-use. When freshness/dependency coverage is unknown, suppress a safely bounded containing set, up to the partition's affected retrieval path, rather than continue serving stale results.

These are acceptance obligations, not a chosen version-counter, transaction, queue or consistency protocol. A version field without an enforced freshness barrier would not meet them. B4/B6 must demonstrate the mechanism across caches, indexes, jobs and model context before runtime approval. Independently asserted information is not automatically a descendant, but an updated **content** classification or Person-wide restriction must be applied wherever that information is present; source-specific independence is not immunity to discovered HEALTH content.

## 11. Adversarial scenarios A–J

These are evaluated architectural outcomes, not executed runtime tests. All objects are in trusted partition P; Ana is A; H is a Circle. Unless stated otherwise, lifecycle/validity is assumed eligible only for evaluating B2, leaving B3 open. Denial means no sensitive candidate search/disclosure, not a final-response filter.

| Scenario | Inputs and applicable requirements | Expected result and adversarial check |
|---|---|---|
| **A — Personal preference** | Authenticated A says “I dislike canned tuna.” PERSON/A, subjects `{A}`, NUTRITION + KNOWLEDGE; direct assertion episode. No sensitive document input. | Own CREATE+VIEW checks permit proposed capture; another viewer needs both domains for A. No invented HEALTH or DOCUMENTS ancestry. B3 decides activation, B5 canonical preference owner. **Pass:** simple capture without permanent unrelated restrictions. |
| **B — Health source → Knowledge summary** | Private medical document about A; authorized extraction → AI summary → contextual claim → vector. Requirements include A HEALTH and applicable DOCUMENTS/source conditions, plus claim KNOWLEDGE and B1 scope checks. | KNOWLEDGE-only viewer denied at candidates. Summary/claim retains source lineage; clinical truth remains with its canonical owner. A permitted narrower release needs section 8, not `domain=KNOWLEDGE`. **Pass:** all transformations retain protection. |
| **C — Mixed document** | HEALTH about A + HOUSEHOLD + logistics in one original. Whole extraction/summary uses all content. | Full conjunction by default. Exact independently safe span may become an approved projection; source-wide conditions remain unless explicitly released. Generate its vector anew. **Pass:** precision possible without automatic passage-based downgrade. |
| **D — Circle wrapper** | “Our family eats early because Ana has condition X.” CIRCLE/H, subjects at least A, domains HOUSEHOLD + HEALTH. | H and A each need KNOWLEDGE, HOUSEHOLD and HEALTH VIEW under B1, plus source requirements. Circle membership/stewardship and authorship cannot replace A's permission. “My partner” still identifies A. **Pass:** whole inseparable claim denied on any missing tuple. |
| **E — Multiple evidence sources** | Restricted medical assertion C1; later authenticated independent first-person assertion C2 from A with similar content. | C2 retains HEALTH but has its own capture/source restrictions, not C1's private document constraint. Keep both lines separate; do not reuse C1's summary/vector or disclose hidden corroboration. If the second event merely confirms C1, inheritance persists. **Pass:** independence without a least-restricted-source loophole. |
| **F — Source accessible, claim not shareable** | Actor has source VIEW about A, but lacks A's required CREATE or H handling authority for reusable Circle content. | Can perform only authorized source use. Cannot publish/activate the shared claim, even with source read access and Circle membership. Private-third-party Knowledge is not a fallback. **Pass:** read permission cannot become publication authority. |
| **G — Claim accessible, full source denied** | Viewer satisfies a released summary's complete requirements, including A HEALTH/KNOWLEDGE, but lacks full-source DOCUMENTS or another Person's source-content permissions. | Allow only the independently supported assertion or exact approved projection; deny original/unauthorized title/author/excerpt/locator. Approval must have explicitly addressed removed source constraints. **Pass:** narrow useful disclosure without source expansion. |
| **H — AI paraphrase laundering** | AI rewrites a private health passage as “The household has special dinner needs,” labels it generic KNOWLEDGE, drops A and requests broad Circle sharing. | Trusted lineage retains HEALTH, A and source restrictions; ambiguous wording cannot establish de-identification. No lower-label output or vector becomes eligible. An independently asserted routine is a different path, not automatic repair. **Pass:** AI cannot weaken requirements. |
| **I — Reclassification** | Active HOUSEHOLD assertion detected to disclose HEALTH about A. | Old revision immediately ineligible for affected use; quarantine until classification is complete. All future decisions include HEALTH; no slow job grace period. Final disclosure revalidates in-flight work. **Pass:** stale label cannot continue authorizing. |
| **J — Surviving derived artifact** | Old chunk/vector/cache still exists after I or after an applicable source-use restriction changes. | Artifact version/dependency state disqualifies it before candidate use; no text deletion shortcut and no cached ALLOW. Fence stale queued writes/restores; clean up under B4. If freshness cannot be proven, deny affected path. **Pass:** survival in storage does not mean retrieval eligibility. |

Additional negative checks: FINANCE → generic Knowledge retains FINANCE; renamed/deleted source leaves dependencies unresolved, not public; missing grant on one subject blocks the whole inseparable statement; source prompt injection cannot change actor/partition; old confirmation cannot certify a new output version; new source permissions cannot retroactively make old mixed-context AI output independent; counts/confidence cannot expose hidden evidence; removing a Circle label cannot bypass its inherited handling restriction.

## 12. Content domain, ownership and access restriction

Keep three concepts separate:

- **Content domain:** what the information concerns, potentially several domains. A dietary rationale can concern NUTRITION and HEALTH.
- **Canonical ownership:** which domain service is authoritative for a structured fact, determined by the architecture/owning process, not the artifact's label or author.
- **Access restriction:** current Home requirements and applicable source/subject use constraints for this particular disclosure, including inherited requirements.

HEALTH protection on Knowledge is a privacy obligation, not a diagnosis record or a claim of medical authority. FINANCE protection does not create a second balance/transaction ledger. DOCUMENTS access does not authorize all medical or financial content inside a file. KNOWLEDGE governance does not replace those categories. Canonical domain references and fetched values remain independently authorized; material derived from them keeps their protection and attribution. B5 must settle disputed ownership without weakening these rules.

## 13. What B2 settles if accepted; obligations left open

B2 would settle what carries restrictions, conjunctive inheritance, the ordinary no-downgrade rule, separate independent assertions, conditions for precise spans/projections, source-versus-claim disclosure, protected AI/retrieval artifacts, and immediate ineligibility semantics for changed classification. It does not claim the implementation can enforce these yet.

| Blocker | Required B2 input | Decision/work explicitly left open |
|---|---|---|
| **B3 — lifecycle** | Confirmation cannot drop dependencies; approved projection binds exact versions and authority; independence is not implied by USER_CONFIRMED. | Admission/activation, AI_SUMMARY/DERIVED activation, correction/dispute/supersession transitions, atomic approvals, concurrency and idempotency. No new lifecycle status is selected here. |
| **B4 — deletion/dependencies** | Preserve derivation versus corroboration/history; applicable source/subject restrictions invalidate dependent use immediately; approvals and derivative families participate; independent assertions stay distinguishable. | Physical deletion/retention promises, audit minimization/retention, cleanup verification, graph/relationship representation, post-revocation execution authority, jobs/backups/restore mechanisms. A lineage record is not a license to retain deleted text forever. |
| **B5 — ownership** | Classification and inherited access do not confer canonical ownership; Home remains grant/operation-policy authority. | Nutrition preferences, Knowledge persistence/service boundary, source/document custodianship responsibilities and migration. B2 describes the authority a release must prove; it does not appoint a service custodian or select storage. |
| **B6 — retrieval** | Complete current requirements before sensitive candidates; protected metadata resolution; exact eligible variants; independently authorized provenance; final disclosure and context reuse must respect reclassification. | Bounded multi-resource decision protocol, single-use delegation integration, freshness/concurrency barriers, repository constraints, cache/index enforcement, final revalidation, model-context isolation and task limits. No concrete retrieval protocol is selected. |

Private third-party assertions, cross-partition transfers and a general public/anonymized publication product remain outside the initial runtime. The overall Knowledge Technology Gate remains OPEN even if B2 is later accepted.

## 14. Product Architect decisions required

These are actual policy choices, not implementation shopping questions. No decision is inferred from this PR.

| Decision | Recommendation and consequence |
|---|---|
| **D1 — Inheritance model** | Accept C with complete conjunctions and actual-influence lineage. Preserve B1's full cross-product; no dynamic any-source permissions. A is a safe restrictive fallback if C is deferred. |
| **D2 — Source boundary and mixed spans** | Inherit source/container use restrictions by default. Permit narrower versioned spans and claim/full-source asymmetry only as explicit approved projections. This adds review friction but avoids silent DOCUMENTS shedding or permanent whole-document overrestriction. |
| **D3 — Independent assertion standard** | Permit separately captured, explicitly attributable independent assertions without unrelated source restrictions; keep known derivation/confirmation dependent and ambiguous restatements restricted. Do not automatically merge similar assertions or their evidence. |
| **D4 — Who can approve decreases** | Require B1 operation permissions, relevant source/Circle authority and explicit affected-Person approval for relaxation. Do not treat MANAGE, uploader status or AI review as personal consent. Defer legal representation and automated declassification categories; absence of authority denies. |
| **D5 — Release validity and disclosure UX** | Releases remain version/use-bound and revocable; source/classification changes require revalidation. Permit minimal separately authorized explanations and neutral unavailable-detail wording. Do not promise full source visibility merely because a claim is visible. |
| **D6 — Initial scope and verification bar** | First preference vertical has no downgrade feature. Require trusted complete classification or ineligibility, plus evidence of pre-candidate and stale-artifact enforcement before later runtime approval. Enabling any release category needs its own approved process and acceptance evidence. |

Acceptance should record owner/date, exact accepted or amended D1–D6 dispositions and scenario outcomes. Only that explicit decision can resolve B2. This document remains PROPOSED pending it.

## 15. Verification and change boundary

Only this new proposal and the B2 entry in the gate register change. Older gate-wide “B2–B6 OPEN” summaries are intentionally untouched: B2 is still unresolved, with a proposal awaiting decision. B1 remains RESOLVED; B3–B6 remain OPEN. Canonical documents, ADRs, contracts, schemas, runtime, deployments and production are unchanged.

Investigation result (structured skill output):

```json
{
  "task": "knowledge_b2_architecture_proposal",
  "baseline_main_sha": "cf34771e6770acc4c91bbd46475f24917a7365fc",
  "baseline_worktree_clean": true,
  "b1": "RESOLVED",
  "b2": "PROPOSED / AWAITING PRODUCT ARCHITECT DECISION",
  "b3_b4_b5_b6": "OPEN",
  "recommended_model": "conjunctive artifact requirements, explicit lineage, approved projections",
  "scenarios": "A-J: conceptual expected outcomes; not runtime tests",
  "technology_selected": false,
  "runtime_implemented": false,
  "production_changed": false
}
```

Verify from the proposal branch after commit:

```powershell
git diff --check origin/main...HEAD
git diff --name-only origin/main...HEAD
git diff origin/main...HEAD -- docs/architecture/proposals/KNOWLEDGE_TECHNOLOGY_GATE.md
git status --short --branch
```

Expected changed paths: `docs/architecture/proposals/KNOWLEDGE_B2_SENSITIVITY_INHERITANCE.md` and `docs/architecture/proposals/KNOWLEDGE_TECHNOLOGY_GATE.md`; gate diff limited to B2. Scenarios are a security argument and later acceptance specification, not proof of implemented enforcement.

**B2 PROPOSED — NOT RESOLVED**

**B1 REMAINS RESOLVED**

**B3–B6 REMAIN OPEN**

**NO TECHNOLOGY SELECTED**

**NO KNOWLEDGE RUNTIME IMPLEMENTED**

**NO PRODUCTION CHANGE**
