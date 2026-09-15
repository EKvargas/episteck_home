# Deployment

## Nodes
- **Ashburn VPS** (US) — `episteck home`. Hosts erp.episteck.com + home.episteck.com
  (Home Control Plane), plus legacy workloads. SSH port 2222, user `frappe`.
- **Nuremberg node** (EU) — `episteck server`. Hosts the agents + domain services.
  SSH port 22, user `episteck`. See node baseline docs.
- Cross-node: **Tailscale** mesh (`episteck-ashburn` 100.71.79.33 /
  `episteck-nuremberg` 100.81.4.57). No cross-region DB.

## Services on Nuremberg (rootless Podman + Quadlet, unprivileged svc users)
| Service | User | Bind | Notes |
| --- | --- | --- | --- |
| Mealie v3.26.0 | svc-mealie (1004) | 127.0.0.1:9925 + tailnet | recipe provider |
| Nutrition API | svc-nutrition (1005) | 127.0.0.1:9930 | FastAPI |
| Nutrition MCP | svc-nutrition (1005) | 127.0.0.1:9931 | FastMCP, home-agent connects |
| infra-agent gateway | infra-agent (1002) | none public | system-scope systemd |
| home-agent gateway | home-agent (1003) | none public | user-scope systemd |

Nothing is exposed to the public Internet. Future public web goes via 80/443 reverse
proxy `[PLANNED]`.

## Source & image flow
- **Home product code:** `EKvargas/episteck_home` (canonical). Company code:
  `EKvargas/episteck`.
- Nutrition service image built on Nuremberg from a recorded commit SHA of
  `episteck_home` (rootless podman build), deployed via Quadlet.
- **Home Control Plane app:** the `episteck_home` Frappe app is installed onto the
  `home.episteck.com` bench on Ashburn (provisioning over SSH; schema via
  `bench migrate`).

## Off-box backup
restic 0.18.1 → Hetzner Storage Box (u670254, EU, SFTP key-based). Daily systemd
timer, keep 7d/4w/3m, client-side encrypted. Backs up Nutrition SQLite (consistent
`.backup`) + Mealie native zip. Restore validated. Secrets in `/etc/episteck/backup`
(root-only). Hermes state = separate future job.
