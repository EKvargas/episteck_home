# ADR-0010: Quarantine Knowledge authority after witness recovery

## Status

Accepted for the Knowledge contract (2026-10-09); implementation and production activation remain open under KAP-2.

## Decision

A Home-owned Knowledge witness restart, replacement or uncertain recovery closes an admission gate independent of the restorable Home and witness tables. A new unpredictable authorization incarnation invalidates prior Knowledge plan contexts and quarantines all prior Knowledge grants and self-access eligibility until an authenticated current issuer or Person explicitly reauthorizes them. Revisions remain ordered within an incarnation; old numeric high-water need not be reconstructed across recovery. An old grant, even if restored with a matching witness row, never becomes usable merely because the gate reopens.

This trades Knowledge availability and reauthorization work for a smaller recovery mechanism than an independently retained latest-commit archive. It changes **Knowledge authorization only**: underlying Home permissions, ConsentGrant data, sessions and existing APIs remain governed by their current policy. A separate Nuremberg MariaDB witness and default-closed admission service are integration candidates, not approved production components. See the [contract §19](../proposals/KNOWLEDGE_AUTHORIZATION_PLAN_RUNTIME_CONTRACT.md) and [KAP-2 amendment](../proposals/KNOWLEDGE_KAP2_INCARNATION_ADMISSION_AMENDMENT.md).
