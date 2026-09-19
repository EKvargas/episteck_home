# Knowledge B1 — Security partition, scope, and subject authorization

Status: ACCEPTED — B1 ARCHITECTURE DECISION

Date: 2026-09-19

Repository: `EKvargas/episteck_home`

Main baseline: `ba7c2ae8189d22c954591cb16a48c8aaa53b8495` (PR #19 merged; clean local `main` equalled `origin/main`).

Gate: [B1 — Tenant / Person / Circle / multi-subject authorization](KNOWLEDGE_TECHNOLOGY_GATE.md#b1--tenant--person--circle--multi-subject-authorization)

Decision owner: Product Architect

Decision date: 2026-09-19

Disposition: ACCEPTED WITH AMENDMENTS — B1 RESOLVED

## 1. Purpose and accepted decision

This accepted proposal is the authoritative B1 architecture decision. Where older Knowledge documentation is less precise about B1 semantics, this decision governs until later consolidation. Existing canonical documents and ADR files are not rewritten in this PR. B1 acceptance does not approve contract/schema changes, select technology, authorize implementation, or complete the Knowledge Technology Gate. B2–B6 remain OPEN. All named people, household statements, and condition X below are synthetic acceptance examples, not records about real people.

**Accept a trusted security-partition invariant and one bounded Authorization Grant / authorization decision model in Home, targeting PERSON or CIRCLE only.** PERSON targets represent Person consent/access authority; CIRCLE targets represent Circle handling/stewardship authority. A Circle cannot itself consent. Keep one grant family and one Home policy authority, with separate issuer rules. Existing implementation may retain the ConsentGrant name; eventual persisted naming is an implementation/migration decision, not a rename required here.

For reusable/shared Knowledge, compose scope access with every affected Person's authorization and every required content-domain permission using AND. Preserve trusted actor binding and VIEW/CREATE/UPDATE/MANAGE. Do not introduce a commercial Tenant entity, arbitrary resource types, a second authority, service-local ACLs, or a general policy language. Private third-party assertions are a deferred product/privacy model, not an exception permitting unauthorized shared Knowledge (section 6.5).

The three independent questions are:

1. **Partition:** in which isolated data boundary does this object exist?
2. **Scope:** to which Person or Circle does the assertion conceptually belong?
3. **Subjects:** about which people does its content disclose information?

An answer to one never supplies an answer to the others. The Product Architect disposition is recorded in section 13. Knowledge remains unavailable for runtime use until the later contracts, authorization path, and remaining gate requirements are approved and implemented; accepting B1 alone supplies no runtime approval.

## 2. Repository evidence: implemented behavior versus accepted architecture

The six canonical architecture documents, the gate register, the independent review, and ADRs 0001–0009 were read. The following findings come from schema/code at the baseline, not assumptions from prose. Paths are relative to this proposal.

| Evidence | Actual baseline behavior and B1 implication |
|---|---|
| [Person schema](../../../apps/episteck_home/episteck_home/episteck_home/doctype/person/person.json) and controller | `linked_user` is optional and unique; Person can exist without a login. The controller is a plain `Document` subclass. No partition field exists. |
| [Circle](../../../apps/episteck_home/episteck_home/episteck_home/doctype/circle/circle.json), [Circle Membership](../../../apps/episteck_home/episteck_home/episteck_home/doctype/circle_membership/circle_membership.json), [Care Relationship](../../../apps/episteck_home/episteck_home/episteck_home/doctype/care_relationship/care_relationship.json) | Circle types are HOUSEHOLD/FAMILY/CARE/CUSTOM. Membership's `role_in_circle` is descriptive only; it has no validity/exit state. Care relationships have Person endpoints, type and dates, but no authorization. Their controllers are also plain subclasses. Circle has no steward/authority or dissolution field. |
| [Consent Grant schema](../../../apps/episteck_home/episteck_home/episteck_home/doctype/consent_grant/consent_grant.json) and controller | Required `actor_person` and `subject_person` both link to Person. One domain, action text, ACTIVE/REVOKED state, optional validity times, optional `granted_by`, and note. No Circle target, partition, authority lineage, or resource discriminator. System Manager has CRUD; the controller adds no grantor validation. `granted_by` is attribution, not proof that its Person could grant. |
| [Pure policy](../../../apps/episteck_home/episteck_home/policy/access.py), [Frappe wrapper](../../../apps/episteck_home/episteck_home/policy/wrappers.py), [policy tests](../../../apps/episteck_home/tests/test_access_policy.py) | Invalid domain/action or empty actor/subject denies. Self-access allows for valid domain/action. Cross-Person access allows if **any** matching active grant covers the action. Explicit MANAGE implies VIEW/CREATE/UPDATE/MANAGE in the **same domain**. A revoked row is unusable, not a deny overriding another active row. No membership/care, resource existence, partition, or `granted_by` validation occurs in the pure predicate. The wrapper loads grants and supplies time; exceptions deny. |
| Policy time handling | The pure policy compares time strings when `now` is supplied; `now=None` skips validity comparisons, and equality with `valid_until` is accepted. This is not a fully specified future freshness/time contract. B1 does not change it or claim the pure predicate alone establishes current authorization. |
| [Actor resolution](../../../apps/episteck_home/episteck_home/identity/actor.py), [auth hook](../../../apps/episteck_home/episteck_home/identity/auth_hook.py), [session lifecycle](../../../apps/episteck_home/episteck_home/identity/session.py) | Authenticated User resolves to exactly one Person through `linked_user`; zero/ambiguous matches deny. Verified delegation refers to an active server-side session, checks replay, expiry and enabled User, and preserves machine/human principals. Actor is not a business API input. A service identity must remain without a human Person binding. No trusted partition binding is implemented here. |
| [Home API](../../../apps/episteck_home/episteck_home/api.py) | `check_access` resolves actor server-side. `check_access_many` ANDs a bounded list of domain/action requirements for **one** Person, with exact input validation and no cache. It does not implement multi-Person or Circle authorization. Person discoverability may use circle/care context; Circle rosters require membership. Discoverability is not permission to read Knowledge. |
| [Home MCP context](../../../services/home-mcp/home_mcp/context.py), [tools](../../../services/home-mcp/home_mcp/server.py), [Nutrition client](../../../services/nutrition/app/home_control/client.py), [service](../../../services/nutrition/app/service.py) | Delegation is transport metadata, not a tool argument. Nutrition independently calls Home using its machine credential and delegation before repository access. Current code makes one delegated request per operation; compound VIEW+CREATE uses `check_access_many`. It makes **no separate `whoami` pre-call**, because delegations are single-use. Some high-level architecture prose compresses this distinction. |
| [Knowledge contracts](../../../packages/home-contracts/src/episteck_home_contracts/knowledge.py) | Claims currently require a nonempty subject tuple even for CIRCLE. PERSON scope does not require its scope Person in that tuple. Episode/Claim have no partition field. `author_person_id` is optional except for USER_CONFIRMED; constructors do not authenticate assertion or confirmation authority. |
| [Context contracts](../../../packages/home-contracts/src/episteck_home_contracts/context.py) and [tests](../../../packages/home-contracts/tests/test_context.py) | Each claim subject requires KNOWLEDGE/VIEW and, if different, its single claim domain/VIEW. MANAGE covers VIEW. Claim scope and `circle_ids` do not authorize a Circle. Authorization records are caller-constructed values; neither their authority nor retrieval ordering is proved. Sources are not independently permission checked. Simply allowing empty subjects would execute zero claim-subject checks. |

The decision preserves the foundations of [ADR-0001](../adr/0001-home-control-plane-is-frappe.md), [ADR-0002](../adr/0002-independent-domain-services.md), [ADR-0006](../adr/0006-family-care-graph.md), [ADR-0008](../adr/0008-consent-fail-closed.md), and [ADR-0009](../adr/0009-trusted-actor-binding.md). It accepts the B1 semantics for a later evolution of ADR-0007's contracts and ADR-0008's Person-only resource signature. This accepted decision governs those B1 clarifications; neither ADR file nor runtime contract is changed here. G1.5/G1.6 validation is historical evidence, not a new production inspection in this task.

## 3. Terminology

| Term | Meaning |
|---|---|
| Security partition | Trusted isolation boundary for data and its references; not an audience, Circle, or permission. A future customer deployment may correspond to one, without defining commercial tenancy today. |
| Person | Domain identity of an individual; distinct from Frappe User. A Person without User can be a subject but cannot act through login. |
| Circle | Organizational/social context, including overlapping household, family and care groups within a partition. |
| Semantic scope | Exactly one PERSON or CIRCLE context for a claim. It is neither ownership nor an automatic audience. |
| Person subject | A person about whom the content makes or reveals an assertion, including indirect identification. Not every reader or Circle member. |
| Authorization resource | Typed target against which Home evaluates permission: initially PERSON or CIRCLE. A Circle resource is not a human data subject. |
| Authorization Grant / authorization decision | Bounded architectural grant family/evaluation model in Home. PERSON means Person consent/access authority; CIRCLE means handling/stewardship authority, never a Circle giving personal consent. The current ConsentGrant implementation name does not determine these semantics. |
| Actor | Human performing the current operation, resolved from trusted authentication; accompanied by the machine caller when delegated. |
| Assertor / author | Who made the assertion in its source. May differ from the capturing actor; attribution does not grant access. |
| Attestor | Person explicitly confirming an exact assertion/version and the capacity in which they confirm it. Reading or acknowledging is not attestation. |
| Viewer | Actor requesting disclosure now; authorization is evaluated now, not inherited from authorship. |
| Circle steward | A Person explicitly granted MANAGE on a particular Circle/domain through Home. Not an inferred household head, membership role, or guardian. |

## 4. Accepted invariants

The content-authorization rules below govern the reusable/shared Knowledge model. They do not design or permanently prohibit a future private-personal-assertion model; that model is deferred and excluded from the initial runtime (section 6.5). Partition and trusted-context invariants are not weakened by this deferral.

1. Every durable Knowledge object and derivative has exactly one nonempty, trusted security partition. No unpartitioned fallback exists.
2. Trusted infrastructure binds partition and actor; neither is an authoritative model/user payload field. Authentication, deployment binding and reference validation precede content retrieval.
3. All internal references resolve within that partition, including actors, subjects, scopes, assertors, episodes and authorization targets. Cross-partition references, joins, sensitive deduplication, Knowledge sharing and retrieval are initially forbidden.
4. Each claim has one typed semantic scope. PERSON scope requires its Person in the complete subject set. CIRCLE scope permits an empty subject set only for content genuinely about no specific Person.
5. Every scope requires permission, even when subjects are empty. Circle membership, care relationships, authorship and a service credential cannot substitute for grants.
6. Scope checks and all applicable subject/domain checks compose with AND. Self-access satisfies only the actor's own Person requirement; it never bypasses Circle or other Person requirements.
7. No domain implies another. MANAGE retains its current same-resource, same-domain action implication; no other action hierarchy is introduced.
8. Untrusted metadata, incomplete classification, unknown references, missing decisions, stale authority or unavailable policy deny. Claim text and labels cannot define their own access policy.
9. Permission to use a claim does not imply permission to open its source or disclose source metadata. Restrictions on a Person survive a Circle wrapper and every derivative.
10. Access revocation, assertion withdrawal, correction, and physical erasure are distinct. Prior membership/authorship creates no perpetual read right. Previously disclosed data cannot be retroactively undisclosed.
11. Home owns the authoritative grant and operation policy. Repositories enforce its complete constraints before sensitive candidate retrieval; neither vectors nor ContextBundle metadata are authority.

## 5. Security partition model

### 5.1 Logical boundary and trusted binding

Define a stable opaque partition key/invariant, **not a Tenant domain entity now**. A partition can contain many Persons and overlapping Circles. A household Circle is not the key, and creating/joining a Circle never creates/selects a partition.

For an initial future single-deployment runtime, trusted server configuration maps the authenticated Home authority/site and the Knowledge deployment to one stable partition. The value is bound outside user/model arguments. A raw Host header, URL argument or `X-Partition-ID` is not trusted configuration. The server checks that the authenticated session's authority, resolved Person and calling service are valid in that same binding. Ambiguous or conflicting mappings deny; there is no default global partition.

If multiple partitions are later reachable through one application, an authenticated server-side session must bind an authorized partition explicitly before any Knowledge operation. A user may request a context switch, but the server must prove entitlement and establish a new trusted binding; the model cannot select a raw key. That switch protocol and commercial provisioning are deferred.

G1.6's opaque session, single-use delegation and independent service authorization remain intact. A proposed multi-resource decision must fit a bounded authenticated operation and validate every required tuple; it must not loop over current Home HTTP endpoints reusing one single-use token. A later API design must solve batching/freshness without weakening replay protection. No new token claim or endpoint is selected here.

### 5.2 Coverage, identity and references

Coverage includes claims, episodes, original/source registrations and locators, chunks, embeddings, summaries, caches, queued jobs, exports, workflow metadata and any retained request/bundle artifacts. A durable derived object may combine inputs only from its own partition. Shared nonsensitive software/configuration is outside this Knowledge-content rule; storing personal content there is not an escape hatch.

An object's effective identity is conceptually `(partition, resource_type, local_id)`, even if its visible ID happens to be globally unique. This is not implemented by this decision. Existing names such as `PSN-00001` are local identifiers, not proof of global identity. Resolve direct IDs only inside the trusted partition; never globally locate an object and then inspect its partition. Validate reference type and local existence using protected control metadata before loading content. Outside-partition, nonexistent and undiscoverable references produce a non-enumerating refusal.

The same real individual may later have separately governed Person records in different partitions; no automatic global identity merge or cross-partition `linked_user` mapping follows. Initially each referenced Person/Circle belongs to the bound Home authority and partition. Their future explicit partition columns or deployment-level mapping are implementation choices, not changes made here.

Copying/moving a claim across partitions is forbidden initially. Exports remain partition-bound protected outputs; importing into another partition is a future explicit transfer process, not permission inheritance. A source URL or external domain record reference cannot be used as an unchecked cross-partition pointer or fetch capability.

Background work retains trusted partition and operation provenance, then revalidates authority before sensitive work or publication. A queue variable supplied by the model cannot establish either. No blanket service self-access, perpetual human impersonation or autonomous cleanup identity is approved; any post-revocation erasure executor requires a separately approved, partition-bound non-disclosing mandate under B4.

Physical stores, encryption keys, placement, provisioning, billing and commercial Tenant lifecycle remain deferred.

## 6. Scope, subjects and attribution

### 6.1 PERSON scope

For `scope_type=PERSON, scope_id=PSN-X`, X must exist in the trusted partition and appear once in the normalized subject set. The assertion belongs to X's personal context; X does not thereby own facts about every other person it mentions.

Additional subjects are permitted in reusable/shared Knowledge. “Erick prefers eating dinner with Ana” is PERSON/Erick with subjects Erick and Ana because the contextual relationship reveals information involving Ana. Both contribute restrictions. An innocuous external public reference need not become a private Person identity, but ambiguous references to household people cannot be silently omitted or treated as public. Admission to this model must resolve them or refuse durable usable admission. This rule does not settle the separately deferred private-third-party-assertion question in section 6.5.

Self-access allows Erick's own checks, not Ana's checks. Permission to author an assertion about Ana does not mean Ana made or agreed with it.

### 6.2 CIRCLE scope

For `scope_type=CIRCLE, scope_id=CIR-HOUSEHOLD`, the assertion describes that Circle's shared context. “Our family normally eats dinner around 19:00” may have `subjects=[]`. Do not fabricate a Person subject and do not expand subjects to every Circle member: membership changes would otherwise rewrite the assertion's meaning and privacy requirements.

The scope still requires explicit Circle KNOWLEDGE and relevant content-domain permissions. Empty subjects only removes Person checks; it never removes the scope checks. Claims revealing a named or identifiable person's condition, preference, decision or participation include that person regardless of wording or Circle placement. Replacing “Ana” with “my partner” does not remove the subject restriction.

Who can act is determined by the operation table below, using explicit Circle grants plus subject requirements. A Circle contributor can make an attributed assertion; only a designated steward with the required permissions can attest that it is suitable as shared Circle context. Steward approval is **not unanimity**, confirmation by every member, or clinical/financial authority.

### 6.3 Complete subjects and domains

`subject_person_ids` is the complete set of people actually concerned, not a list chosen to make authorization pass. Trusted admission validates scope, subjects, content domains and provenance. The model may suggest them, but cannot make them authoritative. User confirmation of wording alone cannot declassify content. If completeness cannot be established, deny usable admission/retrieval; do not broaden access by assuming an empty set.

For this decision, `D(c)` is the nonempty set of required content domains for reusable/shared claim c. KNOWLEDGE is always an additional governance requirement. A single-domain claim retains today's domain plus KNOWLEDGE checks. In a mixed-domain claim, all known domains are required; adding HEALTH or FINANCE can only restrict access. Under accepted B1, every subject and the scope must pass every domain in `D(c)`. B2 may refine the exact subject/domain sensitivity matrix, but may relax this conservative intersection only through an explicit approved projection/declassification model. No such relaxation is accepted here.

This establishes composition, not B2's classification/inheritance algorithm. Source-derived restrictions can add requirements; they cannot be discarded just because the current claim contract has one `domain` string. A diagnosis remains canonical Health/FHIR truth, not a Knowledge diagnosis record.

### 6.4 Minimum author/assertor semantics

Preserve distinct, attributable information without a consensus engine:

- Capture/operation identity: trusted actor, machine caller if any, partition, operation time and source/capture reference.
- Assertion identity: exact claim/version, assertor Person if proven, or attributed external/system producer with its evidence. A model cannot nominate another Person as the authenticated speaker. Unknown/imported attribution remains labeled as such.
- Subject set and typed scope, independent of assertor.
- Any attestation: attesting Person, exact version/content, time, evidence and capacity (`personal assertion` or `Circle stewardship`). This is conceptual metadata, not a contract schema change.

For direct “Our family eats at 19:00,” Erick is the assertor; Ana is not an assertor or attestor unless supported by her own actual assertion or attestation. Circle stewardship can endorse shared use while preserving “asserted by Erick; endorsed by [steward].” That stewardship attestation does not mean every Person agrees that the content is true. Do not create a “family consensus” state or emit that label. Detailed confirmation/lifecycle semantics remain B3. Imported assertions and AI suggestions do not acquire human authorship from the actor who merely uploads them.

An assertor need not automatically be a content subject. Attribution itself is protected metadata: disclose it only under authorized attribution/source rules, and add a Person restriction if it reveals personal content. Neither a bare author ID nor a source pointer grants access to that Person's other data.

### 6.5 Private third-party assertions — deferred product/privacy model

**PRIVATE THIRD-PARTY ASSERTIONS = DEFERRED PRODUCT/PRIVACY MODEL.** They are not part of the initial Knowledge runtime.

Erick privately telling his personal Olin “Ana likes blue” raises a future distinction between Erick's private attributed personal assertion and reusable/shared Knowledge asserted as being about Ana. B1 intentionally does not design that distinction, its permissions, storage or lifecycle. The conservative reusable/shared rule must not become an accidental permanent prohibition on all future private personal notes or observations about another Person.

This deferral supplies no authorization exception. The initial reusable/shared model must not admit that statement as active shared Knowledge without the normal Ana subject restrictions. A private label, PERSON scope, authorship or an LLM inference cannot smuggle it into active reusable/shared Knowledge. A future private-personal-assertion model may be designed separately under an explicit product/privacy decision; none is implemented or approved here.

## 7. ConsentGrant alternatives and accepted authorization model

These alternatives preserve the original tradeoff analysis. The Product Architect accepts the bounded structure closest to A with the terminology and bootstrap amendments below. B's arbitrary-resource generalization is not adopted; no implementation or migration is authorized.

| Alternative | Compatibility and migration impact | Security properties and complexity | Future Health/Finance and Circle effect | Disadvantages |
|---|---|---|---|---|
| **A — Bounded typed PERSON/CIRCLE evolution of existing ConsentGrant (structure accepted with amendments)** | Keep Home authority, domains/actions, Person grantee and existing Person self-access. Existing grants normalize to PERSON resources. Preserve current Person APIs as adapters; later add bounded typed evaluation. Future schema validation/migration, partition binding and Circle issuance rules remain implementation work; no rename is required now. | One Authorization Grant family/evaluation model; AND composition outside any individual grant. Exactly one typed target, no wildcard types, Circle self-access forbidden. Moderate change with a small closed vocabulary. | Health/Finance Person consent stays intact. Circle permission authorizes Circle handling only; it never grants access about an adult. Supports genuine subjectless Circle Knowledge. | The existing ConsentGrant name can obscure the distinction between personal consent and Circle authority. Persisted naming remains an implementation/migration decision. Circle grantor authority is new work. Ambiguous legacy target fields must be rejected, not guessed. |
| **B — Replace/generalize with resource-subject AuthorizationGrant for arbitrary resource types** | Home could remain authoritative, with ConsentGrant mapped to one subtype. Broader API/schema migration for all consumers and possible compatibility adapters. | Can separate authorization target, grantor and human data subjects cleanly. High complexity: generic resources, ownership and delegation rules are undefined; careless generic self-access or wildcards could widen rights. | Flexible for future account/document/Health/Finance resources and Circles, but each still needs its own issuer semantics and Person restrictions. | Speculates beyond B1; risks a policy framework with weakly defined resource semantics and a long migration. Renaming alone solves no consent problem. |
| **C — Keep Person ConsentGrant; add CircleGrant under the same Home authority** | Person consumers unchanged; additive Circle schema and evaluator branch. Shared evaluation utilities can remain central. | Clear personal-consent versus stewardship distinction. Safe only if both results are composed centrally. Moderate complexity, but duplicate grant lifecycle/audit/expiry behavior is likely. | Preserves Person Health/Finance checks and enables subjectless Circle context. | Two grant constructs for almost identical grantee/domain/action/state behavior; services could mistakenly check only one. Justified only if Circle authority needs materially different lifecycle, which is not established. |
| **D — Keep Person-only ConsentGrant and defer Circle Knowledge** | Zero grant migration; explicitly reject all Circle Knowledge in a future first runtime. | Smallest immediate surface; safe if there is no fake Person household owner and no empty-subject bypass. | Personal Health/Finance remain unchanged; cannot support genuine household context or scenarios B/E as shared Circle claims. | Delays the conceptual question rather than resolving it. Viable rollout limitation, not the target B1 authorization model. |

**Accepted: A's bounded structure, described architecturally as an Authorization Grant / authorization decision.** It expresses the one demonstrated new resource kind without creating overlapping service ACLs or arbitrary-resource infrastructure. Personal consent/access and Circle handling/stewardship have different issuer rules but share one grant family, evaluation model and Home decision authority. A Circle cannot itself consent. Existing implementation may continue to be called ConsentGrant for compatibility during migration; whether the persisted DocType retains that name or evolves to a better one is an implementation/migration decision. No rename or migration is required in this architecture PR. Alternatives B and C are not adopted; D is not the target B1 model.

### 7.1 Accepted grant semantics and authority to issue

Conceptually, a grant identifies trusted partition, Person grantee (the existing schema calls this `actor_person`), exactly one typed resource, one domain, actions, active/revoked state, validity and proven issuing authority. A grant's stored grantee is not an actor field a tool may supply to impersonate someone. For PERSON resources the resource Person is the current `subject_person`; for CIRCLE it is a Circle, **not a fabricated Person**.

Keep existing Person grant evaluation compatible. Self-access applies only when typed resource is PERSON and the resolved actor equals that Person. Compare full partition/type/ID identities; a coincidentally equal Circle ID must never trigger self-access. Resource existence and partition binding are prerequisites outside the existing scalar self-access shortcut.

Grant mutation is a separate, constrained Home process, not a side effect of Knowledge CRUD:

- Person grants require the subject's authenticated authorization or separately proven representative authority. `CareRelationship=GUARDIAN`, Circle MANAGE, System Manager status, or a populated `granted_by` field is not business proof. No automatic representative model is added. Cross-Person MANAGE permits the existing data actions but is **not permission to issue further Person consent grants**.
- Normal consumer onboarding must not require manual system administration. When an authenticated Person deliberately creates a Circle through an authorized Home **create Circle** process, the operation may atomically create the Circle, explicitly record the creator's acceptance of initial stewardship, and establish initial bounded Circle MANAGE authority. The authority comes from that explicit authenticated creation/stewardship operation, not from Circle or membership-row existence. Its scope is the new Circle and the bounded domains recorded by that operation; it confers no Person consent or arbitrary cross-domain authority. This is an accepted process rule, not an implemented API.
- First membership, creating a membership row, age, family role, an owner/parent label or an AI inference cannot establish stewardship. No LLM may designate a steward. Imported or pre-existing Circles without a valid steward require an explicit trusted designation/recovery process; no valid designation means no Circle grant issuance or ordinary Circle Knowledge use.
- A steward may explicitly issue/revoke ordinary Circle VIEW/CREATE/UPDATE grants only in domains for which they hold Circle MANAGE. Issued permissions and validity cannot exceed that authority. Ordinary recipients cannot redelegate. Replacing/recovering root stewardship requires an explicit protected Home process; recursive MANAGE delegation is not approved.
- Such grants record their authorizing stewardship and cease to be usable when that authority is revoked/expires, unless explicitly reauthorized by a current steward. This is a grant-validity dependency, not a workflow per claim. It prevents stale subordinate grants from outliving their authority.
- No unrestricted authorization-grant mutation is exposed to Home MCP or the model. Authenticated human authorization, authority verification and audit are required; a manual administrator write is not the required consumer onboarding path and does not itself prove business authority.

MANAGE still implies lesser **data** actions on that exact typed resource and domain. It does not imply other domains, another resource, partition administration, or representation of other adults.

### 7.2 Deferred implementation/migration boundary

In a separately approved future migration, preserve existing grant IDs, actions, state, times and provenance. Treat old `subject_person` records only as PERSON targets, not inferred Circle grants. Establish one unambiguous typed target and reject mixed/missing targets; do not allow old and new fields to be independently authoritative. Review incomplete legacy grantor evidence through an explicit later migration policy rather than silently declaring it verified. Persisted DocType naming remains an implementation/migration decision. No rename, actor-binding or existing Nutrition call behavior changes are authorized by B1 acceptance.

The future central evaluator must expose a complete bounded compound decision and enforce target existence, partition, issuer validity, grant lifecycle and operation predicates. No domain service may recreate Circle permissions in a local table. Contract design, tests, API rollout and migration require separate later approval; B1 architecture acceptance implements none of them.

## 8. Authorization composition and operation mapping

### 8.1 Exact reusable/shared content rule

Let `P` be the trusted partition and `a` the trusted actor. Let `H(P,a,r,d,x)` mean Home currently permits action x on typed resource r in domain d. It includes verified grant authority and the same-domain MANAGE implication; it is conceptual notation, **not an existing callable API**.

For a reusable/shared claim c, define (the deferred private-third-party-assertion model is not specified by this rule):

```text
R(c) = {typed scope of c} UNION {PERSON/s for each s in subjects(c)}
G(c) = {KNOWLEDGE} UNION D(c)

Q(a,c,x) = AND over every r in R(c), d in G(c): H(P,a,r,d,x)

VIEW(c) = trusted identity/partition and valid local references
          AND Q(a,c,VIEW)
          AND applicable subject/source restrictions
          AND current eligibility for the requested use
```

Deduplicate the PERSON scope check when it is already a subject. A claim must have a scope, so `R(c)` is never empty. Additional operation predicates below only narrow this result; no row means “bypass Person restrictions.” Lifecycle eligibility, freshness implementation and inherited restriction derivation are B2/B3/B6 work.

The result is an **intersection of permissions**, not a maximum numerical sensitivity label: any required denial controls disclosure. More privilege on Erick cannot compensate for no HEALTH permission on Ana. Grant unions occur only inside a single Home tuple evaluation, as today; requirements across resources/domains compose with AND.

### 8.2 Domain operations mapped to existing actions

`Q` below includes both Circle/Person scope and all subjects/domains for reusable/shared Knowledge. Reads of old content always require its own VIEW eligibility. Checks on replacement content use the replacement's complete subjects/domains as well as the old ones. Retain exactly VIEW, CREATE, UPDATE and MANAGE as low-level grant actions. DISPUTE, CONFIRM, FORGET and SHARE are domain operations, not new grant actions: compose existing permissions, trusted actor/resource context and operation-specific predicates. Exact lifecycle effects remain B3/B4.

| Operation | Required authorization and authority limits |
|---|---|
| **CREATE** | Q(CREATE) and Q(VIEW) for the proposed content; authorize any source reads separately. Initial Knowledge admission does not support blind writes that the actor cannot inspect. Persist as an attributed assertion, never as other subjects' confirmation. Activation is separately gated by B3. |
| **VIEW** | The complete VIEW rule above, before candidate/content access. No automatic grant to authors, former members, or everyone in the Circle. |
| **UPDATE / CORRECT** | Old VIEW plus Q(old,UPDATE); replacement Q(CREATE) and Q(VIEW), including added subjects/domains. Ordinary correction cannot change scope, remove restrictions or expand audience; that is SHARE/RECLASSIFY. Create a separately attributed correction; never rewrite another person's asserted/confirmed identity. The exact supersession transaction remains B3. |
| **DISPUTE** | An actor who can VIEW can propose an attributed challenge if authorized to CREATE that challenge under its own complete scope/subjects/domains. This does not overwrite the challenged assertion or automatically settle it. A subject or original assertor also has the narrow non-disclosing objection/withdrawal path below, even if they cannot read the full joint claim. B3 decides lifecycle effect and resolution, not who may impersonate an attestor. |
| **Confirm / endorse for Circle use** | Exact claim VIEW plus Q(UPDATE), and Circle MANAGE in every required domain for the steward endorsing shared Circle use. This authorizes a labeled stewardship attestation, not confirmation on behalf of every subject. Each personal confirmation requires that Person's own trusted actor and appropriate access; no proxy confirmation absent separately approved representation. B3 owns activation details. |
| **SHARE / RECLASSIFY** | Old VIEW and Q(old,MANAGE), new Q(CREATE), Q(VIEW) and Q(MANAGE) for proposed target/restrictions. Cross-partition change is forbidden. Broadening recipients additionally requires explicit valid grant issuance by the relevant Person subject authorities and Circle steward; source restrictions cannot be dropped. Circle MANAGE alone cannot consent for Ana. Evaluate each recipient against the whole new claim; never copy the Circle audience onto Person data. |
| **FORGET / REMOVE whole claim** | For content-based selection, old VIEW; for whole-object removal, Q(old,MANAGE) plus the authorized removal process. A pure subjectless Circle claim can be retired by its authorized steward. A subject or assertor can instead exercise the narrow non-disclosing withdrawal below without authority to erase everyone else's evidence. Physical erasure, retention and source cleanup remain B4. |

For ordinary operations, missing permissions mean denial, not an attempt to silently rewrite the user's statement, drop a subject, choose a weaker domain or use another route. Requesting approval to share does not itself disclose the claim to a recipient who lacks current VIEW.

### 8.3 Narrow subject/author control without granting joint-content access

A person must not need another subject's private read permission to withdraw their own contribution or request non-use of information about themselves. Home may authorize a narrowly scoped control command using trusted partition/actor and protected object metadata:

- A subject acts under their own PERSON/KNOWLEDGE MANAGE self-authority, with the relevant own-domain checks, and verified inclusion as a subject. They may revoke effective cross-Person permissions about themselves or request suppression of their involvement in a particular claim.
- A proven assertor may retract their own assertion/attestation, using their own self-authority and a verified assertion binding. Authorship gives this limited withdrawal right, **not** continuing access to the claim or permission to edit another assertion.
- The command returns only a non-disclosing receipt. Possessing a guessed ID is not proof of subjecthood/authorship and must not become a discovery oracle. If the claim cannot safely be identified, a Person-scoped non-use request can be applied inside the trusted authority without listing other subjects' content.

This is a centralized operation predicate, not a second ACL or a new broad grant. It cannot read the full claim, grant new access, delete other people's independent sources, remove the subject label while retaining revealing text, or change another person's words. A subject's valid restriction makes an inseparable claim ineligible for uses covered by that restriction. Keep the underlying record restricted pending B4's retention/removal process; do not claim that issuing a suppression request physically erases it.

Revoking access need not delete the whole claim for everyone. Example: Ana revokes Erick's effective HEALTH/VIEW over Ana; Erick loses the joint health claim, while another fully authorized viewer may retain access. Because current grants are allow-only, revocation must remove **all** effective paths for the tuple, including MANAGE grants; revoking one of several rows is not an effective denial. Ana's own self-access satisfies only her own checks, so she still cannot read private information about Erick without his permission.

For claim-specific non-use, B1 requires the eventual eligibility model to honor the accepted subject restriction even if domain-wide grants remain. Its storage, propagation and cleanup are B4/B6 decisions. No claim-specific ACL engine is implemented or selected here. Until safe separation is established, suppress the inseparable claim for the affected use. A newly worded routine excluding private rationale is a separate proposed assertion, not automatic redaction/declassification; B2 must approve any derived projection.

### 8.4 Claim visibility, source visibility and subject restrictions

These are separate checks. An authorized claim does not grant its original episode, conversation, attachment, document title, excerpt or full source. Conversely, reading a source does not permit every extracted claim or shared use. Sources must independently satisfy their resource, Person and domain requirements before retrieval or explanation.

It can be valid to view a claim while its full source remains unavailable, but only under an approved B2 disclosure policy; an unchecked source link cannot make that decision. B1 supplies the AND composition and non-bypass boundary. It does not decide excerpt inheritance, sanitization or whether a particular derivation may shed a source-container restriction.

## 9. Circle membership and household transitions

Membership remains organizational/navigation information. Its transitions can initiate explicit grant invalidation; adding a membership never creates permission. Authorization evaluates actual effective grants and lifecycle state, not a historical membership or a descriptive role.

| Transition | Accepted authorization effect |
|---|---|
| Person joins Circle | No automatic access, including historical claims. A steward explicitly grants bounded Circle/domain actions; every Person subject still independently controls access about themselves. A grant may explicitly cover retained historical Circle context, but joining does not. |
| Person leaves / is removed from household | The trusted exit process invalidates **all that Person's Circle grants**, including MANAGE, and any ordinary Circle grants dependent on their lost stewardship pending reauthorization. This applies to future reads of old and new Circle claims. Keep authorship and subject identities intact. The exit must not be reported complete while stale Circle grants can still authorize; an inconsistent/unreconciled transition fails closed. |
| Membership deleted outside the exit process | Treat affected Circle access as unresolved and deny until Home reconciles grants. Do not rely on eventual best-effort cleanup while old grants remain usable. Current Membership schema/controller does not implement this behavior. |
| Person rejoins / post-exit collaboration | Old grants do not revive. Require fresh explicit grants after reconciliation. An intentional post-exit grant, including to a nonmember, is possible under Circle steward authority; it is a new decision, not retained membership privilege. |
| Circle dissolves | Make Circle resource unavailable for ordinary Knowledge use and invalidate its grants. Do not migrate all its content into a former member's Person scope. Preserve subject restrictions and limited control paths; retention/export/erasure is B4. Any historical retrieval feature requires a later explicit archive policy. |
| Dependent becomes independent adult | Person identity and prior attribution remain stable; creating a linked User establishes actor capability, not household access. Care/guardian labels confer no permission. Explicitly review and revoke or reauthorize representative-origin grants and stewardship at the transition; uncertain representative authority denies. No automatic permanent guardian access and no automatic right to other adults' data. Age thresholds, representation evidence and transition initiation need separate product policy. |

Independent Person-to-Person grants do **not** silently disappear merely because a Circle membership ends: they may support a separate care relationship. The household exit process must expose their continued existence to the authorized subject/issuer for explicit review and must not promise that Circle exit revoked all personal sharing. Any grant explicitly dependent on now-ended representative authority ceases to be usable. Removal from one Circle does not alter other Circles or move a Person across partitions.

For a departing Person, claims **about them** retain their subject checks and narrow objection/non-use rights. Claims **authored by them** retain attribution and narrow retraction rights, but authorship gives no ongoing Circle VIEW. Already disclosed messages, screenshots, exports and model context cannot be recalled; future service disclosure and reusable context must honor current denial, with B6 defining working-memory handling.

## 10. Retrieval boundary required of B6

The eligible candidate set must be constrained **before sensitive retrieval**, including search/ranking over sensitive content or embeddings. Forbidden: global search → retrieve unauthorized candidates/text → application-filter. Partition isolation alone is insufficient when private Persons coexist inside one partition.

A future repository/provider receives from trusted orchestration, not the model:

- The bound partition and trusted human/machine/request context.
- The requested operation and authorized typed scope constraints.
- Home-backed requirements/decisions tied to the same actor, partition, resource, domain and action; every claim must satisfy its **entire** subject set and every required domain, not merely intersect an allowed-Person list.
- Protected, validated claim security metadata: scope, complete subjects/domains, applicable subject/source restrictions and the object version to which those apply.
- Current eligibility and authority-state information adequate to detect invalidation. B6 defines the concrete freshness, concurrency and final revalidation protocol.
- Separate constraints for any source expansion, derivative, cache lookup or canonical-domain fetch; knowing a source ID is not authorization.

An initial protected authorization-metadata lookup inside the trusted boundary is distinct from retrieving claim statements, snippets or vectors. It must itself be partition-bound, minimized and undisclosed to the model. The repository uses it to establish eligibility before content search; unauthorized text must not be fetched to discover how it should have been authorized. Unclassified content cannot enter the usable retrieval set.

Apply constraints to direct-ID reads, keyword and vector retrieval, chunks, embeddings, query expansion using stored material, candidate selection, reranking, source expansion/evidence lookup, summaries, caches and final assembly. Do not reuse an earlier bundle's `authorized_domains` as a bearer permission. A deny, missing tuple, unknown state, authority outage or oversized compound request denies as a whole; never truncate requirements to fit today's eight-entry, one-Person API. B6 must define the concrete retrieval protocol, freshness, bounded batching and revalidation consistent with single-use delegation. No index/search/storage technology is chosen.

## 11. Mandatory acceptance scenarios A–H

These are **conceptual expected results**, not implemented tests or production validation. P is the trusted current partition, E is synthetic Erick, A is synthetic Ana, and H is a synthetic Household Circle in P. Assume valid/current claims for the requested use; authorization alone does not settle B3 eligibility.

### A — Personal

“I prefer Mediterranean food,” asserted by authenticated E.

- Shape: partition P; PERSON/E; subjects `{E}`; assertor E; content domain NUTRITION, with KNOWLEDGE governance. This does not resolve Nutrition preference ownership (B5).
- CREATE requires E's KNOWLEDGE and NUTRITION CREATE+VIEW. Typed Person self-access satisfies these after partition/reference validation. A source read, if needed, has separate checks.
- Later E VIEW passes own checks; another viewer needs effective Person/E KNOWLEDGE/VIEW **and** NUTRITION/VIEW. A NUTRITION-only grant is insufficient. No grant about Ana is needed.
- Expected: authorized personal capture/read; unrelated viewer denied before retrieval.

### B — Pure household context

“Our family normally eats dinner around 19:00,” asserted by E.

- Shape: P; CIRCLE/H; subjects `{}`; assertor E; D=`{HOUSEHOLD}`.
- CREATE requires explicit H KNOWLEDGE and HOUSEHOLD CREATE+VIEW; membership or authorship supplies neither. E's self-access is irrelevant to the Circle resource.
- If E deliberately created H through the authorized authenticated Home process, that operation may have atomically recorded E's acceptance of initial stewardship and established the required bounded Circle MANAGE grants. Those grants can satisfy the corresponding checks; first membership or a role label cannot. Imported H without a valid steward requires trusted designation/recovery.
- VIEW requires explicit H KNOWLEDGE/VIEW and HOUSEHOLD/VIEW. With zero subjects there are still two resource/domain requirements; no empty authorization loop.
- Correction requires VIEW+UPDATE and authorized replacement creation. Steward endorsement of shared Circle use requires Circle MANAGE under section 8.2; no invented Ana confirmation. Whole-claim removal requires the steward's required MANAGE; E can separately retract E's assertion without claiming to erase others' sources.
- Expected: explicit Circle grants enable genuinely subjectless routine Knowledge; membership-only caller denied.

### C — Multi-person decision

“Erick and Ana decided not to move this year,” said by E about their household decision.

- Shape: P; CIRCLE/H; subjects `{E,A}`; assertor E only; D=`{HOUSEHOLD}`. CIRCLE is appropriate for this joint household decision. A reusable/shared assertion placed in E's personal context could instead use PERSON/E, but would still include A and preserve A's restrictions. Private third-party assertions are separately deferred, not authorized by choosing PERSON/E.
- CREATE: H, E and A each require KNOWLEDGE and HOUSEHOLD CREATE+VIEW. E's self-access covers only E. Without Ana's relevant consent, do not admit the shared claim as usable Knowledge.
- VIEW by any actor requires all six resource/domain VIEW tuples. Ana is not automatically able to read E's private information; self-access satisfies only her tuples.
- E can propose correction only with the operation's complete permissions. Ana may record an authorized challenge or use the narrow own-subject objection path; no full joint read is granted just to dispute it. Neither party may overwrite the other's attestation. Steward endorsement does not establish that Ana agreed; no family-consensus state is created. B3 retains detailed confirmation/lifecycle semantics.
- Expected: intersection-based disclosure and attributed disagreement; no “newest author wins.”

### D — Circle wrapper containing private Person data

“Our family eats early because Ana has health condition X.”

- Shape: P; CIRCLE/H; subjects at least `{A}`; assertor the proven speaker; D=`{HOUSEHOLD,HEALTH}`. Include any other Person whose individual information the actual content reveals; the generic family reference alone does not enumerate all members.
- VIEW requires H KNOWLEDGE/VIEW, HOUSEHOLD/VIEW, HEALTH/VIEW **AND** A KNOWLEDGE/VIEW, HOUSEHOLD/VIEW, HEALTH/VIEW under the conservative all-domain rule. CREATE requires the corresponding CREATE+VIEW checks, plus separately authorized evidence reads.
- H HEALTH permission is only Circle handling authority; it cannot supply A HEALTH consent. A missing A HEALTH/VIEW denies the **whole inseparable statement**, its revealing snippet and sensitive derivative candidate. A KNOWLEDGE-only grant does not cure that denial.
- If condition X came from a private source, that source's applicable restrictions also remain. A separate independently authorized routine might be viewable, but automatically stripping the rationale is not approved declassification.
- Expected: the Circle wrapper never bypasses Ana's HEALTH restriction. No clinical fact is created in a canonical Health service by this example.

### E — Household member without another adult's private access

A legitimate member V has explicit H KNOWLEDGE/VIEW and HOUSEHOLD/VIEW, but no A HEALTH/VIEW.

- V can view B's pure routine when eligible, even though it has no Person subjects.
- V cannot view D. Even adding H HEALTH/VIEW would leave the A HEALTH requirement unsatisfied.
- Remove V's explicit Circle grants and membership alone no longer permits even B.
- Expected: shared routines and private adult Health restrictions coexist without separate service ACLs.

### F — Circle exit

E leaves H.

- The exit process invalidates E's H grants and reconciles any dependent stewardship grants before completing. Future Circle reads of both historical and new claims deny; prior membership and authorship do not help.
- Assertions authored by E preserve historical attribution, subject to later retention rules; E retains only the narrow own-assertion retraction path absent renewed read authority.
- Claims about E continue to include E as subject. E can restrict access/non-use concerning E without gaining access to Ana's private content or automatically erasing everyone else's record.
- Independent Person grants remain explicit and require review; the process does not silently equate Circle exit with universal consent revocation. Rejoining does not revive old Circle grants.
- Previously disclosed content cannot be undisclosed. B6 must stop unauthorized future retrieval/reuse; B4 defines source and derivative cleanup.
- Expected: no permanent historical membership privilege, no loss of attribution, no promise of retroactive secrecy.

### G — Cross-partition attack

A request combines Person from partition P-A with Circle from P-B.

- Trusted context binds only one partition. Protected reference resolution cannot find both as valid local typed resources; fail closed before claim/source/vector content retrieval or claim creation.
- Never fetch from both partitions to decide, fall back to a global ID search, or disclose which outside reference exists. Self-access, matching local ID strings and Circle MANAGE do not override this boundary.
- Expected: non-enumerating denial and no sensitive retrieval.

### H — Forged actor or partition

LLM/tool payload includes `actor_person_id=someone_else` and `security_partition_id=another_partition`.

- These are not permitted authoritative business/tool inputs. Recommend rejecting unexpected security-context fields at the request boundary; adapters must never forward them as trusted context. If a transport ignores unknown fields, the values must remain inert and server-derived context still governs.
- Resolve actor from validated G1.6 session and bind partition through trusted infrastructure. A missing trusted binding denies even if payload values look valid. A forged header, extracted instruction or job variable is equally inert.
- Expected: rejection or inert unknown fields, no impersonation/partition switch, no retrieval under forged authority.

### Deferred scenario — Private third-party assertion

Erick privately tells his personal Olin: “Ana likes blue.”

**Intentionally NOT solved by B1: PRIVATE THIRD-PARTY ASSERTIONS = DEFERRED PRODUCT/PRIVACY MODEL.** A possible future distinction between Erick's private attributed personal assertion and reusable/shared Knowledge about Ana requires separate design. It is not part of the initial Knowledge runtime.

The initial reusable/shared Knowledge model must not admit this as active shared Knowledge without the normal Ana subject restrictions. Private wording, authorship or a PERSON scope cannot bypass those checks. This deferral preserves the ability to design private personal notes/assertions later; it is neither a permanent prohibition on them nor authorization to implement that future model now.

## 12. Rejected alternatives and explicit limits

- **Circle equals Tenant:** confuses overlapping social context with isolation and makes future care/household transitions unsafe.
- **Use a household-owner Person as a fake subject:** misstates subjecthood and lets one person's grants impersonate Circle authority.
- **Membership, caregiver/guardian labels or authorship as authorization:** contradicts the accepted Home boundary and can persist after the relationship ends.
- **One consenting subject, majority consent, or the least restrictive domain wins:** exposes another adult's private information. All required checks must pass.
- **Circle MANAGE includes all members' HEALTH/FINANCE:** a steward cannot grant another person's consent or establish clinical/financial truth.
- **Remove subjects/relabel as KNOWLEDGE to share:** changes labels without removing disclosure; rejected before admission/reclassification.
- **General-purpose ACL/policy engine or service-local grant tables:** unnecessary for two demonstrated resource kinds and prone to policy drift.
- **Vector metadata/ContextBundle as authority; retrieve then filter:** cannot establish trusted identity, complete candidate isolation or fresh permission.
- **Erase provenance when somebody leaves; retain read access because they authored it:** neither follows from membership or authorship.
- **A workflow per claim or technology-led design:** does not answer who may authorize an operation; no workflow engine is selected.

## 13. Product Architect disposition

Decision owner: Product Architect

Decision date: 2026-09-19

Disposition: ACCEPTED WITH AMENDMENTS — B1 RESOLVED. The Product Architect explicitly accepted the core model and the amendments below. This accepted proposal governs B1 where older Knowledge documentation is less precise, until later consolidation. Acceptance is the Product Architect's decision, not an inference from a PR merge; PR #20 remains unmerged by this task.

| Decision | Accepted disposition and amendments |
|---|---|
| 1. Security partition | Exactly one trusted partition per durable Knowledge object/derivative, distinct from Person, Circle, scope, membership and commercial Tenant. No Tenant entity now. Effective identity includes `(partition, resource_type, local_id)`. Initial cross-partition references, joins, sharing, sensitive deduplication and retrieval forbidden. Actor/partition are trusted runtime context. |
| 2. Scope and subjects | PERSON scope includes its Person among subjects. CIRCLE may have no subjects only when genuinely about the Circle; identifiable private Person information still contributes that Person's restrictions. |
| 3. Authorization composition | For reusable/shared Knowledge, scope AND every Person subject AND every required domain. Self-access covers only one's own Person requirement. No majority, membership, authorship or Circle-MANAGE bypass. B2 may relax only through an explicit approved projection/declassification model. |
| 4. Private third-party assertions | Deferred product/privacy model, excluded from the initial runtime. Preserve future private-personal-assertion design without permitting unauthorized active shared Knowledge today. |
| 5. Grant model and terminology | Accept A's bounded PERSON/CIRCLE structure within one Authorization Grant family/evaluation model and one Home authority. PERSON is consent/access authority; CIRCLE is handling/stewardship authority, not personal consent. Existing ConsentGrant name may remain; eventual persisted naming is an implementation/migration decision. Arbitrary-resource B is not adopted. |
| 6. Stewardship bootstrap | An authorized authenticated create-Circle process may atomically create the Circle, record the creator's acceptance of initial stewardship, and establish bounded Circle MANAGE. No manual administration required for normal consumer onboarding. Imported/pre-existing Circles need trusted designation/recovery. No membership/role inference, LLM designation, ordinary-recipient redelegation or recursive MANAGE delegation. Root replacement/recovery requires a protected Home process. |
| 7. Assertions and attestations | Actor, assertor, subject, attestor and viewer remain distinct when identities differ. Stewardship endorsement authorizes shared Circle use, not everyone's agreement. No family-consensus state. Detailed confirmation/lifecycle remains B3. |
| 8. Operations | Retain VIEW/CREATE/UPDATE/MANAGE; DISPUTE/CONFIRM/FORGET/SHARE compose them with trusted context and operation predicates. Lifecycle effects remain B3/B4. |
| 9. Withdrawal | Narrow non-disclosing retraction, objection and own-information non-use/suppression do not require another Person's private VIEW, grant VIEW, rewrite others' words or automatically erase independent sources. B4 owns physical erasure/cleanup. |
| 10. Circle transitions | Joining grants nothing; exit/removal invalidates the Person's Circle-derived grants before completion; rejoining revives none. Dissolution stops ordinary Circle use without moving content to Person scope. Authorship gives no perpetual VIEW. Independent Person grants survive membership changes unless separately revoked. No permanent guardian/representative authority; legal representation remains future policy. |
| 11. Retrieval | Trusted partition and authorization establish the eligible candidate space before sensitive retrieval, including direct/keyword/vector reads, chunks, embeddings, summaries, caches, source expansion and reranking. B6 defines concrete protocol/freshness/revalidation. |

B1 has no remaining Product Architect disposition required for the decisions recorded here. The Knowledge Technology Gate remains OPEN; B2–B6 and their process decisions remain OPEN. Initial runtime scope and implementation/migration approval are later decisions, and private third-party assertions are excluded from the initial runtime. No technology or runtime is approved by this disposition.

## 14. Boundaries for later blockers and implementation deferrals

| Blocker | Accepted B1 input | Remains open |
|---|---|---|
| B2 — sensitivity | Distinct partition/scope/subjects; all required permissions intersect; Circle/source wrappers cannot discard Person domains; claims and sources separately gated. | Classification, source/excerpt inheritance, per-subject domain precision, approved projections, attribution disclosure. |
| B3 — lifecycle | Actor/assertor/subject/steward are distinct; operation authority and non-impersonation rules; endorsement is not consensus. | Activation, confirmation evidence/state rules, dispute resolution, atomic correction/supersession and concurrency. |
| B4 — forget/dependencies | Partition coverage for all artifacts; subject/author withdrawal authority versus whole-claim removal; no privilege from historical membership. | Dependency types, immediate suppression mechanism, retained evidence, physical erasure, jobs, restore and cleanup mandates. |
| B5 — ownership | Home remains identity/grant/policy authority. | Nutrition preference ownership and the Knowledge persistence owner/service boundary; no decisions changed here. |
| B6 — retrieval | Trusted actor/partition; explicit typed scope and complete subject/domain constraints before sensitive candidates; no stale grant reuse or partial decision coverage. | Repository interface, freshness protocol, race handling, final revalidation, working-memory invalidation and task limits. |

Explicitly deferred: changes to `packages/home-contracts/`, Person/Circle/Membership/Care/Consent DocTypes, authorization engine, Home APIs/MCP, Nutrition, Knowledge/ContextBundle contracts, provisioning and deployment. Persisted grant naming is an implementation/migration decision; no rename is required here. Private third-party assertions remain a deferred product/privacy model outside the initial runtime. No `svc-knowledge`, tables, database, vector index, extraction engine, workflow or tool is created. No commercial Tenant/billing/support system, guardian/legal model, generalized policy engine, key-management scheme or technology selection is approved.

## 15. Review and verification boundary

This change contains only this accepted proposal and B1 status/reference edits in `KNOWLEDGE_TECHNOLOGY_GATE.md`. Other canonical architecture and accepted ADR files remain unchanged; this accepted proposal governs B1 precision until later consolidation. Scenarios A–H remain architecture acceptance specifications, not runtime tests. The additional private-third-party-assertion scenario records a deferral, not a new runtime behavior.

Verify from the proposal branch:

```powershell
git diff --check origin/main...HEAD
git diff --name-only origin/main...HEAD
git status --short --branch
```

Expected changed paths: `docs/architecture/proposals/KNOWLEDGE_B1_SECURITY_SCOPE.md` and `docs/architecture/proposals/KNOWLEDGE_TECHNOLOGY_GATE.md`. B1 is **RESOLVED BY PRODUCT ARCHITECT DECISION** dated 2026-09-19; B2–B6 and the Knowledge Technology Gate remain OPEN. No technology, runtime or production change is included.
