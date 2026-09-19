# Stage G1.6 Validation — Trusted Identity / Actor Binding

**Result:** **G1.6 COMPLETE** — production cutover and final trust-boundary evidence
validated on 2026-09-19.

**Validated:** original identity validation 2026-09-16; G1.6 C implementation evidence
2026-09-18; production closeout 2026-09-19

**Scope:** No real family/health domain records were created or read. G1.6 exercised
real authentication/account metadata only as required for the trusted-actor proof;
all Person/domain records used for authorization and Nutrition validation were
synthetic. G2 was not started.

## G1.6 C production cutover — 2026-09-19

The coordinated BFF, gateway, Home MCP, Nutrition, and Hermes cutover is complete.
All three active application images were rebuilt from and resolve to the authoritative
GitHub `main` commit:

`FINAL_MAIN_SHA=ddebab6439c9d68487d180dec6995fc546d3cf68`

No prior image was reused. The running containers, OCI revision labels, Quadlet
configuration, and source checkout were re-verified after cutover.

### Final image provenance

| Service | Image tag / Quadlet `Image=` / running image | Image ID | Digest | Runtime |
| --- | --- | --- | --- | --- |
| Home BFF (`home-bff`, `home-bff-mint`) | `localhost/episteck-home-bff:ddebab6439c9d68487d180dec6995fc546d3cf68` | `88a5734e3d27b91ea8d19a645c8131d67e57fb9821371f28a70bb686208efb58` | `sha256:ee5acacc1af84f1988ff1a36d3b1e44423287f50707bcdb9339edfcff731903d` | active |
| Home MCP (`home-mcp`) | `localhost/episteck-home-mcp:ddebab6439c9d68487d180dec6995fc546d3cf68` | `384a763ff4cb6b9e06ec29de2c60521b2fd6113db1c1e1862a1b5c5866776156` | `sha256:ffd5dfc29ed9ffcdf9d5cf2308279f024eb8d860a4539655c5b73fd3faabd6b7` | active; FastMCP `4.0.3` |
| Nutrition (`nutrition`, `nutrition-mcp`) | `localhost/episteck-nutrition:ddebab6439c9d68487d180dec6995fc546d3cf68` | `80740bf79a900ca43c2151c6ac0a22bcd8cd5e73b90f229e8bac49ae397bd0da` | `sha256:bc2e4c72d320c63bd1ad5731dc80faa858b0ecde789b99d6d94f828f6c16e8fa` | active; FastMCP `4.0.3` |

The complete chain for each row is the same `FINAL_MAIN_SHA` → displayed tag → image
ID → digest → matching Quadlet `Image=` → matching running-container image. OCI
`org.opencontainers.image.revision` is the final SHA on every image.

### Final Hermes transport and gateway identity

| Property | Live value |
| --- | --- |
| Home MCP URL | `http://127.0.0.1:9934/gateway/home/` |
| Nutrition MCP URL | `http://127.0.0.1:9934/gateway/nutrition/` |
| Gateway process identity | `svc-home-gateway` (uid `999`) |
| Hermes Agent | `0.21.2` |
| Hermes MCP client | `mcp 2.0.0` |
| Hermes MCP types | `mcp-types 2.0.0` |

Both Hermes endpoints enter through the dedicated gateway on `9934`; neither points
directly to Home MCP `9932` or Nutrition MCP `9931`. `tools/list` found all 8 Home and
13 Nutrition tools through the gateway.

### Mint socket proof

`/run/episteck/home-bff-mint/mint.sock` is a Unix socket owned by
`svc-home-bff:episteck-gw` with mode `0660`. Its directory is owned by the same
user/group with mode `2770` (setgid).

| Real host identity | Connect to `mint.sock` |
| --- | --- |
| `svc-home-gateway` | **CAN** |
| `www-data` | **CANNOT** |
| `home-agent` | **CANNOT** |

The public BFF TCP application structurally has no mint route: `/internal/mint`
returns 404 and the public OpenAPI surface contains only the intended login/session
routes. Minting remains confined to the separate Unix-socket process.

