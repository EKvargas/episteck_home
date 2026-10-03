# Sanitized evidence

`baseline-v2.jsonl` and `summary-v2.json` are the **decision batch**: 30
observations for each of eight synthetic cases. The client used
`httpx.Client.build_request`, preserving default headers and response gzip behavior.
The first line records package versions; all following lines are synthetic
measurements. The analyzer rejects incomplete batches and recomputes the summary.

`packet-sample-v2.txt` holds the first 120 packets from a capture filtered to
`tailscale0`, Ashburn `100.71.79.33`, and TCP port `18473`. The full host pcap
contained 1,944 packets with zero kernel drops and was removed after this sanitized
timing sample was copied. The text has timestamps, IPs, ports and lengths only,
not TLS payload bytes. Client absolute epoch packet times are **not** subtracted
from server `perf_counter_ns` values.

`exploratory-direct-request.*` and `exploratory-packet-replay.*` preserve the
first run and replay. Those used `httpx.Request` directly, which omitted default
client headers, so they are **excluded from the decision baseline**. The v2 rerun
fixed that error. `exploratory-packet-sample.txt` is from the replay. No outlier
was removed from either batch.

`failure-probes.json` is a separate synthetic two-crossing control and failure
test. It was run before the v2 header correction; failure behavior does not depend
on the omitted default headers. It is not production authorization evidence.

`live-stack.json` is a sanitized dated fact record from read-only SSH, active
config/process inspection and package source. No production credential, family
data, ConsentGrant or Person record is present. The temporary TLS private key,
certificate, raw host pcaps and all temporary host directories were removed.
`manifest.py` hashes **staged Git blob bytes**, so CRLF conversion on Windows
cannot change the evidence identity between this worktree and the PR.

Recompute and verify:

```powershell
python -B spike/knowledge-production-transport-validation/analyze.py `
  spike/knowledge-production-transport-validation/evidence/baseline-v2.jsonl
python -B spike/knowledge-production-transport-validation/manifest.py --check
```
