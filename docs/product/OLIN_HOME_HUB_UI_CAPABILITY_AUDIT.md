# Olin Home Hub UI Capability Audit

## 1. Executive Summary
The Olin Home Hub UI is visually refined and demonstrates a clear intent for a unified household operating system. While the UI surfaces are well-defined, the Home Hub presentation layer currently consumes mock/local data rather than live domain APIs. 

Crucially, **the underlying Olin backend capability already exists and is operational.** The repository has an authoritative Home Control Plane API, Person/Circle/Consent boundaries, trusted server-side actor resolution, a Home BFF, Home MCP, Hermes delegation gateway, a live `svc-nutrition` API with USDA and Open Food Facts providers, and Mealie integration. The immediate priority is not building backend services, but rather creating the UI Integration Foundation to connect the Next.js presentation layer to these existing, trusted domain APIs.

## 2. Existing UI Map
* **`/` (Today):** Dashboard with context switcher, active tasks, schedule, nutrition summary, and physical home controls.
* **`/nutrition`:** Macro/caloric summaries, Mealie integration mock, and routing to specialized views.
* **`/nutrition/pregnancy`:** Detailed micronutrient coverage (iron, calcium, folate, vitamin D) with target tracking.
* **`/health`:** Thin clinical truth layer (FHIR gateway mock), rest rhythm, and medical hydration tracking.
* **`/calendar`:** Multi-source federated calendar with 'Dual Partner Track', agenda, and month views.
* **`/memory`:** Prototype UI for managing Olin's contextual assertions (proposed, active, superseded).
* **`/ask` & `AskOlinModal`:** Chat interfaces for querying the orchestrator, featuring mock tool cards and personalization explanations.
* **`/kiosk`:** Shared wall-display mode with ambient photos, glanceable status, and redacted privacy features.
* **`/settings/privacy` & `/settings/appearance`:** Basic configuration shells, mostly focusing on demonstrating privacy guarantees.

## 3. Backend-Readiness Matrix
| Capability | UI Exists? | Backend Exists? | Integration Exists? | Real-data allowed? | Architecture blocker? | Recommended next step |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Home identity/context | YES (Mock) | YES | NO | YES (Synthetic only) | NONE | Design UI Integration Foundation |
| Nutrition | YES (Mock) | YES | NO | NO (Synthetic only) | NONE | Read Model/API Gap Analysis |
| Pregnancy Nutrition | YES (Mock) | YES | NO | NO (Synthetic only) | NONE | Map to svc-nutrition targets |
| Ask Olin | YES (Mock) | YES | NO | YES | NONE | UX Consolidation + Transport Contract |
| Memory | YES (Mock) | NO | NO | NO | Knowledge Technology Gate | Await Tech Gate resolution |
| Health | YES (Mock) | NO | NO | NO | G2 Architecture + Approvals | Blocked |
| Calendar | YES (Mock) | NO | NO | NO | External Connector Missing | Blocked |
| Physical Home | YES (Mock) | NO | NO | NO | Device Gateway Missing | Blocked |
| Kiosk data | YES (Mock) | PARTIAL | NO | NO (Synthetic only) | NONE | Enforce server-side redaction |
| Settings/Consent | YES (Mock) | YES | NO | YES (Synthetic only) | NONE | Map UI to Home Control Plane |

## 4. UI Capability & Integration Status

### HOME / AUTH (Identity & Context)
* **Status:** BACKEND EXISTS — UI INTEGRATION REQUIRED
* **Details:** The Home/Auth infrastructure is live (G1.6 complete). The missing capability is integrating the Home Hub with existing trusted Home/BFF APIs (authenticated UI session, viewer resolution, trusted context selection, permission-aware data requests, session expiry). The browser's `activeContext` must remain presentation state only and never act as an authorization authority.

### NUTRITION
* **Status:** BACKEND EXISTS — UI READ MODEL/API GAP ANALYSIS REQUIRED
* **Details:** `svc-nutrition` is operational. 
  * *Backend-ready:* planned meals, actual intake concepts, deterministic calculations, provenance, USDA, Open Food Facts, pregnancy targets, Home authorization path.
  * *Needs verification/API mapping:* daily summary read models, micronutrient coverage, rolling averages, supplement logging, history/trends.

