# Olin Home Hub UI Capability Audit

## 1. Executive Summary
The Olin Home Hub UI is visually refined and demonstrates a clear intent for a unified household operating system. However, the current state is primarily a high-fidelity visual prototype rather than a functional application. The UI relies heavily on mock data (`domain/mocks.ts`) and lacks the underlying domain service integrations (Knowledge, Health, Nutrition, Identity/Auth) required to bring the system to life. The immediate priority is to connect the UI to the actual domain services while preserving the established aesthetic, followed by implementing missing workflows for data entry, state management, and authorization.

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

## 3. Screen-by-Screen Audit

### TODAY (`/page.tsx`)
* **Current Functionality:** Displays mock tasks, schedule, memory attention scenarios, nutrition, and home telemetry.
* **Missing Workflows:** Real task completion/syncing, device control execution, dynamic priority sorting, notification/alert dismissal persistence.
* **States Missing:** LOADING, OFFLINE, SYNC ERROR, EMPTY, PERMISSION DENIED.

### NUTRITION (`/nutrition/page.tsx`)
* **Current Functionality:** Displays mock macros (calories, protein, carbs) and Mealie family meal plan.
* **Missing Workflows:** Barcode/photo scanning, manual entry, recipe selection, pantry inventory management.
* **States Missing:** PARTIAL data, ESTIMATED vs MEASURED tracking, EMPTY (not logged).

### PREGNANCY NUTRITION (`/nutrition/pregnancy/page.tsx`)
* **Current Functionality:** Detailed coverage cards for Iron, Calcium, Folate, Vit D.
* **Missing Workflows:** Logging specific supplements (e.g. prenatal vitamins), adjusting clinical targets based on lab results.
* **States Missing:** UNKNOWN (needs better visual representation than 0), STALE (needs freshness indicators).

### HEALTH (`/health/page.tsx`)
* **Current Functionality:** Displays mock FHIR clinical consultation, sleep data, and hydration.
* **Missing Workflows:** Viewing lab results, managing care team, reading clinical documents, updating allergies.
* **States Missing:** SYNCING (with provider), PERMISSION DENIED, CONSENT REQUIRED (shown statically, needs dynamic enforcement), PROVIDER DISCONNECTED.

### CALENDAR (`/calendar/page.tsx`)
* **Current Functionality:** Filters by source, dual-track partner view, event detail drawer.
* **Missing Workflows:** Create/edit/delete events, RSVP, OAuth flow to connect Google/Apple/Work accounts.
* **States Missing:** SYNC ERROR, OFFLINE.

### MEMORY (`/memory/page.tsx`)
* **Current Functionality:** Lists proposed, active, and history memories. Allows quick accept/reject.
* **Missing Workflows:** Dispute resolution, shared review coordination, explicit assertion creation by user, linking to source lineage.
* **Architecture Mismatch:** UI simplifies the B1-B6 Knowledge architecture. Lacks distinction between exact-version lifecycle and control state.

### ASK OLIN (`/ask/page.tsx` & `AskOlinModal.tsx`)
* **Current Functionality:** Two separate interfaces. `AskOlinModal` provides a richer contextual chat with tool cards and personalization explanations.
* **Missing Workflows:** Real agent streaming, multi-turn tool execution, action confirmation (e.g. "Are you sure you want to lock the door?").
* **States Missing:** ACTION PENDING, ACTION FAILED, PARTIAL RESULTS.

### FAMILY KIOSK (`/kiosk/page.tsx`)
* **Current Functionality:** Auto-rotating ambient slides (Status, Photo, Home, Wellness).
* **Missing Workflows:** Real presence detection, locked/idle timeout, emergency broadcast state.
* **Privacy Issues:** Wellness metrics (like weight or sensitive care tasks) must be explicitly redacted in shared mode. Currently mock data is hardcoded to be safe.

### SETTINGS (`/settings/*`)
* **Current Functionality:** Thin shells for Privacy and Appearance.
* **Missing Workflows:** Circle management, Care Relationships, Consent/Delegated Access flows, Data Export/Deletion, Notification configuration.

### NAVIGATION
* **Current Functionality:** Context switcher (Personal, Care, Family) drives mock data loading.
* **Recommendation:** Context switcher must drive actual authorization and data fetching scopes, not just UI state.

## 4. Missing Capability Matrix
| Capability | Status | Dependencies |
| :--- | :--- | :--- |
| Event Creation/Editing | UI ONLY | NEEDS EXTERNAL CONNECTOR (Calendar) |
| Food Logging | UI ONLY | NEEDS DOMAIN API (Nutrition) |
| Device Control | UI ONLY | NEEDS DEVICE/HOME ARCHITECTURE |
| Knowledge Assertion | UI ONLY | NEEDS KNOWLEDGE GATE |
| Consent Management | MISSING | NEEDS HOME/AUTH |
| FHIR Sync | UI ONLY | NEEDS HEALTH/G2 ARCHITECTURE |

