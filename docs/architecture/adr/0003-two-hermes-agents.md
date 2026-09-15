# ADR-0003: Two independent Hermes agents (infra-agent / home-agent)

## Status
Accepted (2026-09-14, reaffirmed 2026-09-15)

## Context
We need both a privileged infrastructure operator and an unprivileged user-facing
brain. One agent with both roles is a security hazard.

## Decision
Run two separate Hermes instances: `infra-agent` (privileged, sudo, infra keys) and
`home-agent` (unprivileged, no sudo/keys/socket). Separate Unix users, `~/.hermes`
state, and systemd scope (system vs user).

## Consequences
+ home-agent's blast radius = its own Unix account; infra power is isolated + auditable.
+ Independent restart/lifecycle (proven).
− Two installs to maintain; future agent-to-agent needs an explicit scoped interface.

## Alternatives
- Single agent, role-switching: rejected (persona switching is not a security boundary).
