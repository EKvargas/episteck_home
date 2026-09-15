# Stage G1.5 Final Validation

**Result:** PASS

**Validated:** 2026-09-15

**Scope:** synthetic identities and synthetic domain data only; G2 was not started.

## 1. Recovered starting state

- The local takeover checkout was clean on `main` at `1003761` after reading the
  canonical architecture set, every ADR, and commits `a8b5a7b`, `81c836d`, and
  `1003761`.
- The Ashburn source checkout was clean at `1003761`. The live Frappe app content
  matched that source. Its Git metadata reflected the already-understood
  shallow-to-triple-nested DocType transition; no unique or unfinished app content
  was overwritten.
- Nutrition and Home Agent were operational on Nuremberg. Nutrition still used its
  Stage F local consent path at takeover.
- No conflicting or unexplained uncommitted work was found.

## 2. Delivered boundaries

### Home Core application API

Actor-aware enforcement now lives in Frappe, not only at MCP:

- linked human Users may act only as their linked Person;
- explicitly allowlisted machine Users may supply a synthetic actor during G1.5;
- `get_person` decides discoverability before loading the Person and gives the same
  not-found response for missing and unrelated ids;
- circle rosters require membership by the resolved actor;
- care relationships and dashboards are filtered to the resolved actor;
- effective-access queries expose only that actor's decisions;
- circle/care context never substitutes for domain authorization.

### Home MCP

The dedicated rootless `svc-home-mcp` service exposes exactly seven business tools:

1. `get_person`
2. `list_my_circles`
3. `list_circle_members`
4. `list_people_i_care_for`
5. `get_access_to_person`
6. `check_access`
7. `get_care_dashboard`

It owns no Home data and exposes no consent mutation. Display casing from an agent is
canonicalized before Frappe validates the exact domain/action; Frappe remains the sole
decision authority.

### Nutrition cutover

Every person-specific Nutrition repository read or write is preceded by an exact
Home `check_access` decision. The dedicated client uses the private Tailscale route,
has a three-second timeout, performs no caching, and treats transport, HTTP, JSON,
shape, or decision ambiguity as DENY.

The old SQLite consent table remains with one synthetic row for migration/audit only.
It is not queried by authorization, `has_consent` no longer exists, and both legacy
HTTP consent endpoints return 404. There is no second active consent authority.

## 3. Automated verification

| Suite | Result |
| --- | ---: |
| Home policy and actor-aware API | 22 passed (including 11 pure policy tests) |
| Nutrition service and canonical domain | 51 passed |
| Knowledge and ContextBundle contracts | 12 passed |
| Home MCP client and fail-closed behavior | 8 passed |
| **Total** | **93 passed** |

Python compilation and Git whitespace checks also passed. No credential or secret
path is tracked in Git.

## 4. Synthetic live authorization matrix

| Case | Expected | Observed |
| --- | --- | --- |
| PSN-00002 -> PSN-00001, NUTRITION:VIEW | ALLOW | Home allow; Nutrition HTTP 200 |
| PSN-00002 -> PSN-00001, MIND:VIEW | DENY | no matching active grant |
| wrong actor PSN-00003 -> PSN-00001 | DENY | Nutrition HTTP 403 |
| wrong subject PSN-00002 -> PSN-00003 | DENY | Nutrition HTTP 403 |
| unrelated Person lookup | non-revealing DENY | not-authorized-or-not-found |
| unauthorized circle roster | non-revealing DENY | not-authorized-or-not-found |
| revoked `CG-00011` | DENY | Home deny; Nutrition HTTP 403 |
| Home unreachable/indeterminate | DENY | Nutrition HTTP 403, `authorization indeterminate (fail closed)` |

`CG-00011` remains revoked as audit evidence. `CG-00012` is the final active,
synthetic NUTRITION:VIEW replacement. A temporary unavailable-Home container was
removed after the test and never replaced or interrupted the live services.

## 5. Actual Home Agent conversation results

The live Home Agent used its loopback Home and Nutrition MCP servers:

| Prompt | Synthetic actor | Result |
| --- | --- | --- |
| "What circles am I part of?" | PSN-00002 | SYN Household only |
| "Who am I helping care for?" | PSN-00003 | SYN Ana, COORDINATOR |
| "Who is in my household?" | PSN-00002 | SYN Ben and SYN Ana |
| "What can I access for Person B?" | PSN-00002 | NUTRITION:VIEW only |
| "Can I see Person B's Nutrition?" | PSN-00002 | Home ALLOW, then Nutrition synthetic profile |
| "Can I see Person B's Mind data?" | PSN-00002 | DENY; no alternate route attempted |

The redacted allow trace shows Home `check_access` before the Nutrition tool. The
revocation trace shows only Home `check_access`; after DENY the agent made no
Nutrition call, changed no identity, and attempted no escalation.

