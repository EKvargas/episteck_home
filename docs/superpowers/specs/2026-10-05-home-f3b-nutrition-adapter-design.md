# Home F3b — Nutrition server adapter: implementation design

**Date:** 2026-10-05 (revised 2026-10-06)
**Status:** Approved for implementation (2026-10-10): Rev 2, decisions D1–D3, and the implementation plan `docs/superpowers/plans/2026-10-06-home-f3b-nutrition-adapter.md`. Execution: subagent-driven. Merges and production deploys still require the operator's explicit go at each gate.
**Parent architecture:** `docs/architecture/proposals/HOME_F3_ACTIVE_CONTEXT_DOMAIN_INTEGRATION.md` (Board-approved, PR #48), §4–§10. This spec fixes the implementation detail for phase F3b. Decision D1 corrects one §5 detail that conflicts with the deployed G1.6 code; nothing else in the architecture changes.
**Baseline:** `origin/main` `6d4e361` (F3a live verification PASS, PR #57).
**Independence:** F3b has no dependency on Knowledge/KAP work or the Ambient Bento theme, and neither depends on F3b.

## Purpose

Give the Hub server a safe, typed way to read one Person's Nutrition profile summary, so F3c can replace the mock Nutrition cluster with real data. F3b ships no UI.

```text
Hub server → BFF POST /delegation?audience=svc-nutrition (session cookie only)
          → Nutrition GET /profile/{S} (X-Episteck-Delegation)
          → Home check_access(S, NUTRITION, VIEW)  — actor derived by Home
          → profile read only after literal ALLOW, or 404
          → Hub strict mapper → DataEnvelope<ProfileSummary>
```

## Invariants carried from the architecture

- No actor, domain, or action is accepted from any caller on this path. The subject comes only from a validated `F3ActiveContext`.
- Exactly one delegation mint and one Home policy request per profile read.
- No decision or domain-data cache anywhere (Hub, BFF, Nutrition, CDN, browser). `no-store` throughout.
- Every positive authorization requires that the subject Person currently exists.
- Missing subject and unauthorized subject are indistinguishable to callers.
- Delegations never carry a Person ID (G1.6, `test_delegation_carries_no_person_id`).
- No production fixtures, Persons, grants, or Nutrition profiles are created. An authorized `ABSENT` is a valid live proof.
- `Network=host` and broad exposure are never fallbacks.
- Production deploys are run by the operator.

## Requirement traceability

| Requirement | Where it is specified |
| --- | --- |
| Exact 401 / 403 / 503 conditions; fail closed; no Home reason text | F3b.2 "Outcome contract" (tables 1 and 2) |
| `reason` mandatory but never interpreted | F3b.2 "Outcome contract", rule R |
| Delegation bound to actor, subject, Nutrition audience, read operation; tokens server-side; no Nutrition call when minting fails | D1, D2, F3b.1 "Delegation audience binding", F3b.3 "Loader" steps 3–4 |
| Required `/delegation` fields validated, extra fields tolerated; where expiry is enforced | F3b.3 "Loader" step 3; D3 |
| Only explicit `ProfileSummary` fields; malformed and missing profiles; no mock substitution | F3b.3 "Contract" and "Loader" mapping table |
| Transport verified from the Hub runtime; 9931/9932/9934 blocked; restart verification; rollback; pasta resolved before rollout; stop if isolation unproven | F3b.3 "Transport" and "Rollout gate" |
| Tests: missing subject vs no grant, cross-subject, invalid/expired delegation, dependency failures, malformed responses, authorized reads | Test sections of F3b.1, F3b.2, F3b.3 |
| F3a verified on a stable frontend baseline before rollout | "Pre-rollout baseline evidence" |

## Decisions

### D1 — Caller-bound `svc-nutrition` audience (corrects §5 against G1.6 code)

**Finding.** Architecture §5 has the Hub mint `audience=svc-nutrition`. Nutrition does not verify delegations; it forwards them to Home. Home's `auth_hook` verifies every delegation against `expected_audience="home-control-plane"` only, and G1.6 pins that with `test_wrong_audience_denies`. A `svc-nutrition` token therefore never binds at Home today, so §5 as written yields `SESSION_INVALID` on every read. The live Hermes → Nutrition path works because the gateway mints `home-control-plane` tokens.

**Decision (recommended).** Home accepts a `svc-nutrition` delegation **only when the authenticated machine caller is Nutrition's own API User**, named by the new site-config key `home_nutrition_machine_user`. `home-control-plane` remains accepted from any authenticated machine caller, so the existing Hermes and Home MCP paths are unchanged. A `svc-nutrition`-bound actor may be used only by the two policy entry points `check_access` and `check_access_many`; every other Home business method refuses it. If the config key is unset, `svc-nutrition` never binds (fail closed). The existing G1.6 test still holds: a `svc-nutrition` token presented by Home MCP is denied.

**Effect.** A Hub-minted token is useless to any machine caller except Nutrition, and even Nutrition can use it only for one policy decision.

**Rejected alternative.** Mint `home-control-plane` from the Hub. No Home change, but the token would be usable by any machine caller and would not satisfy "bound to the Nutrition audience".

### D2 — How the delegation is bound to actor, subject, and operation

G1.6 forbids Person IDs in delegation tokens, and the BFF cannot validate a subject. Subject and operation are therefore bound by the protocol, not by token claims:

| Binding | Mechanism | Enforced by |
| --- | --- | --- |
| Actor | Token carries only the opaque `sid`; Home maps session → User → unique `Person.linked_user` | Home `auth_hook` + `resolve_principals` |
| Audience | `aud=svc-nutrition`, accepted only from Nutrition's machine credential (D1) | Home `auth_hook` |
| Operation | Single-use `jti` allows exactly one Home request; a `svc-nutrition` actor is accepted only by `check_access`/`check_access_many`; Nutrition's `/profile` route fixes `NUTRITION`/`VIEW` in code | Home replay store + `resolve_principals`; Nutrition service |
| Subject | Hub takes it only from the validated `F3ActiveContext` and puts it in the Nutrition path; Home authorizes that exact subject freshly, including existence | Hub adapter; Home policy boundary |
| Server-side only | Token minted server-to-server on loopback; never in a browser response, envelope, log, URL query, or retry | Hub loader; BFF `access_log=False` |

**Rejected alternative.** Add subject and operation claims to the token. This violates the G1.6 no-Person-ID invariant and adds no protection against Nutrition itself, which already owns the data the token unlocks.

### D3 — Delegation expiry

Expiry is enforced **only by Home** (`identity/delegation.verify`): `now >= exp` denies, `iat` in the future denies, and lifetime above 300 s denies. The BFF mints with a 120 s TTL. The Hub mints immediately before its single Nutrition call and never reuses, caches, or retries a token. Nutrition treats the token as opaque and never checks expiry. An expired token surfaces as Home 403 → Nutrition 401 `SESSION_INVALID` → Hub `SESSION_INVALID`.

## Delivery shape

Three PRs, merged and deployed in order. Each is backward compatible; nothing calls the new path until its dependencies are live.

| PR | Scope | Deploy target |
| --- | --- | --- |
| F3b.1 | Home subject-existence guard + caller-bound `svc-nutrition` audience (D1) | Ashburn Frappe bench via the `main` → episteck-deploy job; one site-config key set by the operator |
| F3b.2 | Nutrition typed authorization outcomes | Nuremberg `svc-nutrition` image + both Nutrition Quadlets' `Image=` |
| F3b.3 | Hub Nutrition adapter + narrow 9930 transport | Nuremberg `svc-home-hub` image + Quadlet `Image=`/`Network=`/`Environment=` |

---

## F3b.1 — Home subject-existence guard and delegation audience binding

### Subject-existence guard

`apps/episteck_home/episteck_home/policy/wrappers.py:check_access` is the single function through which every authorization decision flows: `api.check_access`, `api.check_access_many` (per requirement), `api._has_effective_access`, and `api.get_access_to_person`. The guard lives there.

- Input validation runs first: if actor or subject is empty, or domain/action is not in `DOMAINS`/`ACTIONS`, the pure evaluator's "invalid or unknown request" deny is returned **without** an existence lookup. This keeps the existence result out of the invalid-input answer, so it cannot become an oracle.
- New helper `_subject_exists(subject_person_id) -> bool` calls `frappe.db.exists("Person", subject_person_id)`. It runs on every call; no cache across or within requests.
- If the subject does not exist, `check_access` returns `{"allow": False, "reason": "no consent grant (fail closed)"}` — identical to the answer for an existing subject with zero grants — and does not load grants. An orphaned grant for a deleted Person cannot produce `ALLOW`.
- An exception from the lookup falls into the existing `except` and returns the generic `policy error (fail closed)` deny.
- Self requests also pass through the guard.
- Person has no status or soft-delete field (`full_name`, `external_ref`, `linked_user`, `notes`), so existence means the row exists. No schema change and no migrate.
- `check_access_many` needs no code change: a missing subject makes every per-requirement decision deny, so the overall result is `allow: false` with no positive decision.

### Delegation audience binding (D1)

- `identity/delegation.verify` accepts `expected_audience` as a string **or** a set of strings; the token's `aud` must be a member. An empty set fails closed.
- `identity/auth_hook` computes the accepted set per request: `{"home-control-plane"}`, plus `"svc-nutrition"` only when `frappe.session.user == conf.home_nutrition_machine_user` (key present and non-empty). Wrong-audience tokens fail verification **before** the replay claim, so they cannot burn a legitimate token ID (existing behavior).
- On a successful bind the hook records `frappe.local.episteck_delegation_audience`; it resets it to `None` at the start of every request.
- `identity/actor.resolve_principals(*, accept_audiences=frozenset({"home-control-plane"}))`: when a delegated user is bound and the recorded audience is not in `accept_audiences`, it throws `PermissionError` (denial category `actor.delegation_audience_not_accepted`). `resolve_actor` passes the argument through.
- `api.check_access` and `api.check_access_many` call `resolve_actor(accept_audiences=POLICY_AUDIENCES)` with `POLICY_AUDIENCES = {"home-control-plane", "svc-nutrition"}`. All other methods keep the default and refuse `svc-nutrition`.

### Tests (`apps/episteck_home/tests`, pytest, fake-frappe harness)

New `test_policy_boundary.py`:

1. Missing subject with an active orphaned grant → deny; grants are not loaded.
2. Missing-subject response equals the existing-subject-no-grant response exactly.
3. Cross-subject: existing subject with an active `NUTRITION/VIEW` grant → allow; same actor, a different existing subject without a grant → deny.
4. Self access still allows.
5. Bootstrap-then-delete race: allow, delete the Person, next call denies.
6. Existence lookup raising → generic fail-closed deny.
7. Invalid domain gives the same answer for a missing and an existing subject (no oracle), with no existence lookup.
8. Two calls → two existence lookups (no cache).
9. API level with the real wrapper: `check_access` and `check_access_many` for a missing subject return no positive decision and the same reasons as for an existing subject without grants.

`test_delegation.py`: set-valued audience accepts a member, rejects a non-member, empty set fails closed, string form unchanged.

`test_auth_hook.py`: `svc-nutrition` binds only for the configured Nutrition caller and records its audience; it denies from another caller, and when the key is unset; a rejected `svc-nutrition` token does not burn its ID; expired `svc-nutrition` token denies; control-plane binding records `home-control-plane`.

`test_home_api_security.py`: a `svc-nutrition`-bound actor is accepted by `check_access` and `check_access_many` and refused by every other actor-resolving method; a bound delegated user with no recorded audience is refused.

The full existing suite passes; fixtures that set `episteck_delegated_user` directly also set `episteck_delegation_audience = "home-control-plane"`.

### Rollout and rollback gate (R1)

Pre-merge: full Home test suite green in CI/locally.

1. Merge; the episteck-deploy job mirrors `main` to the Ashburn bench (~5 min). Confirm the deployed `policy/wrappers.py`, `identity/auth_hook.py`, `identity/actor.py`, `identity/delegation.py`, and `api.py` SHA-256 match the merge commit.
2. Read-only `bench --site home.episteck.com execute` checks of `episteck_home.policy.wrappers.check_access`: operator self → allow; a synthetic non-existent subject → the no-grant deny.
3. Regression: the established G1.6 live check through Hermes (operator asks the Home Agent for their own Nutrition access) still allows self. This exercises a `home-control-plane` delegation end to end.
4. Operator reads Nutrition's API username (the Frappe User owning Nutrition's `HOME_API_KEY`) and sets `bench --site home.episteck.com set-config home_nutrition_machine_user <username>`. Verify with `bench execute` that `frappe.conf.home_nutrition_machine_user` is set. Nothing mints `svc-nutrition` tokens until F3b.3, so this is inert.

Rollback: revert the merge on `main` (PR) and let the job redeploy; remove the config key. Stop and roll back if step 2 or 3 fails.

---

## F3b.2 — Nutrition typed authorization outcomes

### Outcome contract

**Table 1 — Home answer → outcome** (`home_control/client.py`, both `check_access` and `check_access_many`):

| Home answer | Outcome |
| --- | --- |
| HTTP 200, `message` is an object, `allow` is a boolean, `reason` is a non-empty string; `allow: true` | `ALLOW` (batch: only with exact positional coverage, as today) |
| Same well-formed shape with `allow: false` | `DENY` |
| No delegation supplied | `SESSION_INVALID` |
| HTTP 401 or 403 from Home (actor could not be resolved: invalid, expired, replayed, wrong-audience, or logged-out delegation; also a broken Nutrition credential) | `SESSION_INVALID` |
| Timeout, connection error, any other non-200 status | `UNAVAILABLE` |
| HTTP 200 with a non-JSON body or any other shape, including `allow: true` with a missing, empty, or non-string `reason` | `UNAVAILABLE` |
| Missing subject/domain/action argument; batch coverage or order mismatch | `UNAVAILABLE` |

**Rule R.** `reason` is mandatory for a response to be well-formed, and an incomplete response is rejected. Its wording is never interpreted: only the boolean `allow` (plus batch coverage) decides, and the reason is never returned to callers.

**Table 2 — outcome → HTTP** (`main.py`, `_authorized`, most specific first):

| Outcome | Exception | Status | Body |
| --- | --- | --- | --- |
| `SESSION_INVALID` | `SessionInvalid` | 401 | `{"detail": "SESSION_INVALID"}` |
| `UNAVAILABLE` | `PolicyUnavailable` | 503 | `{"detail": "SERVICE_UNAVAILABLE"}` |
| `DENY` (or any other `PermissionError`) | `AccessDenied` | 403 | `{"detail": "ACCESS_DENIED"}` |
| `ALLOW`, profile present | — | 200 | profile document |
| `ALLOW`, profile absent | — | 404 | `{"detail": "no profile"}` |

So: **401** means the human authentication could not be established; **403** means Home made a valid, well-formed denial; **503** means authorization could not be determined. Every non-`ALLOW` outcome refuses before any repository read.

### Implementation

- `AccessDecision` gains `outcome: str` (`ALLOW`, `DENY`, `SESSION_INVALID`, `UNAVAILABLE`), defaulting from `allow` and excluded from equality so existing `(allow, reason)` comparisons stay valid. `allow` and `outcome` must agree.
- `service.py` adds `AccessDenied`, `SessionInvalid`, `PolicyUnavailable` (all `PermissionError` subclasses, so `app/mcp/server.py` is unaffected). `_require_access` and `_require_all` raise the one matching the outcome.
- Exceptions are re-raised as `HTTPException` with `from None`, so no Home reason is chained into responses or tracebacks.

### Logging

The client logs each non-allow once at WARNING on logger `nutrition.home_control` with a category only: `deny`, `session_invalid`, `home_rejected_credential_or_session`, `home_unreachable`, `home_malformed`, `invalid_request` (a missing subject/domain/action argument, which is a caller bug). No Person ID, delegation value, or Home reason.

### Tests (`services/nutrition/tests`)

- Client matrix covering every row of Table 1, including allow-without-reason → `UNAVAILABLE`, empty reason → `UNAVAILABLE`, Home 401 and 403 → `SESSION_INVALID`, 500 → `UNAVAILABLE`, connect error → `UNAVAILABLE`, non-JSON 200 → `UNAVAILABLE`; one request per call in every case.
- Service: each outcome raises its exception and never calls the repository.
- Route (`/profile/{id}` with a real `NutritionService`, a scripted authorizer, and a spy repository): every row of Table 2 with exact status and body; no Home reason text in any body; cross-subject — authorizer allows only subject A, so B gets 403 with no repository read; authorized present and absent profiles.
- Logs contain the category and none of: Person ID, delegation, Home reason.
- Existing suites (`test_one_request_per_operation`, `test_single_call_authorization`, `test_transport_binding`, `test_boundaries`) pass.

### Rollout and rollback gate (R2)

1. Read-only discovery on Nuremberg: both Nutrition Quadlets (`nutrition`, `nutrition-mcp`) under `/home/svc-nutrition/.config/containers/systemd/`, their current `Image=`, and the running image IDs.
2. Clean host checkout of the merge SHA; rootless build as `svc-nutrition`: `podman build -f services/nutrition/Dockerfile -t localhost/episteck-nutrition:<SHA> .` from the checkout root.
3. Back up both Quadlets to `/var/backups/episteck/home-f3b2-<SHA>/`.
4. Operator changes only the two `Image=` lines, reloads, restarts. Verify: both active, zero restarts; host `/health` 200; `GET /profile/PSN-00013` without a delegation → 401 `{"detail":"SESSION_INVALID"}`; listeners still `127.0.0.1` 9930/9931; logs free of IDs and tokens.
5. Regression: the Hermes Nutrition path (operator asks the Home Agent for their own Nutrition profile) still works.

Rollback: restore both saved Quadlets, reload, restart; the previous image stays on the host.

---

## F3b.3 — Hub Nutrition adapter and 9930 transport

### Configuration (`apps/home-hub/src/integration/home/server-config.ts`)

`HomeHubServerConfiguration` gains `nutritionBaseUrl?: string` from `HOME_HUB_NUTRITION_BASE_URL`, validated by `configuredOrigin` with the BFF rules: required in LIVE, loopback-only in production, HTTP only on loopback, no credentials/path/query/fragment. Absent in MOCK. Production startup fails without it, so the Quadlet must carry the variable before the new image starts. `next.config.ts` also validates this configuration during `npm run build`, so the Dockerfile builder stage gains `ARG`/`ENV HOME_HUB_NUTRITION_BASE_URL=http://127.0.0.1:9930` next to the existing BFF build variable. The startup-config and server-boundary probes add it.

### Contract (`src/integration/nutrition/profile-contract.ts`, pure)

```ts
type ProfileSummary =
  | { presence: 'PRESENT'; context: string; targetSource: string; targetCount: number }
  | { presence: 'ABSENT' };
```

`parseProfileWire(body)` accepts only a plain object with:

- `context`: string matching `^[A-Z_]{1,32}$`
- `target_source`: string matching `^[A-Z_]{1,32}$`
- `targets`: plain object with at most 64 keys; every value is a finite number **or** a numeric string of at most 32 characters (pregnancy profiles store `str(Decimal)` values); `targetCount` is its key count

Any violation throws `ProfileContractError`. Only those three values are read; preferences, dislikes, intolerances, pregnancy fields, `targets_detail`, and any unknown fields are never copied. `isAbsentProfileBody(body)` is true only for exactly `{"detail": "no profile"}`.

### Loader (`src/integration/nutrition/profile-loader.ts`, pure, injectable)

`loadNutritionProfile({ mode, personId, cookieValue, bffBaseUrl, nutritionBaseUrl, fetcher }): Promise<DataEnvelope<ProfileSummary>>`

1. MOCK mode → fixed mock `READY`/`MOCK` envelope with `presence: 'ABSENT'`, no network. LIVE mode never uses this.
2. No cookie → `SESSION_REQUIRED`; a `personId` not matching `^[A-Za-z0-9-]{1,64}$` → `INVALID_RESPONSE`. Neither makes a network call.
3. `POST {bff}/delegation?audience=svc-nutrition` with `Cookie: episteck_home_session=…`, `cache: 'no-store'`, `redirect: 'manual'`, no body.
   - 200 whose body has a non-empty string `delegation` and `audience === 'svc-nutrition'` → continue (other fields such as `expires_at` are ignored)
   - 401 → `SESSION_INVALID`
   - 200 with a malformed body → `INVALID_RESPONSE`
   - any other status or network error → `SERVICE_UNAVAILABLE`
   - **Any mint failure returns immediately; Nutrition is not called.**
4. `GET {nutrition}/profile/{encodeURIComponent(personId)}` with `X-Episteck-Delegation`, `Accept: application/json`, `cache: 'no-store'`, `redirect: 'manual'`. No cookie is sent to Nutrition. The delegation is used once and never retried, logged, or placed in the envelope.

| Nutrition response | Envelope |
| --- | --- |
| 200 + body passing `parseProfileWire` | `READY`, `GRANTED`, `LIVE`, `data.presence = PRESENT` |
| 404 + `isAbsentProfileBody` | `READY`, `GRANTED`, `LIVE`, `data.presence = ABSENT` |
| 403 | `ERROR`, `DENIED`, `ACCESS_DENIED` |
| 401 | `ERROR`, `INDETERMINATE`, `SESSION_INVALID` |
| 503, other 5xx, network error | `ERROR`, `INDETERMINATE`, `SERVICE_UNAVAILABLE` |
| 200 failing the contract; 404 with any other body; any other status; non-JSON | `ERROR`, `INDETERMINATE`, `INVALID_RESPONSE` |

No error envelope carries data, and no mock value is substituted in LIVE.

### Server wrapper (`src/integration/nutrition/profile.server.ts`, `server-only`)

`readNutritionProfile(context: F3ActiveContext)` reads the session cookie and `SERVER_CONFIGURATION`, then calls `loadNutritionProfile` with `context.personId`. No actor, domain, or action parameter. F3b adds no page or route that calls it; F3c wires it into `/nutrition`.

### Transport (`deploy/home-hub`)

- `svc-home-hub.container`: `Network=pasta:-T,9933,-T,9930` and `Environment=HOME_HUB_NUTRITION_BASE_URL=http://127.0.0.1:9930`. The pasta form is resolved on the host before rollout (step 1 of R3); if a different spelling is required, the Quadlet and tests are updated to that exact form before merge.
- `tests/test_home_hub_quadlet.py` and the runbook isolation probe: 9933 and 9930 reachable; 9931, 9932, 9934 blocked.

### Tests

- `profile-contract.test.ts`: valid present body with numeric and with string targets; each field violation; key bound; extra sensitive fields not copied; absent-body recognizer accepts only the exact body.
- `profile-loader.test.ts` with a fake fetcher: authorized present and absent reads; exactly one mint and one Nutrition call; no network without a cookie or with an invalid `personId`; mint 401/500/network/malformed/wrong-audience → no Nutrition call; Nutrition 401/403/503/500/network/malformed/other-404/unexpected status mappings; cookie only to the BFF; delegation never in the envelope; `no-store` and `redirect: 'manual'` on both calls; subject URL-encoded; MOCK makes no calls.
- `configuration.test.ts`: `HOME_HUB_NUTRITION_BASE_URL` required in LIVE, loopback-only in production.
- `npm run test:server-boundary` covers `profile.server.ts`; `npm run test:startup-config` and `npm run build` pass.

### Rollout and rollback gate (R3)

1. **Resolve pasta before merge.** On Nuremberg, as `svc-home-hub`, run throwaway containers from the current Hub image with `--network pasta:-T,9933,-T,9930`: BFF `/health` 200, Nutrition `/health` 200, 9931/9932/9934 refused or timed out. If this cannot be shown, stop: no merge, no rollout, return for a transport decision.
2. Confirm the F3a baseline (see below) is unchanged.
3. Clean host checkout of the merge SHA; rootless build as `svc-home-hub`; the same throwaway isolation probe with the new image.
4. Back up the Quadlet to `/var/backups/episteck/home-f3b3-<SHA>/`. Operator applies `Image=`, `Network=`, and the new `Environment=` together; the diff must be exactly those three lines. Reload, restart.
5. Verify from the running Hub container: 9933 and 9930 reachable; 9931/9932/9934 not. Host `ss`: 9930/9933/9940 on `127.0.0.1` only. External direct `:9930` and `:9940` time out. Anonymous `/app` 307; F3a context matrix spot check (self default, stale → self).
6. **Restart verification:** restart the Hub service once more and repeat step 5's container probes and `/app` check; zero unexpected restarts.

Rollback (any failure in 3–6): restore the saved Quadlet byte for byte, reload, restart, and repeat the step 5 checks against the old topology (9930 blocked again). The previous image stays on the host. No end-to-end profile read is claimed in F3b; that is F3c's live proof.

## Pre-rollout baseline evidence (F3a)

Recorded 2026-10-06T09:05:56Z, read-only:

- `origin/main` `6d4e361` contains PR #57 (F3a live PASS evidence).
- No changes under `apps/home-hub`, `services/home-bff`, `deploy/home-bff`, or `deploy/home-hub/svc-home-hub.container` between `b1a3d5f` and `6d4e361`.
- Live Hub: `localhost/episteck-home-hub:b1a3d5f…`, image ID `9b0f6470…`, up 18 h, 0 restarts; Hub → BFF `/health` 200; internal `/app` 307.
- nginx log format SHA-256 `3a8d7c0d…919e68` (reviewed).
- Host: pasta `0.0~git20260120.386b5f5-1`, podman `5.7.0`.

Re-checked 2026-10-10T07:39:48Z, read-only, with no change:

- `origin/main` still `6d4e361`; no commits touch `apps/home-hub`, `services/home-bff`, `services/nutrition`, `apps/episteck_home`, `deploy/home-hub`, or `deploy/home-bff`.
- Live Hub still image ID `9b0f6470…`, up 4 days, 0 restarts.
- Quadlet SHA-256 prefix `f75178fc…`, same as 2026-10-06.
- nginx log format `3a8d7c0d…`.
- Hub → BFF `/health` 200; internal and public `/app` 307.
- Listeners 9930/9931/9933/9940 on `127.0.0.1` only.

This is re-checked again immediately before R3.

## Out of scope

- Any UI change (F3c).
- Cross-person live checks and any real topology or data (G2-gated).
- `GET /daily` and `/gap-v2` adapters.
- BFF code changes (the BFF already mints `svc-nutrition`).
- Duplicate OIDC `sub` remediation.
- Knowledge/KAP and Ambient Bento work.

## Revision log

- **Rev 2 (2026-10-06)**
  - Added requirement traceability and decisions D1–D3.
  - D1 corrects architecture §5: the Hub's `svc-nutrition` delegation would be rejected by Home as deployed. F3b.1 now also adds caller-bound audience acceptance and restricts `svc-nutrition` actors to the policy entry points.
  - D2 records how subject and operation are bound without Person IDs in tokens.
  - D3 records that expiry is enforced only at Home.
  - F3b.1 guard now validates input before the existence lookup, so invalid-input answers are not an existence oracle.
  - F3b.2 states rule R explicitly and gives the exact HTTP table.
  - F3b.3 accepts numeric-string target values: real pregnancy profiles store `str(Decimal)`, which the Rev 1 rule would have rejected as `INVALID_RESPONSE`.
  - F3b.3 adds the personId format check, the mint-failure short-circuit, the required-env startup ordering, the build-time Dockerfile variable (found while planning: `next.config.ts` validates config at build), the pre-merge pasta probe, and the restart verification.
  - Added per-PR rollout and rollback gates and the F3a baseline evidence.
- **Rev 1 (2026-10-05):** initial design.

## Open questions

- None. **D1 approved by the operator on 2026-10-10.**
- The pasta two-port spelling is an implementation check (R3 step 1), not a design choice.
