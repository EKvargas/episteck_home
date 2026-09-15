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

## Data residency
EU node (Nuremberg) holds Nutrition + Mealie. Off-box backup is EU (Falkenstein).
Home Control Plane currently on Ashburn (US) — cross-node auth calls go over Tailscale;
**no cross-region DB**. Residency of real health data is revisited before G2 real data.
