# KAP-2 recovery and acquisition review — 2026-10-24

**Disposition:** complete the narrow local acquisition correction; retain the recovery mechanism as a disconnected disposable PERSON candidate. This review establishes no KAP-2 completion, Board ratification, remote authorization or production readiness.

**Follow-up:** [R1/R6 local correction and validation](2026-10-24-knowledge-kap2-r1-r6-validation.md) records the subsequent authorized local work. The R1/R6 observations below describe the reviewed baseline; the follow-up fixes witness-only early opening and retained known-incarnation reuse, while retaining the wider production proof gates.

**Reviewed baseline:** `6166594bd91482455440e8e938306769100136bd`, plus this continuation's acquisition check/tests and documentation. The governing inputs are [runtime contract §17/§19](../proposals/KNOWLEDGE_AUTHORIZATION_PLAN_RUNTIME_CONTRACT.md), [ADR-0010](../adr/0010-knowledge-authorization-recovery-incarnation.md), the [incarnation amendment](../proposals/KNOWLEDGE_KAP2_INCARNATION_ADMISSION_AMENDMENT.md) and the [fixed two-host matrix](../../../spike/knowledge-kap2-two-host/README.md). An independent read-only reviewer inspected the recovery code and narrow acquisition diff; no blocking defect was found in the acquisition correction. Findings below distinguish missing proofs from demonstrated authorization failures.

## Recovery decision and tradeoff

The proposed recovery rule remains coherent: uncertainty closes Knowledge authorization; a fresh unpredictable incarnation makes prior plan contexts, grants and Person self-activations ineligible; only a new affirmative act by the currently authenticated, empowered human can reactivate a selected Knowledge permission. An underlying Home permission is necessary but insufficient. Infrastructure recovery does not authorize the operator to act as that human.

The cost is Knowledge unavailability and renewed human permission work after even a clean witness restart. Existing Home/Nutrition permissions remain under their present rules. This is a proposed alternative to reconstructing authorization high-water across restores, and the Board must explicitly accept that tradeoff before production use. A disposable experiment may investigate it before ratification.

This conclusion assumes trusted host/root/database administration, controlled restore procedures, private transport and no direct serving-principal witness access. It does not cover hostile live privileged rewrites. A production mechanism must enforce its gate across every serving, maintenance and restoration path.

## Trace from invariant to candidate evidence

| Invariant | Candidate mechanism and named evidence | Limit of the evidence |
| --- | --- | --- |
| Restored permissive rows cannot open admission | `Gateway.__init__` starts CLOSED, takes an exclusive process lock, and pins DB connections; `authorize` checks these before reading. `test_gateway.py` and integrated restart/physical-restore cases exercise denial. | Historical local evidence; separated-host first-read behavior and production supervision remain unproved. |
| Old grant/self authority does not revive | Fresh `secrets.token_hex(32)` incarnation, witness `DENY_ALL`, guarded Home reset, current-incarnation activations and fresh digest comparison. Integrated tests cover selective authenticated reauthorization after restore. | No production reauthorization API/UI or complete context invalidation implementation exists. |
| Revocation order and unknown outcomes fail closed | Home partition advisory lane spans evaluation/mutation; procedures lock rows; PENDING blocks; exact event IDs bind retries to revision/digest. Reader-first/writer-first and acknowledgement-loss tests exist. | A6 covers selected witness acknowledgement windows, not every Home-commit or network failure window. |
| Recovery authority cannot grant a Person's permission | Separate transport roles/DB principals; Home mutations derive a unique enabled human Person from trusted binding and validate current issuer/dependency evidence. | Test runner holds both test transport roles for automation. Production custody and all bypass paths need separate proof. |
| Unrelated Home behavior survives | Disposable Frappe controls check named read APIs, ordinary Person note writes, session/identity behavior and guarded-write denials. | Not full ordinary authority-mutation compatibility or production source cutover. |

No automatic old-grant revival was found in the reviewed synthetic paths. That is a bounded review finding, not a proof over all production states.

## Open recovery proof items

