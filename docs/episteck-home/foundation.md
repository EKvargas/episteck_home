# EPISTECK HOME — ERPNext Foundation

## Status

**Provisioned:** 2026-09-13

EPISTECK HOME has a clean ERPNext foundation. This is an operational
backbone only; it is not yet a health, finance-connector, Mind, AI-agent, or
personal-data application.

## Canonical identifiers

| Item | Value |
| --- | --- |
| Project | EPISTECK HOME |
| ERPNext site | `home.episteck.com` |
| Bench | `/home/frappe/frappe-bench` |
| Site path | `/home/frappe/frappe-bench/sites/home.episteck.com` |
| Ownership / runtime user | `frappe` (Episteck self-delivery exception) |
| Source repository | `EKvargas/episteck` |

## Installed application baseline

- Frappe `15.99.0`
- ERPNext `15.96.1`

No custom app, DocTypes, Custom Fields, integrations, dashboards, agents,
or real personal data were added. In particular, do not use ERPNext as the
system of record for clinical, wearable/timeseries, raw AI-memory, exercise,
or nutrition data.

## Architecture decision

The site uses the existing shared Frappe bench and its existing MariaDB,
Redis, Gunicorn, worker, scheduler, nginx, and backup architecture. It does
not expose a new application port. This follows ADR-004 for Episteck
self-delivery: the `frappe` user and this existing repository are used rather
than creating a parallel Linux user or repository.

The intended long-term shape is:

```
Specialized systems -> Episteck API/integration layer -> ERPNext operational
backbone -> Episteck UI and constrained AI agents
```

Future agents must use scoped APIs/MCP tools rather than unrestricted
database or financial-provider credentials. Consent, provenance, and the
distinction between user-confirmed facts and AI hypotheses are first-class
requirements for the future custom layer.

## Operational state

- Scheduler is enabled for `home.episteck.com`.
- An initial site database/config backup was created at provisioning time.
- The bench-wide backup cron runs every six hours.
- Internal routed health check (`Host: home.episteck.com`) returns Frappe
  `pong`.
- `host_name` is explicitly set to `https://home.episteck.com` in the
  site runtime configuration. This is required for secure absolute URLs such
  as OAuth callbacks.

## Public routing and TLS

Public DNS for `home.episteck.com` resolves to the VPS. The managed source
for the dedicated nginx vhost is
`infra/nginx/home.episteck.com.conf`; it was derived from `bench setup nginx`
and installed as `/etc/nginx/conf.d/home.episteck.com.conf`. This avoids
replacing the shared generated bench configuration, which has certificate
customizations for other live sites.

Let's Encrypt TLS is active for `https://home.episteck.com`. Certbot manages
the deployed certificate material and renewal; the current certificate
expires on 2026-12-12. HTTPS login and the Frappe ping endpoint were verified.

## Outgoing mail (OAuth foundation)

A `Connected App` named `Google Gmail OAuth — EPISTECK HOME` was created in
the site on 2026-09-13. It is deliberately incomplete: it contains no Google
client ID, client secret, token, or active Email Account. Its configured
callback is:

```
https://home.episteck.com/api/method/frappe.integrations.doctype.connected_app.connected_app.callback/s8i69fsfik
```

The configuration requests the Gmail scope `https://mail.google.com/` and an
offline refresh token. Before it can be used, the Google Cloud OAuth client
must register that exact callback, and its client ID/secret must be entered
only in the ERPNext Connected App UI. Keep incoming/IMAP disabled; the first
Email Account must be outgoing-only until a separate decision authorizes mail
ingestion.

The outgoing-only `Email Account` is `EPISTECK HOME Mail`
(`episteck@gmail.com`). It uses SMTP `smtp.gmail.com:587` with TLS, the
Connected App above, and the ERPNext System Manager user as its OAuth token
owner. It is the default outgoing account; no inbox sync is enabled. It must
not send mail until that user completes **Authorize API Access** in the
ERPNext UI and an OAuth token is present.

OAuth authorization completed successfully on 2026-09-13: ERPNext holds an
access token and refresh token, and SMTP XOAUTH2 authentication passed. A
single controlled self-test from `episteck@gmail.com` to that same address was
sent successfully through the ERPNext queue. The Google app remains in
Testing; its authorization/refresh token therefore expires after seven days.
This is temporary validation only, not a production mail design.

## Next foundation actions (explicitly deferred)

1. Log in as Administrator, change the initial password, and complete the
   standard ERPNext setup wizard with the deliberate legal/company and
   currency choices.
2. Define the minimum role model, technical integration identity, and
   outgoing-email configuration only when their ownership and credentials are
   available. The Gmail OAuth Connected App foundation exists, but Google
   client credentials and user authorization are still intentionally pending.
3. Separately design the version-controlled `episteck_home` Frappe app before
   introducing domain models such as Household, Person, Consent, Data Source,
   External System Integration, or Integration Event.

## Runbook note

The requested filename `new-client-bootstrap.md` was not present on the VPS.
The applicable complete runbook is
`/home/frappe/.openclaw/workspace/docs/operating-model/new-client-bootstrap-playbook.md`.
Its foundation track was followed, with two deliberate scope adaptations:

1. Episteck is self-delivery, so ADR-004 permits the existing `frappe` user
   and `EKvargas/episteck` repository.
2. The requested clean foundation takes precedence over the generic
   customer-custom-app step; no empty or speculative custom app was created.
