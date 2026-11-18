# ADR-0016: svc-finance keeps its own receivables ledger for family exchanges and never moves money

## Status
Proposed (2026-11-18). Accepted when the PR that introduces the ledger tables merges.
Governing design: `docs/superpowers/specs/2026-11-18-finance-i2-exchanges-design.md`
(§5, §8.1, §11–13). It replaces proposal `OLIN_FINANCE_V1.md` §5.2, §6.5 and §9.1.
Amends ADR-0011 point 7.

## Context
I2 covers the family currency exchange: the owner converts USD for relatives through a
trusted exchange partner (socio de cambio), relatives pay back in several currencies, and
a custodial fund (Fondo F) finances part of it. Today this lives in chat messages and
memory. Olin must answer "who owes what, in which currency, and what is still open?" from
recorded facts, with every correction traceable. The flow is not a linear state machine:
debts can be agreed after delivery, and repayment can be partial, in cash, or an advance.
ADR-0011 made Finance read-only in I1; I2 needs Finance to write its own records, and
those writes must stay safe when a language model proposes them.

## Decision
1. **Finance writes its own receivables ledger, never money.** Counterparties, exchanges
   with lines, a per-person, per-currency running account (append-only), receipts,
   allocations and pending questions are Finance data. No tool moves, requests or
   authorises a payment. Bank movements are never altered, only their interpretation.
2. **Approach B (spec §5): an exchange with lines plus a running account.** One mechanism
   covers debt, advance, prepayment and fund. Approach A (a state machine per request)
   models steps that do not exist and adds a question per state. Approach C (full double
   entry) is premature and overlaps I3.
3. **Two-phase confirmation for money-affecting writes (spec §8.1).** Phase 1 returns
   `confirmation_required` with a code and an echo and writes only the `PendingItem`.
   Phase 2, `finance_resolve_pending(code, "yes")`, executes the **stored** payload; the
   model never resends it. The residual risk of proposal §8.3 stays accepted.
4. **Content-derived idempotency with `possible_duplicate`.** A write whose payload equals
   one already completed the same day returns `possible_duplicate` with
   `[Es otro] [Es el mismo]` instead of being dropped, because two identical receipts in
   a day can be real. "Es otro" adds a uniqueness suffix. A retry over an open `CONFIRM`
   returns the same `CONFIRM`. `resolve_pending` is idempotent by `(code, choice)`. Every
   write goes through `run_command` and `command_log`.
5. **Level-3 actions are confirmed in Telegram until I4a deploys** (owner decision
   2026-11-18). Cash at or above the high-value threshold and reversal of interpretations
   of bank facts need `CONFIRM` with a reinforced echo. This exception **expires when
   I4a ships**; from then on those actions move to the web.
6. **The matcher runs inside the sync unit and makes no Home call.** It is not a user
   operation, so it has no actor. Its writes are attributed
   `machine_caller="sync"`, `human_actor=NULL`. User-initiated tools still make one Home
   request per operation through the `Authorizer` port, as in ADR-0011.
7. **Facts are append-only.** New fact tables get `BEFORE UPDATE`/`BEFORE DELETE`
   triggers. Undo is a `revocation` row and/or a `REVERSAL` ledger entry. I2 only adds
   tables; it never alters I1 tables.
8. **Amends ADR-0011 point 7.** "Read-only in I1; no payments, ever in v1" becomes:
   Finance may write its own receivables records (I2); it still never moves money or
   stores payment credentials, and bank facts stay immutable.

## Consequences
+ One ledger answers debts, advances, prepayments and the fund with the same arithmetic.
+ Every figure traces to a recorded fact; corrections are visible, not overwritten.
+ A mistaken model call cannot change money data without a stored, echoed confirmation.
− Two-phase writes add one round trip and one question to each money-affecting action.
− Telegram level-3 confirmation is weaker than the web; it is temporary and bounded by
  I4a.
− The matcher's `human_actor=NULL` writes rely on the ledger and intervention log to show
  why a receipt was linked.
− More tables to back up (covered by the existing restic job).

## Alternatives Considered
- **Approach A, extend proposal §6.5 with a per-request state machine:** already reviewed,
  but each state is another question and the fund and partner debt stay add-ons.
- **Approach C, full double-entry (Beancount-style):** rigorous, but heavy, hard to
  explain in plain language and overlapping with I3.
- **One-phase writes with the model resending the payload:** simpler, but the confirmed
  payload could differ from the one echoed; rejected.
- **Silently ignoring duplicate payloads:** hides real repeated receipts; rejected in
  favour of `possible_duplicate`.
- **Matcher asking Home per link:** adds latency and a Home dependency to every sync for
  no authorisation gain, since it only reads and writes the owner's own workspace.