### ASK OLIN
* **Status:** AGENT INFRASTRUCTURE EXISTS — WEB UI TRANSPORT/UX INTEGRATION REQUIRED
* **Details:** Hermes (infra-agent & home-agent), Home MCP, Nutrition MCP, and the delegation gateway are live. The missing capability is the web UI transport (authenticated agent session, streaming, tool state cards, user confirmations, partial results, provenance explanations).

### HEALTH & MEDICAL
* **Status:** G2 ARCHITECTURE + REAL-DATA APPROVAL BLOCKER
* **Details:** Real family/health data onboarding is completely blocked. 

### CALENDAR
* **Status:** EXTERNAL CONNECTOR / DOMAIN NOT YET DELIVERED

### MEMORY (Knowledge)
* **Status:** TECHNOLOGY GATE OPEN — MEMORY RUNTIME INTEGRATION BLOCKED

### PHYSICAL HOME
* **Status:** DEVICE GATEWAY / HOME ARCHITECTURE NOT YET DELIVERED

## 5. Mock-vs-Live Inventory
Instead of treating the entire UI as uniformly mock, the presentation layer maps to the following integration states:
* **Context Switcher / Identity:** BACKEND EXISTS BUT NOT WIRED
* **Nutrition / Pregnancy:** BACKEND EXISTS BUT NOT WIRED
* **Ask Olin (Agent Chat):** BACKEND EXISTS BUT NOT WIRED
* **Settings / Consent:** BACKEND EXISTS BUT NOT WIRED
* **Memory (Knowledge):** ARCHITECTURALLY BLOCKED (Tech Gate Open)
* **Health (FHIR):** ARCHITECTURALLY BLOCKED (G2)
* **Calendar:** BACKEND DOES NOT YET EXIST
* **Physical Home Control:** BACKEND DOES NOT YET EXIST
* **Kiosk Redaction:** BACKEND EXISTS BUT NOT WIRED

## 6. Standard UI Data-State Envelope (Proposed)
To handle the transition from mock to live data, a reusable frontend standard data envelope is required. Conceptually:
```typescript
{
  status: 'LIVE' | 'STALE' | 'PARTIAL' | 'ESTIMATED' | 'MOCK' | 'UNAVAILABLE';
  updated_at: string;
  source: string;
  provenance: string;
  error?: string;
  authorization_state: 'GRANTED' | 'DENIED' | 'INDETERMINATE';
}
```

## 7. G2 / Real Data Boundary
**CRITICAL:** Real family/health data onboarding is NOT authorized merely because the UI now exists. Current blockers remain:
* Complete Knowledge Technology Gate.
* Explicit Product Owner approval for real family/health data.
* Approved G2/Health architecture and real-person onboarding/ConsentGrants.

Prototype names (Ana/Erick) may remain in UI mocks, but this does not make mock health/nutrition values real records. All initial integration work must remain **synthetic/test-safe**.

## 8. Roadmap (P0 - P1)

### P0-A — Home Hub Integration Foundation
Create the conceptual UI architecture for: trusted session, viewer/context, domain API client adapters, loading/error/stale/partial states, and mock-vs-live provenance.

### P0-B — First real/synthetic domain integration
Use **Nutrition** as the preferred first domain because substantial backend capability already exists. (Must use synthetic data only).

### P0-C — Standard UI data-state envelope
Define a reusable frontend model (as detailed in Section 6).

### P1 — Ask Olin UI ↔ existing agent infrastructure
Integrate the UI chat transport with the existing Hermes agent backend.

## 9. Recommended Next Three Gemini Tasks
**TASK 1: Home Hub Integration Foundation design + frontend adapter/state architecture.**
Inspect actual Home BFF/API contracts and propose how the Next.js UI authenticates and receives trusted context. No production integration yet unless separately approved.

**TASK 2: Nutrition UI API Contract Gap Analysis + synthetic read integration.**
Map existing `svc-nutrition` functionality into Today, Nutrition, and Pregnancy Nutrition views. Identify missing backend endpoints. Prefer a read-only integration first.

**TASK 3: Ask Olin UX consolidation + transport contract.**
Unify `/ask` and `AskOlinModal` around one shared component/runtime contract. Define integration with the existing Hermes/Home/Nutrition tool infrastructure. Do not yet enable destructive real-world actions.
