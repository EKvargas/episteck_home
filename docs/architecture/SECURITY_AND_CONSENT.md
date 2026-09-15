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

## Actor binding — hard G2 blocker

G1.5 synthetic validation may pass an explicit synthetic `actor_person_id`. This is
**not** an identity mechanism. No real family, health, Nutrition, Mind, document, or
other personal data may be exposed to Home Agent until an authenticated user/session
is cryptographically or otherwise authoritatively bound to exactly its allowed
Person identity. The future real Home Agent must never establish identity by simply
supplying `actor_person_id="..."`. G2 is blocked until this binding is designed,
implemented, and tested against actor substitution.

During G1.5, defense in depth still applies inside the Home Core API:
- linked human Users may assert only their linked Person;
- unlinked machine Users must be explicitly allowlisted and have no DocType mutation
  permissions;
- `get_person` denies unrelated/guessed ids without loading or revealing the Person;
- circle rosters require actor visibility of the circle;
- care and dashboard results are filtered to the resolved actor;
- effective-access queries return only that actor's decisions.

## Service authorization boundary

The Home MCP and svc-nutrition use separate machine credentials stored in
owner-readable service secret files. `home-agent` cannot read either credential.
Nutrition asks Home `check_access` before every person-specific repository read or
write. Network failure, timeout, non-2xx response, malformed JSON, missing fields, or
non-boolean decisions are DENY.

The old SQLite Nutrition consent table is retained solely for audit/migration. It is
not queried for authorization, has no `has_consent` decision helper, and is not
exposed through Nutrition FastAPI or MCP. ConsentGrant/can_access in Home is the sole
authorization authority.

## Data residency
EU node (Nuremberg) holds Nutrition + Mealie. Off-box backup is EU (Falkenstein).
Home Control Plane currently on Ashburn (US) — cross-node auth calls go over Tailscale;
**no cross-region DB**. Residency of real health data is revisited before G2 real data.
