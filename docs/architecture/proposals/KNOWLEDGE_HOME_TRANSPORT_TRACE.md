# Knowledge Home transport trace (synthetic private traffic)

**Date:** 2026-09-28

**Branch:** `spike/knowledge-home-transport-trace` from `origin/main` `91c8a68`

**Scope:** Explain the warm/cold spike's ~198 ms versus ~239 ms reused Home request observation. This is a transport probe, not a change to authorization or a closure of Knowledge pre-runtime obligation #2.

## Result

The earlier synthetic Home responder's 250-byte RT#2 request was reproduced at **238.7 ms median** over a reused TLS connection (30/30 requests, 237.7–239.8 ms). A minimal responder with the same 250-byte request, 82-byte JSON response, and HTTP/1.1 header/write shape took **237.7 ms median** without plan evaluation. The delay therefore does not require Home authorization computation. In both captures, the response headers reached the client after ~99 ms, the client ACK followed ~40 ms later, and the response body arrived after another ~98 ms, at ~238 ms total. The server's two unbuffered writes had already returned; client read time and TCP segment timing carried the delay.

`TCP_NODELAY` and write grouping strongly changed the controlled probe. With a small request and split header/body writes, both endpoints' `TCP_NODELAY` off yielded 335.2 ms. Enabling it only on the server gave 237.0 ms, only on the client 196.7 ms, and on both 98.7 ms. These are transport-mechanism comparisons, **not** proposed production configuration changes. Python `http.client` enables `TCP_NODELAY` on the client socket; the earlier `BaseHTTPRequestHandler`/`StreamRequestHandler` leaves it off on the server and writes response headers and body separately. The earlier responder's ~239 ms is consistent with a Nagle/delayed-ACK interaction on the response side. The trace demonstrates that ACK timing and a held second response segment account for the extra ~40 ms in this run; it does not establish which specific Linux ACK heuristic or HTTP header byte caused that timing.

The simplified responder with different HTTP response headers gave ~197 ms at all four exact request sizes on both host Python 3.14 and the earlier pinned Python 3.11.8 client. A few of those requests had ~237 ms tails, with the same 40 ms late ACK before the response body. Thus **body size alone did not reproduce the persistent 198/239 split**. Restoring the earlier responder's response header/JSON wire shape made the ~239 ms latency persistent even without its plan evaluation. The causal boundary is the HTTP response write/ACK behavior under this topology, not the plan size or cryptographic work in Home.

## Setup and method

- Nuremberg client `100.81.4.57` to Ashburn responder bound only to Tailscale `100.71.79.33:18463`. Only generated synthetic bytes, synthetic plan IDs, and disposable mTLS credentials were sent. No production Home, Nutrition, BFF, gateway, public HTTP route, family data, or production credential was used. The host-network Podman client used the already present Python **3.11.8** image for the matching-client passes; the controlled raw-socket pass used host Python **3.14.4**. Ashburn used Python **3.12.3**.
- Each controlled variant had 30 measured requests, one excluded warmup, randomized case order, and an already open connection unless labeled fresh. The five `http.client` compatibility variants and four minimal-header sizes had 30 each. The original-responder and no-evaluation mimic comparisons had 30 each. No outlier was removed.
- `time.perf_counter_ns()` measured client send, response-header read and body read, plus server body-read, processing and write boundaries. The controlled server wrote via TLS `sendall`; the legacy path used `BaseHTTPRequestHandler.end_headers()` and `wfile.write()`. `StreamRequestHandler.wbufsize` is 0, so `wfile` is an unbuffered socket writer; an explicit Python `flush()` would not drain another application buffer. The comparison tests separate writes versus one combined write, rather than a buffered-flush policy.
- Nuremberg `tcpdump` observed only `tailscale0`, host `100.71.79.33`, TCP port `18463`, snap length 96. It recorded timing, TCP flags/ACKs and segment lengths, with TLS ciphertext truncated. Captures across the controlled, compatibility, exact, pinned, original and mimic passes had **4,179 / 1,412 / 923 / 921 / 230 / 232** packets respectively, all with **0 kernel drops**. UTC client timestamps and packet epoch timestamps were matched to individual sequential requests. No packet capture of production traffic was taken.
- The 2026-09-28 warm/cold validation on `spike/knowledge-warm-cold-e2e` (`1f1324e`) reported a 238.49 ms reused 250/82-byte baseline and a ~198/~239 ms plan-shape split. This probe uses the same private route and the committed earlier responder code for the exact baseline, but does not repeat the full Knowledge E2E benchmark.

## Controlled comparisons

All values are milliseconds. Medians are from 30 measured requests per row; p95 uses type-7 interpolation. `request` excludes connection setup. Fresh setup includes TCP and TLS, measured together. The controlled request uses `Content-Length`; `chunked` below changes response framing only.

