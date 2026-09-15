# Security & Consent

## Consent is the authorization backbone
Canonical **ConsentGrant** lives in the Home Control Plane. A central policy engine
answers one question, **fail closed**:

```
can_access(actor_person_id, subject_person_id, domain, action) -> ALLOW | DENY
```

- **Domains:** NUTRITION, HEALTH, CALENDAR, DOCUMENTS, FINANCE, MIND, HOUSEHOLD, KNOWLEDGE
- **Actions:** VIEW, CREATE, UPDATE, MANAGE
- **Self-access:** a Person may always act on their own subject data (actor==subject),
  subject to domain existence. Cross-person access requires an explicit grant.

### Invariants (must always hold)
1. **Membership ≠ authorization.** Being in the same Circle grants nothing.
2. **Care relationship ≠ authorization.** Being a CAREGIVER/COORDINATOR grants nothing
   by itself; an explicit ConsentGrant is still required.
3. **Revoked or expired grant → DENY.**
4. **Unknown/unavailable state → DENY** (fail closed).
5. **One domain never implies another.** A NUTRITION grant does not permit MIND, etc.
6. **Action scoping.** A VIEW grant does not permit UPDATE/MANAGE.

## Secrets handling
- Secrets never enter Git, home-agent context, Nutrition MCP output, or logs.
- Service secrets live in owner-readable `600` files (`/srv/episteck/services/*/secrets`,
  `/etc/episteck/backup`). Backup credentials are root/infra-operable only.
- **Do not put a secret value on a `sudo <cmd>` command line** — it lands in the sudo
  audit journal. Write via `tee`/heredoc from stdin, or edit as the owning service user.

## Agent boundaries
- home-agent: no sudo, no infra keys, no socket, no raw creds; business-safe MCP only;
  **no unrestricted consent mutation**.
- infra-agent: privileged ops, but not given business/health content for routine admin.

## Trusted actor binding `[G1.6 — DELIVERED]`

**`actor_person_id` is never an input.** It is always a server-side derivation of
validated authentication context:

```
validated authentication -> Frappe User -> Person.linked_user -> actor
```

Neither `actor_person_id` nor `User.name` is ever a caller assertion. No caller — user
text, LLM, MCP tool argument, client JSON, or request header — may supply an actor. No
Home business method, MCP tool, or Nutrition route has an actor parameter, so actor
substitution is **unrepresentable** rather than merely rejected.

### Dual principal
Every delegated sensitive request carries two independent principals:

| Principal | Proven by | Means |
| --- | --- | --- |
| `machine_caller` | service API key on `Authorization` | "this service may call this interface" |
| `human_actor` | delegated session, resolved server-side | which human this request acts for |

A machine credential **never** means "this service is Person X". A machine credential
alone yields `PermissionError` for any person data. Both identities are retained in
audit context.

### Delegated context (never a trusted header)
A short-lived, single-audience token carries an **opaque session id** and never a
Person id. It is verified for issuer, audience, issued-at, expiry, unique token id,
session binding, replay, and a maximum lifetime; any anomaly is DENY. A plain
`X-Actor-ID: PSN-123` header is **forbidden** and inert.

Frappe `auth_hooks` verifies the delegation and maps the session to a User through a
`Home Delegated Session` record. Because the User comes from a server-side record
rather than a token claim, **logout and revocation deny the very next call** even if
the token is still unexpired.

### Binding integrity
- `Person.linked_user` is **unique**: one User maps to at most one Person.
- Two Persons for one User, or a User with no Person, **fails closed** — never guesses.
- A **Person without a User** remains a valid *subject* of consent and care, but can
  never be an *actor*. Children and dependents are not forced to have logins.
- Creating or changing `linked_user` is administrative: not in the business API, not
  available to machine users, not reachable by the agent.

### Token secrecy
Bearer/refresh material never enters Hermes prompts, LLM context, MCP tool arguments,
model-visible memory, logs, or Git. The agent holds an opaque session reference; the
delegation travels as transport metadata resolved outside model-controlled arguments.

## Service authorization boundary

The Home MCP and svc-nutrition use separate machine credentials stored in
owner-readable service secret files. `home-agent` cannot read either credential.

**Nutrition resolves the actor INDEPENDENTLY** `[G1.6]`: it asks Home who the human is
using its own machine credential and the delegated session, then asks `check_access`
before every person-specific repository read or write. It never accepts an actor string
from the Home Agent or Home MCP, so no upstream component can say "trust me, the actor
is PSN-00002". Two services resolving the same session independently must agree. Network failure, timeout, non-2xx response, malformed JSON, missing fields, or
non-boolean decisions are DENY.

The live Home Agent policy also makes denial terminal. It may proceed to a
person-specific downstream tool only after literal `allow: true`; otherwise it stops
without retrying a different actor, subject, domain, action, or route. A redacted
revocation trace confirmed that no Nutrition call followed Home DENY.

The old SQLite Nutrition consent table is retained solely for audit/migration. It is
not queried for authorization, has no `has_consent` decision helper, and is not
exposed through Nutrition FastAPI or MCP. ConsentGrant/can_access in Home is the sole
authorization authority.

The complete synthetic denial matrix is recorded in `G1_5_VALIDATION.md`.

## Data residency
EU node (Nuremberg) holds Nutrition + Mealie. Off-box backup is EU (Falkenstein).
Home Control Plane currently on Ashburn (US) — cross-node auth calls go over Tailscale;
**no cross-region DB**. Residency of real health data is revisited before G2 real data.

**The Home BFF runs on the EU node (Nuremberg)** `[G1.6]` so no BFF migration is needed
later. The Control Plane is still US-hosted, which is acceptable only while all Home
data is synthetic. **Stage G1.7 (EU Home Control Plane migration) is a hard G2
blocker** — see `ROADMAP.md`.
