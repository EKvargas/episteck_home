# ADR-0007: Knowledge architecture (governance layer; tech deferred)

## Status
Accepted (2026-09-15) — contracts only

## Context
We need durable, portable, consent-governed personal/family knowledge with provenance
— distinct from structured domain facts and from Hermes working memory.

## Decision
Define an Episteck-owned **Knowledge governance layer**: KnowledgeScope (PERSON/CIRCLE),
KnowledgeEpisode (source), KnowledgeClaim (with provenance + lifecycle). Knowledge
references canonical domain data, never duplicates it. **AI_HYPOTHESIS never silently
becomes USER_CONFIRMED.** Do **not** install Knowledge tech yet.

## Consequences
+ Person/Circle/Consent are ready for a future Knowledge service; provenance preserved.
− Retrieval/extraction tech (Mem0/Docling/pgvector/Graphiti) is a later gated decision.

## Alternatives
- Adopt a turnkey RAG stack (e.g. RAGFlow) now: rejected — heavier, and Episteck needs
  custom Person/Circle/Consent governance a turnkey stack won't provide.