The first conversational pass revealed that the model supplied `nutrition` in lower
case. The adapter initially denied that malformed value, while Nutrition's internal
canonical request independently allowed. This was not a service bypass, but the agent
had continued after its direct denial. PR #2 canonicalized display casing and the
Home Agent now has a persistent deny-stop rule. Both allow and revoked-deny traces
then passed.

## 6. Latency measurements

Thirty warm/live samples were measured from Nuremberg. The direct ping sample creates
a new TLS connection per request; the service samples use the deployed persistent
Home client.

| Path | Median | p95 | Result |
| --- | ---: | ---: | --- |
| Nuremberg -> `home.episteck.com` ping over Tailscale | 307.48 ms | 311.56 ms | 30/30 HTTP 200 |
| Home `check_access` from svc-nutrition | 111.57 ms | 119.88 ms | 30/30 ALLOW |
| Cross-person Nutrition profile request | 114.55 ms | 121.60 ms | 30/30 HTTP 200 |

No distributed authorization cache was introduced.

## 7. Deployment and credentials

- Frappe Home code is deployed only by the `episteck-deploy` job from GitHub `main`.
  A dedicated `episteck_home` deploy block was added without changing the older
  `episteck_dev_factory` block.
- Home MCP runs rootless as `svc-home-mcp` on `127.0.0.1:9932` from code revision
  `243bede`.
- Nutrition API/MCP run rootless as `svc-nutrition` on `127.0.0.1:9930/9931` from
  cutover revision `7af4cd8`.
- Home MCP and Nutrition use different Frappe Website Users with zero privileged
  roles. Generic Consent Grant REST access returned 403.
- Credentials are owner-readable mode 0600 files. `home-agent` cannot read either
  file and receives only loopback MCP URLs.

Implementation was merged through
[PR #1](https://github.com/EKvargas/episteck_home/pull/1) and the runtime-discovered
input hardening through
[PR #2](https://github.com/EKvargas/episteck_home/pull/2).

## 8. Knowledge contracts

`packages/home-contracts` is dependency-free and formalizes `KnowledgeScope`,
`KnowledgeEpisode`, `KnowledgeClaim`, provenance, lifecycle status, and
`ContextBundle`. Confirmation creates a new `USER_CONFIRMED` claim referencing the
AI hypothesis; it never rewrites hypothesis provenance. Structured domain truth is a
reference, credentials are rejected as Knowledge, and ContextBundle requires prior
matching authorization for sensitive content.

No retrieval engine, persistence service, Mem0, Graphiti, RAGFlow, pgvector,
Postgres-for-Knowledge, or Docling was installed. Live package scans found none of
the prohibited Knowledge runtimes in the G1.5 Home/Nutrition images.

## 9. Security findings and remaining blocker

- **Hard G2 blocker:** explicit `actor_person_id` is synthetic test context, not
  authentication. No real family data may reach Home Agent until an authenticated
  session is authoritatively bound to exactly one allowed Person and actor
  substitution tests pass.
- Authorization precedes sensitive retrieval in Home and Nutrition.
- Machine credentials cannot mutate Consent Grant through MCP or generic REST.
- Denial, revocation, wrong tuple, wrong domain, and unavailable authority all fail
  closed.
- All live validation records are synthetic. No real family member or real pregnancy
  profile was created.

## 10. Proposed Knowledge Technology Gate

Do not select or install a runtime until all of these are approved:

1. Trusted actor/session binding is live and substitution-tested.
2. One narrow Knowledge use case and measurable retrieval quality target are chosen.
3. Scope/Claim/Episode persistence, deletion, correction, retention, and provenance
   semantics are specified against the pure contracts.
4. Authorization-before-retrieval and source-level revocation have adversarial tests.
5. Nuremberg capacity, backup/restore, encryption, and data-residency impacts are
   measured.
6. Candidate technology is evaluated behind the Episteck governance boundary;
   Graphiti remains deferred and RAGFlow remains rejected unless a new ADR changes
   that decision.
7. An ADR and explicit user approval authorize the selected runtime.

## 11. Proposed G2 real-family onboarding sequence

G2 remains blocked. When the blocker is resolved, proceed in this order:

1. Implement authenticated session-to-Person binding outside agent-supplied inputs.
2. Prove actor substitution, replay, wrong-session, and service-credential isolation
   failures.
3. Obtain explicit approval to begin G2.
4. Create the first real Person as self-only; verify discovery denial from every
   unrelated identity.
5. Add real circles/care relationships incrementally; keep them non-authorizing.
6. Add a confirmed-user consent grant/revoke flow and verify audit/revocation.
7. Create the real Pregnancy Nutrition Profile only after the exact grant is active.
8. Validate providers, meal planning, planned-to-actual intake, and agent denial with
   real-session binding.
9. Re-run privacy, backup/restore, deletion, latency, and incident rollback checks.

Stop after those prerequisites and obtain the next explicit stage approval; do not
infer permission to add more real people or domains.
