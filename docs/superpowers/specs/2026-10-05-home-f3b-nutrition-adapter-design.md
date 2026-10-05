# Home F3b — Nutrition server adapter: implementation design

**Date:** 2026-10-05
**Status:** Draft for review
**Parent architecture:** `docs/architecture/proposals/HOME_F3_ACTIVE_CONTEXT_DOMAIN_INTEGRATION.md` (Board-approved, PR #48), §4–§10. This spec does not change that architecture; it fixes the implementation detail for phase F3b.
**Baseline:** `origin/main` `6d4e361` (F3a live verification PASS, PR #57).

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
- No production fixtures, Persons, grants, or Nutrition profiles are created. An authorized `ABSENT` is a valid live proof.
- `Network=host` and broad exposure are never fallbacks.
- Production deploys are run by the operator.

## Delivery shape

Three PRs, merged and deployed in order. Each is backward compatible; nothing calls the new path until its dependencies are live.

| PR | Scope | Deploy target |
| --- | --- | --- |
| F3b.1 | Home subject-existence guard | Ashburn Frappe bench, via the `main` → episteck-deploy job |
| F3b.2 | Nutrition typed policy outcomes | Nuremberg `svc-nutrition` image + Quadlet `Image=` |
| F3b.3 | Hub Nutrition adapter + narrow 9930 transport | Nuremberg `svc-home-hub` image + Quadlet `Image=`/`Network=`/`Environment=` |

---

## F3b.1 — Home subject-existence guard

### Placement

`apps/episteck_home/episteck_home/policy/wrappers.py:check_access` is the single function through which every authorization decision flows today: `api.check_access`, `api.check_access_many` (per requirement), `api._has_effective_access` (Person discovery), and `api.get_access_to_person`. The guard lives there, so all current and future entry points inherit it without duplication.

### Behavior

- New helper `_subject_exists(subject_person_id) -> bool` calls `frappe.db.exists("Person", subject_person_id)`. It runs on every call; no cache across or within requests.
- `check_access` calls it **before** `_load_grants`. If the subject does not exist it returns `{"allow": False, "reason": "no consent grant (fail closed)"}` — byte-identical to the response for an existing subject with no grants. An orphaned grant for a deleted Person therefore cannot produce `ALLOW`.
- An exception from the lookup falls into the existing `except` and returns the generic `policy error (fail closed)` deny.
- Self requests also pass through the guard (one indexed lookup).
- Person has no status or soft-delete field (`full_name`, `external_ref`, `linked_user`, `notes`), so existence means the row exists. No schema change and no migrate.

### `check_access_many`

Unchanged. A missing subject makes every per-requirement decision deny, so the overall result is `allow: false` with no positive decision. Up to `MAX_REQUIREMENTS` (8) identical existence lookups per request is accepted; no in-request reuse.

### Tests (`apps/episteck_home/tests`, existing fake-frappe harness)

1. Missing subject with an active orphaned grant → deny; the grant loader is not called.
2. Missing-subject response equals the no-grant response exactly.
3. `check_access_many` with a missing subject → every decision `allow: false`, overall `allow: false`.
4. `exists` raising → fail-closed deny.
5. Bootstrap-then-delete race: Person exists, is deleted, next `check_access` denies.
6. Existing self-access and grant-allow paths unchanged; full existing suite passes.

### Deploy and verification

Merge to `main`; the episteck-deploy job mirrors it to the Ashburn bench. Verify read-only with `bench --site home.episteck.com execute` calling `episteck_home.policy.wrappers.check_access` for the operator Person and a synthetic non-existent subject ID: the non-existent subject denies with the no-grant reason; self still allows.

---

## F3b.2 — Nutrition typed policy outcomes

### Decision type (`services/nutrition/app/home_control/client.py`)

`AccessDecision` gains `outcome: str` with values `ALLOW`, `DENY`, `SESSION_INVALID`, `UNAVAILABLE`. It defaults from `allow` (`ALLOW` if true, else `DENY`) so existing `AccessDecision(bool, reason)` constructions keep working.

### Classification (both `check_access` and `check_access_many`)

| Home answer | Outcome |
| --- | --- |
| HTTP 200, `message` is a dict, `allow` is a bool, `reason` is a non-empty string | `ALLOW` / `DENY` |
| HTTP 200 with any other shape, including allow with a missing or non-string reason | `UNAVAILABLE` |
| No delegation supplied | `SESSION_INVALID` |
| HTTP 401 or 403 from Home (actor could not be resolved) | `SESSION_INVALID` |
| Timeout, connection error, other non-2xx, non-JSON body | `UNAVAILABLE` |
| Missing subject/domain/action arguments | `UNAVAILABLE` |
| `check_access_many` coverage/order mismatch (existing checks) | `UNAVAILABLE` |

A denial in `check_access_many` still needs no corroboration; an allow still requires exact positional coverage.

### Service (`services/nutrition/app/service.py`)

New exceptions, all subclasses of `PermissionError` so `app/mcp/server.py` and other callers are unaffected:

- `AccessDenied` for `DENY`
- `SessionInvalid` for `SESSION_INVALID`
- `PolicyUnavailable` for `UNAVAILABLE`

`_require_access` and `_require_all` raise the matching exception for any outcome other than `ALLOW`. The repository is never read unless the outcome is `ALLOW`.

### HTTP boundary (`services/nutrition/app/main.py`)

`_authorized` maps exceptions to fixed responses, most specific first:

| Exception | Status | Body |
| --- | --- | --- |
| `SessionInvalid` | 401 | `{"detail": "SESSION_INVALID"}` |
| `PolicyUnavailable` | 503 | `{"detail": "SERVICE_UNAVAILABLE"}` |
| `AccessDenied` or any other `PermissionError` | 403 | `{"detail": "ACCESS_DENIED"}` |

No Home reason text appears in any response body. `GET /profile/{id}` keeps 404 `{"detail": "no profile"}` for an authorized absent profile.

### Logging

Each non-allow logs one WARNING with a category only — `deny`, `session_invalid`, `home_rejected_credential_or_session`, `home_unreachable`, `home_malformed` — and no Person ID, delegation, token, or Home reason. This distinguishes a broken machine credential (which also yields Home 401/403) from a user session problem for an operator.

### Tests (`services/nutrition/tests`)

- Client classification matrix covering every row above, including allow-without-reason → `UNAVAILABLE` and Home 401/403 → `SESSION_INVALID`.
- Route tests for `/profile/{id}` per outcome: exact status and body, no reason text, repository read never invoked on non-allow.
- Exactly one Home request per operation (existing suites `test_one_request_per_operation`, `test_single_call_authorization`, `test_transport_binding` pass unchanged).
- Log records contain the category and none of: Person ID, delegation value, Home reason.

### Deploy and verification

Rebuild the Nutrition image from the merge SHA; operator changes the Quadlet `Image=` line and restarts. Read-only checks from the host: `/health` 200; `GET /profile/PSN-00013` with no delegation → 401 `{"detail":"SESSION_INVALID"}` (previously 403). Hermes and Home MCP reach Nutrition through its MCP (9931) in-process and are unaffected. Rollback: restore the saved Quadlet.

---

## F3b.3 — Hub Nutrition adapter and 9930 transport

### Configuration (`apps/home-hub/src/integration/home/server-config.ts`)

`HomeHubServerConfiguration` gains `nutritionBaseUrl?: string`, from `HOME_HUB_NUTRITION_BASE_URL`, validated by `configuredOrigin` with the BFF rules: required in LIVE, loopback-only in production, HTTP permitted only on loopback, no credentials/path/query/fragment. Absent in MOCK.

### Contract (`src/integration/nutrition/profile-contract.ts`, pure)

```ts
type ProfileSummary =
  | { presence: 'PRESENT'; context: string; targetSource: string; targetCount: number }
  | { presence: 'ABSENT' };
```

`parseProfileWire(body)` accepts only:

- `context`: string matching `^[A-Z_]{1,32}$`
- `target_source`: string matching `^[A-Z_]{1,32}$`
- `targets`: plain object, at most 64 keys, every value a finite number; `targetCount` is its key count

Any violation throws a contract error the loader maps to `INVALID_RESPONSE`. Only those three values are read; preferences, dislikes, intolerances, pregnancy fields, and any unknown fields are never copied.

### Loader (`src/integration/nutrition/profile-loader.ts`, pure, injectable)

`loadNutritionProfile({ mode, personId, cookieValue, bffBaseUrl, nutritionBaseUrl, fetcher }): Promise<DataEnvelope<ProfileSummary>>`

1. MOCK mode → fixed mock `READY`/`MOCK` envelope, no network.
2. No cookie → `SESSION_REQUIRED`, no network.
3. `POST {bff}/delegation?audience=svc-nutrition` with `Cookie: episteck_home_session=…`, `cache: 'no-store'`, `redirect: 'manual'`.
   - 200 whose body has a non-empty string `delegation` and `audience === 'svc-nutrition'` → continue (other fields such as `expires_at` are ignored)
   - 401 → `SESSION_INVALID`
   - 200 with a malformed body → `INVALID_RESPONSE`
   - any other status or network error → `SERVICE_UNAVAILABLE`
4. `GET {nutrition}/profile/{encodeURIComponent(personId)}` with `X-Episteck-Delegation`, `Accept: application/json`, `cache: 'no-store'`, `redirect: 'manual'`. No cookie is sent to Nutrition. The delegation is used once, never retried, logged, or placed in the envelope.

| Nutrition response | Envelope |
| --- | --- |
| 200 + valid body | `READY`, `GRANTED`, `LIVE`, `data.presence = PRESENT` |
| 404 with body exactly `{"detail":"no profile"}` | `READY`, `GRANTED`, `LIVE`, `data.presence = ABSENT` |
| 403 | `ERROR`, `DENIED`, `ACCESS_DENIED` |
| 401 | `ERROR`, `INDETERMINATE`, `SESSION_INVALID` |
| 503, other 5xx, network error | `ERROR`, `INDETERMINATE`, `SERVICE_UNAVAILABLE` |
| 200 with invalid body; 404 with any other body; any other status | `ERROR`, `INDETERMINATE`, `INVALID_RESPONSE` |

No partial data is ever returned in an error envelope.

### Server wrapper (`src/integration/nutrition/profile.server.ts`, `server-only`)

`readNutritionProfile(context: F3ActiveContext)` reads the session cookie and `SERVER_CONFIGURATION`, then calls `loadNutritionProfile` with `context.personId`. No actor, domain, or action parameter. F3b adds no page or route that calls it; F3c wires it into `/nutrition`.

### Transport (`deploy/home-hub`)

- `svc-home-hub.container`: `Network=pasta:-T,9933,-T,9930` (exact pasta syntax confirmed on the host's pasta version before rollout) and `Environment=HOME_HUB_NUTRITION_BASE_URL=http://127.0.0.1:9930`.
- `tests/test_home_hub_quadlet.py` and the runbook isolation probe updated: 9933 and 9930 reachable; 9931, 9932, 9934 blocked.

### Tests

- `profile-contract.test.ts`: valid present body; each field violation; extra sensitive fields not copied; key/size bounds.
- `profile-loader.test.ts` with a fake fetcher:
  - exactly one mint and one Nutrition call per read
  - no network without a cookie; MOCK makes no network calls
  - cookie sent only to the BFF, never to Nutrition
  - delegation value never present in the returned envelope
  - `no-store` and `redirect: 'manual'` on both calls
  - subject is URL-encoded
  - every row of both mapping tables
- `server-config` tests for `HOME_HUB_NUTRITION_BASE_URL` (required in LIVE, loopback-only in production).
- `npm run test:server-boundary` still passes; `npm run build` passes.

### Deploy and live gate

Rebuild the Hub image from the merge SHA. Back up the Quadlet; operator applies the `Image=`, `Network=`, and `Environment=` changes and restarts. Gate — roll back immediately if any check fails:

- From the running Hub container: 9933 reachable (BFF `/health` 200) and 9930 reachable (Nutrition `/health` 200); 9931, 9932, 9934 not reachable.
- Host `ss`: 9930, 9933, 9940 bound to `127.0.0.1` only.
- External direct `91.98.132.9:9930` and `:9940` time out.
- Anonymous `/app` still 307 to login; F3a context behavior unchanged.

No end-to-end profile read is claimed in F3b; that is F3c's live proof.

## Out of scope

- Any UI change (F3c).
- Cross-person live checks and any real topology or data (G2-gated).
- `GET /daily` and `/gap-v2` adapters.
- Changes to the BFF or the Home bootstrap.
- Duplicate OIDC `sub` remediation.

## Open questions

None. The pasta multi-port syntax is an implementation check, not a design choice: if the reviewed form cannot isolate 9931/9932/9934, the rollout stops for a new transport decision per the architecture.
