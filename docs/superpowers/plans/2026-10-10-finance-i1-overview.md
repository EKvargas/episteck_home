# Olin Finance I1 "How much do we have, and where?" Implementation Plan (Phase A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `services/finance/` (`svc-finance`): a multi-workspace, read-only Finance domain service that ingests real balances and movements from Enable Banking (Sparkasse, Trade Republic cash) and SimpleFIN (Bank of America) and answers `finance_overview()` with per-currency, per-liquidity subtotals, per-account source and date, and explicit dated EUR valuation. Phase A is everything that does not touch H5 files and needs no deployment. Delivered as five small PRs.

**Spec:** `docs/architecture/proposals/OLIN_FINANCE_V1.md` (PR #74, branch `architecture/olin-finance-v1`). Sections that govern: §0.1, §3, §6, §7, §11 (I1), §13 (A4, A6, A7, A11, A12, A13), §14. The proposal wins over this plan if they disagree.

**Architecture:** FastAPI REST + thin FastMCP adapter over ONE service layer (chat and web cannot diverge), SQLite WAL, rootless Quadlet on Nuremberg, same pattern as `services/nutrition`. Authorization is one Home call per operation through an `Authorizer` port shaped like the proposed H2 `authorize_batch`; Phase A only has fakes. Connectors sit behind one `Connector` interface; sync is a systemd timer that runs the same image with a different command.

**Tech stack:** Python 3.11+, FastAPI >=0.140, FastMCP pinned `==4.0.3` (same coupling as Nutrition's pin), httpx, pydantic 2, PyJWT[crypto] (RS256), stdlib `sqlite3` and `decimal`. Tests: pytest, `httpx.MockTransport`, `fastapi.testclient`.

## Verified facts this plan relies on (checked 2026-10-10)

Official docs, fetched today. Anything marked UNVERIFIED must be proven in the live Nuremberg gate, not assumed.

| Area | Fact | Source |
| --- | --- | --- |
| EB base URL | `https://api.enablebanking.com` (`api.tilisy.com` deprecated) | enablebanking.com/docs/api/reference |
| EB auth | `Authorization: Bearer <JWT>`; header `typ=JWT, alg=RS256, kid=<application id>`; claims `iss=enablebanking.com`, `aud=api.enablebanking.com`, `iat`, `exp`; max lifetime 86400 s; only RS256 | same |
| EB flow | `POST /auth` `{access:{valid_until}, aspsp:{name,country}, state, redirect_url, psu_type}` returns `{url, authorization_id}`. Redirect returns `code`; `POST /sessions {code}` returns `{session_id, accounts[], aspsp, access.valid_until}`. `GET /sessions/{id}` status: AUTHORIZED, PENDING_AUTHORIZATION, RETURNED_FROM_BANK, CANCELLED, CLOSED, EXPIRED, INVALID, REVOKED | same |
| EB consent | `access.valid_until` must be <= now + `maximum_consent_validity` (seconds, per ASPSP, from `GET /aspsps?country=DE`). Example value 15552000 = 180 d. Exact Sparkasse/TR values UNVERIFIED | same |
| EB data | `GET /accounts/{id}/balances` returns `balances[]` with `balance_amount{currency,amount}` (amount is a string), `balance_type` (CLAV, CLBD, ITAV, ITBD, OPBD, OPAV, VALU, XPCD, ...), `reference_date`, `last_change_date_time`. `GET /accounts/{id}/transactions?date_from&date_to&continuation_key&transaction_status` returns `transactions[]` + `continuation_key`; fields `transaction_id`, `entry_reference`, `booking_date`, `value_date`, `transaction_amount`, `credit_debit_indicator` (CRDT/DBIT), `status` (BOOK, PDNG, HOLD, CNCL, RJCT, SCHD, OTHR), `creditor`/`debtor`, `remittance_information[]` | same |
| EB limits | Many banks allow 4 unattended fetches/day/account. Fetch with NO PSU headers is "background"; any PSU header marks the user as present. Send all required PSU headers or none. Over limit: HTTP 429 with `error=ASPSP_RATE_LIMIT_EXCEEDED`. Other codes: `PSU_HEADER_NOT_PROVIDED`, `EXPIRED_SESSION`, `CLOSED_SESSION`, `REVOKED_SESSION`, `ACCESS_DENIED` | docs + enablebanking.com/docs/faq |
| SimpleFIN claim | Setup token is base64 of a claim URL. `POST` to it returns the Access URL (Basic Auth embedded). 403 means unknown or already claimed (treat as possible compromise) | simplefin.org/protocol.html |
| SimpleFIN data | `GET <access>/accounts?version=2&start-date&end-date&pending=1&balances-only=1&account=`. Response: `errlist[] {code,msg,conn_id?,account_id?}`, `connections[] {conn_id,name,org_id,sfin_url}`, `accounts[] {id,name,conn_id,currency,balance,balance-date,available-balance?,transactions[]?}`. Numbers are STRINGS; timestamps are unix epoch; `currency` may be an ISO code or a URL; tx: `id, posted, amount, description, transacted_at?, pending?` and `posted=0` while pending. 402/403 are errors. No `org` field on accounts in v2 | same |
| SimpleFIN limits | Rate limit and 90-day window are NOT in the spec. UNVERIFIED, measure live | n/a |
| ECB | Daily reference rates, ~16:00 CET on working days, feed `https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml`. "Informational only; transaction use strongly discouraged". The `data-api.ecb.europa.eu` SDMX route could not be fetched (503), so the plan uses the XML feed | ecb.europa.eu euro_reference_exchange_rates |

**Consequences for the design**
- Money parsing is string to `Decimal` to minor units at the connector edge; floats never appear. An unknown currency exponent is a hard error.
- The unattended budget is enforced by us, per account, per rolling 24 h (Task 12). A 429 never retries inside the same run.
- A SimpleFIN `errlist` entry for a connection marks that connection's accounts stale (never zero); `con.auth` becomes `REAUTH_REQUIRED`.
- Valuation is labelled "reference rate, informational", which is exactly what the ECB allows.

## Global constraints

- **No real financial data on this laptop or in Git.** Fixtures are hand-written synthetic payloads that follow the schemas above. Real-account tests run only on Nuremberg in Phase B.
- **Secrets** (EB private key + app id, SimpleFIN access URL, IBAN-hash pepper, later the Telegram token) live in `600` files owned by the service user, are read from paths in env vars, and never enter the DB, logs, MCP output, chat or Git. Config objects reject being repr'd with secret values.
- **No actor, SQL, credential or workspace override in any API or tool signature.** The actor comes only from Home (`Authorizer`).
- **One Home request per operation. Any non-ALLOW outcome means no repository read.** No decision cache.
- Money is `int` minor units + ISO currency. Currencies are never summed together. VES is never valued.
- Facts are immutable (DB triggers). Corrections arrive later as new facts; PENDING to BOOKED is a NEW row that supersedes the old one.
- Phase A touches NONE of: `apps/episteck_home/episteck_home/identity/*`, `services/home-bff/*`, `deploy/home-bff/*`, `deploy/gateway/*`.
- Nothing is deployed. Infra commands are prepared as a runbook for the operator (`! ssh ...`).
- Commits `<type>: summary` lowercase; branches `feature/...`; commit messages end with `Claude-Session: https://claude.ai/code/session_013rCiDE4Shm6SYxyosg6dcm`.
- The untracked pilot in the primary checkout (`services/finance/`) and the untracked 2026-10-05 research report are NOT touched or copied. The pilot lives on `spike/finance-synthetic-pilot` as reference only.

## Branches and PRs (each <= 800 lines changed; stacked, retargeted to `main` as each merges)

| PR | Branch | Contains | Tasks |
| --- | --- | --- | --- |
| A1 | `feature/finance-i1-overview` | ADR-0010, DATA_OWNERSHIP/ARCHITECTURE/STATUS, package skeleton, money, domain, SQLite store, idempotency | 1-5 |
| A2 | `feature/finance-i1-read-model` | `Authorizer` port + fake, overview read model, REST API, MCP, session seam | 6-9 |
| A3 | `feature/finance-i1-connectors` | `Connector` interface, SimpleFIN, ECB, sync engine, admin CLI | 10-14 |
| A4 | `feature/finance-i1-enable-banking` | EB JWT, authorize/callback/session flow, accounts, balances, transactions, budget | 15-18 |
| A5 | `feature/finance-i1-deploy` | Dockerfile, Quadlet units + timer, backup doc, operator runbook | 19-21 |

The ADR/DATA_OWNERSHIP/ARCHITECTURE/STATUS update ships in A1, the PR that introduces the service (Architecture Change Rule). ADR number 0010 is the next free one on `origin/main`; if the H5 session lands an ADR first, renumber at merge.

## File map (all under `services/finance/` unless noted)

```
pyproject.toml            Dockerfile
app/config.py             # env + secret-file loading, no secret in repr
app/money.py              # exponent table, Decimal<->minor units
app/domain.py             # enums + frozen dataclasses (no I/O)
app/clock.py              # injectable clock
app/store/db.py           # connect(), pragmas, BEGIN IMMEDIATE helper, schema + triggers
app/store/repo.py         # FinanceRepository (all SQL here)
app/authz.py              # Authorizer port, Decision, outcomes, Requirement
app/overview.py           # read model: authority, freshness, subtotals, valuation
app/service.py            # FinanceService: authorize-then-read, nothing else reads the repo
app/session.py            # delegation header seam (mirrors nutrition/app/session.py)
app/main.py               # FastAPI: /health, /overview
app/mcp/server.py         # finance_overview()
app/connectors/base.py    # Connector protocol, RawBalance, RawMovement, ConnectorError kinds
app/connectors/simplefin.py   app/connectors/ecb.py
app/connectors/enable_banking.py   app/connectors/eb_jwt.py
app/sync.py               # SyncEngine + __main__ entrypoint
app/admin.py              # operator CLI: init workspace, add connection, link account
tests/ conftest.py support.py (FakeAuthorizer, FakeConnector, clock, synthetic fixtures)
deploy/finance/           # finance-api.container finance-mcp.container finance-sync.container finance-sync.timer README.md tests/
docs/architecture/adr/0010-svc-finance-domain-service.md
docs/runbooks/finance-i1-nuremberg-bringup.md
```

**Test command (isolated, from `services/finance`):**
```bash
uv run --no-project --python 3.13 --with "fastapi>=0.140" --with uvicorn --with "pydantic>=2" --with httpx --with fastmcp==4.0.3 --with "pyjwt[crypto]" --with pytest python -m pytest tests -q ; echo EXIT=$?
```

---

# PR A1: docs, skeleton, money, domain, store

### Task 1: ADR and architecture docs
**Files:** create `docs/architecture/adr/0010-svc-finance-domain-service.md`; modify `DATA_OWNERSHIP.md` (Finance row: balances, movements, classification, case data owned by `svc-finance`; Home owns Person/consent/activation; bank is the source for balances), `ARCHITECTURE.md` (component map + `svc-finance` ports 9935/9936), `STATUS.md` (Finance: "I1 code in review, not deployed").
- [ ] ADR sections per `docs.md`: Context, Decision (own service; bank-first; connectors behind one interface; read-only, no payments; workspace partitioning; authorization via H2-shaped port), Consequences, Alternatives (Firefly III/ERPNext rejected, per proposal D1).
- [ ] Verify: `grep -n "svc-finance" docs/architecture/*.md docs/architecture/adr/0010*.md` shows all four files.

### Task 2: Money
**Files:** `app/money.py`, `tests/test_money.py`.
- [ ] Failing tests: `parse_amount("1234.50","EUR") == 123450`; `"-0.05"`; `"1,234.50"` rejected (no locale guessing); JPY exponent 0; unknown currency raises `UnknownCurrency`; float input raises `TypeError`; more decimals than the exponent raises (never silently rounds a bank amount); `format_minor(123450,"EUR") == "1234.50"`; sign preserved.
- [ ] Implement with a fixed exponent table (EUR, USD, GBP, CHF, JPY, VES, ...), `Decimal` only at the edges, `int` everywhere else.

### Task 3: Domain types
**Files:** `app/domain.py`, `tests/test_domain.py`.
- [ ] Enums: `AccountType`, `Liquidity` (AVAILABLE/INVESTED/RESTRICTED), `BalanceAuthority` (PROVIDER/LEDGER/EVIDENCE_SNAPSHOT), `MovementAuthority`, `Provider` (ENABLE_BANKING/SIMPLEFIN/FILE_IMPORT), `ConnectionStatus` (OK/REAUTH_DUE/REAUTH_REQUIRED/FAILING/PAUSED), `BalanceKind` (BOOKED/AVAILABLE/VALUATION), `MovementStatus` (PENDING/BOOKED).
- [ ] Frozen dataclasses `Workspace`, `Account`, `Connection`, `BalanceObservation`, `Movement`. `Account.owner_person_ids` is a non-empty tuple. No float fields (test asserts annotations).

### Task 4: SQLite store with immutability
**Files:** `app/store/db.py`, `app/store/repo.py`, `tests/test_store.py`.
- [ ] Failing tests first:
  - pragmas: `journal_mode=wal`, `synchronous=FULL`, `foreign_keys=ON`, `busy_timeout>0`.
  - tables: `workspace`, `workspace_member`, `account`, `connection`, `balance_observation`, `movement`, `command_log`, `fx_rate`, `sync_run`, `access_log`; every row table carries `workspace_id` (schema-introspection test, no globals).
  - `UPDATE`/`DELETE` on `balance_observation` and `movement` raise (triggers).
  - `movement` unique on `(account_id, provider_tx_id)` and on `(account_id, fingerprint)` when no provider id.
  - PENDING to BOOKED: inserting a BOOKED row with `supersedes_id` marks the pending one superseded in a view (`current_movements`), never edited, never duplicated.
  - `latest_balance(account_id, kind)` returns max `as_of`, tie-broken by `observed_at`.
  - cross-workspace read returns nothing (two workspaces, same provider ids).
- [ ] Writes use `BEGIN IMMEDIATE` through one helper; `counterparty_iban_hash` is HMAC-SHA256 with the pepper (a bare hash of an IBAN is brute-forceable).

### Task 5: Idempotent commands
**Files:** `app/store/repo.py` (`run_command`), `tests/test_idempotency.py`.
- [ ] Failing tests (covers part of A4/A13): same key + same payload hash returns the stored result without a second effect; same key + different payload raises `IdempotencyConflict`; the effect and the `command_log` row commit in ONE transaction (inject a failure after the effect, expect neither row); `command_log` records `human_actor`, `machine_caller`, `channel` (`sync|telegram|web|admin`).
- [ ] Verify PR: run the test command; expect all green. Open PR A1.

---

# PR A2: authorization port, read model, API, MCP

### Task 6: Authorizer port (H2-shaped)
**Files:** `app/authz.py`, `tests/support.py` (`FakeAuthorizer`), `tests/test_authz_port.py`.

Contract (proposed H2 `authorize_batch`, one HTTP request per operation):
```
request:  delegation (header, opaque) + requirements[ {subject: "SELF" | "PSN-...", domain: "FINANCE", action: "VIEW|CREATE|UPDATE"} ]   # 1..8
response: {actor_person_id, decisions: [ {subject, domain, action, allow, reason} ]}                # positional, same length and order
```
- [ ] `Authorizer.authorize(delegation, requirements) -> BatchDecision` with `outcome` in `ALLOW | DENY | SESSION_INVALID | UNAVAILABLE` (same semantics as Nutrition's `AccessDecision`).
- [ ] Pure validator `validate_batch(sent, response)`: positional match of subject/domain/action, equal length, `allow` is a real `bool`, non-empty `actor_person_id`, non-empty `reason`. Any mismatch becomes `UNAVAILABLE`, never an allow. More than 8 requirements is rejected locally before any call.
- [ ] `FakeAuthorizer` records calls so tests assert exactly ONE call per operation; scripted per-subject allow/deny, plus modes `unavailable`, `session_invalid`, `raises`.
- [ ] The real HTTP `HomeAuthorizer` is NOT written in Phase A (the server contract is unmerged). It is Phase B Task B2.

### Task 7: Overview read model (pure)
**Files:** `app/overview.py`, `tests/test_overview.py`.
- [ ] Failing tests drive the rules:
  - **Authority (A7):** account total = latest observation of its `balance_authority` kind; movements never change a total; two sources for one account count once.
  - **Preferred kind:** `BOOKED` unless the account says otherwise; SimpleFIN `available-balance` is stored as `AVAILABLE`, not mixed in.
  - **Currencies (A12):** subtotals keyed by `(currency, liquidity)`; no cross-currency sum anywhere in the structure; VES present only as its own subtotal and never valued.
  - **Freshness (A11):** per-account status `FRESH | STALE | REAUTH_DUE | REAUTH_REQUIRED | NO_DATA` from `as_of` vs `freshness_sla` and connection state. Stale keeps its last amount AND last date and sets `stale=True` on the subtotal. `NO_DATA` is excluded from totals and listed, never shown as 0. Sync failing 2 days gives STALE with last good date.
  - **Consent:** `consent_expires_at` within 7 days gives `REAUTH_DUE`.
  - **Valuation:** only when `valuation_currency` is requested; uses stored ECB rates; output line carries `rate_date`; currencies with no rate go to `unvalued`; VES is always `unvalued`; Decimal math with round-half-even to the minor unit at the end; rate older than 5 days is flagged.
  - Every account row carries `institution`, `source` (provider), `as_of`, `observed_at`.
  - Receivables are out of I1 and absent.

### Task 8: FinanceService (authorize first, read second)
**Files:** `app/service.py`, `tests/test_service_authorization.py`.
- [ ] Failing tests (A6 and visibility):
  - No delegation: DENY, `repo` mock never touched (call-count assertion on every repo method).
  - `SESSION_INVALID`, `UNAVAILABLE`, `DENY`, exception from the authorizer, malformed batch: all give a typed refusal, zero repo reads, zero retries, exactly one authorizer call.
  - Requirements built from the workspace owners: `SELF` + each other distinct owner as `PSN-...`, all `FINANCE/VIEW`. More than 8 distinct owners fails closed.
  - Actor must be a `workspace_member`; a stranger who Home says is allowed still gets DENY.
  - Visibility rule: an account is shown only if EVERY owner is allowed (joint accounts). A hidden account is omitted and the response says `hidden_accounts: n` (no names, no amounts). Own accounts are matched through the returned `actor_person_id`.
  - Workspace inactive (`PAUSED/ARCHIVED`) returns `FEATURE_OFF` before any read. (Home Feature Activation is Phase B.)
  - No method accepts an actor, workspace override, or SQL (signature test via `inspect`).
- [ ] The workspace is resolved server-side from the actor's membership (single workspace in I1; multi-workspace stays in the schema).

### Task 9: REST + MCP + session seam
**Files:** `app/session.py`, `app/main.py`, `app/mcp/server.py`, `tests/test_api.py`, `tests/test_mcp_transport.py`, `tests/conftest.py`.
- [ ] `session.py` copies Nutrition's seam: read ONLY `X-Episteck-Delegation` via `get_http_headers()`, never `include_all`.
- [ ] `GET /overview?valuation_currency=EUR`: header-only delegation; fixed bodies 401 `SESSION_INVALID`, 403 `ACCESS_DENIED`, 503 `SERVICE_UNAVAILABLE`, 409 `FEATURE_OFF`; Home's reason text never reaches a body. `GET /health` public. No actor/workspace parameters.
- [ ] MCP `finance_overview(valuation_currency: str | None)` is a thin call into the same `FinanceService.overview`; refusals return the same typed business-safe dicts. Test that REST and MCP return byte-identical overview JSON for the same fixture.
- [ ] Tests assert: response JSON contains no `float`, amounts are minor-unit ints plus a formatted string, and logs (caplog) contain no amounts, IBANs, person ids or delegation.
- [ ] Run the full test command. Open PR A2.

---

# PR A3: connectors, ECB, sync, admin CLI

### Task 10: Connector interface
**Files:** `app/connectors/base.py`, `tests/test_connector_contract.py`.
- [ ] `Connector` protocol: `list_accounts()`, `fetch_balances(account_ref)`, `fetch_movements(account_ref, since)`, `check_health()`. Result types `RawBalance(kind, amount_minor, currency, as_of)` and `RawMovement(provider_tx_id|None, status, booking_date, value_date, amount_minor, currency, counterparty_name, counterparty_iban, remittance)`.
- [ ] `ConnectorError(kind)` with kinds `AUTH_REQUIRED | RATE_LIMITED | UNAVAILABLE | MALFORMED | CONSENT_EXPIRED`. A shared contract test suite runs against every connector (and the fake) so Enable Banking in A4 is held to the same rules.

### Task 11: SimpleFIN connector
**Files:** `app/connectors/simplefin.py`, `tests/test_simplefin.py`.
- [ ] Failing tests with `httpx.MockTransport` and synthetic v2 payloads:
  - `claim(setup_token)`: base64 decode, POST, returns the Access URL; 403 raises a distinct `TokenAlreadyClaimed` and the log line says "possible compromise" without echoing the token.
  - Basic-auth credentials are taken from the Access URL userinfo into an `Authorization` header and are never logged.
  - Parses string `balance`/`available-balance` to minor units; `balance-date` epoch to UTC `as_of`; pending (`posted=0`) tx gets `PENDING` and a fingerprint id; posted gets `BOOKED`.
  - `currency` that is a URL (custom currency) is rejected as `MALFORMED`, not guessed.
  - `errlist` entry `con.auth`/`gen.auth` becomes `AUTH_REQUIRED` for that connection; 402/403 map to errors; other accounts' data still returned.
  - Request uses `version=2`, `balances-only=1` for balance polls, `start-date` for transactions, `pending=1`.
  - Text fields are sanitised (control characters stripped, length capped) because the spec says to treat them as untrusted.

### Task 12: ECB reference rates
**Files:** `app/connectors/ecb.py`, `tests/test_ecb.py`.
- [ ] Parse `eurofxref-daily.xml` (synthetic sample): `Cube time="..."` and `Cube currency rate`. Rates kept as decimal strings. Stored in `fx_rate(date, currency, rate)` idempotently (same date + currency is a no-op; a different rate for the same key is an error). Fetch failure leaves old rates and never raises into the sync. Use `defusedxml`-style safe parsing (no entity expansion).
- [ ] Test A12: VES and any currency not in the feed are `unvalued`.

### Task 13: Sync engine
**Files:** `app/sync.py`, `tests/test_sync.py`.
- [ ] Failing tests (A4, A13):
  - Same movement in two consecutive syncs gives one row; PENDING then BOOKED gives a superseding row, one visible movement.
  - Provider id absent: fingerprint (`booking_date|amount|currency|counterparty|remittance|ordinal`) is stable across runs; two identical same-day payments get distinct ordinals; re-run adds nothing.
  - Interrupted sync: inject an exception after the balance insert and before the movements commit; per-account atomic transaction means nothing partial; the re-run completes with no duplicates; killing mid-run leaves `sync_run` as `FAILED`/`INTERRUPTED`, not `OK`.
  - `ConnectorError` `AUTH_REQUIRED` sets the connection `REAUTH_REQUIRED`; `RATE_LIMITED` stops that account for the run without retry; one failing connection never blocks another.
  - Writes `human_actor=NULL`, `channel='sync'`.
  - Never writes a balance observation when the fetch failed (no zero rows).
  - `PAUSED` connections and `PAUSED` workspaces are skipped.
- [ ] Entry point `python -m app.sync` loads config, runs one pass, exits non-zero if any connection failed (so systemd records it).

### Task 14: Admin CLI (bootstrap without the API)
**Files:** `app/admin.py`, `tests/test_admin.py`.
- [ ] Commands: `init-workspace --name --owner PSN-...`, `add-connection --provider simplefin|enable_banking --owner PSN-... --secret-file PATH`, `link-account --connection --provider-account-id --institution --type --liquidity --balance-authority --currency --owner PSN-...`, `claim-simplefin --setup-token-file PATH --out PATH` (writes the Access URL with mode 600, prints no secret), `list`.
- [ ] Operator-only: no HTTP surface, so no account can be added by a model or a remote caller. Secret files must exist and be mode 600 or the command refuses (test).
- [ ] Run the full suite. Open PR A3.

---

# PR A4: Enable Banking

### Task 15: JWT signer
**Files:** `app/connectors/eb_jwt.py`, `tests/test_eb_jwt.py`.
- [ ] Tests generate a throwaway RSA key in-test (never a fixture file). Assert header `{typ:JWT, alg:RS256, kid}` and claims `iss=enablebanking.com`, `aud=api.enablebanking.com`; `exp - iat <= 3600` (we use 1 h, spec max 24 h); signature verifies with the public key; tokens are minted per process start and refreshed before expiry; the private key path must be mode 600; `repr`/logs never show key material.

### Task 16: Authorization and session flow
**Files:** `app/connectors/enable_banking.py` (auth part), `app/store/repo.py` (`oauth_state`), `tests/test_eb_authorize.py`.
- [ ] `GET /aspsps` read of `maximum_consent_validity` per bank; requested `valid_until = min(now + configured, max)`; stored `consent_expires_at` comes from `POST /sessions` response, not from what we asked.
- [ ] `start_authorization(connection)` returns `{url}` and stores a single-use `state` (bound to connection and owner, expires in 15 min). Callback handler validates `state` (unknown, expired, reused, wrong connection all fail identically), exchanges `code`, checks returned accounts against the linked set: an unexpected new account yields a pending-confirmation record, never silent linking.
- [ ] The public route is NOT added here; this is service logic plus a handler. Exposing it is Phase B (narrow route on the BFF vhost).

### Task 17: Accounts, balances, transactions
**Files:** `app/connectors/enable_banking.py` (data part), `tests/test_eb_data.py`.
- [ ] Synthetic payloads: string amounts parsed to minor units; `CRDT/DBIT` sets the sign; status `BOOK` becomes BOOKED, `PDNG` becomes PENDING, `CNCL/RJCT/SCHD/HOLD/OTHR` are not ingested as booked facts (documented, tested); `continuation_key` paging is followed to a cap; balance types map `CLBD/ITBD/OPBD` to BOOKED and `CLAV/ITAV/OPAV` to AVAILABLE, unknown types are skipped and counted; Trade Republic cash rows with missing description do not crash and get an empty counterparty and a fingerprint.
- [ ] Error mapping: `EXPIRED_SESSION/CLOSED_SESSION/REVOKED_SESSION/ACCESS_DENIED` become `CONSENT_EXPIRED/AUTH_REQUIRED`; 429 + `ASPSP_RATE_LIMIT_EXCEEDED` becomes `RATE_LIMITED`; `PSU_HEADER_NOT_PROVIDED` is surfaced as `UNAVAILABLE` with a static log category (we send NO PSU headers on unattended runs and never fake presence).
- [ ] Runs through the Task 10 contract suite.

### Task 18: PSD2 access budget
**Files:** `app/store/repo.py` (`access_log`), `app/connectors/enable_banking.py`, `tests/test_eb_budget.py`.
- [ ] Every data request (balances, each transactions page) is recorded per account. A request is refused locally (`RATE_LIMITED`, nothing sent) when the rolling-24 h count is at the cap (`EB_MAX_DATA_REQUESTS_PER_ACCOUNT_PER_24H`, default **4**, counting EVERY data call, which is the conservative reading). Default timer is 2 syncs/day = 2 balance + 2 transaction calls = at the cap. A bank-reported 429 also closes the account's window until the next day. Whether banks count per call or per sync is UNVERIFIED; the cap is config so the live gate (Phase B) can relax it from evidence.
- [ ] Run the full suite. Open PR A4.

---

# PR A5: deploy artifacts (not deployed)

### Task 19: Image and Quadlet units
**Files:** `services/finance/Dockerfile`, `deploy/finance/finance-api.container`, `finance-mcp.container`, `finance-sync.container`, `finance-sync.timer`, `deploy/finance/tests/test_finance_quadlets.py`.
- [ ] Dockerfile like Nutrition's (python 3.11-slim, installs the package, runs as non-root UID via `--userns=keep-id` in the unit). API `127.0.0.1:9935`, MCP `127.0.0.1:9936`, loopback only (test asserts no `0.0.0.0` publish).
- [ ] `finance-sync.container` has no `[Install]`; `finance-sync.timer` (`OnCalendar=*-*-* 06:20,18:20`, `Persistent=true`, `RandomizedDelaySec=300`) activates the generated `finance-sync.service`. Command `python -m app.sync`, `Restart=no`, memory cap.
- [ ] Shared bind mount `/srv/episteck/services/finance/data` (SQLite, WAL) and read-only `secrets/` (mode 600 files). `PodmanArgs=--memory=...` on each unit.
- [ ] Tests parse the units: images are pinned to a SHA placeholder that fails the test if left as `latest`; secrets are `EnvironmentFile`/read-only volume only; no secret value appears in any unit file.

### Task 20: Backup inclusion
- [ ] Update `docs/architecture/DEPLOYMENT.md` (ports 9935/9936, svc-finance uid, unit list) and document the restic addition: a consistent `sqlite3 finance.sqlite ".backup ..."` snapshot before `restic backup`, `PRAGMA integrity_check` on the snapshot, secrets directory EXCLUDED (re-obtainable, same rule as other services). The existing job is root-owned under `/etc/episteck/backup`, so this plan only prepares the exact diff in the runbook; the operator applies it.

### Task 21: Operator runbook
**Files:** `docs/runbooks/finance-i1-nuremberg-bringup.md`.
- [ ] Exact `! ssh -F C:/Users/D064974/.ssh/config episteck-node1 '...'` blocks (start with `cd /`), each with a verify command and a rollback:
  1. Pre-check: ports 9935/9936 free (`ss -tlnH`), next free uid (current users 1004-1008, 999), disk (51 GB free), RAM.
  2. Create user `svc-finance`, `chmod 700` home, `loginctl enable-linger`, rootless podman env (`XDG_RUNTIME_DIR=/run/user/<uid>`). Rollback: stop units, `userdel -r`.
  3. Directories `/srv/episteck/services/finance/{data,secrets}` with 700/600.
  4. Secret files created by the operator on the node (EB private key, app id, SimpleFIN access URL, pepper): `install -m 600`, content typed or piped on the node, never through chat or the agent.
  5. Build image from a recorded commit SHA, install units, `systemctl --user daemon-reload`, start API/MCP, enable the timer.
  6. Read-only verification: `curl 127.0.0.1:9935/health`, `/overview` returns 401 without delegation, `ss` shows loopback only, `journalctl --user` has no secrets, `systemctl --user list-timers`.
  7. Admin bootstrap (`init-workspace`, `add-connection`, `link-account`) run as `svc-finance` on the node.
  8. Rollback section: stop and disable units, remove units, keep or `shred` data, restic restore drill.
- [ ] Phase B placeholders are listed but clearly marked "blocked on H5".
- [ ] Run suite + quadlet tests. Open PR A5.

---

## Scenario coverage (proposal §13)

| Scenario | Where it is proven in Phase A |
| --- | --- |
| A4 duplicates | Tasks 4, 5, 13 |
| A6 no authorization means deny with no read | Tasks 8, 9 (repo call counts, one authorizer call) |
| A7 double counting | Task 7 |
| A11 stale or reauthorize | Tasks 7, 13, 16 |
| A12 currencies | Tasks 7, 12 |
| A13 replay and restart | Tasks 5, 13 (restic restore drill is live, Task 21) |

## Review focus

1. A stale or failed account must never render as 0 (Task 7 `NO_DATA`/`STALE` tests).
2. Exactly one authorizer call and zero repo reads on every non-ALLOW path (Task 8).
3. The EB unattended budget counts every call and sends no PSU headers (Tasks 17, 18).
4. No secret, IBAN, amount, person id or delegation in logs or error bodies (Tasks 9, 11, 15).
5. Immutability is enforced by triggers, not by convention (Task 4).

## Open questions for the owner (defaults chosen if you do not object)

1. **Joint accounts:** visible only if the actor is allowed on EVERY owner (conservative). Alternative: any owner.
2. **Trade Republic cash liquidity:** default `AVAILABLE`; set `INVESTED` per account at link time if you prefer.
3. **Owner identifiers:** `init-workspace` needs Erick's real `PSN-...` id from Home. I will not read it from Home myself; you pass it on the node.
4. **uid / ports:** `svc-finance` takes the next free uid and ports 9935/9936 (free as of today). Re-checked in the runbook pre-check.
5. **Bootstrap via admin CLI** instead of REST commands, to keep the API surface read-only in I1.
6. **EB budget:** counting every call (cap 4) may need relaxing after the live measurement.

## Phase B (blocked until H5 merges; I will ask before starting)

B1 H1 `svc-finance` audience + machine user; B2 H2 `authorize_batch` in Home and the real `HomeAuthorizer` client; B3 H3 Feature Activation (manual `bench migrate` on home); B4 H4 `/gateway/finance/` route, per-audience mint, nft rule; B5 narrow PSD2 callback route on the BFF vhost; B6 Telegram on `home-agent` (new bot, `TELEGRAM_ALLOWED_USERS` = Erick only, groups off, `stt.language: es`); B7 `openai-codex` login (operator) with Kimi fallback; B8 "Olin Finance" skill (figures only from tools, no amounts in memory); B9 live verification Telegram to Hermes to gateway to Finance to Home on Nuremberg with real data.
