# Olin Finance I2: progress board

> Board for I2 (family currency exchanges) inside svc-finance. Synthetic data only: this is a public repo, so no real names, amounts, IBANs, phone numbers or frequencies appear here. Roles are "el dueño", "socio de cambio", "Familiar A" and "Fondo F". The I1 board stays in `FINANCE_I1_PROGRESS.md`.

Last updated: 2026-11-19 (Tasks 1-12 merged in #128, #129, #130, #132, #133, #134, #135 and #137; final-review fixes R57-R64 on `feature/finance-i2-final-fixes`, not merged; Task 13 next; Task 0 S1 waiting on the owner).

## 0. How to work with this board

1. Read sections 1-3, then pick the first task in section 4 whose status is `not started` and whose dependencies are done. Say which one you picked.
2. Verify the facts you depend on before acting. Anything that contradicts this file: stop, correct it, tell the owner.
3. Use TDD (`superpowers:test-driven-development`). Small PRs, at most 800 changed lines. Commits `<type>: summary`, lowercase, branches `feature/...`. Commit and PR bodies end with the session-link line the harness gives you.
4. **No stacked PRs:** each PR branches from the current `origin/main`; the next starts after the previous one merged.
5. **Production changes are run by the owner.** Prepare exact `! ssh -F <ssh config> episteck-node1 '...'` commands with a rollback; verify read-only afterwards. Secrets never go through the chat.
6. When a task ends: set its status, add PR numbers and evidence, append one line to the session log (section 6), and tell the owner what is next. Warn at about 70% context.
7. Off limits: Nutrition files, `apps/home-hub/**` (I4a is a later PR) and `apps/episteck_home/**`.

Statuses: `not started`, `in progress`, `in review` (PR open), `waiting on owner`, `done`, `blocked`.

## 1. Goal and scope

The owner records family exchanges by chat; Olin keeps an append-only receivables ledger per person and currency, links partner payments and relatives' receipts to exchanges, asks only the questions it cannot answer, and reports what is owed and what is open. Finance never moves money.

Governing documents: `docs/superpowers/specs/2026-11-18-finance-i2-exchanges-design.md` (design, Spanish), `docs/superpowers/plans/2026-11-18-finance-i2-exchanges.md` (plan), `adr/0016-finance-exchanges-ledger.md`, and `adr/0011-svc-finance-domain-service.md` (I1 base).

## 2. Standing rules

- Money is `int` minor units plus ISO currency, never `float`.
- No tool or route accepts an actor, workspace, token, account id or SQL.
- One Home request per user operation; the matcher in the sync unit makes none (ADR-0016).
- Facts are append-only; undo is a revocation or a `REVERSAL` entry. I2 only adds tables.
- Logs carry kinds and counts only, never labels, aliases, notes or amounts.
- Level-3 actions are confirmed in Telegram until I4a deploys (ADR-0016).

## 3. PR map

| PR | Branch | Tasks |
| --- | --- | --- |
| 1 | `feature/finance-i2-exchanges` (holds the design commit) | 1, 2 |
| 2 | `feature/finance-i2-store` | 3, 4 |
| 3 | `feature/finance-i2-ledger` | 5, 6 |
| 4 | `feature/finance-i2-receipts` | 7, 8 |
| 5 | `feature/finance-i2-matcher` | 9 |
| 6 | `feature/finance-i2-tools` | 10, 11 |
| 7 | `feature/finance-i2-hermes` | 12 (needs Task 0 results) |
| - | (owner-run) | 13 deploy, live check, initial load |
| 8 (optional) | `feature/finance-i2-chat-import` | 14 |

Task 0 runs on the node in parallel with PRs 1-6.

## 4. Task board

| Task | Work | PR | Status |
| --- | --- | --- | --- |
| 0 | Two spikes on the node (owner-run, no repo code) | - | S2 done; S1 waiting on owner |
| 1 | ADR-0016, documentation pointers and the I2 board | 1 | done (#128) |
| 2 | Pure core: model, FX arithmetic, allocation, text keys | 1 | done (#128) |
| 3 | Schema and repository | 2 | done (#129) |
| 4 | Pending queue and intervention log | 2 | done (#129) |
| 5 | Ledger: record an exchange and the receivables view | 3 | done (#130) |
| 6 | Funding: link partner payments, rate, EUR shares | 3 | done (#130) |
| 7 | Receipts, allocation, credits, held cash, small-difference adjustment | 4 | done (#132) |
| 8 | Corrections, forgiveness and generic reversal | 4 | done (#132) |
| 9 | Matcher after each sync, and operator commands | 5 | done (#133) |
| 10 | Commands and `ReceivablesService` | 6 | done (#134) |
| 11 | MCP tools and REST routes | 6 | done (#135) |
| 12 | Hermes skill, cron and runbook (needs Task 0) | 7 | done (#137) |
| 13 | Deploy, live check and initial load (owner-run) | - | not started (next, after the final-review fixes merge) |
| 14 | Fund reconstruction from the chat export (optional) | 8 | not started (optional) |

## 5. Spikes (Task 0, owner-run on the node)

Facts only, no real data. Produces `S1 = BUTTONS | CODE_REPLY` plus the exact `hermes cron` invocation, and `S2 = STABLE | UNSTABLE` plus the path where Hermes stores files sent to the bot.

### S1. Cron to Telegram with buttons

A one-off cron job delivers to the owner's Telegram a message with two inline buttons; a second job stays silent when there is nothing to report. Both jobs are removed afterwards.

| Field | Result |
| --- | --- |
| Buttons render and the choice comes back | pendiente |
| Silence works when there is nothing to report | pendiente |
| Exact create / list / remove `hermes cron` syntax | pendiente |
| S1 verdict (`BUTTONS` or `CODE_REPLY`) | pendiente |

Read-only findings from the installed Hermes 0.21.2 docs and code (2026-11-18), before the owner test:

- Cron runs cannot use `clarify` ("cron jobs cannot ask clarifying questions"), so a cron message carries no inline buttons. Buttons exist in live Telegram sessions (`send_clarify` in the Telegram adapter). Expected: `CODE_REPLY` for the cron message (the owner answers "P3", "P3 sí"), with buttons once the owner is in the live session.
- `hermes cron create --name <n> --deliver telegram "<schedule>" "<prompt>"`; one-shot schedule `in 2m`; cron expressions use the node time zone (UTC), so `35 6,18 * * *`; `hermes cron list`; `hermes cron remove <id or name>`.
- A final response containing `[SILENT]` suppresses delivery (failed runs always deliver).
- `--deliver telegram` uses the configured Telegram home channel (set on the node).

### S2. Shape of USD-account credit descriptions (read-only)

Counts and token-class templates only (letters to `A`, digits to `9`, a short list of known words kept); no names, no amounts.

| Field | Result |
| --- | --- |
| Count of credits | small sample (history since I1 go-live); exact counts stay off the repo |
| Count of distinct `description_key` values | fewer keys than credits |
| Repeated payers map to one key | yes. Zelle keys carry the payer name and no other variable text once digit tokens drop. Caveat: the alphanumeric code after `CONF#` can, rarely, have no digit; `description_key` therefore also drops the token that follows a token ending in `#` (ruling at Task 2) |
| Directory where Hermes stores documents sent to the bot | `/home/home-agent/.hermes/cache/documents` |
| S2 verdict (`STABLE` or `UNSTABLE`) | `STABLE` (2026-11-18, run read-only as `svc-finance` on the host, `mode=ro`) → Task 13 sets `FINANCE_DESCRIPTION_RULES=on` |

## 6. Session log (append one line per session)

- 2026-11-18: design and plan approved; execution started (Tasks 1-2 in PR 1; Task 0 waiting on the owner). Nothing deployed.
- 2026-11-18: PR 1 merged (#128); Tasks 3–4 implemented on feature/finance-i2-store.
- 2026-11-18: PRs #129, #130, #132 merged; Task 9 on feature/finance-i2-matcher.
- 2026-11-19: PRs #133, #134, #135 and #137 merged (Tasks 9-12). The final whole-I2 review over a realistic month found 1 Critical and 6 Important defects between the PRs; fixed on `feature/finance-i2-final-fixes` (rulings R57-R64: owner-reversed fundings wait for the owner, credits count once BOOKED, go-live history, partner IBANs forgotten with the funding that taught them, re-ask after "register it", fund opening echo with flows, superseded echoes) plus two read-only go-live checks in the runbook. Nothing deployed. Next: Task 13.
