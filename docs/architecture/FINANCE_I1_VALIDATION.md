# Olin Finance I1 Validation (B11)

**Result:** automated live checks **PASS** on 2026-11-08. Two owner checks remain (O1 logout,
O2 stranger), see [Owner checks](#owner-checks).

**Scope:** live system on `episteck-node1`, the owner's real bank data (decision P1). The
evidence holds statuses, refusal codes, account slugs, dates, booleans and counts. It holds
no amount, IBAN, delegation, token or bank reference. The probe scripts and how to re-run
them are in [`spike/finance-i1-b11/`](../../spike/finance-i1-b11/README.md).

## What runs

| Property | Live value |
| --- | --- |
| Finance image (`finance-api`, `finance-mcp`, `finance-sync` Quadlets) | `localhost/episteck-finance:dbe66328f9e0a30d85987fbb8646fe5d5e7a846d` (`main` after #119) |
| Image ID / digest | `5e310f15a015af74699fd83fa8f73e7c2d1717b9e188d0e2a25fa7ec49e745b9` / `sha256:4bec6bc82587cca7c0b74339d3820c58da24cc3a4d29880c8cf55767f8f8b1e1` |
| Running | `finance-api` and `finance-mcp` on that image ID; `finance-sync` is the timer's oneshot |
| Accounts | `bofa-checking`, `bofa-savings` (USD, SimpleFIN); `sparkasse-giro`, `traderepublic-cash` (EUR, Enable Banking) |
| Hermes | `home-agent`, Hermes Agent 0.21.2, model `openai-codex` / `gpt-5.6-sol`, no fallback |
| Hermes Finance MCP URL | `http://127.0.0.1:9934/gateway/finance/` |
| Gateway identity | `svc-home-gateway` (uid 999); `home-agent` is uid 1003 |

## Trust boundary

### nftables (`table inet episteck_gateway`, output chain)

```
ip daddr 127.0.0.1 tcp dport 9934 meta skuid 1003 accept
ip daddr 127.0.0.1 tcp dport 9934 drop
ip daddr 127.0.0.1 tcp dport { 9931, 9932, 9936 } meta skuid 999 accept
ip daddr 127.0.0.1 tcp dport { 9931, 9932, 9936 } drop
```

### Real-user TCP matrix (connect only)

| Identity | Gateway 9934 | Finance API 9935 | Finance MCP 9936 |
| --- | --- | --- | --- |
| `home-agent` (1003) | **CAN** | CAN (see F1) | **CANNOT** |
| `svc-home-gateway` (999) | CANNOT | CAN | **CAN** |
| `www-data` (33) | CANNOT | CAN | CANNOT |
| `svc-home-bff` (1007) | CANNOT | CAN | CANNOT |
| `svc-finance` (1010) | CANNOT | CAN | CANNOT |
| `svc-nutrition` (1005) | CANNOT | CAN | CANNOT |

### Mint socket

`/run/episteck/home-bff-mint/mint.sock` is `svc-home-bff:episteck-gw 0660` in a
`2770` directory. `svc-home-gateway` **CAN** connect. `home-agent`, `www-data` and
`svc-finance` **CANNOT** (`PermissionError`).

## Delegation probes (`b11_probe.py`)

| # | Caller | Request | Result | Expected |
| --- | --- | --- | --- | --- |
| G0 | `home-agent` | `initialize` through the gateway | HTTP 200 | ✅ |
| G1 | `home-agent` | `tools/list` | one tool, `finance_overview(valuation_currency)`: no actor, workspace, token or SQL argument | ✅ |
| G2 | `home-agent` | `finance_overview` through the gateway | 4 accounts, all `FRESH`, all with a figure | ✅ allow |
| G3 | `home-agent` | same, with a forged `X-Episteck-Delegation` | same as G2: the gateway replaces the header with its own minted delegation (`nginx-mcp-gateway.conf`, `proxy_set_header` and `proxy_hide_header`), so the forged value never reaches Finance | ✅ |
| G4 | `home-agent` | TCP to 9936 | CANNOT (timeout, nft drop) | ✅ |
| D1 | `svc-home-gateway` | 9936 with no delegation | `session_invalid`, no data | ✅ |
| D2 | `svc-home-gateway` | 9936 with a garbage delegation | `session_invalid`, no data | ✅ |
| D3 | `svc-home-gateway` | mint | 204, delegation returned | ✅ |
| D3a | `svc-home-gateway` | first use of D3 | 4 accounts, `FRESH` | ✅ |
| D3b | `svc-home-gateway` | replay of D3 | `session_invalid`, no data | ✅ single use |
| E1/E2 | `svc-home-gateway` | mint, wait 130 s, use (TTL 120 s) | `session_invalid`, no data | ✅ expiry |

The `finance-mcp` journal for 2026-11-08 holds exactly three
`home authorization not granted: home_rejected_credential_or_session` lines: D2, D3b and
E2. D1 never reaches Home, because Finance refuses a missing delegation itself.

## Home unavailable (`b11-homedown.sh`)

A throwaway container from the live image ran the API and MCP with `--network none`, an
empty temp DB, a throwaway pepper, a fake Home credential and
`HOME_CONTROL_PLANE_URL=http://127.0.0.1:9999`. The probe played Home on that port.
Each row was checked on `GET /overview`, `GET /overview?valuation_currency=EUR` and the MCP
tool.

| # | Home behaviour | API | MCP | Data in any response |
| --- | --- | --- | --- | --- |
| H1 | (no delegation sent) | 401 `SESSION_INVALID` | `session_invalid` | none |
| H2 | port closed | 503 `SERVICE_UNAVAILABLE` | `service_unavailable` | none |
| H3 | accepts, never answers | 503 after 3.0 s (`HOME_API_TIMEOUT_SECONDS`) | `service_unavailable` after 3.0 s | none |
| H4 | HTTP 500 | 503 | `service_unavailable` | none |
| H5 | HTTP 200, malformed answer | 503 | `service_unavailable` | none |
| H6 | HTTP 401 (control) | 401 `SESSION_INVALID` | `session_invalid` | none |

The container log held only the expected static categories (`home_unreachable` ×6,
`home_unavailable` ×3, `home_malformed` ×3, `home_rejected_credential_or_session` ×3) and
no `Traceback` or `ERROR`. `--rm` removed the container, and the live units stayed
`active`.

## Model and log hygiene

- **Only OpenAI sees Finance data (P2).** In `agent.log` since the 2026-11-07 22:07
  switch, all 8 model calls went to `provider=openai-codex`. Tool calls were
  `mcp__home__whoami`, `mcp__home__check_access` and `mcp__finance__finance_overview`,
  with no web, browser or image tool. The other provider names in the log are plugin
  registrations at startup, not calls.
- **The owner's Telegram test** (2026-11-07, night) answered with all three banks. The
  `finance-mcp` journal from 2026-11-07 22:07 to 2026-11-08 06:00 shows `POST /mcp`
  163 × 200 and 2 × 202, `GET /mcp` 2 × 200 and 2 × 400, and `DELETE /mcp` 2 × 200. The two
  400s are refused stream opens, which is normal for MCP over HTTP.
- **No figures in logs.** `b11-logscan.sh` found 0 IBANs, 0 amounts, 0 amount fields and
  0 Enable Banking references across 13 sources: the `finance-api`, `finance-mcp`,
  `finance-sync` and `episteck-mcp-gateway` journals, the nginx BFF logs, the Hermes
  `agent.log`, `errors.log` and `gateway.log`, the Hermes memories, and the
  `hermes-gateway` journal.

## Unit evidence (same commit)

`services/finance` suite on `dbe6632`: **298 passed, 2 skipped**. The tests that carry the
rules not proven live:

- `test_no_delegation_is_refused_without_calling_home_or_the_repository`
- `test_every_non_answer_is_refused_with_one_home_call_and_no_data_read`: one Home
  decision per operation, and nothing read on a refusal
- `test_denied_self_view_is_refused_and_reads_nothing`: zero-role deny
- `test_actor_who_is_not_a_workspace_member_is_denied_even_if_home_allows`
- `test_joint_account_is_hidden_unless_every_owner_is_allowed`
- `test_no_method_accepts_an_actor_workspace_or_sql`

## Findings

| # | Severity | Finding | Proposed action |
| --- | --- | --- | --- |
| F1 | Low | `finance-api` 9935 accepts TCP from every local uid; nft covers 9934, 9931, 9932 and 9936 only. Not a bypass: `/overview` needs a delegation, only the mint socket issues one, and Home checks it (D1, D2, H1). | Owner decision. Add `tcp dport 9935 meta skuid 33 accept` and `tcp dport 9935 drop` (nginx serves the public callback as `www-data`), or accept as is. |
| F2 | Low | The Finance image has no `org.opencontainers.image.revision` label. The tag carries the full SHA. | Add `--label org.opencontainers.image.revision=<sha>` in the next Finance build. |
| F3 | Low | Audience isolation is one-way (`auth_hook.py`, `_accepted_audiences`). Home accepts a Control Plane delegation from any machine caller, Finance's included, so one minted for Home MCP or Nutrition would also pass `authorize_batch`. Only `svc-home-gateway` ever holds one (mint socket matrix), for 120 s and single use. | Owner decision. A small Home PR: when the caller is `home_finance_machine_user`, accept only `svc-finance`. |
| F4 | Info | MCP refusals are tool results (`{"ok": false, "error": …}`) over transport HTTP 200. The API uses 401, 403 and 503. | None: by design. |

## Owner checks

| # | Check | Expected | Result |
| --- | --- | --- | --- |
| O1 | Log out of Home (or revoke the grant at `/runtime`), then ask the bot for the balance | no figure; the bot says it has no access | pending |
| O1b | Log in, grant again at `/runtime`, note the grant's expiry | balance answers again until that expiry | pending |
| O2 | A Telegram account outside the allowlist messages `@EpisteckHome_bot` | no reply | pending |
