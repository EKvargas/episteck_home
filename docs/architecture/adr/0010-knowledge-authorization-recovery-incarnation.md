# ADR-0010: Quarantine Knowledge authority after witness recovery

## Status

Proposed Board amendment. The architect accepts its Knowledge-only scope and default-closed gateway for disposable integration; no explicit Board ratification or production approval is recorded.

## Decision

The proposed amendment makes a Home-owned Knowledge witness restart, replacement or uncertain recovery close an admission gate independent of the restorable Home and witness tables. A new unpredictable authorization incarnation invalidates prior Knowledge plan contexts and quarantines all prior Knowledge grants and self-access eligibility until an authenticated current issuer or Person explicitly reauthorizes them. Revisions remain ordered within an incarnation; old numeric high-water would not need reconstruction across recovery. An old grant, even if restored with a matching witness row, never becomes usable merely because the gate reopens. Recovery ordered before RT#2 denies; an RT#2 allow ordered before recovery retains only the contract §9 immediate release, with no reusable permit or extra Home crossing.

This trades Knowledge availability and reauthorization work for a smaller recovery mechanism than an independently retained latest-commit archive. It changes **Knowledge authorization only**: underlying Home permissions, ConsentGrant data, sessions and existing APIs remain governed by their current policy. A separate Nuremberg MariaDB witness and default-closed admission service are integration candidates, not approved production components. See the [contract §19](../proposals/KNOWLEDGE_AUTHORIZATION_PLAN_RUNTIME_CONTRACT.md) and [KAP-2 amendment](../proposals/KNOWLEDGE_KAP2_INCARNATION_ADMISSION_AMENDMENT.md).