### Active nftables real-user matrix

The active `table inet episteck_gateway` output chain accepts uid `1003`
(`home-agent`) only to gateway port `9934`, drops all other local access to `9934`,
accepts uid `999` (`svc-home-gateway`) to MCP ports `9931`/`9932`, then drops all
other local direct access to those MCP ports.

| Real host identity | Destination | Result |
| --- | --- | --- |
| `home-agent` (uid `1003`) | gateway `9934` | **CAN** |
| `home-agent` | direct `9931` / `9932` | **CANNOT** |
| unrelated local service user (`www-data`) | gateway `9934` | **CANNOT** |
| `svc-home-bff` | direct `9931` / `9932` | **CANNOT** |
| `svc-home-gateway` (uid `999`) | direct `9931` / `9932` | **CAN** |

The live ruleset was recorded with `sudo nft list table inet episteck_gateway`; it was
not flushed or redesigned during closeout.

```nft
table inet episteck_gateway {
    chain output {
        type filter hook output priority filter; policy accept;
        ip daddr 127.0.0.1 tcp dport 9934 meta skuid 1003 accept
        ip daddr 127.0.0.1 tcp dport 9934 drop
        ip daddr 127.0.0.1 tcp dport { 9931, 9932 } meta skuid 999 accept
        ip daddr 127.0.0.1 tcp dport { 9931, 9932 } drop
    }
}
```

### Final Home path proof

All operations used Hermes → gateway → Home MCP → Home Control Plane with synthetic
Persons only.

- Initialization and `tools/list` succeeded through the final gateway URL.
- The normal operator binding `home-agent-primary` resolved server-side to
  `PSN-00001`; `whoami`, a self operation, and an allowed cross-person read succeeded.
- The dedicated enabled zero-role user claimed the same fixed runtime deliberately
  after the operator logged out. `whoami` resolved `human_actor=PSN-00002`, retained
  `machine_caller=home-mcp-service@episteck.invalid`, and `list_my_circles` succeeded
  without System Manager privileges. Both self tools have empty input schemas.
- The low-privilege session then logged out. The runtime binding cleared and the next
  gateway initialization returned 401 immediately. The normal operator subsequently
  reauthenticated; final-path `whoami` again resolved `PSN-00001` and
  `home-agent-primary` remains restored.
- A fresh delegation worked. A forged inbound delegation header could not override the
  gateway-minted value. Reuse of a delegation failed closed through the shared Redis
  single-use claim.
- No actor argument, delegation, bearer token, or credential appeared in any tool
  schema, result, or model-visible output.

### Final Nutrition path proof

All operations used Hermes → gateway → Nutrition MCP → Nutrition service → Home
authorization.

- An allowed Nutrition profile read for `PSN-00001` succeeded; a read for synthetic
  `PSN-00003` was denied fail-closed.
- `record_planned_meal` followed by compound `ate_as_planned` succeeded for synthetic
  date `2099-12-31` and marker
  `G1_6_CLOSEOUT_20260919_SYNTHETIC_EMPTY`. An attempted mutation for `PSN-00003`
  was denied and created zero rows.
- No model-supplied actor or delegation was accepted or exposed. Nutrition made no
  separate `whoami` pre-call.
- Before cleanup, an exact person/date/marker query returned only the expected one
  PLANNED and one ACTUAL row. A guarded transaction deleted those two exact IDs only;
  the marker query and explicit-ID query both returned zero afterward.

Existing secret-free production logs did not provide safe per-call counting, so the
live evidence establishes final-path success while exact call cardinality is proven by
the deployed source and its isolated test suite. From checkout
`ddebab6439c9d68487d180dec6995fc546d3cf68`, with exact source paths forced ahead of
editable installs and FastMCP `4.0.3`:

```text
services/nutrition/tests/test_one_request_per_operation.py
56 passed, 1 upstream deprecation warning
```

