# Image rollout (Nutrition, Home BFF, Home Hub)

`image-rollout.sh` rolls out an image built from a merge SHA on the Nuremberg node (rootless Podman Quadlets). The owner runs the live steps; an agent never runs this script against the node.

## Components

| component | account | units (restart order) | image |
| --- | --- | --- | --- |
| `nutrition` | `svc-nutrition` | `nutrition`, `nutrition-mcp` | `localhost/episteck-nutrition` |
| `home-bff` | `svc-home-bff` | `home-bff-mint`, `home-bff` | `localhost/episteck-home-bff` |
| `home-hub` | `svc-home-hub` | `svc-home-hub` | `localhost/episteck-home-hub` |

## Steps

| step | kind | what it does |
| --- | --- | --- |
| `baseline` | read-only | running image, ActiveState, NRestarts, sha256 of each live Quadlet |
| `build <SHA>` | prep | builds the image from `/home/<account>/build/<SHA>`, prints the image ID |
| `apply <SHA>` | LIVE | backs up the live Quadlets, installs the rendered templates, prints `diff -u`, restarts, prints the rollback command |
| `verify` | read-only | health, isolation and BLS probes per component |
| `rollback <backup-dir>` | LIVE | restores the backed-up Quadlets byte for byte, reloads, restarts |

`<SHA>` is the full 40-character lowercase merge SHA, never a branch. Backups go to `/var/backups/episteck/<component>-<sha7>-<UTC stamp>/` (mode 0700). The script never prints EnvironmentFile contents, tokens or delegations.

## Run order

1. Archive the merge SHA onto the node. Paths per component:
   - `nutrition`: `services/nutrition packages/nutrition-domain deploy/nutrition`
   - `home-bff`: `services/home-bff deploy/home-bff`
   - `home-hub`: `apps/home-hub deploy/home-hub`

   ```bash
   git archive <SHA> <paths> | ssh -F C:/Users/D064974/.ssh/config episteck-node1 \
     "cd /; sudo -n -u <account> bash -c 'mkdir -p /home/<account>/build/<SHA> && tar -x -C /home/<account>/build/<SHA>'"
   ```

2. Run each step, piping the script over ssh:

   ```bash
   ssh -F C:/Users/D064974/.ssh/config episteck-node1 \
     'sudo -n bash -s -- <component> <step> [arg]' < deploy/ops/image-rollout.sh
   ```

   Order: `baseline`, `build <SHA>`, `apply <SHA>`, `verify`.

## Verification

- `verify` ends with `verify: PASS`; any `FAIL` line makes it exit non-zero.
- Nutrition: `/health` 200, MCP answers, person probe without delegation is 401, both containers resolve a `bls:` food id.
- Home BFF: `/health` 200, mint socket answers 401 without `X-Runtime-ID`.
- Home Hub: 9933 and 9930 reachable from the container, 9931/9932/9934 refused, anonymous `/app/nutrition` is 307.

## Rollback

`apply` prints the exact command: `... 'sudo -n bash -s -- <component> rollback <backup-dir>' < deploy/ops/image-rollout.sh`.

## Tests

```powershell
C:\AIProjects\episteck-delivery-workspace\.venvs\nutrition-r1\Scripts\python.exe -m pytest -q -p no:cacheprovider deploy/ops/tests
```
