# Knowledge direct warm/cold benchmark harness

Read [PROTOCOL.md](PROTOCOL.md) before running. This is a disposable synthetic
measurement rig, not Knowledge production runtime or R13 provisioning. It uses
the Technology Gate's SQLite schema/corpus and the existing pinned Nuremberg
Python 3.11.8 / SQLite 3.41.2 validation image as a base. No production Home
API, Nutrition records, ConsentGrants or family topology are accessed.

## Components

* `provision.py create <outside-repo-directory>` generates a short-lived CA,
  mTLS leaf certificates, separate Home Ed25519 signer, trust distribution
  signer, pinned runtime SPKI and signed five-minute trust bundle.
  `provision.py refresh <directory>` publishes the next signed generation.
  Private files must stay outside Git. Copy only Home's CA, server certificate,
  server key, signing key and config to Ashburn. Copy only the CA, domain
  certificate/key, runtime certificate/key, Home and distribution public keys,
  and trust bundle to the Nuremberg rig. Never copy the distribution private
  key into the domain container.
* `responders.py home` binds the Ashburn Tailscale address and a temporary
  private TLS port (18443 in this run). It checks the client mTLS peer against
  its out-of-band SPKI registration, evaluates complete synthetic operations,
  signs exact domain operations at RT#1, and freshly reevaluates at RT#2.
* `responders.py domain` binds Nuremberg loopback ports 18444–18448. Each
  domain checks the live TLS peer URI SAN and exact SPKI, signed JCS-profile
  basis, audience, operation, trust generation/lease, and atomic replay claim
  before a local synthetic SQLite repository read. All domain operations add
  zero Home sends.
* `runner.py prepare --db <ext4-path>` creates the 100-assertion C-small
  synthetic Knowledge DB. `runner.py batch` runs `--samples 200 --warmup 10`
  for each warm P1/P2/P3 and `--samples 100` for each cold P1/P2/P3. Warm
  keeps Home and domain TLS connections; cold launches a new Python process
  for each observation and includes process start/exit in total latency.
* `baseline.py` records explanatory TLS/reused Home timing and timer overhead.
  Measure Tailscale RTT separately on the host if the pinned container lacks
  the Tailscale CLI. `faults.py` runs the six separate fail-closed arms.
* `analyze.py` validates every successful row's counters and recomputes
  distributions. Pass the primary files listed in [evidence/README.md](evidence/README.md).

## Reproduction checks

From the worktree on Windows:

```powershell
python spike\knowledge-warm-cold-e2e\selftest.py
python spike\knowledge-warm-cold-e2e\analyze.py spike\knowledge-warm-cold-e2e\evidence\P1-warm.jsonl
python -m json.tool spike\knowledge-warm-cold-e2e\evidence\manifest.json > $null
```

The local self-test exercises behavior only. Its loopback timing is never
acceptance evidence. The direct raw rows were collected with real
Nuremberg→Ashburn→Nuremberg mTLS Home requests. The `git_sha` in those rows
names the fetched `origin/main` baseline; the harness was uncommitted while
running. `evidence/manifest.json` hashes the later reviewed source and raw
files. V2 changes warm domain connection reuse only; initial v1 cold and P1
paths retain the same behavior.

After measurement, stop the verified temporary Home process and domain
container, remove the uniquely named temporary image, verify copied evidence
hashes, and remove the exact temporary directories and generated keys. Verify
port 18443 and ports 18444–18448 closed, public routing unchanged, and the
existing Nutrition health endpoint still returns 200. Cleanup observations
are in the architecture report.