The suite exhaustively discovers every person-sensitive service operation, HTTP route,
and MCP tool and asserts exactly one Home request per invocation. Replay-aware tests
pass. `test_ate_as_planned_asks_for_view_and_create_in_one_request` asserts one
`check_access_many` call whose ordered requirements are `NUTRITION/VIEW` and
`NUTRITION/CREATE`; the Home request count is exactly one.

The earlier shared-interpreter result (`47 passed, 9 errors`) was an
**environment/harness failure**, not a product failure. Its nine errors were exactly
the MCP inventory case and eight parametrized MCP operation cases. Their shared fixture
failed while importing FastMCP because that interpreter's incompatible package set did
not provide `mcp.server.request_state`; none reached an authorization assertion. The
shared interpreter was not modified.

### Final security invariants

| Invariant | Result | Evidence |
| --- | --- | --- |
| Browser/model cannot select actor | **PASS** | actor absent from public and tool schemas; resolved from authenticated session |
| Model cannot supply delegation | **PASS** | delegation is transport context, not a tool argument |
| Gateway overwrites forged delegation | **PASS** | live forged-header request retained the session-resolved actor |
| `Authorization` / `Cookie` stripped before MCP upstream | **PASS** | active nginx config and gateway tests |
| Delegation response header suppressed | **PASS** | active `proxy_hide_header` and gateway tests |
| Direct `9931` / `9932` bypass blocked | **PASS** | live real-user nftables matrix |
| Public BFF cannot access mint socket | **PASS** | socket group/mode matrix |
| Mint endpoint absent from public BFF TCP app | **PASS** | route inventory and live 404 |
| Replay is single-use | **PASS** | live second-use denial via shared Redis |
| Logout/revocation immediate and fail-closed | **PASS** | binding cleared; next gateway init 401 |
| `aud=home-control-plane` on Home path | **PASS** | live Home authorization path |
| `aud=home-control-plane` on Nutrition path | **PASS** | live Nutrition → Home authorization path |
| Delegation invisible to tool output | **PASS** | Home and Nutrition results inspected |

### OIDC `sub` ruling

The duplicate `(provider, userid)` historical finding remains present. Approved
amendment A5 is binding and supersedes the older acceptance wording: G1.6 does not use
OIDC `sub` for actor resolution. The live actor path is authenticated session → User →
Person. No `User Social Login` value was regenerated or otherwise changed during
closeout. Remediation and a uniqueness invariant remain mandatory before any
native/public OIDC client relies on `(issuer, sub)`; the collision is not a G1.6
completion blocker.

### Rollback and latency

The unexecuted rollback bundle remains at
`/root/episteck-rollbacks/g1-6-20260918T203149Z-ddebab6` (`root:root`, mode `0700`)
with a validated manifest. Previous images remain available as BFF `:3079cd1`, Home
MCP `:243bede`, and Nutrition `:7af4cd8`. Rollback was not needed; the final cutover
remains active.

Thirty live final-path samples each produced:

| Path | Success | Median | p95 |
| --- | ---: | ---: | ---: |
| Hermes → gateway → Home `whoami` | 30/30 | 130.79 ms | 133.94 ms |
| Hermes → gateway → Nutrition profile | 30/30 | 131.23 ms | 139.06 ms |

**Final verdict: G1.6 COMPLETE.** Knowledge Technology Gate remains next; no Knowledge
runtime or G2/Health work was started during this closeout.

## 0. G1.6 C implementation validation (offline, 2026-09-18)

Tasks 1–6 of the approved delegation-gateway plan were implemented on an isolated
branch from merged PR #14 (`def611f`). No production host, live service, public
nginx, nftables table, Hermes configuration, or shared/local FastMCP installation
was changed. Tasks 10–11 (cutover and rollback execution) were not performed.

The repository environment is `.venv-g1-6-c` using Python 3.13.9. The server
dependency is pinned and installed there as `fastmcp==4.0.3`; its transitive
packages resolve `mcp 2.2.0` / `mcp-types 2.2.0`. This is separate from the
observed Hermes client environment documented for deployment (`mcp 2.0.0` /
`mcp-types 2.0.0`); FastMCP 4.0.3 is not the Hermes client dependency.

