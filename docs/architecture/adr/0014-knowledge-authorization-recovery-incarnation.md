# ADR-0014: Quarantine Knowledge authority after witness recovery

## Status

**Accepted — Board ratified for v1 on 2026-11-07** (owner Erick, acting as Board). It may later be superseded by a cross-restore high-water design. Ratification makes the amendment the governing Knowledge-only recovery rule. It does **not** complete KAP-2 or approve production installation, schema, credentials or activation. Those stay behind the open KAP-2 proof items and the one authorized two-host run (see the [decision sheet](../../../spike/knowledge-kap2-two-host/DECISION_SHEET.md)).

Numbering: this ADR was first filed as `0010-knowledge-authorization-recovery-incarnation.md` and collided with [ADR-0010 agent runtime grant](0010-agent-runtime-grant.md). It was renumbered to 0014 on 2026-11-07. The content was unchanged apart from the ratification.

## Context

Runtime contract §17 requires the Home-owned Knowledge authorization revision/fence to be rollback-safe: after a restore, it must never fall below its previous high-water mark. Proving that across a Home and witness restore needs an independently retained latest-commit archive. The GCS request-time variant of that archive was measured and rejected (PR #63). The transactional MariaDB witness (PR #64) is simpler. But a witness restart or restore still loses the guarantee that its rows are the latest.

## Decision

A Home-owned Knowledge witness restart, replacement or uncertain recovery closes an admission gate. The gate is independent of the restorable Home and witness tables. A new, unpredictable authorization incarnation does two things:

- It invalidates prior Knowledge plan contexts.
- It quarantines all prior Knowledge grants and self-access eligibility until an authenticated current issuer or Person explicitly reauthorizes them.

Revisions stay ordered within an incarnation, so old numeric high-water never needs to be rebuilt across recovery. An old grant never becomes usable just because the gate reopens, even if it is restored with a matching witness row. Recovery ordered before RT#2 denies. An RT#2 allow ordered before recovery keeps only the contract §9 immediate release, with no reusable permit and no extra Home crossing.

This changes **Knowledge authorization only**. Underlying Home permissions, ConsentGrant data, sessions and existing APIs keep their current policy. A separate Nuremberg MariaDB witness and a default-closed admission service are integration candidates, not approved production components. See [contract §19](../proposals/KNOWLEDGE_AUTHORIZATION_PLAN_RUNTIME_CONTRACT.md) and the [KAP-2 amendment](../proposals/KNOWLEDGE_KAP2_INCARNATION_ADMISSION_AMENDMENT.md).

## Consequences

### Positive
- A smaller recovery mechanism: no latest-commit archive and no rebuilt high-water.
- A restored backup, Redis value or signed artifact can never reopen Knowledge access.
- Same-incarnation ordering, partition isolation and fresh RT#2 evaluation are unchanged.

### Negative (accepted for v1)
- **Every witness restart closes Knowledge**, including a routine Nuremberg reboot or service update. Each Person must then re-authorize each Knowledge permission they still want. The operator cannot do this for them.
- Knowledge is unavailable from witness restart until the first reauthorization.
- **Operator:** Erick is the sole accountable witness operator, with **no backup delegate**. This is an accepted risk for the personal/family deployment. If Erick is unavailable, the witness stays CLOSED and Knowledge denies, while Home, Nutrition and Finance carry on.

## Alternatives Considered

- **Cross-restore high-water archive (contract §17 as written):** keeps grants valid across restarts. It needs an independently retained, restore-safe latest-commit authority, which costs more mechanism and operations. It stays available as a later superseding design.
- **GCS request-time journal (Candidate A):** rejected after a measured Ashburn run (PR #63). Witness-only paired p95 reached 1,335 ms warm / 1,833 ms cold at suffix 8, and a real `429` occurred on rapid head replacement. See [GCS evidence](../proposals/KNOWLEDGE_KAP2_GCS_EVIDENCE.md).
