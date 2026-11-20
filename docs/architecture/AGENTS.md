# Agents

Three **independent** Hermes instances on the Nuremberg node. Separate Unix users,
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

## home-agent-ana (unprivileged, one person)
Ana's own instance (ADR-0017, Nutrition release 1). Runbook: `docs/runbooks/nutrition-r1-rollout.md`
(B5 and B6); installer: `deploy/hermes/install-home-agent-ana.sh`. Not deployed until the owner runs the rollout.
- Unix user `home-agent-ana`, **no sudo**, uid of its own (never 0, 1003, the gateway's or `www-data`'s).
  It is **not in `episteck-gw`** and cannot reach the mint socket, so it cannot choose its own
  `X-Runtime-ID`. User-scope `hermes-gateway.service` (lingering) with `MemoryMax=900M`.
- Network: only `127.0.0.1:9937` (`/gateway/home/` and `/gateway/nutrition/`; no Finance route).
  nftables lets only its uid reach 9937; the owner's agent stays on 9934 and each is dropped on the
  other's port. The gateway mints for runtime `home-agent-ana`, which acts only as the one person who
  granted it at `/runtime`.
- Tools: the `skills` and `clarify` built-ins on Telegram and in cron, plus the MCP servers `home` and
  `nutrition`. No terminal, files, web or Finance. The `olin-nutrition` skill lives in
  `/etc/episteck/hermes-ana/skills` (root-owned, read-only to the agent).
- Model: `openai-codex` / `gpt-5.6-sol` (credential `ana-codex`), fallback `kimi-coding` / `kimi-k2.6`.
- Memory is **off**: Ana's diary lives in Nutrition, not in Hermes.
- Telegram: its own bot, with a one-user allowlist (the token arrives through the secret drop, slot `telegram-ana`).
- Housekeeping: voice notes and images older than 10 minutes are deleted, checked every 10 minutes (`ana-media-purge.timer`); the
  evening check-in is the cron job `olin-nutrition-checkin` (Europe/Berlin).

## Agent authorization model
- The Home Agent is **NOT a Person**. It acts **on behalf of** an authenticated human
  session and operates on a `subject_person_id`.
- `[G1.6]` **The agent cannot choose, alter, or observe who it acts as.** No tool has an
  actor parameter; identity is resolved server-side from the session. Prompt injection
  has no channel to identity. The agent holds an opaque session reference — never a
  bearer token, never a Person id.
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