The pre-change isolated baseline was 537 passing tests. Implementation evidence:

| Area | Result |
| --- | ---: |
| Home Control Plane, contracts, Nutrition domain | 193 passed |
| Home BFF Windows run | 149 passed, 10 Unix-only skips |
| Home BFF WSL/Linux run | 159 passed |
| Gateway config/nft/FastMCP tests | 10 passed, 6 Linux-nginx skips on Windows |
| Real nginx gateway + lifecycle tests in isolated Linux container | 6 passed, 0 skipped |
| Real WSL socket tests | 19 passed |
| Exact rootless Podman BFF mint image lifecycle | initial + restart socket `1000:1000 660 socket` |

The final Windows command matrix totals **582 passed, 16 skipped**. The skips are ten
Unix ownership/socket tests, five real-nginx gateway tests, and one real-nginx
lifecycle test; each skipped test was rerun on Linux. The post-fix WSL BFF suite is
**159 passed**, and the isolated Linux nginx run is **6 passed, 0 skipped**. The exact
BFF image was rebuilt locally from the implementation checkout for the socket
lifecycle proof only; no image was published or deployed.

The remaining warnings are upstream Starlette/AnyIO deprecations (and WSL's
Starlette/httpx compatibility warning); no test failure is hidden by them. The
gateway integration harness ran against nginx 1.27 in an isolated Linux container as
the unprivileged `svc-home-gateway` identity (uid 10001). It proved both gateway paths,
one mint and one upstream request per client request, sequential and concurrent token
freshness, header controls including response-side delegation suppression, unchanged
body forwarding, no retry, and no JSON-RPC parsing. The same identity started nginx,
owned both master and worker processes, reloaded to a replacement worker, and stopped
cleanly through the dedicated PID path. WSL `nft --check` was not considered proof
because the unprivileged environment cannot initialize netlink; the rendered table
was not loaded.

Final verification commands, all directed at the isolated environment, are:

```bash
python -m pytest services/home-bff/tests services/home-mcp/tests \
  services/nutrition/tests deploy/home-bff/tests deploy/gateway/tests -q
python -m compileall -q services/home-bff services/home-mcp services/nutrition
git diff --check
```

Before any future cutover, build all three final images from one merged post-C
SHA, stage without switching runtime, capture the complete previous transport
stack, and follow the coordinated cutover/complete rollback procedures in the
approved plan. No such stage, service switch, image deployment, or nftables load
was executed here.

---

## 1. Recovered starting state

`main` was clean at `25328dc`, in sync with origin, with three merged G1.5 PRs. The
baseline suite was re-run before any change: **93 tests passing**, matching the
documented G1.5 state exactly.

Live inspection of `home.episteck.com` (Frappe **v15.99.0**, oauthlib **3.3.1**) found
three synthetic Persons all with `linked_user: null`, two zero-role machine users, two
real human Users, and **no** OAuth clients. All inspection was read-only.

---

## 2. Delivered boundaries

### The invariant

```
validated authentication -> Frappe User -> Person.linked_user -> actor
```

`actor_person_id` is not a parameter of any Home business method, any MCP tool, or any
Nutrition route. Actor substitution is **unrepresentable**, not merely rejected.

### Control Plane
- `identity/delegation.py` — pure, dependency-free verification (issuer, audience,
  issued-at, expiry, unique token id, session binding, replay, maximum lifetime).
  Mirrors `policy/access.py`: the security core is testable in isolation.
- `identity/actor.py` — `resolve_principals()` returns **both** principals. Ambiguous
  `linked_user` fails closed rather than guessing.
- `identity/auth_hook.py` — Frappe `auth_hooks` seam. Maps a verified delegation's
  opaque session id to a User via a **server-side** `Home Delegated Session` record, so
  logout and revocation deny the very next call even with an unexpired token.
- `api.py` — no actor parameter; `whoami` exposes the resolved actor and both
  principals without revealing consent or relationship data.
- `Person.linked_user` is now **unique**.

