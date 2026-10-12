# ADR-0012: Feature Activation is a Home DocType, separate from consent

## Status
Accepted (2026-10-12). Part of Olin Finance I1, task B3.

## Context
The Hub and later domains need to know whether a feature is switched on for a Person
or a Circle (for example, whether to show the Finance entry). Consent (ADR-0008)
answers a different question: may this actor access this subject's data. Mixing the
two would make a UI switch look like an authorization, or the reverse.

Finance in I1 gates on workspace status inside `svc-finance` (ADR-0011) and does
**not** consult this DocType.

## Decision
1. **`Feature Activation`** is a new Home DocType: `feature`, `scope_type`
   (`Person` or `Circle`), `scope` (Dynamic Link driven by `scope_type`), `state`
   (`ACTIVE` or `PAUSED`, default `PAUSED`), `activated_by`, `activated_at`,
   `deactivated_at`. `(feature, scope_type, scope)` is unique, enforced in
   `validate`; the scope must exist. Timestamps are stamped on state transitions.
2. **Admin-only permissions** (`System Manager`), like every other Home DocType. No
   guest or browser write path.
3. **Hub reads** come through `get_home_bootstrap`, which gains a `features` list:
   ACTIVE rows only, scoped to the actor's own Person or the actor's circles, minimal
   fields (`feature`, `scope_type`, `scope`, `state`), under the existing
   `MAX_BOOTSTRAP_ROWS` bound (fail closed above it).
4. **Machine reads** use `get_feature_state(feature, scope_type, scope)`. The actor is
   resolved with `POLICY_AUDIENCES`, so a machine holding a delegation for an accepted
   audience can ask; no delegation means `PermissionError`. This reuses the existing
   audience set rather than adding a new one.
5. The actor may ask only about their own Person or a Circle they belong to. Any
   other scope and any malformed input raise one uniform `PermissionError` (no
   oracle). A permitted scope with no record reports `PAUSED`.
6. **Not an authorization.** `ACTIVE` never grants access to data; `can_access` and
   ConsentGrant remain the only decision.

## Consequences
+ One place to switch a feature on or off per person or household, readable by the Hub
  and by machines.
+ No change to consent semantics or to `POLICY_AUDIENCES`.
− Home has no post-deploy hook, so the table needs a manual `bench migrate` after the
  deploy job syncs `main`.
− Finance does not honour the switch in I1; pausing a feature here does not stop
  Finance. Revisit when Finance moves from workspace status to Feature Activation.
− Writes are admin-only (Desk or `bench`); there is no self-service activation yet.

## Alternatives Considered
- **Reuse ConsentGrant:** conflates "feature visible" with "data access"; rejected.
- **Site config or environment flags:** not per Person or Circle, needs a deploy to
  change; rejected.
- **Have Finance consult it in I1:** couples the first deploy to an unmigrated
  DocType; deferred.
- **A separate machine audience for reads:** more surface for no gain over
  `POLICY_AUDIENCES`; rejected.
