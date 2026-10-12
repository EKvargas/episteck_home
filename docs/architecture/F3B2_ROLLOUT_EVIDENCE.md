# F3b.2 rollout evidence: Nutrition typed authorization outcomes

Rolled out 2026-10-12 on Nuremberg (`episteck-node1`) under gate R2 of `docs/superpowers/specs/2026-10-05-home-f3b-nutrition-adapter-design.md`. Result: **PASS**.

## What shipped

| Item | Value |
| --- | --- |
| PRs | #73 (typed outcomes), #80 (uvicorn `--no-access-log`) |
| Merge SHA built | `cf80194734caf6fada78e28efbebe8054f280c4b` |
| Image | `localhost/episteck-nutrition:cf80194734caf6fada78e28efbebe8054f280c4b` |
| Image ID / digest | `2e71e7a9ff8f` / `sha256:46bdebee09008f45437a1d04d99badd3ce79d121f457d498bccb9d99d142de25` |
| Previous image (kept for rollback) | `…:ddebab6439c9d68487d180dec6995fc546d3cf68`, ID `80740bf79a90` |
| Quadlet backups | `/var/backups/episteck/home-f3b2-cf80194/` (root, `0700`) |
| Backup SHA-256 | `nutrition.container` `ec0bf72c…`, `nutrition-mcp.container` `dc130004…` (matched the live files before the change) |

The host has no GitHub credentials, so the build tree was the exact `git archive` of `services/nutrition` and `packages/nutrition-domain` at the SHA, streamed to `/tmp/episteck-home-f3b2-cf80194`. The image was built rootless as `svc-nutrition`; its CMD is `uvicorn app.main:app --host 0.0.0.0 --port 9930 --no-access-log`.

## Change applied (operator)

Only the `Image=` line changed in each of `nutrition.container` and `nutrition-mcp.container` (one `<`/`>` pair per file in the diff against the backup). Reload and restart of both units; both reported `active`.

## Verification (read-only)

| Check | Result |
| --- | --- |
| Units | `active/running`, `NRestarts=0`, up since 2026-10-12 10:00:35 UTC |
| Running image | both containers on the new image, ID `2e71e7a9ff8f` |
| Host `GET /health` | 200 |
| `GET /profile/PSN-00013`, no delegation | 401 `{"detail":"SESSION_INVALID"}` |
| Listeners | `127.0.0.1` 9930 and 9931 only |
| Logs since restart | no request lines for the HTTP service; only the static `home authorization not granted: session_invalid` category |
| Scan for `PSN-`, bearer, `eyJ` | 0 matches in both containers, both before and after the regression test |

## Regression: Hermes Nutrition path

The operator asked the Home Agent (Hermes `home-agent`, over the MCP path) for their own Nutrition access and profile summary:

- Access: `PSN-00013`, allowed, reason `self-access`, VIEW and CREATE allowed.
- Profile summary: no profile set up (the normal absent case); no errors.

This exercises a real `home-control-plane` Home answer through the new classifier. `nutrition-mcp` access-log lines (`POST /mcp 200`) contain no person IDs or tokens.

## Not covered

- The HTTP `/profile/{id}` 403 and 503 bodies were exercised by the test suite only. The Hub (F3b.3) is the first real caller of that route; its live proof will cover it.
- `nutrition-mcp` still prints uvicorn access lines because its `Exec=` override bypasses the Dockerfile CMD. They carry no identifiers.
- The MCP boundary still returns Home's reason text via `str(error)` (unchanged by F3b.2). Spec Rule R says the reason is never returned to callers; clarify the wording or add a follow-up that gives MCP fixed codes.

## Rollback (not needed)

Restore both saved Quadlets from the backup directory, reload, restart both units, re-run the health checks. The previous image remains on the host.