### Home MCP
Eight business tools (the original seven plus `whoami`), none accepting an actor or any
credential. Self-scoped tools take **no parameters at all**. Delegation is read from
FastMCP 4.0.3's live per-request HTTP context via narrowly scoped
`get_http_headers()` access, outside model-controlled arguments. The earlier local
`ContextVar` design was removed because production never populated it.

### Nutrition
Makes exactly one delegated Home authorization request per person-sensitive business
operation: `check_access` for one permission or `check_access_many` for a compound
operation. Home resolves the actor server-side from the machine credential plus the
single-use delegation; Nutrition neither calls `whoami` first nor accepts an actor
string from the Home Agent or Home MCP. Retained unchanged: 3 s timeout,
**no authorization caching**, and DENY on transport, HTTP, JSON, shape, coverage, or
decision ambiguity.

### Home BFF (new, Nuremberg EU node — amendment A1)
An **operational FastAPI service**, not merely a client library. Routes: `/login`,
`/callback`, `/logout`, `/health`, plus `/session`, `/whoami` and `/delegation` for the
trusted runtime.

Confidential OAuth client, always S256 PKCE. `/login` persists state, nonce and the
PKCE verifier **server-side**; the browser carries only an opaque state key. `/callback`
consumes that transaction atomically, so a replayed `state` finds nothing. The browser
receives only an opaque `Secure + HttpOnly + SameSite=Lax` cookie — `Lax` is required
because the cookie is set on the top-level redirect back from the authorization
endpoint, where `Strict` would withhold it.

Session state (tokens, verifiers) lives in SQLite on a service-owned volume — no new
infrastructure dependency. Delegations minted per call carry **no Person id**.

**Session creation preserves the invariant.** `identity/session.py` exposes
`open_session`/`close_session`, which take **no user parameter**: the BFF calls them
with the human's own OAuth access token, so Frappe resolves the User itself. The BFF
cannot open a session for anyone other than the person who just authenticated, and
needs no elevated credential to do so.

---

## 3. Automated verification

| Suite | Before (G1.5) | After (G1.6) |
| --- | ---: | ---: |
| Home Control Plane (policy, API, delegation, auth hook, session) | 22 | **98** |
| Knowledge + ContextBundle contracts | 12 | 12 |
| Nutrition domain (deterministic calc) | 9 | 9 |
| Home MCP (client + tool contract) | 8 | **19** |
| **Home BFF (new)** | — | **117** |
| Nutrition service + boundaries | 42 | **57** |
| **Total** | **93** | **312** |

All 93 original tests still pass. `policy/access.py` was **not modified**: same
signature, same six invariants, same 11 pure policy tests.

---

## 3a. Pre-merge adversarial audit of the operational BFF

Requested before merge, and kept as permanent tests (`tests/test_security_audit.py`,
46 cases) so a later regression fails the build.

| # | Property | Result |
| --- | --- | --- |
| 1 | `/delegation` unreachable without a valid session | **PASS** — denied with no cookie, forged cookie, empty cookie, post-logout, expired, server-side-deleted, and a guessed Home session id; `GET` is 405 |
| 2 | Cross-site POST cannot mint a delegation | **PASS** — cookie is `SameSite=Lax` + `HttpOnly`, so a cross-site POST arrives with no cookie and is denied; all three form-submittable content types denied; nginx additionally returns 404 for `/delegation` |
| 3 | Actor cannot be supplied via body/query/header | **PASS** — 5 body keys × 5 query keys × 4 headers all ignored; the minted delegation stays bound to the session's own Home session; OpenAPI declares no actor or credential parameter anywhere |
| 4 | No token or secret in any response or normal log | **FOUND AND FIXED** — see below |
| 5 | `/health` exposes no sensitive configuration | **PASS** — fixed two-key body, no host/port/path/client id, requires no session, creates no state, never calls upstream |

### Finding: upstream error text reached the log (fixed)

