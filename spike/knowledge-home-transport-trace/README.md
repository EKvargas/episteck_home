# Home transport trace probe

This disposable probe compares reused/fresh TLS, `TCP_NODELAY`, HTTP/1.1 write grouping and response framing over synthetic private traffic only. The [report](../../docs/architecture/proposals/KNOWLEDGE_HOME_TRANSPORT_TRACE.md) gives the interpretation. No production endpoint is contacted.

## Verify

From the worktree:

```powershell
python -m py_compile spike\knowledge-home-transport-trace\probe.py spike\knowledge-home-transport-trace\original_client.py spike\knowledge-home-transport-trace\analyze.py
python spike\knowledge-home-transport-trace\analyze.py
python -m json.tool spike\knowledge-home-transport-trace\evidence\summary.json > $null
git status --short --branch
```

`analyze.py` requires 30 rows per case and a matching server event for every controlled or compatibility row. It emits structured JSON with min/p50/p95/max and representative segment timelines. The checked-in `summary.json` is its captured output. A new run needs two disposable Tailscale hosts, a new private temporary port, short-lived synthetic mTLS credentials outside Git, and a port-only capture. `probe.py certs` generates the controlled probe certificates; `probe.py server` binds only the hard-coded private Ashburn address; `probe.py run`, `legacy`, and `exact` generate client JSONL. `original_client.py` replays the earlier synthetic RT#2 plan against the earlier responder code. Do not point these scripts at production Home or use production credentials.

## Evidence files

| File | Contents |
| --- | --- |
| `evidence/client.jsonl` | 13 controlled cases, 30 measured rows each |
| `evidence/legacy-client.jsonl` | Five `http.client` cases with probe headers |
| `evidence/exact-client.jsonl` | Four minimal-header cases on host Python 3.14 |
| `evidence/exact-py311-client.jsonl` | Four minimal-header cases on pinned Python 3.11.8 |
| `evidence/original-responder-client.jsonl` | 250/82-byte RT#2 against the earlier responder |
| `evidence/mimic-responder-client.jsonl` | Same wire shape without plan evaluation |
| `evidence/server-all.jsonl` | Controlled/compatibility/mimic server read and write events |
| `evidence/server.jsonl` | First controlled-pass server events, retained as an acquisition snapshot |
| `evidence/packets*.txt` | TCP segment/ACK timelines, only private port 18463 |
| `evidence/tcpdump*.txt` | Capture counts and zero-drop checks |
| `evidence/summary.json` | Recomputed structured statistics and representative timelines |

No private key, certificate, authorization payload, or production packet content is retained in Git. The capture text has TCP metadata and sizes only; `tcpdump` snap length was 96 bytes and port filtering excluded unrelated traffic.
