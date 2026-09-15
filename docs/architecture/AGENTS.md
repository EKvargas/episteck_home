# Agents

Two **independent** Hermes instances on the Nuremberg node. Separate Unix users,
separate `~/.hermes` state, separate systemd scope. They do not share config and
do not currently talk to each other.

## infra-agent (privileged operator)
- Unix user `infra-agent` (uid 1002), **NOPASSWD sudo**, dedicated SSH key to Ashburn.
- Purpose: server/infrastructure administration for the operator (Erick) only.
- systemd: **system-scope** `hermes-gateway.service`.
- **Not** given business/health data content for routine admin.

## home-agent (unprivileged, user-facing)
- Unix user `home-agent` (uid 1003), **no sudo**, no infra keys, no Podman socket.
- Purpose: the conversational intelligence layer of Episteck Home.
- systemd: **user-scope** `hermes-gateway.service` (lingering).
- Connected to the **Nutrition MCP** (business tools only). Consumes future Home
  Core API + domain MCPs.

## Agent authorization model
- The Home Agent is **NOT a Person**. It acts **on behalf of** `actor_person_id`
  and operates on a `subject_person_id`.
- It receives **business-safe** MCP capabilities only. It must **not** be given
  unrestricted consent mutation, SQL, raw credentials, arbitrary HTTP, or filesystem.
- Every sensitive operation is gated by the central policy engine (`can_access`),
  which fails closed.

## Hermes memory vs Episteck Knowledge (boundary)
- **Hermes memory** = working memory, agent operational knowledge, session
  continuity, skills/tool learning. Ephemeral-ish, agent-local.
- **Episteck Knowledge** = durable personal/family knowledge with ownership,
  provenance, consent, sharing, correction/deletion, cross-agent portability.
- **Hermes must not become the canonical family knowledge store.** Durable family
  facts belong in Episteck Knowledge (or the owning domain service).

## Escalation (documented, not implemented)
`home-agent` may later request infra capabilities from `infra-agent` via a scoped,
authenticated MCP/API (`request_infrastructure_help`) — it **requests** capability,
never inherits infra credentials.