`/callback` logged `logger.warning("token exchange failed: %s", exchange_error)` and
the equivalent on session refusal. The **response** correctly withheld upstream detail,
but the **log line** interpolated the exception message — and an upstream OAuth error
can echo request parameters, including the client secret. The log is the record that
persists, so this was the more durable leak of the two.

Both call sites now log the exception **class only**. All four `logger.warning` calls in
the service are class-only or fixed strings, and the only f-string exception message in
the package is a configuration key name. Two regression tests cover the happy path and
both failure paths.

Also verified: `access_log=False` on uvicorn, so `/callback?code=…` query strings are
never written to an access log, and the PKCE verifier never appears in a redirect,
response body, or log.

---

## 4. Threat matrix

| # | Threat | Expected | Observed |
| --- | --- | --- | --- |
| T-1 | Actor substitution | unrepresentable | **`TypeError`** — no such parameter exists |
| T-2 | Prompt injection ("act as PSN-00001") | no effect | identity not model-reachable; no channel |
| T-3 | Service credential alone → person data | DENY | `PermissionError: no human actor bound to this session` |
| T-4 | Wrong session acts as another Person | DENY | resolves only to its own Person; foreign roster denied |
| T-5 | Cross-service delegation replay | DENY | audience binding rejects both directions |
| T-6 | Forged/tampered delegation | DENY | constant-time HMAC comparison fails |
| T-7 | Confused deputy (Nutrition trusts actor string) | DENY | Nutrition resolves the actor itself |
| T-8 | Expired delegation | DENY | valid at `exp-1`, denied at `exp` |
| T-9 | Revoked session / logout | DENY next call | server-side record consulted per call |
| T-10 | Disabled User | DENY | enabled flag checked at bind time |
| T-11 | Person↔User unlink | DENY immediately | actor resolved per call from live link |
| T-12 | Two Persons → one User | DENY | ambiguity fails closed; unique index |
| T-13 | One Person → two Users | rejected at write | unique index on `linked_user` |
| T-14 | Person without User as actor | DENY | valid subject, never an actor |
| T-15 | Subject substitution | policy-gated | unchanged G1.5 behaviour |
| T-16 | Domain/action substitution | policy-gated | exact match; no cross-domain implication |
| T-17 | Stale authz after revocation | DENY | no caching anywhere |
| T-18 | Replayed delegation token id | DENY | atomic `SET NX EX` claim in shared Redis (`identity/replay.py`); **live-verified after PR #7** |
| T-19 | Overlong delegation lifetime | DENY | max-lifetime bound caps the replay window |
| T-20 | Plain `X-Actor-ID` header (forbidden, A7) | inert | `"PSN-00001"` as a token fails verification |
| T-21 | Anonymous request + delegation header | inert | no machine caller ⇒ no bind |
| T-22 | Token/credential leak to LLM | none | no tool exposes a token; schema-asserted |
| T-23 | Hook raises into request path | never | wrapped; DB failure leaves context unset |

### Correction: T-18 was unit-true and production-false (PR #7)

The original T-18 evidence was `verify()`'s `seen_token_ids` parameter. That parameter
is a **test seam**: it lets a test express replay semantics against a pure function,
but the production hook never passed one, so nothing enforced single use. Live
validation presented the same `jti` twice and both calls succeeded.

An in-process set could not have fixed it either — four gunicorn workers means four
sets, so a replay lands on a different worker and is accepted.

Production enforcement is now one atomic `SET key 1 NX EX ttl` against the shared
Frappe Redis cache (`identity/replay.py`), claimed after the token is proven authentic
and before any identity is resolved. Cache unavailable denies. Forged, expired and
wrong-audience tokens never burn a legitimate token id.

This is the same failure shape as the timezone defect: every component correct in
isolation, the composition wrong. Both now have integration tests that fail when the
fix is reverted.

### Live delegation matrix (production Python runtime, Ashburn)

Executed with the bench interpreter against the feature branch checkout:

```
valid_token_binds_session        true
forged_signature_denied          true
wrong_audience_denied            true
wrong_issuer_denied              true
expired_denied                   true
replay_denied                    true
overlong_lifetime_denied         true
plain_actor_header_denied        true
person_id_claim_never_surfaces   true
malformed_denied                 true
ALL_PASS: True
```

