# ADR-0017: Per-person agent runtimes

## Status
Accepted (owner approval of the release 1 design, 2026-11-18). Amends ADR-0010. Spec:
`docs/superpowers/specs/2026-11-18-nutrition-release-1-design.md` section 6.3.

## Context

ADR-0010 assumes one agent identity, `home-agent-primary`, so every call from the bot runs as
the owner. Release 1 adds a second Hermes agent, `home-agent-ana`, that must act only as Ana,
while the owner's agent keeps working as today. With two grant holders, the ADR-0010 rules
leave two holes: Ana could replace or delete the owner's grant (the grantee list is per
deployment, and revoke deletes the row when Home is unreachable), and the BFF stores no owner of
a grant row.

## Decision

**Identity comes from the transport, never from the caller.** The runtime is the gateway port,
which the firewall ties to a Linux user. Port 9934 (uid 1003) stamps `X-Runtime-ID:
home-agent-primary`; port 9937 (only the `home-agent-ana` uid) stamps `home-agent-ana`. Each
mint location keeps `proxy_pass_request_headers off`, so the caller cannot send the header.
The BFF reads it in `/internal/mint`; a missing or unknown value returns 401 and **never**
falls back to the primary. This trust model holds only while the gateway is the sole client of
the mint socket. `/internal/mint_finance` requires `home-agent-primary`.

**Configured runtimes.** BFF `RUNTIME_IDS` (comma-separated, default `home-agent-primary`, must
contain it, ids match `^[a-z0-9][a-z0-9-]{0,62}$`, no duplicates). Both Quadlet units set
`RUNTIME_IDS=home-agent-primary,home-agent-ana`.

**Home.** New site config `home_runtime_grantees_by_runtime` (runtime id to list of user ids).
When absent, `home_runtime_grantees` applies to `home-agent-primary` only and any other runtime
is denied; when present it is the only source; a malformed value denies. `open_runtime_grant`
therefore refuses a caller not listed for that runtime. New `get_grantable_runtimes()` (GET only,
no parameters) returns `{"runtime_ids": [...]}` for the caller only. No schema change.

**Audiences, per runtime.** `home-agent-primary` keeps `{home-control-plane, svc-nutrition,
svc-finance}`. Every other runtime gets `{home-control-plane}` only. Finance is unreachable for
Ana twice over: no route on 9937, and no audience.

**Person reference.** `bff_session.person_ref` and `runtime_grant.grantor_ref` hold the hex
HMAC-SHA256 of `b"episteck-person-ref\x00" + PersonId`, keyed with the delegation secret. It is
computed at login from `whoami`, before the Home session opens (unreachable gives 503, any other
failure 403). The key is the Home **Person** id, not the user id: Person to User is one to one
and the Person is Home's identity. The reference is never logged, rendered or put in a cookie;
an empty reference matches nothing. Rotating the delegation secret changes every reference, so
after a rotation each person must re-grant (R9).

**Ownership rules.** `/runtime` lists only the agents Home lists for the person and shows grant
details only when `grantor_ref` matches the person's own reference. With Home unreachable it
lists only the person's own stored grants. Revoke, the "Home unreachable, delete locally"
fallback and `/logout/all` act only on the person's own grants and never call Home for anyone
else's. Grant needs a session with a non-empty reference; the `agent` form field defaults to the
primary and any unconfigured value returns 400.

**Legacy rows.** Grant rows written before this change have an empty `grantor_ref`. The mint
still honours them, so the owner's bot keeps working, but the BFF shows and revokes them for
nobody. Until the owner re-grants `home-agent-primary`, `/runtime` says "no tiene permiso" and
"Cerrar sesión y revocar permiso" does not revoke that row. The rollout therefore has the owner
re-grant immediately after deploy, which replaces the row.

**Guards.** `RUNTIME_LEGACY_BINDING=on` with more than one runtime is a startup error; the legacy
browser binding applies only to the primary. Each runtime has its own mint limit of 600/min.

## Consequences

Positive: Ana's agent can only act as Ana, with no Finance; the owner's agent is unchanged;
neither person can revoke, replace or see the other's grant, even during a Home outage.

Negative / accepted: the owner must re-grant once at rollout; a delegation-secret rotation forces
every person to re-grant; the BFF has two near-duplicate gateway server blocks to keep in sync;
security depends on only `svc-home-gateway` reaching the mint socket (rollout precondition).
Deploy order matters: never serve 9937 in front of a BFF older than this change; the BFF goes
first and the owner's bot is briefly refused (fail closed) until the gateway reload.

## Alternatives Considered

- **One shared bot (spec non-goal):** cannot separate identities; rejected.
- **A user column instead of an HMAC:** stores Home identity in the BFF; the HMAC keeps the BFF
  free of identifiers and unlinkable without the secret.
- **Runtime chosen by a request header or form value from the agent:** forgeable; rejected in
  favour of port and uid.
