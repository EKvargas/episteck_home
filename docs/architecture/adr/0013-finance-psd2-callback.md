# ADR-0013: One public PSD2 callback for Finance; the code exchange stays with the operator

## Status
Proposed (2026-10-24). Accepted when the PR that introduces the route merges. Amends
ADR-0011 (Finance was loopback-only). Governing text: `proposals/OLIN_FINANCE_V1.md` §7.2
("Callback PSD2 público").

## Context
Enable Banking (PSD2) needs a browser redirect after the owner approves access at the
bank (SCA). The redirect carries `state` plus `code` on success, or `state` plus `error`
and `error_description` on refusal. The `code` is exchanged for a session with
`POST /sessions`, signed with the application's private key. Sparkasse and Trade
Republic cash depend on this flow; until it exists no Enable Banking account can be read.

Until now no Finance route was reachable from the Internet, and only the sync job
mounted provider credentials. Account details (identification hash, uid, product)
come back once, in the `POST /sessions` answer.

## Decision
1. **One exact public route.** nginx on the existing `bff.home.episteck.com` vhost
   proxies `location = /finance/connect/callback` (GET only) to the Finance API on
   `127.0.0.1:9935/connect/callback`. No other Finance path is exposed; the vhost keeps
   its query-free access log (`episteck_noqs`) and the API runs uvicorn without an
   access log, so `code` and `state` reach no log.
2. **The state is the only authority.** The callback takes no delegation and never
   calls Home or the bank. `state` is 256-bit random, single-use, expires in 15 minutes,
   is bound to the workspace, connection and owner, and only its SHA-256 is stored.
   Unknown, expired, replayed and malformed requests get one generic 400. A refusal
   consumes the state too.
3. **The API never holds a provider credential.** The callback only stores the code in
   `oauth_callback` (same transaction as consuming the state). The operator's command
   `python -m app.connect authorize` started the consent; it waits for that row, takes
   it once (deleting it), and exchanges the code with the application key it reads
   from the mode-600 secret. Codes nobody collected are purged when the next
   authorization starts.
4. **Who starts a consent in I1: the operator command only.** It prints the bank's
   consent link in the owner's terminal. `POST /connections/{id}/authorize` (proposal
   §7.2) is deferred: nothing can reach the REST API with a human delegation today
   (the gateway serves the MCP port), and serving it would put the application key in
   the request-serving process.
5. **Every returned account is mapped, none is linked silently.** The session map
   (identification hash to session uid) keeps every account the bank returned, so an
   account linked after the first consent needs no second SCA. Only `link-account`
   (an owner step) creates the account row that sync reads. The command prints each
   returned account as `reference | product | currency | linked/not linked`.
6. **Rate limit (amendment, 2026-10-25).** nginx applies `limit_req` to the callback
   location only: zone `finance_callback` keyed on `$binary_remote_addr` (DNS points
   straight at the node, no proxy in front), 10 requests per minute, burst 5, `nodelay`,
   status `429`. The zone lives in `conf.d/episteck-rate-limit.conf` because
   `limit_req_zone` is http-level. Limited requests never reach Finance. `limit_req` runs
   before `limit_except`, so a client that is already limited gets `429` even for a POST.

## Consequences
- Positive: Sparkasse and Trade Republic cash can be connected. The Internet-facing
  surface is one GET path that can only consume a state Finance itself issued. A
  compromise of the API process does not expose the Enable Banking key.
- Positive: the access budget is untouched: consent calls (`/aspsps`, `/auth`,
  `/sessions`) are not account-data requests.
- Negative: the owner must keep the terminal open (up to 15 minutes) during SCA.
  Reconnecting from chat or the Hub needs a later decision (see Open questions).
- Negative: the code sits in the Finance database for seconds (until the command
  takes it). It is useless without the application key, and the row is deleted on use.
- Positive (amended 2026-10-25): the route is rate limited per client address (see
  decision 6), so a scan costs Finance at most a handful of hash lookups per minute.
- Negative: a client that exceeds the limit gets `429` for a few seconds. One consent
  needs one request, so the owner only meets it after repeated reloads of the result page.

## Alternatives considered
- **Mount the EB key into the API and exchange in the callback:** one step fewer for
  the owner, but the public-facing process would hold the provider credential.
- **A separate callback container with the key:** same exposure, one more unit.
- **REST `POST /connections/{id}/authorize` now:** no caller exists in I1 (see 4).

## Open questions
- Who starts a reauthorization after I1 (MCP tool `finance_connection_link`, Hub)?
  That caller needs a human delegation and either the key in its process or a
  hand-off to an operator-side worker.
- Should the callback answer show more than "return to the terminal"? It must stay
  free of account data.
