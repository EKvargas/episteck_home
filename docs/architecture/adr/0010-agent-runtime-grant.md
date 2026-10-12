# ADR-0010: Agent runtime grant (90-day delegated session)

## Status
Accepted (owner approval 2026-10-10) — Stage H5. Proposal: PR #74,
`docs/architecture/proposals/HOME_AGENT_RUNTIME_GRANT.md`. Supersedes the "agent acts only while
a browser session exists" rule of ADR-0009 for `home-agent-primary`; every other ADR-0009
invariant is unchanged.

## Context

ADR-0009 ties the agent to a browser login: `bff_session` and its `Home Delegated Session`
last 12 h, and the agent's runtime binding vanishes with them. Olin Finance needs Hermes to act
by chat and by cron without a daily login (about 30 interventions a month).

## Decision

The owner **explicitly grants** `home-agent-primary` permission to act as them for at most
**90 days**, revocable at any time, independent of any browser session.

- **Home:** a grant is a `Home Delegated Session` with `client = "agent-runtime:<runtime_id>"`.
  No schema change, no `bench migrate`. `open_runtime_grant(runtime_id, ttl_days)` takes no user
  parameter (same self-service seam as `open_session`), so a machine can never create one.
  Controls: runtime must be in `home_runtime_ids` (default `["home-agent-primary"]`);
  caller must be in `home_runtime_grantees` (absent/empty denies everyone); `ttl_days` is an
  integer in `1..home_runtime_grant_max_days` (default 90). A new grant revokes the previous
  Active grant of the same user and runtime. `close_runtime_grant` is owner-only and answers
  identically for "not yours", "not a grant" and "missing". `get_runtime_grant_status` is
  callable only with a control-plane delegation from the Home MCP service and returns
  `{granted, expires_at, days_left}` with no identifier.
- **BFF:** table `runtime_grant` holds a pointer (`home_session_id`, `allowed_audiences`,
  timestamps) and **no OAuth tokens**. `/internal/mint` resolves the grant first and falls back
  to the browser binding only while `RUNTIME_LEGACY_BINDING=on`. `/callback` stops claiming the
  runtime when the flag is off. Granting needs cookie + CSRF + a login at most 10 minutes old.
  Mint is capped at 600/min with a static log line.
- **Unchanged:** delegations stay 120 s, single use, with no Person id; Home resolves the actor;
  revocation denies the next call; disabled or unlinked users are denied.

## Consequences

Positive: Olin works without a daily login; one 30-second renewal per 90 days; revocation is
immediate; the grant row cannot leak OAuth tokens.

Negative / accepted risk (owner decision P4): a compromised `home-agent` account can act as the
owner for up to 90 days instead of 12 h. Mitigations: only the agent uid reaches the gateway;
the agent has no sudo, credentials or mint socket; audiences are limited; "last use" is shown;
revocation is immediate; mint is rate-limited.

Changes from the proposal made during implementation (all recorded in the plan):
1. `home_runtime_grantees` allowlist, because the grant row is per runtime, not per user, and any
   linked family member could otherwise overwrite it.
2. Revoke asks Home first and deletes the local row when Home confirms or is unreachable; a
   refusal ("not yours") keeps it. Otherwise any logged-in user could kill the owner's grant.
3. No "log out everywhere" existed. `POST /logout` keeps the grant; new `POST /logout/all`
   closes this session and revokes the grant. `bff_session` has no user column, so
   "everywhere" means this session plus the grant.
4. "Recent login" means a BFF session at most 10 minutes old. If Frappe's own session is live
   the password may not be re-entered; this still stops a stolen BFF cookie.

## Alternatives Considered

- **New DocType fields (`kind`, `runtime_id`, `allowed_audiences`):** more explicit, but needs a
  manual `bench migrate` (Home has no post-deploy hook). Can be adopted later without changing
  the contract.
- **Keep 12 h sessions and auto-renew:** needs a stored long-lived credential for the agent,
  which is exactly what ADR-0009 avoids.
- **Longer-lived delegation tokens:** breaks the 120 s / single-use guarantee.
