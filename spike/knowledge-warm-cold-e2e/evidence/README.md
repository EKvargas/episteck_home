# Sanitized direct E2E evidence

`summary.json` is the deterministic acceptance summary. Regenerate it with
`analyze.py` over the **primary** files below. Percentiles use type-7 linear
interpolation; standard deviation is the sample statistic. Every raw JSONL
line is one successful measured request. Warmups are absent. No outlier was
removed.

| Scenario | Primary warm file | Primary cold file |
| --- | --- | --- |
| P1 | `P1-warm.jsonl` (v1; no domain client) | `P1-cold.jsonl` (v1) |
| P2 | `P2-warm-pooled.jsonl` (v2) | `P2-cold.jsonl` (v1) |
| P3 | `P3-warm-pooled.jsonl` (v2) | `P3-cold.jsonl` (v1) |
| Five-domain informative | `P4-warm-pooled.jsonl` (v2) | `P4-cold.jsonl` (v1) |

The v2 change only reuses local domain mTLS connections between **warm**
requests. It does not change the cold request path. `P2-warm.jsonl`,
`P3-warm.jsonl`, `P4-warm.jsonl` and `initial-summary.json` retain the initial
fresh-domain-TLS warm run as exploratory evidence; they are excluded from
acceptance. `P*-warm-window2.jsonl` and `window2-summary.json` are a separate
30-request second-window subset using the initial transport settings. They
confirmed the stable ~40 ms difference between small P1 and larger P2/P3 Home
requests, but did not establish its packet-level cause.

`network-baseline.json`, `tailscale-rtt.json`, `failure-probes.json`, and
`host-conditions.json` are explanatory or correctness evidence, not substitutes
for E2E rows. `manifest.json` records hashes and the source/baseline identity.

All identifiers in runtime requests were synthetic. Evidence contains only
timings, counts, byte lengths, topology, version, iteration and UTC time. It
contains no operation body, signed basis, private key, family/person data or
production credential.
