# Nutrition Quadlets

Two rootless Podman Quadlets for `svc-nutrition` on the Nuremberg node: `nutrition` (port 9930) and `nutrition-mcp` (port 9931). Both mount the BLS 4.0 reference database read-only at `/reference`.

## Files

- `nutrition.container` — web/API unit.
- `nutrition-mcp.container` — MCP server unit (`python -m app.mcp.server`).
- Both carry `Image=localhost/episteck-nutrition:REPLACE_WITH_COMMIT_SHA`. The rollout script substitutes the commit SHA at install time.

## When to Use

Follow this runbook when the BLS reference file is built or replaced. The file is never committed to git.

## Prerequisites

- `openpyxl` in the venv (the `nutrition-r1` venv has it).
- BLS source: `.data/bls-4.0/BLS_4_0_2025_DE/BLS_4_0_Daten_2025_DE.xlsx`.
- SSH config at `C:/Users/D064974/.ssh/config` with host `episteck-node1`.
- `PY` below is the local Python of the `nutrition-r1` venv (`C:\AIProjects\episteck-delivery-workspace\.venvs\nutrition-r1\Scripts\python.exe`). Run every local command from the repo root.
- `/home/episteck/stage` exists on the node (step 3 creates it).

## Steps

1. Build the database locally.

   ```powershell
   PY services/nutrition/scripts/import_bls.py <xlsx> <out>
   ```

   Expected output: `wrote 7140 foods to <out>`.

2. Record the checksum.

   ```powershell
   (Get-FileHash <out> -Algorithm SHA256).Hash.ToLower()
   ```

   `Get-FileHash` prints uppercase hex and `sha256sum` lowercase, so compare case-insensitively (the `.ToLower()` does it).

3. Stage the file on the node.

   ```powershell
   ssh -F C:/Users/D064974/.ssh/config episteck-node1 'mkdir -p /home/episteck/stage'
   scp -F C:/Users/D064974/.ssh/config <out> episteck-node1:/home/episteck/stage/bls-4.0.sqlite
   ```

4. Install it as root on the node (operator step).

   ```bash
   install -d -m 0750 -o svc-nutrition -g svc-nutrition /srv/episteck/services/nutrition/reference
   install -m 0440 -o svc-nutrition -g svc-nutrition /home/episteck/stage/bls-4.0.sqlite /srv/episteck/services/nutrition/reference/bls-4.0.sqlite
   sha256sum /srv/episteck/services/nutrition/reference/bls-4.0.sqlite
   ```

## Verification

The `sha256` on the node equals the one recorded in step 2. Both containers see `/reference/bls-4.0.sqlite` (`BLS_DB`). After the Quadlets carry the mount (`deploy/ops/image-rollout.sh nutrition apply <SHA>`), `image-rollout.sh nutrition verify` checks the container side: in both `nutrition` and `nutrition-mcp` the first `Apfel` search hit has a `bls:` food id.

## Rollback

`image-rollout.sh nutrition apply` copies both Quadlets to a backup directory and prints the command that restores them: `image-rollout.sh nutrition rollback <BACKUP_DIR>` (see `deploy/ops/README.md`). The reference file may stay; the old image ignores it. To remove it, delete `/srv/episteck/services/nutrition/reference/bls-4.0.sqlite`.

## Attribution

Data: Max Rubner-Institut, BLS 4.0, licensed CC BY 4.0. Show `Datos: Max Rubner-Institut, BLS 4.0` wherever BLS values appear.

## Never Commit the Database

`bls-4.0.sqlite` stays out of git. Build it locally and stage it with `scp`.
