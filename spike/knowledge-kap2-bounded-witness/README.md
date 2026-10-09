# Disposable bounded-witness failure model

Run with Python 3.11 or later:

```sh
python spike/knowledge-kap2-bounded-witness/test_model.py
python -m unittest discover -s spike/knowledge-kap2-bounded-witness -p 'test_*.py' -v
python spike/knowledge-kap2-bounded-witness/request_ledger.py --pairs-per-temperature 30
```

The first command prints one JSON result and exits nonzero on any failed assertion. The full suite covers 11 bounded-read schedules, five publisher-process failure schedules and three request-ledger checks. It uses only the Python standard library and calls no cloud or Home service. The bounded model tests fresh heads, signed-checkpoint suffixes, pending/read lock orders, delayed old-epoch publication, restore including combined valid-head/Home rollback, uncertain PREPARE/COMMIT publication, missing checkpoint/history and witness outage. `MAX_SUFFIX=2` forces checkpoint rollover; it is not a production setting. The HMAC key is an embedded **synthetic stand-in** for separately registered production signatures. The publisher model simulates MariaDB/GCS ordering; it does not prove their real behavior.

Expected bounded-model result has `"status":"PASS","tests":11,"failures":0,"errors":0`; the full suite has 19 passing tests. The executable ledger rejects the old 100-pair plan because its GET count exceeds the proposed cap. [Evidence](evidence/) records the local results and planned counts. The design and live validation requirements are in [the amendment](../../docs/architecture/proposals/KNOWLEDGE_KAP2_BOUNDED_WITNESS_AMENDMENT.md).

The [2026-10-09 Ashburn integration evidence](evidence/2026-10-09/LIVE_EVIDENCE.md) records a separate disposable GCS/KMS/MariaDB run. [`live_bounded_probe.py`](live_bounded_probe.py) is the synthetic-data runner; [`invoke_live_probe.ps1`](invoke_live_probe.ps1) records the exact isolated project and short-lived in-memory token launch used for that run. The project has been deletion-requested, so the launcher is an archival reproduction record and requires newly approved isolated resources before any future paid run. To verify the archived per-step JSONL and all-client experimental counters locally:

```sh
python spike/knowledge-kap2-bounded-witness/summarize_live_evidence.py
python -m json.tool spike/knowledge-kap2-bounded-witness/evidence/2026-10-09/summary.json
```
