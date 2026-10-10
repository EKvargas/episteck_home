# Knowledge KAP-2 consolidation handoff

**State:** draft, disconnected candidate; KAP-1 accepted, KAP-2 open. This branch begins at `origin/main` `45b0958b46aa27b1326fdaba2f4811ebf20a90e0` (2026-10-10). The selected local PERSON implementation source is PR #69 at `dde967d21a6e0452f3ab3c717d15d0c91b3f8c3c`. The exact consolidated implementation commit is `743aec2dc09b9a7229719bac61c8bf2c968d7501`; this handoff commit follows it and its exact SHA is recorded in the draft PR. No Board ratification of the recovery amendment or production activation is recorded.

## Inventory and disposition

Exact heads and dispositions were checked against GitHub after fetch. The worktree column names preserved local worktrees; `—` means no corresponding local worktree. All #56–69 PRs remain open, and no old worktree or branch was removed.

| PR / worktree | Exact head SHA | Dependency | Architectural status and unresolved decision | Destination |
| --- | --- | --- | --- | --- |
| #19 `knowledge-architecture-gate` | `56d9a0db53f4b5cd0840914027a63a3946ae7f01` | main | Merged architecture gate; later KAP obligations supersede its progress snapshot | Main baseline |
| #20 `knowledge-b1-security-scope` | `f262a7544d6b4605e3fd91c5461e089cf515e4f6` | #19 | Merged B1 security semantics; typed grants remain implementation work | Main baseline |
| #24 `knowledge-b2-sensitivity` | `48c4765410586c86710ce3c264f8cea029b0da24` | B1 | Merged B2 sensitivity contract | Main baseline |
| #25 `knowledge-b3-lifecycle` | `74cb84afefc8092d17f11aaa63c177413ba2d3ef` | B2 | Merged B3 lifecycle contract | Main baseline |
| #27 `knowledge-b4` | `6232eb9fae4e6708b0e7dbf2e7b945916d42ee94` | B3 | Merged B4 deletion contract | Main baseline |
| #28 — | `e7e5b313bd8f810584b2731de2a57fbefe6d603d` | B4 | Merged B5 ownership boundaries | Main baseline |
| #29 — | `2b3777b15085ced6acebe8ccd6d68f7de700927d` | B5 | Merged B6 retrieval/ContextBundle | Main baseline |
| #30 — | `3a310233caca4484901a28cd80ad7e110e446e5b` | B1–B6 | Merged Technology Gate phase-one authorization | Experiment evidence on main |
| #33 `kgate-r13-closure` | `61fb70627fee7e944e5f85e98d4ccbe5368b921c` | #30 | Merged SQLite technology selection; no Knowledge runtime installed | Main baseline |
| #40 `knowledge-restore-freshness` | `6b8f7cc5345ebc19c296d8b816e1b08e015cc2b5` | #33 | Merged Knowledge-owner restore-freshness decision; Home witness is distinct | Main baseline |
| #43 — | `c58c148451e8d647f4e466c488b13b27ecbcd35e` | #33 | Merged journal-store probe; does not select GCS for Home request-time authorization | Experiment evidence on main |
| #45 `knowledge-journal-store-probe` | `924270617a59bb479dbfefe83ccce7ef18ca349d` | #33 | Merged SQLite durability proposal | Main baseline |
| #47 `knowledge-sqlite-durability-validation` | `5d6ad1e0492655e0b67f9663d7aedbeb819a30fb` | #45 | Merged local durability validation | Experiment evidence on main |
| #49 `knowledge-r13-production-mechanism` | `4b6a232ad17cdc59607773fa76afd8b1bd9f6c13` | B1–B6 | Merged R13 mechanism selection; issuance is later KAP-5 | Main baseline |
| #52 `knowledge-warm-cold-e2e` | `1f1324ea374d7b0ff52be7f6be1e462e7a76577a` | #33 | Merged latency experiment; complete live Knowledge gate still open | Experiment evidence on main |
| #54 `knowledge-home-transport-trace` | `de2feec7c5c865596a66cf5dddb84160c477a617` | #52 | Merged transport trace | Experiment evidence on main |
| #55 `knowledge-production-transport-validation` | `c999ef621b8adc586643a6663be40ac86bc48220` | #54 | Merged production-shaped transport validation; no full Knowledge path | Experiment evidence on main |
| #56 `knowledge-authorization-plan-contract` | `2b1b9e5f896594027d35afe45d5fcabff70eafb7` | main | Open; Board accepted original runtime contract and recorded decisions | Selected governing contract transferred |
| #58 `knowledge-kap1-contracts` | `e5b2e4ff47245d7d1af4d74873e7eaabc57e7718` | #56 | Open draft; KAP-1 architecturally accepted; no merge/deploy | Selected wire types/tests transferred |
| #59 `knowledge-kap2-design` | `8d9e3f904eae6015872cf4dc2178972ab4e03579` | #58 | Open draft; early GCS/guard candidate, superseded by transactional direction | Superseded design, retained in PR |
| #60 `knowledge-kap2-evaluator` | `bb57108b3e7e1b4718ea3dd2634057eab48d392a` | #58 | Open draft; disconnected typed evaluator accepted in that scope | Selected evaluator/tests transferred |
| #61 `knowledge-kap2-integration-probes` | `74b92ca0189b0669cf852bc749c4d4f11568558d` | #59 | Open draft; disposable Frappe/GCS probe, not production mechanism | Experiment evidence in PR |
| #62 `knowledge-kap2-bounded-witness` | `b941b78613135363ed2c2ad2a99d317556cb8703` | #59/#61 | Open draft; bounded-head candidate direction, not accepted runtime | Superseded design/evidence in PR |
| #63 `knowledge-kap2-bounded-live` | `3f69b0bedb073e9200a8dd7f7669bb25b2f2717c` | #62 | Open draft; measured Ashburn run; request-time GCS Candidate A rejected | Experiment evidence linked, no runtime import |
| #64 `knowledge-kap2-transactional` | `b00692d0fe6f08d4cbcdffd8dbab9811370dfa49` | #63 | Open draft; transactional witness feasibility; operator/restore proof open | Selected rationale transferred |
| #65 `knowledge-kap2-incarnation` | `8bda8b6a490dc6825fb88c66e099f6d3f053da0a` | #64 | Open draft; Knowledge-only recovery amendment proposed; **Board ratification pending** | Selected proposal/ADR transferred |
| #66 `knowledge-kap2-gateway` | `cd6abedac61f5305760d357ad74a70127c6fb607` | #65 | Open draft; Task 1 corrections accepted for disposable integration | Selected gateway/procedure probe transferred |
| #67 `knowledge-kap2-home-authority` | `a15d1083984b9d35af4dd9568c6fa924e67b8166` | #66 + #60 | Open draft; Task 2 integration candidate, not full KAP-2 | Selected disconnected Home authority/probe transferred |
| #68 `knowledge-kap2-person-vertical` | `0c8c0006ec115b9084e1393df572b5a753771bcc` | #67 | Open draft; integrated PERSON lane/digest accepted for further disposable work | Selected PERSON code/probe transferred |
| #69 `knowledge-kap2-person-procedures` | `dde967d21a6e0452f3ab3c717d15d0c91b3f8c3c` | #68 | Open draft; bounded local PERSON task complete; KAP-2 still open | Selected procedure-only PERSON implementation transferred |