| ID | Observation and concrete gap | Required disposition |
| --- | --- | --- |
| R1 | [`Gateway.recover`](../../../spike/knowledge-kap2-transactional-witness/gateway.py) sets `closed=False` after witness-only default-deny readback. [`PersonAuthority.recover`](../../../apps/episteck_home/episteck_home/knowledge_authority/integrated.py) installs/readbacks Home afterward under the Home lane. `DENY_ALL`, incarnation mismatch and the lane prevent old permission use in this prototype, but the independent gate does not implement the full CLOSED → REAUTH_ONLY → OPEN sequence through cross-store proof. | Keep the candidate scoped. Before production, implement or separately approve an equivalent staged protocol, and inject Home reset/readback failure plus a competing reader before opening admission. A passing current A0–A11 run alone cannot close this item. |
| R2 | [`recover_e2`](../../../spike/knowledge-kap2-transactional-witness/gateway_schema.sql) repeatedly assigns numeric writer/publisher epoch 2; A2 exercises epoch-1 rejection. Previous-incarnation calls still reject, so numeric reuse alone is not a demonstrated bypass. | Prove repeated recovery/takeover, delayed old writer/publisher calls and actual principal/connection retirement. Do not describe the current result as complete repeated credential/epoch rotation. |
| R3 | [`home_runner.py`](../../../spike/knowledge-kap2-two-host/home_runner.py) deliberately loses acknowledgements after successful witness PREPARE/COMMIT and checks event outcomes. It does not simulate uncertain Home COMMIT acknowledgement or all before/after failure positions. | Retain the named matrix; separately prove remaining failure windows before complete KAP-2 acceptance. Never infer a committed Home mutation from client timeout alone. |
| R4 | CIRCLE source, all production Home authority writes, restored Redis/RT#2 contexts, the private reauthorization interface and production credential custody are not implemented by this PERSON package. | Track as open implementation/production gates. Do not treat protected-write fixtures or local Frappe compatibility as full Home cutover. |
| R5 | A10 measures 30 warm/30 cold synthetic policy/witness pairs with an unratified screening budget. | Accept/reject the screen before measurements; retain complete RT#1/RT#2, Knowledge/domain path, timing/oracle and live latency obligations for later KAP phases. |
| R6 | `recover_e2` rejects only reuse of the current head incarnation. If A has retained event history, recovery to B followed by a forced candidate A is not rejected by the procedure. Normal 256-bit CSPRNG collision probability is negligible, but §19 also requires rejecting known collisions. This is not a demonstrated old-permission allow. | Add rejection against retained known incarnation history and a forced-collision test before claiming conformance with the complete recovery contract. Do not weaken this requirement based on random-collision probability. |

These findings do not require expanding this acquisition-only correction into production recovery work. They do prevent claiming that a successful disposable PERSON run completes KAP-2 or proves the whole proposed amendment. R6 is a concrete known-history collision-validation gap; its practically negligible unforced collision probability does not make the contract requirement optional.

## Latest remote outcome and local correction

The [last authorized attempt](https://github.com/EKvargas/episteck_home/pull/71#issuecomment-6132455875) stopped at A0 at the reviewed baseline. The SQL-path correction passed; the pinned install script deliberately returned 1 for help. The current shell change accepts **only exit 1 plus recognizable usage**, rejects unexpected status/incomplete output, and changes no package version, download/extract method, wrapper, path, budget, runner or authority code. See the [acquisition analysis](../../../spike/knowledge-kap2-two-host/ACQUISITION_REVIEW.md#2026-10-24-help-status-correction).

Fresh local checks: **17 acquisition tests passed**, including a demonstrated RED run before correction; **51 contracts/typed-policy/authority unit tests passed** after providing the declared `rfc8785==0.1.4` dependency; shell syntax and an installed local MariaDB help-only check passed. The archived attempt result and historical loopback evidence hashes were checked. No database integration, Frappe, physical restore, two-host matrix or latency measurement was rerun in this continuation. The [structured result](../../../spike/knowledge-kap2-two-host/evidence/2026-10-24-local-review/result.json) records commands and limitations.

## Concrete next gate

1. Review this correction and the recovery proof items at the final local commit. Preserve the draft/unmerged hold; merging copies candidate code to the live bench.
2. If proceeding with the bounded experiment, explicitly authorize one new preparation/matrix attempt at that exact commit using the existing decision sheet: verify both hosts/IP, name experiment supervisor/delegate, accept the unchanged scope/capacity/latency screen, and include preparation disposal after an A0 failure. The previous roles and IP are historical facts to reverify, not a new appointment or authorization.
3. Run the unchanged A0–A11 matrix once if prerequisites pass; archive all outcomes and distinguish preparation disposal from a passed runner cleanup criterion. Any unexpected failure stops the attempt without retry or workaround.
4. Keep R1–R6, Board ratification, full source cutover and later KAP phases open regardless of that experiment's outcome.

**Verify:** `python -m json.tool spike/knowledge-kap2-two-host/evidence/2026-10-24-local-review/result.json`; `python -m pytest spike/knowledge-kap2-two-host -q`; `git diff --check` (tests require Linux/WSL).
