# EPISTECK HOME — Mealie capacity and runtime gate

**Status:** `NOT APPROVED FOR INSTALLATION OR TESTING` · **Date:** 2026-09-14. Source/documentation and read-only host inspection only; no image, container, volume, account or runtime configuration was created.

## Decision

Mealie is the preferred future recipe, weekly planning and shopping-list UX, but it is **not safe to install or test on the current VPS**. Continue the small Episteck Nutrition core without it. Re-open this gate only after RAM is upgraded/isolated (or separately approved workload is removed) and a synthetic rootless-Podman test is authorized.

## Measured live baseline

| Fact | Reading |
| --- | --- |
| Total RAM | 3.7 GiB |
| `MemAvailable` | about 1.14 GiB |
| Swap used | about 1.53 GiB of 4.0 GiB |
| Runtime | rootless Podman 4.9.3 |
| Compose provider | podman-compose 1.0.6 |
| Existing workloads | 11 rootless workloads; nginx owns 80/443 |

## Documented upstream facts

- Mealie v3.26.0 SQLite deployment is one persistent `mealie` container, stores state in `/app/data`, and its official template recommends a pinned image plus a **1000M memory limit**. [SQLite deployment](https://docs.mealie.io/documentation/getting-started/installation/sqlite/)
- SQLite is documented for roughly 1–20 users with limited concurrent writes. WAL is optional; NAS is unsuitable. PostgreSQL adds a second persistent service and a health-condition Compose dependency. [Installation checklist](https://docs.mealie.io/documentation/getting-started/installation/installation-checklist/)
- Official installation guidance is Docker/Compose, not an assertion of rootless Podman support. The SQLite template avoids `depends_on`, but rootless volumes, port binding and resource-limit behavior still need testing.
- Backup requires all `/app/data` after stopping the container; UI restore is destructive. [Backup and restore](https://docs.mealie.io/documentation/getting-started/usage/backups-and-restoring/)
- API documentation is OpenAPI `/docs`; tokens are long-lived per-user API tokens. Recipe/shopping-list seams are useful, but API rate limiting is not enabled by default. [API usage](https://docs.mealie.io/documentation/getting-started/api-usage/)
- Code is AGPL-3.0; commercial/legal obligations need review before production use. [License](https://github.com/mealie-recipes/mealie/blob/mealie-next/LICENSE)

## Estimate and required conditions

The upstream 1000M setting is a ceiling recommendation, **not** an observed working set. Reserving only 1000 MiB leaves about 0.16 GiB of currently available memory before host/cache variation, while swap is already used. One service means lower complexity than wger, not safe capacity. No runtime measurement can honestly be claimed without a separately approved synthetic deployment.

Before a future test: upgrade/isolate RAM; use SQLite initially; pin an image; bind a high loopback-only port behind existing nginx; prove rootless volume ownership/Compose resource behavior/backup restore with synthetic data; and apply per-person consent plus proxy rate limits in the adapter.
