# ADR-0014: Finance asks Home once per operation, through its own audience and mint route

## Status
Accepted (2026-11-08), written after the fact. Implemented by #89 (Home accepts
`svc-finance`), #92 (`authorize_batch`), #93 (finance mint, gateway route, nft 9936) and
#97 (Finance `HomeAuthorizer`). Proven live in `FINANCE_I1_VALIDATION.md`. These are
Home changes H1, H2 and H4 of the Finance I1 plan. H3, Feature Activation, is ADR-0012.
Extends ADR-0009 (trusted actor binding) and ADR-0010 (agent runtime grant) to a third
domain service. Governing text: `proposals/OLIN_FINANCE_V1.md` §7.3.

## Context
ADR-0011 makes `svc-finance` the Finance source of truth and delegates authorization to
Home. Nutrition already asks Home through `check_access`, one call per subject. Finance has
three needs that Nutrition did not:

- An overview spans the actor and every co-owner of a joint account. One question needs
  several decisions, and an account is shown only if every owner allows it.
- Delegations are single use. Several Home calls per request would each need a fresh
  delegation, or the second one would be refused as a replay.
- The financial path must not share a delegation with the Home and Nutrition paths: a
  token minted for one service must be useless at another.

## Decision
1. **H1, a dedicated audience.** Home defines `FINANCE_AUDIENCE = "svc-finance"` and accepts
   it only from the machine user named in site config `home_finance_machine_user`
   (`identity/auth_hook.py`, `_accepted_audiences`). A Finance delegation is therefore
   useless to Home MCP and Nutrition. The reverse is not enforced: as in G1.6, any machine
   caller, Finance's included, may still present a Control Plane delegation.
2. **H2, one batch decision per operation.** Finance sends
   `POST /api/method/episteck_home.api.authorize_batch` once per operation, with its
   machine credential, the opaque delegation and up to 8 requirements
   (`SELF` plus each owner, `FINANCE`/`VIEW`). Home resolves the actor itself. It answers
   with the actor id and one decision per requirement, in order. Finance matches the answer
   by position and refuses anything that does not cover exactly what it sent.
3. **Fail closed on every non-answer.** Finance refuses the operation and reads no data:
   - no delegation, or a Home 401/403: `SESSION_INVALID`;
   - Home unreachable, timing out (3 s), returning another non-200 status, or a malformed
     answer: `UNAVAILABLE`, which the API serves as 503 and the MCP as
     `service_unavailable`.

   No caller ever supplies an actor; no Finance method has an actor parameter.
4. **H4, a static mint route per audience.** The BFF mint process exposes
   `/internal/mint_finance` next to `/internal/mint`, both only on its Unix socket. The
   gateway route `/gateway/finance/` calls it through `auth_request`, overwrites
   `X-Episteck-Delegation` with the fresh value and hides it from the response.
   nftables lets only the gateway user reach Finance MCP `9936`. Delegations stay 120 s,
   single use and without a Person id. They come from the owner's runtime grant, which
   must list `svc-finance` among its audiences.

## Consequences
**Positive**
- A joint account needs all its owners' consent, decided in one round trip.
- A leaked or replayed Finance delegation is worth nothing. Live, the replay, a delegation
  used after 130 s and a forged header were all refused or overwritten (B11).
- An outage at Home costs availability, never confidentiality. Live, Finance answered 503
  with no data for a refused port, a hang, a 500 and a malformed answer (B11).

**Negative**
- Every Finance read depends on Ashburn being reachable from Nuremberg. There is no cache
  of decisions, by design.
- Requirements are capped at 8, so a workspace with more than 7 owners fails closed
  (`PolicyUnavailable`) until the cap or the design changes.
- One more internal mint route and one more nft port to keep in step with the gateway
  config.
- Audience isolation is one-way. A Control Plane delegation (minted for Home MCP or
  Nutrition) would also pass `authorize_batch` if Finance presented it. Only the gateway
  ever holds one, for 120 s and single use. Restricting the Finance machine user to
  `FINANCE_AUDIENCE` would close it (finding F3 in `FINANCE_I1_VALIDATION.md`).

## Alternatives considered
- **Call `check_access` once per subject (the Nutrition pattern).** Rejected: several calls
  per operation clash with single-use delegations and multiply latency.
- **One mint endpoint with an `?audience=` parameter.** Rejected: the audience is a routing
  decision, not a caller value. Static locations are easier to audit and cannot be
  confused by a varying string.
- **Reuse the Home/Nutrition audience for Finance.** Rejected: a delegation minted for one
  domain would then be valid at another.
- **Let Finance cache Home decisions.** Rejected: revocation must deny the very next call
  (ADR-0009).