| Variant | Request/response bytes | Reused request p50 | p95 | Observation |
| --- | ---: | ---: | ---: | --- |
| Small, split writes, both NODELAY off | 832 / 112 | 335.2 | 337.3 | Request second segment delayed ~139 ms; response second segment delayed ~98 ms |
| Medium, split writes, both off | 1297 / 204 | 294.9 | 295.5 | Request remainder delayed ~98 ms |
| Large, split writes, both off | 2222 / 5036 | 294.9 | 295.5 | Large response segmented; final segment also waits ~98 ms |
| Large request, small response | 2222 / 112 | 294.9 | 295.3 | Request size controls first delay |
| Small request, large response | 832 / 5036 | 335.3 | 336.1 | Response size alone does not remove small-request delay |
| Small, client NODELAY on | 832 / 112 | 196.7 | 197.3 | Request body leaves immediately; response body still waits ~98 ms |
| Small, server NODELAY on | 832 / 112 | 237.0 | 237.7 | Request body remains delayed; response parts leave together |
| Small, both NODELAY on | 832 / 112 | 98.7 | 99.1 | Both parts arrive within one route round trip |
| Small, combined request write | 832 / 112 | 196.8 | 197.4 | Removes request-side wait |
| Small, combined response write | 832 / 112 | 237.1 | 237.7 | Removes response-side wait |
| Small, chunked response | 832 / 112 | 335.2 | 337.8 | Chunked framing did not remove the two waits |

The fresh small case had median **199.2 ms TCP+TLS setup**, **336.5 ms request**, and **535.6 ms setup-plus-request**. The fresh large case had **199.3 / 238.2 / 437.5 ms** respectively. Compared with a reused connection, fresh setup adds about 199 ms, while the first request's ACK state also changes the request-only timing. Treat setup and request phases separately; a single fixed “new TLS penalty” does not explain the small/large request differences.

The server's small split/off medians were **138.6 ms waiting to read the request body**, **0.012 ms processing after the full body**, and **0.076 ms across both response writes**. The client then waited **237.0 ms for the first response bytes** and **98.2 ms after the header to finish the body**. With client NODELAY on, server body-read wait dropped to **0.078 ms**; with server NODELAY on, client post-header body read dropped to **0.033 ms**. Those comparisons locate the waits outside Home's application work.

Representative segment offsets from the first client request segment:

| Case | Client request segments | Server response segments |
| --- | --- | --- |
| Small, both off | 0, 138.7 | 236.9, 335.1 |
| Medium, both off | 0, 0.04, 98.4 | 196.6, 294.6 |
| Small, both on | 0, 0.04 | 98.4, 98.4 |
| Earlier Home responder, reused baseline | 0, 0.08 | 99.1, 238.3 |
| No-evaluation mimic, reused baseline | 0, 0.04 | 98.4, 237.4 |

Packet lengths and per-case min/p50/p95/max are in the [machine-readable summary](../../../spike/knowledge-home-transport-trace/evidence/summary.json); the filtered text captures and sanitized client/server rows are beside it. In original-responder round 10, the response header segment was observed at epoch `1790609865.642623`, the client ACK at `.683604` (**40.981 ms** later), and the response body at `.781892` (**98.288 ms** after the ACK). The no-evaluation mimic shows the same response timing shape.

## Interpretation and limits

The ~40 ms component is an ACK-timer effect in these observations: the client receives a small response header segment, sends an ACK ~40 ms later, and the small body segment reaches it about one route RTT after that. `TCP_NODELAY` on the server or combining response bytes eliminates the response-side wait in the controlled probe. The original responder and a no-evaluation mimic preserve the ~239 ms median, so changing Home authorization or R13 is not supported as a latency fix by this evidence.

This does **not** prove that a particular production `httpx`, nginx, kernel version, congestion state, or Tailscale implementation will show the same distribution. The original responder is disposable Python, not the deployed Frappe Plan endpoint. The exact Linux delayed-ACK decision was not instrumented inside the kernel or at both endpoints; ACK and segment arrival times were observed on Nuremberg. No production change, firewall change, cache, or relaxation of mandatory RT#2 was made. The prior E2E acceptance failure and Knowledge obligation #2 remain open. A later production-shaped client/server test should retain split header/body timestamps, actual socket `TCP_NODELAY` state, and packet-level ACK timing when the Home Plan endpoint exists.

## Evidence and verification

See [probe README](../../../spike/knowledge-home-transport-trace/README.md) for commands and the exact evidence file map. Recompute the JSON summary with:

```powershell
python spike\knowledge-home-transport-trace\analyze.py
```

The probe and analysis are isolated under `spike/knowledge-home-transport-trace/`. Disposable remote listeners and captures were stopped before evidence copy; the temporary directories and credentials are removed after the evidence hash and file checks recorded in the README.