---

## 5. PKCE findings (live, `home.episteck.com`)

| Property | Result |
| --- | --- |
| S256 supported; computation matches our client **byte-for-byte** | ✅ verified on the live box, 4/4 samples |
| Challenge present but verifier missing → fail (code also deleted) | ✅ present |
| Authorization code single-use | ✅ `invalidate_authorization_code` |
| Token checks expiry **and** revocation | ✅ `oauth.py:244` |
| **Client may omit PKCE entirely** | ❌ **passes** — `validate_code` falls through to `return True` |
| **Per-client `require_pkce` flag** | ❌ **does not exist** |
| **`public_client` client type** | ❌ **does not exist** |
| `plain` method rejected for public clients | ❌ accepted |

Verified `OAuth Client` fields: `client_id, app_name, user, allowed_roles, cb_1,
client_secret, skip_authorization, sb_1, scopes, cb_3, redirect_uris,
default_redirect_uri, sb_advanced, grant_type, cb_2, response_type`.

**Conclusion.** Frappe v15.99.0 cannot enforce safe PKCE for public clients. Per the
approved amendments this does **not** replace Frappe as IdP. We create **no public
client**; the BFF is confidential and always sends S256, so the downgrade path is
unreachable. **Direct native/mobile OIDC remains deferred**; mobile ships against the
BFF with no redesign.

**Historical status at the 2026-09-16 inspection:** the authorization-code round-trip
cases (correct verifier, wrong verifier, code reuse, redirect mismatch) still required
an OAuth client and were blocked at that time. Subsequent G1.6 work deployed the BFF
and OAuth client and live-validated the authorization-code/login path; these cases are
no longer pending. Section 8 preserves the original pre-deployment snapshot.

---

## 6. Duplicate OIDC `sub` — root cause and status

| User | `sub` | Created | Created by |
| --- | --- | --- | --- |
| `vargas3rick@gmail.com` | `8a07ad04…14069` | 21:19:44 | Administrator |
| `aemarchan1@gmail.com` | `8a07ad04…14069` | 21:24:45 | **`vargas3rick@gmail.com`** |
| `home-mcp-service@…` | `aeace5d5…34d0` | 19:48:27.42 | — |
| `nutrition-auth-service@…` | `d0260de6…27ff` | 19:48:27.78 | — |

**Root cause: data propagation, not an RNG flaw.** `user.py:200` generates a hash only
`if not self.get_social_login_userid("frappe")`. `frappe.generate_hash` uses
`secrets.token_hex` (CSPRNG); six live samples were unique, and the two service users
created 0.36 s apart got distinct values. `aemarchan1@` was created **by**
`vargas3rick@` in the desk UI, and the child `User Social Login` row was carried into
the new document, permanently suppressing generation. Frappe never asserts
`(provider, userid)` uniqueness across Users.

**Why it matters:** `oauth.py:463-464` resolves an inbound `sub` back to a User. With a
duplicate, that lookup is ambiguous, and one of the two accounts is a System Manager.

**Status at the 2026-09-16 reference audit (amendment A5 — remediation gated on a
reference audit).** The audit then found **zero** consumers: no OAuth clients, no
bearer tokens, no social login keys. A confidential BFF OAuth client was created in
the subsequent live work, so the zero-consumer statement is historical, not current.
Regeneration is therefore provably safe, but per A5 no irreversible identity-data
change was made. `sub` is **off the G1.6 critical path** — internal resolution uses the
authenticated session, never `sub`. Remediation is required before any native/public
OIDC client relies on `(issuer, sub)`.

---

## 7. Latency

The G1.5 baseline was Home `check_access` 119.88 ms p95 and cross-person Nutrition
profile 121.60 ms p95, dominated by the Nuremberg→Ashburn cross-Atlantic hop.

