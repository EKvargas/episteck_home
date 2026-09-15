# Episteck Home — Architecture docs

**Read `ARCHITECTURE.md` first.** It is the canonical, current-truth description of
the system and links every other document.

## Contents
- `G1_6_VALIDATION.md` — trusted actor binding evidence (threat matrix, PKCE, live runs)
- `G1_5_VALIDATION.md` — final synthetic security, conversation, deployment, and latency evidence
- `ARCHITECTURE.md` — canonical architecture + component map (read first)
- `DATA_OWNERSHIP.md` — who owns which data (no universal DB)
- `AGENTS.md` — infra-agent / home-agent; Hermes-memory vs Episteck-Knowledge boundary
- `SECURITY_AND_CONSENT.md` — can_access, fail-closed invariants, secrets
- `KNOWLEDGE.md` — Knowledge contracts (Scope/Episode/Claim) + ContextBundle (no tech installed)
- `DEPLOYMENT.md` — nodes, services, images, backup
- `ROADMAP.md` — delivered / gates ahead / **Architecture Change Rule**
- `proposals/` — approved design proposals (G1.6 trusted identity; its §23 records the
  2026-09-16 residency correction that withdrew G1.7)
- `STATUS.md` — current state (update with every change)
- `adr/` — Architecture Decision Records (0001–0009)
- **`architecture-diagram.html`** — explorable whole-product diagram (open in a browser)
- `architecture-diagram.json` — archify source for the diagram

## Change rule (contributors & agents)
Before architectural changes: read `ARCHITECTURE.md`, read relevant ADRs, do not
silently contradict accepted decisions. If architecture changes: update
`ARCHITECTURE.md`, create/update an ADR, update `STATUS.md`, and commit the docs **with**
the implementation change. Git documentation is the architecture source of truth.
