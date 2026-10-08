# Disposable bounded-witness failure model

Run with Python 3.11 or later:

```sh
python spike/knowledge-kap2-bounded-witness/test_model.py
```

The command prints one JSON result and exits nonzero on any failed assertion. It uses only the Python standard library, writes no files and calls no cloud or Home service. Ten schedules test a fresh head, bounded signed-checkpoint suffix, pending/read lock orders, delayed old-epoch publication, restore, uncertain PREPARE/COMMIT publication, missing checkpoint/history and witness outage. `MAX_SUFFIX=2` forces checkpoint rollover; it is not a production setting. The HMAC key is an embedded **synthetic stand-in** for separately registered production signatures.

Expected successful result has `"status":"PASS","tests":10,"failures":0,"errors":0`. The current run's complete structured result is in [evidence/model-results.json](evidence/model-results.json). The design and live validation requirements are in [the amendment](../../docs/architecture/proposals/KNOWLEDGE_KAP2_BOUNDED_WITNESS_AMENDMENT.md).
