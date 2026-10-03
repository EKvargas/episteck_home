# Knowledge production-component Home transport validation

**Date:** 2026-10-03

**Fetched `origin/main`:** `8b41dc83692475fcd53b495ffeee1574da8991e3`, containing PR #52 (`47a2100`) and PR #54 (`8b41dc8`)

**Branch/worktree:** `spike/knowledge-production-transport-validation` at `C:\AIProjects\episteck-delivery-workspace\.worktrees\knowledge-production-transport-validation`
**Disposition:** **pre-runtime obligation #2 REMAINS OPEN**. The reusable Home transport components did **not** reproduce the prior synthetic latency pathology. The exact Knowledge Authorization Plan client and endpoint do not exist, so this cannot close #2. **#3 OPEN; #5 OPEN.** No production transport change was deployed.

## 1. Canonical question and stop rule

[PR #52's direct E2E validation](KNOWLEDGE_WARM_COLD_E2E_VALIDATION.md) found exactly two actual Home sends on every successful P1/P2/P3 request, but cold p95 and all p50 aspirations failed. [PR #54's transport trace](KNOWLEDGE_HOME_TRANSPORT_TRACE.md) located ~198/~239/~335 ms behavior in its disposable Python `http.client`/`BaseHTTPRequestHandler` exchange, with a split response and delayed ACK-like gap. It explicitly did not establish that a production `httpx`/nginx/Frappe path behaves that way. The [R13 decision](KNOWLEDGE_R13_PRODUCTION_MECHANISM.md) selects direct runtime-to-domain mTLS and a Home-signed basis, not a Knowledge-to-Home client library or Home mTLS. The [B6 decision](KNOWLEDGE_B6_TRUSTED_RETRIEVAL.md) requires a complete Plan at RT#1, a fresh Home reevaluation at RT#2, and independent crossing counters.

The [predeclared protocol](../../../spike/knowledge-production-transport-validation/README.md) says to stop transport optimization if the reusable Home stack does not reproduce the pathology. This happened. The TCP_NODELAY matrix, coalescing variants, predictive 30/30 gate and canonical full E2E were therefore not run. This is a **no-go for claiming #2 closure**, not a negative finding about an unimplemented future Knowledge path.

## 2. Production realization recovered

The **existing legacy Home API path** is concrete. Nutrition and Home MCP use persistent synchronous Python `httpx.Client`; the live Nutrition image contains `httpx 0.28.1` and `httpcore 1.0.9`, and its site-packages path identifies Python 3.11. The [Nutrition client](../../../services/nutrition/app/home_control/client.py) configures a three-second timeout, verified HTTPS by default, Frappe machine token and opaque human delegation. It calls `check_access` by GET or single-subject `check_access_many` by JSON POST. Its deployed client has no `http2`, custom pool, custom transport, client certificate or socket-option argument. `httpcore`'s installed sync backend sets `TCP_NODELAY=1` when it creates the TCP socket (`_backends/sync.py:215`, read from the running image). HTTPX's [documented default limits](https://www.python-httpx.org/advanced/resource-limits/) are 100 total connections, 20 idle keepalive connections and five-second idle expiry. `httpx` owns socket creation, framing, request writes and pooling. For known-length JSON it sends `Content-Length`; no application streaming/chunked request path was selected. The existing container image's exact OpenSSL build was not inspected; the disposable Python 3.11.8 image used OpenSSL 3.0.22.

The existing services resolve `home.episteck.com` to Ashburn's `100.71.79.33` over Tailscale while retaining hostname verification; Nuremberg is `100.81.4.57` ([deployment](../DEPLOYMENT.md), [BFF Quadlet](../../../deploy/home-bff/home-bff.container)). A read-only Nuremberg-to-Ashburn `openssl s_client` connected to the private IP with Home SNI and verified the certificate; this connection negotiated TLS 1.3. The current Home vhost does **not** require a client certificate. The disposable PR #52/#54 mTLS responder is not a production Home mTLS policy.

Read-only Ashburn inspection found the active Home vhost at `/etc/nginx/conf.d/home.episteck.com.conf`: nginx **1.24.0**, built with OpenSSL **3.0.13**, terminates TLS on the existing 443 listener. The Home vhost has no `http2` listen option. It sends HTTP/1.1 to `frappe-bench-frappe` at `127.0.0.1:8000`, using 128 KiB initial response buffer, four 256 KiB proxy buffers, 256 KiB busy buffers, 16 KiB request-body buffer, 15-second client keepalive, 120-second upstream read timeout and gzip for eligible bodies. nginx's global config has `tcp_nopush on`; the Home vhost does not explicitly override `tcp_nodelay`, `proxy_buffering` or `proxy_request_buffering`. Their [nginx documented defaults](https://nginx.org/en/docs/http/ngx_http_core_module.html#tcp_nodelay) are `tcp_nodelay on` on SSL/keepalive connections and `tcp_nopush off` unless configured; [proxy request/response buffering](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_buffering) defaults on. `tcp_nopush` acts with sendfile, so the global setting alone does not establish response corking for proxied JSON. The upstream stanza has no keepalive pool. Gunicorn **23.0.0** runs four sync workers, 120-second timeout, Frappe **15.99.0**. [Gunicorn's sync workers](https://docs.gunicorn.org/en/stable/design.html#sync-workers) close each upstream connection after a response. The app writes a WSGI response to nginx; nginx controls downstream response buffering and TLS writes. Exact Frappe Plan response framing is unknown because that handler is absent.

```text
Existing legacy route (implemented):
Nuremberg Nutrition/Home MCP Python 3.11 + httpx/httpcore HTTP/1.1
  -> verified HTTPS/TLS over Tailscale, home.episteck.com -> 100.71.79.33
  -> Ashburn nginx 1.24 / OpenSSL 3.0.13, TLS termination on :443
  -> HTTP/1.1, buffered proxy, 127.0.0.1:8000
  -> Gunicorn 23.0.0 sync workers -> Frappe 15.99 Home API

Proposed Knowledge path (not implemented):
Nuremberg trusted runtime -> Home Plan RT#1 -> local work -> fresh Home RT#2
  -> ContextBundle only after successful RT#2
```

This diagram distinguishes the implemented legacy route from the proposed Knowledge flow. It does not insert a gateway, mTLS terminator or other component into the Home path. Additional source and live facts are in [transport-inventory.md](../../../spike/knowledge-production-transport-validation/transport-inventory.md) and [live-stack.json](../../../spike/knowledge-production-transport-validation/evidence/live-stack.json).

## 3. Endpoint classification: C

The current [Home API](../../../apps/episteck_home/episteck_home/api.py) has `check_access` and bounded `check_access_many`, but no multi-operation Authorization Plan endpoint, Home-signed R13 basis issuer, or RT#2 fresh-revalidation API. No Knowledge runtime, Home Plan client, final authentication wire contract, client pool or Knowledge-specific mTLS decision is implemented. **C = the Knowledge production transport realization itself is not yet implemented.** Reusable legacy HTTP/TLS, nginx and Frappe components exist, which would be **B** if a later design explicitly selected them unchanged as the Knowledge path; that selection has not occurred. A is unsupported. Replaying a single-use legacy delegation for RT#2 would contradict B6.

## 4. Private production-component seam

A disposable client on Nuremberg used the existing Python **3.11.8** image with the live Nutrition `httpx 0.28.1`/`httpcore 1.0.9` versions. The client used `httpx.Client.build_request`, preserving default headers, three-second timeout, HTTP/1.1 and connection pooling. A synthetic machine token replaced any real credential. The synthetic Home listener bound **only `100.71.79.33:18473`**, with a disposable self-signed IP-SAN server certificate; a separate unprivileged nginx 1.24 process terminated TLS. It proxied HTTP/1.1 with the live Home vhost's relevant buffering, gzip, 15-second keepalive and request buffer settings to a disposable Gunicorn 23.0.0 four-worker sync WSGI responder at **`127.0.0.1:18474`**. No public nginx route, production Frappe app file, DB, Person, ConsentGrant, family or health data was touched. TLS server verification stayed enabled. The R13 runtime-to-domain mTLS seam was outside this test.

The first exploratory pass used `httpx.Request` directly and omitted default headers such as `Accept-Encoding`. It is retained under `exploratory-*` filenames, **excluded** from the decision. The corrected `build_request` pass is `baseline-v2.jsonl`. Its 5,036-byte synthetic JSON response arrived as 2,938 gzip bytes (the 112-byte response remained 112), proving the default request headers reached nginx. Neither pass exhibited the prior pathological timings. The reported result below uses only v2.

## 5. Baseline reproduction and timing

Each row is **30/30 successful observations**, one excluded connection warmup for reused cases. Milliseconds; type-7 percentiles, sample SD; no outlier removed. Requests and responses use synthetic bodies. The representative RT#1/RT#2 sizes come from PR #52 P3 body-size observations, not a deployed Plan contract.

| Case (request/response bytes) | Min | p50 | p90 | p95 | p99 | Max | Mean | SD |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Reused small/small (832/112) | 97.3 | 98.0 | 98.6 | 99.1 | 100.1 | 100.5 | 98.1 | 0.60 |
| Reused large/small (2222/112) | 97.2 | 97.9 | 98.6 | 99.0 | 100.0 | 100.4 | 98.0 | 0.62 |
| Reused small/large (832/5036) | 97.5 | 97.9 | 98.2 | 98.3 | 98.4 | 98.4 | 97.9 | 0.23 |
| Reused large/large (2222/5036) | 97.3 | 98.1 | 98.7 | 99.4 | 100.3 | 100.6 | 98.3 | 0.63 |
| Fresh representative RT#1 (1297/1756) | 291.4 | 292.9 | 294.4 | 294.6 | 295.2 | 295.4 | 293.0 | 0.93 |
| Fresh representative RT#2 (1297/204) | 290.8 | 292.3 | 293.0 | 293.0 | 293.4 | 293.6 | 292.3 | 0.63 |
| Reused representative RT#1 (2222/5036) | 97.6 | 98.1 | 98.7 | 98.9 | 99.8 | 100.1 | 98.2 | 0.50 |
| Reused representative RT#2 (2222/387) | 97.3 | 98.1 | 99.0 | 99.1 | 99.1 | 99.1 | 98.3 | 0.53 |

The fresh RT#1 median trace reached TCP connect completion at **95.9 ms**, TLS completion at **195.0 ms**, request-body write completion at about **195.4 ms**, response-header completion at about **292 ms**, and full completion at **292.9 ms**. The reused representative RT#1 median reached request-body write completion at **0.50 ms**, response-header completion at **97.9 ms**, first body read at **97.9 ms**, and full completion at **98.1 ms**. The WSGI app's server-side input-read and app durations were usually hundredths or thousandths of a millisecond. The WSGI timer starts after nginx proxy processing; separate host monotonic clocks were never subtracted.

The v2 Nuremberg packet capture was restricted to `tailscale0`, the Ashburn private IP and TCP port `18473`: **1,944 packets, zero kernel drops**. Its [selected timing sample](../../../spike/knowledge-production-transport-validation/evidence/packet-sample-v2.txt) shows response records returning on the next ~97 ms route RTT, without a persistent extra ~40 ms ACK gap or another ~98 ms between response segments. The capture contains ciphertext lengths and ACK timing, not semantic HTTP header bytes. Thus `httpx` tracing gives header **completion**, not exact first header byte; that requested sub-boundary cannot be asserted for every row.

**Reproduction decision:** none of ~198 ms, ~239 ms, ~335 ms, a persistent ~40 ms ACK-like pause, or an extra response-segment route RTT reproduced in this corrected reusable-stack surrogate. The PR #54 behavior depended on its different Python response writer and split-write shape; nginx buffering/TLS writes and `httpcore` socket defaults plausibly remove that interaction here. That causal explanation is an **inference**, not proof that a future Frappe Plan response will have identical framing.

## 6. Variants, candidate and configuration owner

Following the no-reproduction stop rule, **no new TCP_NODELAY matrix** (production default, client only, server only, both), request/response coalescing variant, proxy-buffering variant or upstream-keepalive variant was run. PR #54's synthetic matrix remains evidence about that responder only. The existing `httpcore` sync backend already sets client `TCP_NODELAY=1`; nginx documents `tcp_nodelay on` for SSL/keepalive and this vhost does not override it. Changing the production client or nginx without a reproduced issue would be unsupported.

**Candidate correction: none. Configuration owner: none selected.** If the eventual Knowledge client/Plan endpoint shows a split-write delay, the owner must be identified from that implementation's socket and response path. Supported client pool settings, nginx directives or application response writing would be candidate layers then; no monkey patch, undocumented runtime hook or global kernel tuning is proposed. Mandatory RT#2, R13 semantics, mTLS for domains, trust freshness and fail-closed policy remain unchanged.

## 7. Predictive gate, GO/NO-GO, acceptance and crossings

The 30 warm + 30 cold representative **two-crossing predictive gate was not run** because the issue did not reproduce and there is no selected Knowledge client/Plan endpoint or safe correction to test. Two ~98 ms component crossings suggest headroom in the reusable route, but arithmetic is not direct E2E evidence; a fresh connection costs ~293 ms before any local work. **NO-GO for the full canonical #2 rerun at this phase** because its selected realization is absent. P1/P2/P3 200-warm/100-independently-cold reruns were **not performed**; no new P1/P2/P3 acceptance numbers or `home_auth_round_trip_count` claim is made. The prior PR #52 direct rig remains the evidence that its successful ordinary requests made exactly two actual Home sends, flat with fanout. Two Home crossings remain mandatory in the future runtime.

B6 §18A.8/§23 retains **p50 ≤ 300 ms** as an **aspiration**, reasonable for P1 and contingent on real domain cost for P2/P3; **p95 ≤ 500 ms** as the ordinary-read architecture target, subject to Gate measurement; and **p99 ≤ 800 ms** as the initial Gate target, revisable on evidence. They were not changed or evaluated against synthetic single-call numbers. If a future full direct E2E passes mandatory p95/p99 but misses only aspirational p50, the Architecture Board must dispose that distinction. Here **obligation #2 REMAINS OPEN**. #3 timing-equivalence remains OPEN; #5 awaits real R14/domain measurement and remains OPEN.

## 8. Failure safety, limits and cleanup

Separate [synthetic failure probes](../../../spike/knowledge-production-transport-validation/evidence/failure-probes.json) produced **no ContextBundle** for RT#1 unavailable, RT#2 unavailable after the local-read stand-in, and an untrusted TLS certificate. A successful synthetic control did construct one after two responses. These probes test only disposable control flow, not the unimplemented production Knowledge authorization path. Invalid R13 basis/signature was **not exercised** because this transport seam has no R13 issuer/verifier; PR #52 and the R13 mechanism tests provide earlier separate synthetic evidence. No timing-equivalence claim is made.

Limits: the Home Plan endpoint/client and real Frappe handler are absent; the temporary certificate used an IP SAN instead of the production Home hostname/Let's Encrypt chain; the WSGI responder is synthetic; proxy defaults were matched from the active vhost but ran in a separate unprivileged nginx process; request/response first-byte subevents inside TLS were not instrumented; packet timing was sampled on the Nuremberg side; no real R14/domain read or full E2E occurred. These prevent exact-production or #2 closure claims.

Both temporary Ashburn nginx/Gunicorn seams were stopped and their listeners, certificates, keys, staging directories and scripts removed. Nuremberg client containers used `--rm`; their temporary directories and CA copies were removed. Both host pcaps were removed after sanitized packet timing text was copied. After cleanup, ports `18473/18474` were closed, no public nginx route named `18473`, `nginx -t` passed, Home `/api/method/ping` returned **200**, and Nutrition `/health` returned **200**; these health responses also returned 200 before cleanup. No production listener, application code, credential or transport config was changed.

Recompute the canonical summary and hashes with the commands in the [evidence README](../../../spike/knowledge-production-transport-validation/evidence/README.md). The [manifest](../../../spike/knowledge-production-transport-validation/manifest.json) binds the protocol, harness, sanitized evidence and inventory. **Ready for Architecture Board review of this no-go and #2-open disposition; not ready for #2 closure.**
