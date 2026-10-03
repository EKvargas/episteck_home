# Knowledge → Home transport inventory

Repository inspection for the production-shaped transport validation. This inventory describes repository evidence only; it is not a live host configuration audit. **A Knowledge Authorization Plan transport has not been selected or implemented in this repository.** The live legacy Home path supplies reusable components, but it cannot be called the exact Knowledge production transport without an explicit implementation decision.

## Evidence status and diagram

```text
Nuremberg: proposed trusted Knowledge runtime (not implemented)
    └─ proposed Authorization Plan RT#1 / fresh RT#2 client (not implemented)
       └─ selected network route: Tailscale Nuremberg ↔ Ashburn
          └─ Ashburn Home hostname with verified HTTPS certificate
             └─ documented Ashburn nginx / Let's Encrypt ingress
                └─ documented shared Frappe bench / Gunicorn
                   └─ episteck_home Frappe app (Plan endpoint not implemented)
```

The Nuremberg↔Ashburn Tailscale addresses are documented as `100.81.4.57` and `100.71.79.33`; current Home MCP, Nutrition and BFF deployments resolve `home.episteck.com` to the Ashburn tailnet address while retaining hostname verification. [Deployment](../../docs/architecture/DEPLOYMENT.md) §§Nodes, Source & image flow; [BFF Quadlet](../../deploy/home-bff/home-bff.container). The Home site runs on an Ashburn Frappe bench, and the dated foundation record describes shared nginx/Gunicorn and a dedicated Let's Encrypt nginx vhost. The vhost source path cited there, `infra/nginx/home.episteck.com.conf`, is **absent from this checkout**, so its effective directives cannot be asserted from the repository. [Foundation](../../docs/episteck-home/foundation.md) §§Installed application baseline, Architecture decision, Public routing and TLS. The Nuremberg BFF public nginx and standalone MCP gateway nginx are **different listeners** and do not establish the Ashburn Home proxy settings. [Deployment](../../docs/architecture/DEPLOYMENT.md) §§Services, Source & image flow; [gateway README](../../deploy/gateway/README.md).

## Existing client implementation; applicability limit

| Item | Repository fact | Applicability to Knowledge Plan |
| --- | --- | --- |
| Language and library | Legacy Home MCP, Nutrition and BFF outbound clients are Python 3.11+ services using persistent synchronous `httpx.Client`. Their package manifests specify `httpx>=0.27` with **no exact pin**. [Home MCP client](../../services/home-mcp/home_mcp/client.py), [Home MCP manifest](../../services/home-mcp/pyproject.toml), [Nutrition client](../../services/nutrition/app/home_control/client.py), [Nutrition manifest](../../services/nutrition/pyproject.toml), [BFF client](../../services/home-bff/home_bff/frappe_client.py). | A plausible existing stack, **not** a selected Knowledge client. Live installed `httpx`/`httpcore` versions need inspection. |
| URL and private route | The services call `home.episteck.com` over HTTPS with tailnet address resolution and hostname verification. BFF's Quadlet has explicit `AddHost=home.episteck.com:100.71.79.33`; deployment docs state the same routing for Home MCP and Nutrition. [BFF Quadlet](../../deploy/home-bff/home-bff.container); [Deployment](../../docs/architecture/DEPLOYMENT.md) §§Source & image flow. | Private route is an accepted topology input. The proposed runtime's container and DNS mechanism are not configured. |
| Authentication | Legacy MCP/Nutrition clients send `Authorization: token key:secret` plus a short-lived human delegation; Home authenticates the machine and derives the human server-side. BFF uses a human OAuth bearer token for session calls. [Home MCP client](../../services/home-mcp/home_mcp/client.py), [Nutrition client](../../services/nutrition/app/home_control/client.py), [R13 decision](../../docs/architecture/proposals/KNOWLEDGE_R13_PRODUCTION_MECHANISM.md) §§2–3. | Plan authentication and the RT#2 retained Home-owned authorization context are architectural requirements, not a deployed wire contract. Do not replay a one-use legacy delegation as a substitute. |
| Timeout and reuse | MCP and Nutrition construct one `httpx.Client` per service client and pass `timeout=3.0` by default (override via `HOME_API_TIMEOUT_SECONDS`); BFF uses 10 s. B6 states reuse is obligatory for a future path and cites the deployed persistent clients. [Home MCP client](../../services/home-mcp/home_mcp/client.py), [Nutrition client](../../services/nutrition/app/home_control/client.py), [BFF client](../../services/home-bff/home_bff/frappe_client.py), [B6](../../docs/architecture/proposals/KNOWLEDGE_B6_TRUSTED_RETRIEVAL.md) §18A.1 F16. | Persistent client is an established pattern. Knowledge pool limits, keep-alive expiry and timeout are not specified. |
| HTTP and TLS details | Current client code passes no `http2`, `verify`, `cert`, `limits`, `transport`, `trust_env`, or socket options for production construction. Test constructors accept injectable `httpx.BaseTransport`. [Home MCP client](../../services/home-mcp/home_mcp/client.py), [Nutrition client](../../services/nutrition/app/home_control/client.py). | HTTP version, TLS/OpenSSL version, mTLS, effective `TCP_NODELAY`, socket ownership, pooling limits, request framing, buffering and proxy environment **must be measured or resolved against the exact selected client build**; no Knowledge setting exists here. Do not infer those values from the Python `http.client` spike. |
| Request shape | Nutrition uses GET for `check_access` and JSON POST for single-subject `check_access_many`; both use the 3 s client. [Nutrition client](../../services/nutrition/app/home_control/client.py). | Neither route is an Authorization Plan endpoint. Exact RT#1/RT#2 headers, body serialization and `Content-Length`/chunked behavior are unspecified. |

