# Private production-component Home transport validation protocol

Baseline: fetched `origin/main` `8b41dc83692475fcd53b495ffeee1574da8991e3`.

This protocol was written before collecting measurements. The final Knowledge
Authorization Plan endpoint and Knowledge HTTP client do not exist. The experiment
therefore measures a **surrogate made from deployed transport components**: Python
3.11 and `httpx.Client` 0.28.1, Tailscale between Nuremberg and Ashburn, a private
nginx 1.24 TLS listener, and Gunicorn 23.0.0 sync WSGI upstream. It does not claim
to be the exact future Knowledge transport or authorization implementation.

## Scope and topology

```text
Nuremberg disposable Python 3.11 client
  -> HTTPS/HTTP/1.1 over Tailscale (100.81.4.57 -> 100.71.79.33)
  -> Ashburn nginx 1.24 private listener :18473 (disposable server certificate)
  -> HTTP/1.1 to 127.0.0.1:18474
  -> Ashburn Gunicorn 23.0.0 sync WSGI synthetic responder
```

Only `/probe` accepts synthetic POSTs. The listener binds the Ashburn Tailscale
address; it is absent from public nginx configuration. The app has no Frappe,
Person, ConsentGrant, family or health data. The self-signed disposable certificate
has only the private IP as SAN; its key stays on Ashburn. No production Home listener
or application code is changed.

## Frozen baseline protocol

Each of eight cases has **30 successful measured requests**, with one unmeasured
warmup for each reused-connection case. Fresh cases create a new `httpx.Client`
for every observation. Cases use exact synthetic HTTP body sizes:

| Case | Request / response bytes | Connection |
| --- | ---: | --- |
| reused_small_small | 832 / 112 | Reused |
| reused_large_small | 2222 / 112 | Reused |
| reused_small_large | 832 / 5036 | Reused |
| reused_large_large | 2222 / 5036 | Reused |
| fresh_rt1 | 1297 / 1756 | Fresh TCP/TLS |
| fresh_rt2 | 1297 / 204 | Fresh TCP/TLS |
| representative_rt1 | 2222 / 5036 | Reused |
| representative_rt2 | 2222 / 387 | Reused |

The representative sizes come from the P3 RT#1 and RT#2 body-size observations in
PR #52; they are not production Authorization Plan payloads. The client uses the
deployed Nutrition Home client's `httpx` version, default HTTP/1.1 pool settings,
three-second timeout, and synthetic machine authorization header. It constructs
requests with `client.build_request` so the persistent client's default headers
(including `Accept-Encoding`) are present. The disposable CA path and
`trust_env=False` are seam specific. The nginx proxy uses the Home vhost's response
buffer sizes, 15-second
keepalive, 16 KiB request body buffer, gzip and HTTP/1.1 upstream without a
keepalive pool. The Gunicorn worker count and timeout match the live process.

Client and server use `perf_counter_ns`. Client trace events capture TCP connect,
TLS setup, body-write completion, header completion, first body chunk and response
completion. WSGI headers report server input-read and app durations; absolute
monotonic clocks on separate hosts are never subtracted. A port-filtered packet
trace may be taken for selected synthetic flows only. No outlier is discarded.

The analyzer requires 30 distinct sequences per case and calculates type-7
min/p50/p90/p95/p99/max/mean/sample SD. Failure probes stay outside latency data.
If the baseline does not reproduce the PR #54 pathology, stop transport variant
optimization. The predictive 30/30 and full P1/P2/P3 E2E are then **not run**:
neither can close obligation #2 while the selected Knowledge client and endpoint
are absent. Any phase not run is explicitly recorded as such in the report.

## Commands

`setup-home.sh` runs under the unprivileged `frappe` user on Ashburn from a
temporary staging directory. It creates its own private temporary directory,
certificate, nginx configuration and Gunicorn app. `client.py` runs in the
Nuremberg Python 3.11 container with `httpx==0.28.1` and `httpcore==1.0.9`.

```powershell
python -B spike/knowledge-production-transport-validation/analyze.py `
  spike/knowledge-production-transport-validation/evidence/baseline-v2.jsonl `
  --output spike/knowledge-production-transport-validation/evidence/summary-v2.json
Get-FileHash spike/knowledge-production-transport-validation/evidence/summary-v2.json -Algorithm SHA256
```

The exact temporary host paths, commands, packet filter, versions, hashes and
cleanup checks are recorded with the evidence after collection.
