# ADR-0010: svc-finance is the Finance source of truth, bank-first and read-only

## Status
Proposed (2026-10-10). Accepted when the PR that introduces the service merges.
Governing proposal: `proposals/OLIN_FINANCE_V1.md`. Owner decisions P1–P4 are recorded in
its §0.1.

## Context
Olin Finance must answer "how much do we have, and where?" from real accounts with the
source and date of every figure, without asking the owner to type balances. Money
figures must never come from an LLM, and a stale figure must never look like zero.
Home already owns identity and consent (ADR-0008, ADR-0009); Nutrition proved the
domain-service pattern (ADR-0002, ADR-0004).

## Decision
1. **`svc-finance`** is a new domain service on Nuremberg (rootless Quadlet, loopback
   only) following the Nutrition pattern: FastAPI + a thin FastMCP adapter over one
   service layer, SQLite in WAL. It owns balances, movements and, later, classification
   and case data.
2. **Bank-first.** Balances and movements come from connectors behind one interface
   (Enable Banking for PSD2 banks, SimpleFIN for Bank of America, ECB reference rates for
   explicit valuation). The conversation explains movements; it is never a ledger.
3. **Facts are immutable.** Balance observations and movements cannot be updated or
   deleted (database triggers). A correction is a new fact; PENDING→BOOKED is a new row
   that supersedes the old one.
4. **One balance authority per account.** Net position is the sum of the latest
   observation of each account's authority, never a sum of movements. Currencies are never
   summed; a EUR valuation is a separate, dated, explicit line, and VES is never valued.
5. **Workspace-partitioned from day one.** Every tenant row carries `workspace_id`;
   there are no singletons. Membership does not grant data access.
6. **Authorization stays in Home.** Finance accepts no actor, workspace or SQL from any
   caller. It asks Home once per operation through an `Authorizer` port shaped like the
   proposed H2 `authorize_batch` (`SELF` plus other subjects, one request, positional
   decisions). Any non-ALLOW outcome means no repository read and no cache.
7. **Read-only in I1; no payments, ever in v1.** No tool moves money or stores payment
   credentials.
8. **Secrets** (provider keys, access URLs, the IBAN-hash pepper) live in mode-600 files
   owned by the service user. They never enter the database, logs, MCP output or Git.
9. **Real data stays on Nuremberg.** Development and CI use synthetic fixtures only.

## Consequences
+ Figures are auditable, dated and reproducible; chat and web read the same functions.
+ Adding a user or household is a workspace and a connection, not a code change.
+ Connectors are swappable (Sparkasse to N26 is configuration).
− Another service to deploy and back up (≈150 MB RAM; included in the restic job).
− PSD2 consent expires (≤180 days per bank) and costs the owner a re-authorisation.
− Enable Banking restricted mode covers the owner's own accounts only; serving other
  people needs a contract.
− Depends on Home changes H1–H5 before the chat path can go live (Phase B).

## Alternatives Considered
- **Firefly III / Savvy / ERPNext as the ledger:** duplicates the data model and the
  identity layer; rejected (proposal D1).
- **LLM-side parsing of statements as the source of balances:** unverifiable and not
  reproducible; rejected. Evidence from chats is "reported", never "verified".
- **A single global ledger with an owner column:** conflicts with ADR-0002 and makes
  multi-household reuse and deletion harder.