## Selected architecture and isolation

The original Authorization Plan runtime contract and KAP-1 immutable wire parser are included with the pure typed PERSON/CIRCLE evaluator. A proposed, **not Board-ratified**, Knowledge-only recovery amendment adds a default-closed, fresh-incarnation quarantine candidate. The disconnected gateway uses private MariaDB procedures, an exclusive process lock and volatile CLOSED startup. The local PERSON vertical joins a guarded Home partition lane, exact event/revision transition and canonical evaluated-state digest to a fresh witness comparison; serving mutation credentials are procedure-only. Existing Home API/identity files, endpoint registration, DocTypes, patches and production startup are unchanged. CIRCLE issuance stays denied.

Only the local selected code and local synthetic probes were transferred. [GCS findings](KNOWLEDGE_KAP2_GCS_EVIDENCE.md) link to the original evidence; no GCS reader, publisher, IAM/KMS runner, head/checkpoint implementation or rejected request-time path is present. The former stacked branches remain reviewable in their own PRs.

## Merge implications and hold

The workspace deployment standard (`shared/standards/deployment-and-change-flow.md` in the parent delivery workspace) says the `episteck-deploy` timer compares each configured repository's `origin/main` roughly every five minutes, clones changed main, `rsync --delete`s the mapped app source into the bench, clears cache and restarts Frappe web/workers. Its optional post-deploy hook can migrate where configured; the standard says Episteck has no such hook. The proposed branch adds importable `episteck_home` Python files. **Merging would therefore copy candidate code to the live bench and restart it even while the candidate is disconnected.** This PR must stay draft and unmerged while the production installation/activation gate is open. No schema file is registered as a production migration, and no gateway service startup is configured.