## 5. Missing Attribute/Data Matrix
| Domain | Missing Attributes |
| :--- | :--- |
| Nutrition | Provenance (User vs Device), Completeness score, Measurement quality (ESTIMATED vs EXACT) |
| Health | Data freshness timestamp, Reference ranges, Measurement units standardization |
| Calendar | Sync status timestamp, External provider ID, Travel time estimates |
| Memory | Assertor ID, Control State (active/suppressed), Source Lineage IDs |

## 6. Action/Workflow Matrix
* **Create/Update/Delete Calendar Event:** Needs external sync.
* **Log Meal/Supplement:** Needs Nutrition API.
* **Accept/Reject Memory:** Needs Knowledge Gate API.
* **Grant Care Proxy Consent:** Needs Home Auth API.

## 7. UI State Matrix
Currently, most components assume a **LIVE/FRESH** state. We need to implement UI wrappers/components for:
* **LOADING:** Skeleton screens.
* **ERROR / UNAVAILABLE:** Fallback boundaries.
* **STALE:** Subtle visual indicators (e.g., dimmed text, "last updated X mins ago").
* **ESTIMATED / UNKNOWN:** Distinct styling from "0" or "None".

## 8. Domain Ownership Map
* **Process:** Real-world event (e.g., eating lunch).
* **Domain Model:** Nutrition API.
* **Services:** svc-nutrition.
* **Agent Tools:** `log_meal`.
* **UI:** `/nutrition` (Reads from svc-nutrition, does NOT hold source of truth).

## 9. Mock-vs-Live Inventory
**EVERYTHING IS CURRENTLY MOCK.**
* `domain/mocks.ts` provides all data.
* `AskOlinModal` uses hardcoded text matching for responses.
* Context switcher (`activeContext`) fakes authorization.

**Recommendation:** Introduce a global `MockProvider` or visual overlay (e.g., a subtle diagonal watermark or badge) during development to clearly distinguish mock data from live API data.

## 10. Privacy/Context Issues
* **Kiosk:** Needs strict, server-enforced redaction of clinical and personal data before sending to the client.
* **Context Switcher:** Currently relies on client-side logic to hide/show data (e.g., Ana's pregnancy dashboard). This must be driven by server-side Consent Grants.

## 11. Responsive/Kiosk Observations
* Kiosk is well-designed for a 10-foot UI experience.
* Needs explicit handling for touch interactions vs passive viewing.

## 12. Ask Olin UX Consolidation Proposal
Deprecate the dedicated `/ask` page in favor of the `AskOlinModal` pattern. The modal provides better context-in-place interaction, allowing users to reference the underlying screen while conversing.

## 13. Settings Information Architecture
1. **Account & Identity:** Profile, Circles, Care Relationships.
2. **Security & Privacy:** Consent Grants, Memory Controls, Data Export.
3. **Connected Services:** Calendars, Health Providers, Home Assistant.
4. **Preferences:** Appearance, Notifications, Kiosk settings.

## 14. Navigation Recommendation
* **Primary Navigation:** Today, Nutrition, Health, Calendar.
* **Utility:** Settings, Memory (move Memory to Settings/Privacy context rather than top-level).
* **Context Switcher:** Keep prominent in header.

## 15. Roadmap (P0-P3)
* **P0 (MVP):** Auth/Identity integration, Home API integration (real context switching), Ask Olin Agent backend connection.
* **P1:** Calendar Sync, Nutrition Logging API, Basic Device Control.
* **P2:** Memory/Knowledge Gate integration, Settings (Consent Management).
* **P3:** Health/FHIR integration (complex regulatory requirements).

## 16. Dependencies / Blockers
* **Auth/Home Service:** Required to make the Context Switcher functional and secure.
* **Agent Backend:** Required to make Ask Olin functional.
* **Database/ORM:** Required for Nutrition and Memory data persistence.

## 17. Recommended Next Three Gemini Implementation Tasks
1. **Context & Auth Integration:** Replace the client-side `activeContext` mock with a real integration to the Home/Auth service, enforcing proper data visibility.
2. **Ask Olin Backend Hookup:** Connect the `AskOlinModal` to a real agent execution backend, removing the hardcoded responses.
3. **Nutrition API Integration:** Replace `getTodaySummaryMock` with real fetching logic for the Nutrition domain, handling LOADING, ERROR, and EMPTY states.
