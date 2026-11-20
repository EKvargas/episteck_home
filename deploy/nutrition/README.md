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

## Steps

1. Build the database locally.

   ```powershell
   PY services/nutrition/scripts/import_bls.py <xlsx> <out>
   ```

   Expected output: `wrote 7140 foods to <out>`.

2. Record the checksum.

   ```powershell
   Get-FileHash <out> -Algorithm SHA256
   ```

3. Stage the file on the node.

   ```powershell
   scp -F C:/Users/D064974/.ssh/config <out> episteck-node1:/home/episteck/stage/bls-4.0.sqlite
   ```

4. Install it as root on the node (operator step).

   ```bash
   install -d -m 0750 -o svc-nutrition -g svc-nutrition /srv/episteck/services/nutrition/reference
   install -m 0440 -o svc-nutrition -g svc-nutrition /home/episteck/stage/bls-4.0.sqlite /srv/episteck/services/nutrition/reference/bls-4.0.sqlite
   sha256sum /srv/episteck/services/nutrition/reference/bls-4.0.sqlite
   ```

## Verification

The `sha256` on the node equals the one recorded in step 2. Both containers see `/reference/bls-4.0.sqlite` (`BLS_DB`).

## Attribution

Data: Max Rubner-Institut, BLS 4.0, licensed CC BY 4.0. Show `Datos: Max Rubner-Institut, BLS 4.0` wherever BLS values appear.

## Never Commit the Database

`bls-4.0.sqlite` stays out of git. Build it locally and stage it with `scp`.