G1.6 adds one delegation verification per call. That work is **pure in-process HMAC
and JSON** with no network, no database round trip beyond a single indexed session
lookup, and no authorization caching. The expected added cost is well under a
millisecond against a ~120 ms network-bound baseline.

This pre-cutover estimate is retained as history. Final post-cutover observations are
recorded in the 2026-09-19 production closeout section above. The cross-Atlantic hop is
a permanent property of this deployment: Stage G1.7 was withdrawn on 2026-09-16 and
the Control Plane stays in Ashburn.

---

## 8. Historical pre-deployment snapshot (superseded)

This section records the state on 2026-09-16 and is retained as architecture history.
Its pending-BFF statements are not current: subsequent G1.6 work deployed and
live-validated the BFF, OAuth authorization-code/login path, real-login actor binding,
shared replay claim, and the coordinated G1.6 C gateway/MCP/Hermes cutover recorded in
the 2026-09-19 production closeout section.

### 8.1 The BFF was a library, now it is a service

The first G1.6 pass delivered `services/home-bff` as **two pure modules** — parameter
builders and PKCE/HMAC math — with no HTTP layer, no routes, no deployment. It was
correct and well tested, but nothing could log in through it. That gap is now closed:
the service exists, with 71 tests covering login, callback, session, delegation and
logout, including the adversarial cases.

### 8.2 Items that were pending in the 2026-09-16 snapshot

**DNS is live.** `bff.home.episteck.com` → `91.98.132.9`, created by the operator and
verified propagated on 2026-09-16 against three independent resolvers (corporate,
`8.8.8.8`, `1.1.1.1`). The callback URL is therefore final:
`https://bff.home.episteck.com/callback`.

| Item | Blocked on |
| --- | --- |
| ~~`bff.home.episteck.com` DNS A record~~ | ✅ **done** — propagated and verified |
| nginx + certbot on the Nuremberg node | Phase 2 deployment |
| OAuth Client creation on `home.episteck.com` | Phase 2, after the callback is serving |
| Authorization-code round trip (PKCE live cases) | the OAuth client |
| Operator real login → synthetic Person (A10-A) | the deployed service; the operator logs in personally |
| Low-privilege test User → second synthetic Person (A10-B) | the User does not exist yet; creation is a G1.6 write |
| Post-cutover latency measurement | the live path |

Everything not dependent on public ingress is done and verified offline, including
the full delegation matrix on the production runtime and byte-for-byte S256 agreement.

## 9. Historical deployment status (2026-09-16 snapshot)

The following paragraphs and preflight table describe the pre-deployment state when
this document was first written. They are not the current runtime status. PRs #4–#15
subsequently merged, and the BFF/login, replay, gateway, Home MCP, Nutrition, and Hermes
paths were live-validated in the final production cutover above.

The feature branch is pushed. The `episteck-deploy` job polls `main` only, so nothing
has changed in production; `home.episteck.com` still runs G1.5. Verified live:
`whoami` returns HTTP 417 (method absent) and anonymous calls return 403.

**After merge, a manual `bench --site home.episteck.com migrate` is required** for the
`Home Delegated Session` DocType and the unique index on `Person.linked_user`.
`home.episteck.com` has **no** post-deploy hook — only `imox` does.

### `linked_user` migration preflight — PASS (read-only, 2026-09-16)

| Check | Result |
| --- | --- |
| Persons | 3 — `PSN-00001` SYN Ana, `PSN-00002` SYN Ben, `PSN-00003` SYN Cara |
| Non-null `linked_user` | **0** |
| Duplicate non-null `linked_user` | **0** |
| Real Person bindings | **none** — all three are synthetic |
| Existing index on `linked_user` | none (only `PRIMARY`, `modified`) |
| OAuth Clients | **0** |
| `Home Delegated Session` table | absent, as expected pre-migrate |
| `home_delegation_secret` / `_issuer` in site config | **absent — must be provisioned** |

All values are NULL, which cannot collide under a MySQL unique index. **The unique
index is safe to create.**

Rollback: the branch is additive at the transport layer and subtractive at the
parameter layer. Reverting it restores G1.5 behaviour exactly.