## Local verification and remaining gate

Reproduction from this branch uses a disposable Python environment with `pytest`, `PyMySQL` and `rfc8785`; `PYTHONPATH` includes `apps/episteck_home` and `packages/home-contracts/src`. Run:

```sh
python -m pytest -q packages/home-contracts/tests apps/episteck_home/tests/test_typed_access_policy.py apps/episteck_home/tests/test_knowledge_authority.py
python -m pytest -q -s spike/knowledge-kap2-transactional-witness/test_gateway.py spike/knowledge-kap2-home-authority/test_lane.py
python -m pytest -q -s spike/knowledge-kap2-person-vertical/test_integrated.py
python spike/knowledge-kap2-person-vertical/run_frappe.py --bench <disposable-frappe-15.99.0-bench> --evidence <outside-repo-result.json>
```

Clean-branch results: **51 passed** for the complete `home-contracts` suite and typed/authority unit suites; **12 passed in 66.18 s** against real disposable MariaDB for gateway and Home lane; **18 passed in 213.77 s** for the integrated PERSON suite, including real cold physical restore of both local datadirs. The marked disposable Frappe **15.99.0** run passed nine named grant/self, denial, compatibility and reauthorization assertions. Its result reports `site_removed`, `private_db_stopped`, `private_witness_stopped` and `private_redis_stopped` as true. The first Frappe attempt failed before site creation because the disposable bench `PATH` omitted `/usr/sbin`; the corrected rerun passed. Afterward the disposable bench, Python environment, Yarn directory and temporary result file were removed; each exact path was checked absent. No Knowledge worktree was deleted. No cross-host witness, production backup/restore or complete RT#1/RT#2 live latency gate was executed.

These tests use local disposable MariaDB and a marked synthetic Frappe site; they are not cross-host or live Knowledge validation. The next finite integration gate, after architectural review, is a disposable production-shaped two-host run of admission/connection cutover, protected authority-field inventory, both race orders, unknown outcomes, restore/restart first-read denial, explicit current-incarnation reauthorization, ordinary Home API compatibility and complete RT#1/RT#2 latency. The Board must ratify or reject the recovery amendment and Erick must appoint the witness operator and backup delegate before any persistent installation or activation. Trusted transport, credentials, backup/restore operations, full CIRCLE source, KAP-3–10 and live gates remain open.

**Verify:** `rg -n 'Board ratification pending|#69|episteck-deploy|next finite integration gate' docs/architecture/proposals/KNOWLEDGE_KAP2_CONSOLIDATION_HANDOFF.md`.