The PR #52 and #54 probes used disposable Python `http.client`/`BaseHTTPRequestHandler` and private mTLS, not the existing `httpx`/nginx/Frappe path. PR #54 expressly warns that its result does not prove production `httpx` or nginx behavior. [Warm/cold report](../../docs/architecture/proposals/KNOWLEDGE_WARM_COLD_E2E_VALIDATION.md) §§2–3, 8; [transport trace](../../docs/architecture/proposals/KNOWLEDGE_HOME_TRANSPORT_TRACE.md) §§1–2, 4.

## Server and proxy evidence

Home's current application API is `apps/episteck_home/episteck_home/api.py`. Its whitelisted authorization methods are `check_access` and `check_access_many`; the latter is bounded to eight requirements for **one subject** and returns one overall decision. It does not implement a multi-operation Authorization Plan, Home-signed R13 execution basis, or a fresh RT#2 endpoint. [Home API](../../apps/episteck_home/episteck_home/api.py) (`check_access`, `MAX_REQUIREMENTS`, `check_access_many`); [warm/cold protocol](../knowledge-warm-cold-e2e/PROTOCOL.md) §Feasibility inventory; [R13 decision](../../docs/architecture/proposals/KNOWLEDGE_R13_PRODUCTION_MECHANISM.md) §§4–5.

The dated Home foundation record identifies Frappe **15.99.0**, ERPNext **15.96.1**, shared bench nginx/Gunicorn and Let's Encrypt TLS. [Foundation](../../docs/episteck-home/foundation.md) §§Installed application baseline, Architecture decision, Public routing and TLS. A later G1.6 validation also reports four Gunicorn workers. [G1.6 validation](../../docs/architecture/G1_6_VALIDATION.md) §3. This does not establish the present exact versions, ingress interface, nginx `listen` options, TLS termination config, HTTP version on either hop, `proxy_http_version`, upstream keepalive, `tcp_nodelay`, `tcp_nopush`, request/response buffering, or Frappe/Gunicorn socket settings. Those require read-only inspection of the active Ashburn nginx/bench and process configuration. The only checked-in nginx files are for **Nuremberg** BFF/gateway, not the Home vhost; their proxy directives must not be transferred to Home by assumption. [BFF nginx](../../deploy/home-bff/nginx-home-bff.conf); [gateway nginx](../../deploy/gateway/nginx-mcp-gateway.conf).

R13's selected direct mTLS identity is for the **trusted runtime → domain** hop; its domain TLS connection must reach the domain verifier without an identity-losing terminator. It does not select mTLS for the **runtime → Home** hop. [R13 decision](../../docs/architecture/proposals/KNOWLEDGE_R13_PRODUCTION_MECHANISM.md) §§3–5. The prior private Home responder's mTLS was a disposable benchmark control, not a production Home ingress statement. [Warm/cold report](../../docs/architecture/proposals/KNOWLEDGE_WARM_COLD_E2E_VALIDATION.md) §§2–3, 8.

## Endpoint classification and validation consequence

**B for available legacy components, with a selection gap:** HTTPS/Tailscale, existing Python `httpx.Client` callers, and Frappe/nginx/Gunicorn are documented, while the final Plan endpoint is absent. **C under the stricter meaning of “exact Knowledge production transport”:** neither a Knowledge runtime/Plan client nor a chosen client package/version, Home ingress wire contract or mTLS policy is implemented. Classification A is unsupported. The validation report should state which interpretation it uses. A disposable benchmark may test the existing Home transport components, but cannot claim exact production equivalence until the client and active proxy realization are fixed and checked.

Read-only checks still needed: active Nuremberg client image/package lock (`httpx`, `httpcore`, Python, OpenSSL), effective `HOME_CONTROL_PLANE_URL` and proxy environment without disclosing secrets, active Ashburn nginx vhost and global `http` settings, bench/Gunicorn bind and worker settings, listeners/TLS termination, and request/response packet behavior on a scoped private synthetic flow. No production configuration is changed by this inventory.

Verify this file and its source references:

```powershell
git diff --check
git status --short -- spike/knowledge-production-transport-validation/transport-inventory.md
rg -n 'class HomeControlPlaneClient|httpx.Client|check_access_many|MAX_REQUIREMENTS|AddHost=home.episteck.com' services apps/episteck_home deploy/home-bff
```
