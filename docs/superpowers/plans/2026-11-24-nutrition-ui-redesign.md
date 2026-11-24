# Nutrition UI redesign (Hub) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On a 390 px phone, Hoy answers "am I on track today?" in one sentence and four fixed bars. All 15 tracked nutrients appear through one calm status language. Perfil becomes readable and moves behind a header chip. The Telegram how-to becomes a small "¿Cómo anoto?" page.

**Architecture:** This is a front-end change only: no backend, agent or env changes. One pure module (`nutrient-status.ts`) owns the status language: the states, the verdict, "faltan X", the weekly judgment and the grouping. The panel models only map wire data through it. The day and period mappers widen to all 15 nutrients and 16 averages. Hoy gains a second Live panel, the weekly status, which reads the 7-day period. A new nutrient-detail route has its own Live panel. Every Live panel keeps today's trust model. The shared header (chip, tabs, "Actualizado") renders inside each page's primary Live panel, so the chip reads that panel's own payload. On Hoy, the weekly panel is passed into the day panel as a slot. That keeps DOM order equal to reading order (verdict, bars, vitamins, meals). The cost: the weekly read starts only after the day read returns.

**Tech Stack:** Next.js 16.3.5 (App Router, server components), React 19.2, TypeScript 5, CSS modules over `--olin-*` tokens, `@phosphor-icons/react`, `node --test` with `--experimental-strip-types`, Playwright with the fake BFF and fake Nutrition in `apps/home-hub/test-support/`.

**Spec:** `docs/superpowers/specs/2026-11-24-nutrition-ui-redesign-design.md`. Product truth is in `apps/home-hub/PRODUCT.md`; the visual system is in `apps/home-hub/DESIGN.md`. Executors read all three.

**Finish review (not a task):** After Task 11, the controller runs Impeccable's finish reviewer: the `impeccable-finish-reviewer` agent or, failing that, `reference/degraded/finish-reviewer.md` in a fresh agent. It receives the Task 11 screenshots, the `detect --json` output, this spec and the direction contract from the surface brief (Task 1). The controller then acts on the verdict and runs the documenter pass on `DESIGN.md`.

## Global Constraints

- `$IMP` means `$HOME\.claude\plugins\cache\impeccable\impeccable\4.8.2\skills\impeccable` (PowerShell). Every task that edits UI (Tasks 3–10) reads `$IMP\reference\craft-floor.md` before editing.
- Read the relevant guide in `apps/home-hub/node_modules/next/dist/docs/` before writing page, route or component code. `apps/home-hub/AGENTS.md` warns that this Next.js has breaking changes.
- Spanish copy and `lang="es"` on every new panel. Numbers are `es-ES` with grouping always on (`1.640`, `2.250`), through `nutrition-format.ts`.
- The app is read-only and sends only `GET` to Nutrition.
- Trust:
  - each Live panel render makes exactly one `POST /delegation?audience=svc-nutrition` and one Nutrition `GET`, and never retries;
  - the `episteck_home_session` cookie goes only to the BFF;
  - a `*.server.ts` adapter may be imported only by the files listed for it in `test-support/verify-adapter-callers.mjs` `PAIRS`.
- No nutrition maths in the app:
  - totals, averages and percentages come from Nutrition;
  - the one exception is "faltan X": the target minus the known value, both as displayed;
  - comparisons (≥, ≤, >, <) are allowed;
  - bar widths are CSS ratios of raw wire decimals (`--bar-value` / `--bar-scale`), so no percentage is computed in TypeScript.
- Status language: green `bien` (`--olin-status-success`), amber `corto` / `bajo` / `por encima` / `pasado del límite` (`--olin-status-caution`), grey `faltan datos` / `pocos días (N)` / `sin cerrar` / `Sin registros` (`--olin-status-unknown`), neutral `en curso` (`--olin-status-progress`). No red. Every state carries its word.
- Unknown is never 0. An unknown value reads `sin dato`; a day without entries reads `Sin registros`.
- Chat prompts and text addressed to the subject (`Te faltan…`, `Tu prenatal…`, `tu perfil`) are for the subject only. A consent viewer sees the neutral variants this plan pins, and no prompt (ruling R7 of plan 3).
- `?person=` keeps its meaning. Every link between nutrition pages carries it when the URL has it.
- Links to nutrition pages are plain `<a>` with `HUB_BASE_PATH`, or `next/link` with `prefetch={false}`. A nutrition page must never render, and so never mint, before a tap.
- Phone first:
  - one column at 390 px, and the page never scrolls sideways;
  - touch targets ≥ 44 px;
  - text ≥ 4.5:1;
  - text placed directly on the canvas (header, tabs, "Actualizado") uses `--olin-text-main`, because the gradient's darker stops fail with `--olin-text-muted`.
- Hoy layout is stable. The four headline rows (Energía, Proteína, Fibra, Azúcares libres) always render, in that order and at the same height, whether or not a bar is drawn.
- Icons come from `@phosphor-icons/react` (`ForkKnife`, `CaretRight`, `Info`), with `aria-hidden`. The spec's `›` and `ⓘ` are drawn this way, never typed as Unicode glyphs (craft floor).
- Use role tokens only: no hex literal in new CSS, and status colours only from `--olin-status-*`.
- No per-meal kcal (Owner decision 3). No placeholder controls for supplements.
- Logs: one line per panel render, `nutrition.<view> outcome=<KIND>`, with view in `profile | today | week | period | nutrient`. Never IDs, names, dates or values.
- Fixtures are synthetic. No real names, person IDs or host names in code, tests, docs or screenshots.
- The direction contract lives only in the surface brief (`apps/home-hub/.impeccable/surfaces/`). It never goes into source, DOM, comments or `data-*` attributes.
- Pure modules covered by `node --test` import relatively, with the `.ts` extension, like the existing models. They never import `.tsx`.
- Commands, all run from `apps/home-hub`:
  - `CHECKS` = `npm test && npm run lint && node node_modules/typescript/bin/tsc --noEmit && npm run test:server-boundary`. Never use `npx tsc`, which hangs.
  - `E2E` = `HOME_HUB_DATA_MODE=LIVE HOME_HUB_BFF_BASE_URL=http://127.0.0.1:3323 HOME_HUB_NUTRITION_BASE_URL=http://127.0.0.1:9930 HOME_HUB_PUBLIC_ORIGIN=http://127.0.0.1:3322 npm run build && npm run test:startup-config && npx playwright test`. `test:startup-config` must run right after the build, because the e2e run deletes `.next/standalone`.
  - Every task ends with `CHECKS` green. Every task that touches UI or e2e also ends with `E2E` green; the suite was 226 unit and 70 e2e tests at the start.

## Review Focus

1. **A consent viewer opens the pregnant member's Hoy.** Expected: neutral copy (`Va en camino. Le falta proteína.`, `El prenatal aún no se cuenta…`, `Todavía no hay perfil completo.`, `Ver de dónde sale en su perfil`), no copy button, and a profile chip that reads `Sin perfil` and is not a link. Tests: Task 1 `verdict: a viewer reads neutral copy`, Task 5 `without a profile: "Crear perfil" for the person, "Sin perfil"…`, Task 9 `a viewer gets "Ver de dónde sale en su perfil"`, Task 7 `a consent viewer sees neutral copy and no prompt`.
2. **Late evening on an open day, close to the target.** The displayed difference rounds to zero or below, or mixes decimals (`9,5 de 30 mg`). Expected: `en curso` with no `faltan 0 g`, and `faltan 20,5 mg` so the numbers add up. Test: Task 1 `missingAmount…`.
3. **A past day the person never closed** (skipped the evening check-in). Expected: `sin cerrar` and a grey ring in Días, `sin cerrar` in the detail view, never amber. The weekly status reads `pocos días (N)` instead of judging. Tests: Task 1 status table (`OPEN_PAST`), Task 8 `an unclosed past day…`.
4. **The first week, or a person without a profile.** Micronutrients with 0–2 closed days, partial data or no target. Expected: grey `faltan datos` / `pocos días (N)` or a `Sin objetivo` group, never `corto`. Tests: Task 1 `weeklyState…`, Task 6 `no targets at all…`.
5. **The 14-day range on a 390 px phone.** Expected: two stacked 7-day grids, `Media` only on the latest one, and no sideways scroll. Test: Task 8 `14 days at 390 px…`.

---

## File map

| File | Responsibility |
| --- | --- |
| `src/integration/nutrition/nutrient-status.ts` | Status language: states, bars, verdict, "faltan X", weekly judgment, grouping (pure) |
| `src/integration/nutrition/nutrition-format.ts` | Gains `nutrientName`, `unitOf`, `spanishList`, `weekdayInitial`, `dayOfMonth`, `berlinClock` |
| `src/integration/nutrition/diary-contract.ts`, `period-contract.ts` | All 15 nutrients; 16 averages; `DiaryItem.withFacts` |
| `test-support/nutrition-fixtures.mjs` | Synthetic wire bodies shared by the fake Nutrition and unit tests |
| `src/styles/tokens.css`, `src/styles/status-tokens.test.ts` | Three new status tokens × 6 themes; the contrast proof |
| `src/integration/nutrition/nutrition-href.ts` | Nutrition links and the `/nutrition` redirect target (pure) |
| `src/components/layout/live-routes.ts` | Which routes hide the demo banner (pure) |
| `src/integration/nutrition/profile-chip.ts` | The header chip from a page's own payload (pure) |
| `src/components/features/nutrition/panel-error.ts` | One error-code → panel-kind mapping for new models |
| `src/components/features/nutrition/weekly-model.ts`, `WeeklyStatus.tsx`, `WeeklyPanel.tsx` | Vitamins and minerals grouped status |
| `src/components/features/nutrition/StatusBar.tsx` | One bar: 0–150 % track, tick / band / cap, toned fill, word |
| `src/components/features/nutrition/nutrient-detail-model.ts`, `NutrientPanel.tsx` | Nutrient detail |
| `src/app/nutrition/{perfil,ayuda,nutriente/[code]}/page.tsx` | New routes; `src/app/nutrition/page.tsx` redirects |
| `src/app/nutrition/hoy/LiveWeeklyPanel.tsx`, `src/app/nutrition/nutriente/LiveNutrientPanel.tsx`, `src/app/nutrition/perfil/LiveProfilePanel.tsx` (moved) | Live panels |
| `e2e/nutrition-support.ts` | Shared e2e helpers (sign-in, counters, secrets, CSP) |

---

### Task 1: Status language core and the direction contract

**Files:**
- Create: `apps/home-hub/src/integration/nutrition/nutrient-status.ts`, `nutrient-status.test.ts`
- Modify: `apps/home-hub/src/integration/nutrition/nutrition-format.ts`, `nutrition-format.test.ts`
- Create (by the Impeccable CLI): `apps/home-hub/.impeccable/surfaces/src-app-nutrition-hoy-page-tsx.md`

**Interfaces:**
- Consumes: `NutrientBlock` (`diary-contract.ts`); `amount`, `unitLabel`, `nutrientLabel` (`nutrition-format.ts`).
- Produces, in `nutrition-format.ts`:

```ts
export function nutrientName(code: string): string;   // sentence form: 'energía', 'vitamina D', 'DHA', 'azúcares libres'
export function unitOf(code: string): string;         // unit suffix of the code: 'iron_mg' -> 'mg', 'folate_ug' -> 'ug', 'energy_kcal' -> 'kcal'
export function spanishList(names: string[]): string; // '', 'a', 'a y b', 'a, b y c'
export function weekdayInitial(iso: string): string;  // es-ES narrow weekday in UTC: '2026-11-18' -> 'X'
export function dayOfMonth(iso: string): string;      // '2026-11-08' -> '8'
export function berlinClock(at: Date): string;        // 'HH:MM' in Europe/Berlin, h23
```

- Produces, in `nutrient-status.ts` (used by Tasks 6–9):

```ts
export type Tone = 'ok' | 'caution' | 'unknown' | 'progress' | 'unclosed' | 'empty' | 'plain';
export interface NutrientState { tone: Tone; word: string | null; detail: string | null }
export type DayPhase = 'NO_ENTRIES' | 'OPEN_TODAY' | 'OPEN_PAST' | 'CLOSED';
export type Target = NutrientBlock['target'];                    // { value, displayValue, unit, kind } | null
export type Mark = 'tick' | 'band' | 'cap';                      // MIN | ABOUT | MAX (limit)
export interface Bar { value: string | null; scale: string; mark: Mark } // value null = empty track
export interface DayInput { known: string | null; status: 'NONE' | 'KNOWN' | 'PARTIAL'; target: Target; percent: string | null }
export interface WeeklyInput { averageKnown: string | null; averagePercent: string | null; daysUsed: number }
export interface Headline { code: string; kind: 'ABOUT' | 'MIN' | 'MAX' | null; state: NutrientState }
export type GroupKey = 'short' | 'fine' | 'missing' | 'plain';
export interface WeeklyGroup<T> { key: GroupKey; summary: string; items: T[] }

export function dayPhase(dayStatus: 'NO_ENTRIES' | 'OPEN' | 'COMPLETE', isToday: boolean): DayPhase;
export function limitTarget(limitG: string): NonNullable<Target>;        // { value: limitG, displayValue: limitG, unit: 'g', kind: 'MAX' }
export function dayState(input: DayInput, phase: DayPhase): NutrientState;
export function weeklyState(input: WeeklyInput, target: Target): NutrientState;
export function missingAmount(targetDisplay: string, known: string, unit: string): string | null;
export function barFor(target: Target, known: string | null, phase: DayPhase): Bar | null;
export function latestTarget(days: readonly { nutrients: Record<string, { target: Target }> }[], code: string): Target;
export function verdict(v: { phase: DayPhase; headline: Headline[]; uncounted: number; self: boolean }): string;
export function groupWeekly<T extends { code: string; state: NutrientState }>(items: T[]): WeeklyGroup<T>[];
```

The rules below are the spec's tables, made exact.

**`dayState`.** Rules apply in this order; the first match wins.
1. `NO_ENTRIES` → `empty` / `Sin registros`.
2. Target null → `plain`, word null.
3. Known null → `unknown` / `faltan datos`.
4. `OPEN_PAST` → `unclosed` / `sin cerrar`.
5. By the target's kind:
   - **MIN.** Known ≥ `target.value` (number comparison) → `ok` / `bien`. Otherwise:
     - `OPEN_TODAY` → `progress`, with the word `en curso · faltan X <unit>`;
     - `CLOSED` and `PARTIAL` → `unknown` / `faltan datos`;
     - `CLOSED` and complete → `caution` / `corto`.
   - **ABOUT**, judged by the wire `percent`:
     - `OPEN_TODAY`: percent > 110 → `caution` / `por encima`; else `progress` / `en curso · faltan ~X <unit>`;
     - `CLOSED`: percent > 110 → `caution` / `por encima`; then `PARTIAL` → `unknown` / `faltan datos`; then 90 ≤ percent ≤ 110 → `ok` / `bien`; then `caution` / `bajo`;
     - a percent of null here → `unknown` / `faltan datos`.
   - **MAX**, also used for free sugars through `limitTarget`: known > `target.value` → `caution` / `pasado del límite`; `PARTIAL` → `unknown` / `faltan datos`; otherwise `ok` / `bien`.
6. When `missingAmount` returns null, the word is just `en curso`. The unit is `unitLabel(target.unit)`.

**`missingAmount`.** Format both strings with `amount(…, unit)` and parse them back (strip the `.` grouping, change `,` to `.`). Subtract. Return null if the result is ≤ 0. Otherwise format it with at most one decimal and grouping always on. Never use the raw decimals.

**`weeklyState`.** Rules apply in this order:
1. Target null → `plain`.
2. `daysUsed` 0 → `unknown` / `faltan datos`.
3. `daysUsed` 1–2 → `unknown` / `pocos días (N)`.
4. `averagePercent` null → `unknown` / `faltan datos`.
5. By kind:
   - MIN: < 100 → `caution` / `corto`; else `ok` / `bien`;
   - ABOUT: the CLOSED rule without the partial step;
   - MAX: > 100 → `caution` / `pasado del límite`; else `ok` / `bien`.

   Every judged state carries `detail: 'con N días'`.

**`barFor`.**
- Target null → null.
- `NO_ENTRIES`, or known null → `{ value: null, scale: target.value, mark }`.
- Otherwise → `{ value: known, scale: target.value, mark }`.

**`verdict`.** `headline` holds energy, protein, fiber and free sugars, in that order.

Copy for the subject (`self` true), with the viewer variant in brackets:
- `NO_ENTRIES` → `Aún no has anotado nada hoy.` [`Aún no hay nada anotado hoy.`]
- Free sugars `caution` → `Hoy te has pasado de azúcares libres.` [`Hoy se ha pasado de azúcares libres.`]
- `OPEN_TODAY`:
  1. energy, protein and fiber all `plain` → `Día abierto.`;
  2. else, any of them `caution` → `Vas por encima en <names>.` [`Va por encima en …`];
  3. else → `Vas en camino.` [`Va en camino.`].

  After that, the MIN rows in `progress` add one more sentence: one name → ` Te falta <name>.` [` Le falta …`]; two or more → ` Te faltan <list>.` [` Le faltan …`].
- `CLOSED` → `Día cerrado: ` and these parts, in this order, joined by `; `, then `.`:
  - `bien en <ok names>`;
  - `corto en <names whose word is corto or bajo>`;
  - `por encima en <names whose word is por encima>`.

  With no part at all, the sentence is `Día cerrado.`
- Free-sugar ordering: the free-sugar sentence replaces the open and closed sentences. Free sugars that are `ok` join the `bien en` list.
- When `uncounted` > 0, append ` Faltan datos de 1 alimento.` or ` Faltan datos de N alimentos.` This applies after every sentence except `NO_ENTRIES`.
- Names use `nutrientName` and lists use `spanishList`.

**`groupWeekly`.**
- Tone to group: `caution` → `short`, `ok` → `fine`, `plain` → `plain`, any other tone → `missing`.
- Group order: short, fine, missing, plain. Empty groups are left out, and items keep their input order.
- Summaries:
  - `Corto: <names joined with ', '>`;
  - `Bien: N`;
  - `Faltan datos: N`;
  - `Sin objetivo: N`.

**`latestTarget`.** The target of the last day in the array whose block for `code` has a target; null when no day has one.

- [ ] **Step 1: Write the failing tests**

`nutrition-format.test.ts` (new cases):

```ts
test('sentence names keep acronyms and the vitamin letter', () => {
  assert.equal(nutrientName('energy_kcal'), 'energía');
  assert.equal(nutrientName('vitamin_d_ug'), 'vitamina D');
  assert.equal(nutrientName('dha_g'), 'DHA');
  assert.equal(nutrientName('free_sugars_g'), 'azúcares libres');
});
test('units, lists, weekday initials and the Berlin clock', () => {
  assert.equal(unitOf('folate_ug'), 'ug');
  assert.equal(spanishList(['proteína', 'fibra']), 'proteína y fibra');
  assert.equal(spanishList(['a', 'b', 'c']), 'a, b y c');
  assert.equal(weekdayInitial('2026-11-18'), 'X');
  assert.equal(weekdayInitial('2026-11-20'), 'V');
  assert.equal(dayOfMonth('2026-11-08'), '8');
  assert.equal(berlinClock(new Date('2026-11-24T13:05:00Z')), '14:05');
  assert.equal(berlinClock(new Date('2026-07-01T13:05:00Z')), '15:05');
});
```

`nutrient-status.test.ts`. Fixtures: `MIN = { value: '65', displayValue: '65', unit: 'g', kind: 'MIN' }` and `ABOUT = { value: '2241.6', displayValue: '2250', unit: 'kcal', kind: 'ABOUT' }`. Helper: `s(tone, word, detail = null)`.

```ts
test('MIN: today open is bien or en curso · faltan X; closed is bien, faltan datos or corto', () => {
  assert.deepEqual(dayState({ known: '65.0', status: 'KNOWN', target: MIN, percent: '100' }, 'OPEN_TODAY'), s('ok', 'bien'));
  assert.deepEqual(dayState({ known: '48.2', status: 'PARTIAL', target: MIN, percent: '74' }, 'OPEN_TODAY'), s('progress', 'en curso · faltan 17 g'));
  assert.deepEqual(dayState({ known: '70.0', status: 'PARTIAL', target: MIN, percent: '108' }, 'CLOSED'), s('ok', 'bien'));
  assert.deepEqual(dayState({ known: '48.2', status: 'PARTIAL', target: MIN, percent: '74' }, 'CLOSED'), s('unknown', 'faltan datos'));
  assert.deepEqual(dayState({ known: '48.2', status: 'KNOWN', target: MIN, percent: '74' }, 'CLOSED'), s('caution', 'corto'));
});
test('ABOUT: 90–110 % is bien when closed; open days only warn above 110 %', () => {
  assert.deepEqual(dayState({ known: '1640.3', status: 'KNOWN', target: ABOUT, percent: '73' }, 'OPEN_TODAY'), s('progress', 'en curso · faltan ~610 kcal'));
  assert.deepEqual(dayState({ known: '2490.0', status: 'KNOWN', target: ABOUT, percent: '111' }, 'OPEN_TODAY'), s('caution', 'por encima'));
  assert.deepEqual(dayState({ known: '2260.0', status: 'KNOWN', target: ABOUT, percent: '101' }, 'OPEN_TODAY'), s('progress', 'en curso'));
  for (const p of ['90', '110']) assert.equal(dayState({ known: '2100.0', status: 'KNOWN', target: ABOUT, percent: p }, 'CLOSED').word, 'bien');
  assert.deepEqual(dayState({ known: '1990.0', status: 'KNOWN', target: ABOUT, percent: '89' }, 'CLOSED'), s('caution', 'bajo'));
  assert.deepEqual(dayState({ known: '2490.0', status: 'PARTIAL', target: ABOUT, percent: '111' }, 'CLOSED'), s('caution', 'por encima'));
  assert.deepEqual(dayState({ known: '1790.0', status: 'PARTIAL', target: ABOUT, percent: '80' }, 'CLOSED'), s('unknown', 'faltan datos'));
});
test('limit: over is amber in any phase, partial is grey, at the limit is bien', () => {
  const L = limitTarget('50');
  for (const phase of ['OPEN_TODAY', 'CLOSED'] as const) {
    assert.deepEqual(dayState({ known: '51.0', status: 'PARTIAL', target: L, percent: null }, phase), s('caution', 'pasado del límite'));
  }
  assert.deepEqual(dayState({ known: '12.0', status: 'PARTIAL', target: L, percent: null }, 'OPEN_TODAY'), s('unknown', 'faltan datos'));
  assert.deepEqual(dayState({ known: '50.0', status: 'KNOWN', target: L, percent: null }, 'CLOSED'), s('ok', 'bien'));
});
test('no entries, no target, nothing counted and a past day left open', () => {
  assert.deepEqual(dayState({ known: null, status: 'NONE', target: MIN, percent: null }, 'NO_ENTRIES'), s('empty', 'Sin registros'));
  assert.deepEqual(dayState({ known: '58.0', status: 'KNOWN', target: null, percent: null }, 'CLOSED'), s('plain', null));
  assert.deepEqual(dayState({ known: null, status: 'PARTIAL', target: MIN, percent: null }, 'CLOSED'), s('unknown', 'faltan datos'));
  assert.deepEqual(dayState({ known: '20.0', status: 'KNOWN', target: MIN, percent: '31' }, 'OPEN_PAST'), s('unclosed', 'sin cerrar'));
});
test('dayPhase: only today is open; a past open day is OPEN_PAST', ...);   // ('OPEN', true) OPEN_TODAY; ('OPEN', false) OPEN_PAST; ('COMPLETE', false) CLOSED; ('NO_ENTRIES', true) NO_ENTRIES
test('missingAmount uses the displayed numbers, never the raw decimals', () => {
  assert.equal(missingAmount('65', '48.2', 'g'), '17');
  assert.equal(missingAmount('2250', '1640.3', 'kcal'), '610');
  assert.equal(missingAmount('2250', '200', 'kcal'), '2.050');
  assert.equal(missingAmount('30', '9.5', 'mg'), '20,5');
  assert.equal(missingAmount('60', '59.6', 'g'), null);   // 60 − 60
  assert.equal(missingAmount('2250', '2260', 'kcal'), null);
});
test('weeklyState: 0 days, 1–2 days, judged with con N días, no target', () => {
  const IRON = { value: '27', displayValue: '27', unit: 'mg', kind: 'MIN' } as const;
  assert.deepEqual(weeklyState({ averageKnown: null, averagePercent: null, daysUsed: 0 }, IRON), s('unknown', 'faltan datos'));
  assert.deepEqual(weeklyState({ averageKnown: '120.0', averagePercent: '55', daysUsed: 2 }, IRON), s('unknown', 'pocos días (2)'));
  assert.deepEqual(weeklyState({ averageKnown: '9.8', averagePercent: '36', daysUsed: 4 }, IRON), s('caution', 'corto', 'con 4 días'));
  assert.deepEqual(weeklyState({ averageKnown: '27.5', averagePercent: '100', daysUsed: 3 }, IRON), s('ok', 'bien', 'con 3 días'));
  assert.deepEqual(weeklyState({ averageKnown: '9.8', averagePercent: null, daysUsed: 4 }, IRON), s('unknown', 'faltan datos'));
  assert.deepEqual(weeklyState({ averageKnown: '9.8', averagePercent: null, daysUsed: 5 }, null), s('plain', null));
  assert.equal(weeklyState({ averageKnown: '2400', averagePercent: '115', daysUsed: 4 }, ABOUT).word, 'por encima');
  assert.equal(weeklyState({ averageKnown: '31', averagePercent: '101', daysUsed: 4 }, limitTarget('50')).word, 'pasado del límite');
});
test('barFor: tick, band and cap; an empty track without entries; no bar without a target', ...);
// barFor(MIN, '48.2', 'OPEN_TODAY') -> { value: '48.2', scale: '65', mark: 'tick' }; ABOUT -> 'band'; limitTarget('50') -> 'cap';
// barFor(MIN, null, 'NO_ENTRIES') -> { value: null, scale: '65', mark: 'tick' }; barFor(null, '58.0', 'CLOSED') -> null
test('latestTarget takes the most recent day that has one', ...);   // days [MIN-target day, target-null day] -> MIN; all null -> null
```

The verdict tests. The helper `h(code, kind, tone, word)` builds a `Headline`.

```ts
test('verdict: open day, with the singular and plural of faltar and the partial suffix', () => {
  const open = [h('energy_kcal', 'ABOUT', 'progress', 'en curso · faltan ~610 kcal'), h('protein_g', 'MIN', 'progress', 'en curso · faltan 17 g'),
    h('fiber_g', 'MIN', 'ok', 'bien'), h('free_sugars_g', 'MAX', 'unknown', 'faltan datos')];
  assert.equal(verdict({ phase: 'OPEN_TODAY', headline: open, uncounted: 2, self: true }),
    'Vas en camino. Te falta proteína. Faltan datos de 2 alimentos.');
  const both = [...open]; both[2] = h('fiber_g', 'MIN', 'progress', 'en curso · faltan 4 g');
  assert.equal(verdict({ phase: 'OPEN_TODAY', headline: both, uncounted: 1, self: true }),
    'Vas en camino. Te faltan proteína y fibra. Faltan datos de 1 alimento.');
});
test('verdict: no entries, sugars over the limit, energy above on an open day, no targets', ...);
// 'Aún no has anotado nada hoy.' / 'Hoy te has pasado de azúcares libres.' / 'Vas por encima en energía. Te falta fibra.' /
// energy, protein, fiber all plain + uncounted 1 -> 'Día abierto. Faltan datos de 1 alimento.'
test('verdict: closed day lists bien, corto and por encima; all grey is just Día cerrado.', ...);
// [ok, ok, caution corto, unknown] -> 'Día cerrado: bien en energía y proteína; corto en fibra.'
// [caution por encima, ok, ok, ok] -> 'Día cerrado: bien en proteína, fibra y azúcares libres; por encima en energía.'
// all unknown -> 'Día cerrado.'
test('verdict: a viewer reads neutral copy', ...);
// 'Aún no hay nada anotado hoy.' / 'Hoy se ha pasado de azúcares libres.' / 'Va en camino. Le falta proteína. Faltan datos de 2 alimentos.'
test('groupWeekly: Corto lists names, the others count; empty groups are hidden', () => {
  const g = groupWeekly([
    { code: 'calcium_mg', state: s('ok', 'bien') }, { code: 'iron_mg', state: s('caution', 'corto') },
    { code: 'folate_ug', state: s('caution', 'corto') }, { code: 'vitamin_b12_ug', state: s('unknown', 'faltan datos') },
    { code: 'iodine_ug', state: s('unknown', 'pocos días (2)') }, { code: 'dha_g', state: s('plain', null) },
  ]);
  assert.deepEqual(g.map((x) => x.summary), ['Corto: hierro, folato', 'Bien: 1', 'Faltan datos: 2', 'Sin objetivo: 1']);
  assert.deepEqual(groupWeekly([{ code: 'zinc_mg', state: s('ok', 'bien') }]).map((x) => x.key), ['fine']);
});
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd apps/home-hub && npm test -- src/integration/nutrition/nutrient-status.test.ts src/integration/nutrition/nutrition-format.test.ts`
Expected: FAIL (`nutrient-status.ts` not found; `nutrientName` is not exported).

- [ ] **Step 3: Implement the six format helpers and `nutrient-status.ts`**

`nutrientName`:
- returns `nutrientLabel(code)` unchanged when the label is all upper case;
- otherwise lowercases the first letter, and for `free_sugars_g` the whole label.

`weekdayInitial`: the es-ES `weekday: 'narrow'` format in `timeZone: 'UTC'`.

- [ ] **Step 4: Run the tests until they pass**

Run: `cd apps/home-hub && npm test -- src/integration/nutrition/nutrient-status.test.ts src/integration/nutrition/nutrition-format.test.ts`
Expected: PASS.

- [ ] **Step 5: Record the direction contract in the surface brief**

1. Read the existing brief from `apps/home-hub`:

   `& "$IMP\scripts\impeccable.cmd" surface-brief read src/app/nutrition/hoy/page.tsx`

2. Write the body below to a temporary file outside the repository.
3. Write the brief from `apps/home-hub`:

   `& "$IMP\scripts\impeccable.cmd" surface-brief write src/app/nutrition/hoy/page.tsx <body-file> src/app/nutrition/dias/page.tsx src/app/nutrition/page.tsx`

The body (`## Direction contract`, then six blocks):

```text
THESIS: One calm answer per day. A verdict sentence and four bars in fixed positions answer "am I on track today?" before anything else; the page refuses the dashboard default of tiles, rings and a hero metric.
OWN-WORLD: The active Olin theme's tokens only. One column of hairline-separated rows, one card per section, never a card inside a card. Status speaks in four role colours (success, caution, unknown, progress), always with its word; bars are thin 0–150 % tracks with a tick, band or cap mark. Phosphor icons only.
STORY: She opens the Home Screen shortcut, reads one sentence, scans four bars that never move, and knows whether today is on track. She opens a vitamin group or a meal only when she wants detail; every change happens in her chat.
FIRST VIEWPORT (390×844): "Nutrición" with the profile chip at its right; the person switcher only for more than one person; the Hoy · Días tabs; "Actualizado HH:MM · Actualizar"; the verdict in large body type; four equal rows (name, "known de target", bar, state word), all above the bottom nav. No primary action: the page is read-only.
FORM: Structure A (first of the dealt A–D): verdict, four bars, one column, with D's grouped weekly status for vitamins and minerals. Owner-pinned 2026-11-24. seed:54d5b8d57a485594
FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
```

- [ ] **Step 6: Verify the brief**

Run: `& "$IMP\scripts\impeccable.cmd" surface-brief read src/app/nutrition/hoy/page.tsx`
Expected: all six blocks and `seed:54d5b8d57a485594` are present, and the FINISH line is verbatim. Nothing from the contract appears under `src/`.

- [ ] **Step 7: Run `CHECKS` and commit**

```bash
git add apps/home-hub/src/integration/nutrition apps/home-hub/.impeccable/surfaces
git commit -m "feat(hub): one status language for nutrition, with the Hoy direction contract"
```

---

### Task 2: All fifteen nutrients in the contracts, and shared fixtures

**Files:**
- Modify: `apps/home-hub/src/integration/nutrition/diary-contract.ts`, `diary-contract.test.ts`, `diary-loader.ts` (`emptyDay`), `period-contract.ts`, `period-contract.test.ts`, `period-loader.ts` (`emptyPeriod`)
- Modify: `apps/home-hub/src/components/features/nutrition/today-panel-model.ts`, `period-panel-model.ts` (imports only)
- Create: `apps/home-hub/test-support/nutrition-fixtures.mjs`, `nutrition-fixtures.test.mjs`
- Modify: `apps/home-hub/test-support/fake-nutrition.mjs`

**Interfaces:**
- Produces, in `diary-contract.ts` (used by every later task):

```ts
export const DAY_NUTRIENTS = ['energy_kcal', 'protein_g', 'fat_g', 'carb_g', 'fiber_g', 'calcium_mg', 'iron_mg', 'folate_ug',
  'vitamin_b12_ug', 'vitamin_d_ug', 'iodine_ug', 'zinc_mg', 'selenium_ug', 'choline_mg', 'dha_g'] as const;   // Nutrition's order
export type DayNutrient = (typeof DAY_NUTRIENTS)[number];
export const HEADLINE_NUTRIENTS = ['energy_kcal', 'protein_g', 'fiber_g'] as const;
export type HeadlineNutrient = (typeof HEADLINE_NUTRIENTS)[number];
export const MICRONUTRIENTS = ['calcium_mg', 'iron_mg', 'folate_ug', 'vitamin_b12_ug', 'vitamin_d_ug', 'iodine_ug',
  'zinc_mg', 'selenium_ug', 'choline_mg', 'dha_g'] as const;
export type Micronutrient = (typeof MICRONUTRIENTS)[number];
// DiaryDay.nutrients: Record<DayNutrient, NutrientBlock>: all 15 keys are required.
// DiaryItem gains withFacts: HeadlineNutrient[]: the headline codes present as keys of facts.nutrients_per_100g
//   (empty when facts is null); a present facts object without an object nutrients_per_100g is rejected.
```

- `DAY_NUTRIENTS_SHOWN` is removed; its two users switch to `HEADLINE_NUTRIENTS`.
- In `period-contract.ts`, `PeriodDay.nutrients` holds all 15 blocks, and `averages` holds all 16 keys (`AveragedNutrient = DayNutrient | 'free_sugars_g'`). Both are required.
- `nutrition-fixtures.mjs` exports these synthetic wire bodies (used by the fake and by the unit tests of Tasks 6–10):
  - days: `EMPTY_DAY`, `PARTIAL_DAY`, `NO_PROFILE_DAY`, `PREGNANCY_DAY`;
  - periods: `PERIOD_THREE`, `PERIOD_NO_PROFILE`, `PERIOD_WEEK_PREGNANCY`, `PERIOD_FOURTEEN`;
  - profiles: `PRESENT`, `MODE_ONLY`, `LONG_TEXT`.

  Existing bodies move here unchanged except that every day carries all 15 blocks and every period all 16 averages. The helpers `fullBlocks(over)` and `fullAverages(over)` fill the missing codes with `{ known: null, items_total: 0, items_uncounted: 0, status: 'NONE', target: null, percent: null }` and with `days_used: 0` averages.

  Like Nutrition, every block that has both a known value and a target carries a `percent`, and no other block does. So `PARTIAL_DAY` gains energy `19`, protein `21` and fiber `10`.

`PREGNANCY_DAY` (`today-pregnancy`):
- date `2026-11-24`, `PREGNANCY`, trimester 2, `profile_version` 2, `OPEN`;
- `sugar_status` `PARTIAL`, `free_sugars_known_g` `12.0`, `items_total` 4, `items_uncounted` 1, limit `50`.

| Code | known | status / uncounted | target (value / display / kind) | percent |
| --- | --- | --- | --- | --- |
| energy_kcal | 1640.3 | PARTIAL / 1 | 2241.6 / 2250 / ABOUT | 73 |
| protein_g | 48.2 | PARTIAL / 1 | 65 / 65 / MIN | 74 |
| fiber_g | 31.0 | PARTIAL / 2 | 30 / 30 / MIN | 103 |
| fat_g | 58.0 | PARTIAL / 1 | 75 / 75 / ABOUT | 77 |
| carb_g | 190.4 | PARTIAL / 1 | null | null |
| micronutrients | any positive values | PARTIAL / 1 | MIN: calcium 1000, iron 27, folate 550, vitamin B12 4.5, vitamin D 20, iodine 220, zinc 11, selenium 60, choline 480, DHA 0.2 | any |

Entries:
- `08:10+01:00`: `Avena con leche` (matched, all keys, free sugars `2.5`) and `Plátano` (matched, no `fiber_g` key, free sugars `0.5`);
- `13:30+01:00`: `Lentejas con arroz` (matched, BLS source, free sugars `1.0`) and `Tarta casera` (`facts: null`, free sugars null).
- Attribution is the BLS line.

`PERIOD_WEEK_PREGNANCY` (`today-pregnancy`, `days-pregnancy`):
- start `2026-11-18`, end `2026-11-24`, `has_profile` true;
- every day is `PREGNANCY`, trimester 2, with the same targets as `PREGNANCY_DAY` and a `free_sugars` block with `limit_g` `50`.

| Date | day_status | energy known / % | protein known (status) | fiber known (status) | free sugars known (status) / % |
| --- | --- | --- | --- | --- | --- |
| 11-18 | COMPLETE | 2105 / 94 | 70 (KNOWN) | 31 (KNOWN) | 18.0 (KNOWN) / 36 |
| 11-19 | COMPLETE | 1980 / 88 | 60 (KNOWN) | 22 (KNOWN) | 55.0 (KNOWN) / 110 |
| 11-20 | COMPLETE | 2300 / 103 | 66 (KNOWN) | 30 (KNOWN) | 20.0 (KNOWN) / 40 |
| 11-21 | COMPLETE | 2600 / 116 | 50 (PARTIAL) | 25 (KNOWN) | null (PARTIAL) / null |
| 11-22 | OPEN | 1500 / 67 | 40 (KNOWN) | 18 (KNOWN) | 10.0 (KNOWN) / 20 |
| 11-23 | NO_ENTRIES | null | null (NONE) | null (NONE) | null (NONE) |
| 11-24 | OPEN | 1640.3 / 73 | 48.2 (PARTIAL) | 31.0 (PARTIAL) | 12.0 (PARTIAL) / 24 |

Energy is `KNOWN` on 11-18 to 11-22 and `PARTIAL` on 11-24. Known values are the wire strings shown (`'2105'`, `'1640.3'`).

Averages (`average_known` / `average_percent` / `days_used`):

| Code | Average |
| --- | --- |
| energy | 2246.3 / 100 / 4 |
| protein | 61.5 / 95 / 3 |
| fiber | 27.0 / 90 / 4 |
| free sugars | 31.0 / 62 / 3 |
| fat | 70.2 / 94 / 4 |
| carb | 260.0 / null / 4 |
| iron | 9.8 / 36 / 4 |
| folate | 310.0 / 56 / 4 |
| vitamin D | 2.1 / 11 / 4 |
| choline | 260.0 / 54 / 4 |
| calcium | 1050.0 / 105 / 4 |
| zinc | 11.2 / 102 / 4 |
| selenium | 70.0 / 117 / 4 |
| vitamin B12 | null / null / 0 |
| iodine | 120.0 / 55 / 2 |
| DHA | 0.1 / 50 / 1 |

`PERIOD_FOURTEEN` (`days-fourteen`) is `PERIOD_WEEK_PREGNANCY`'s days moved back 7 days and followed by the same 7 days: start `2026-11-11`, end `2026-11-24`, with the same averages.

Fake routing for `/diary/{id}/period`:

| Scenario | Answer |
| --- | --- |
| `days-three` | `PERIOD_THREE` |
| `days-no-profile` | `PERIOD_NO_PROFILE` |
| `days-pregnancy`, `today-pregnancy` | `PERIOD_WEEK_PREGNANCY` |
| `days-fourteen` | `PERIOD_FOURTEEN` |
| `days-denied`, `today-denied` | 403 |
| `days-error`, `today-week-error` | 500 |
| `today-two-subjects` | `PERIOD_THREE` for `PSN-00001`, else 403 |
| any other `today-*` | `PERIOD_THREE` |
| anything else | 404 |

For `/days/today`, `today-pregnancy` answers `PREGNANCY_DAY` and `today-week-error` answers `PARTIAL_DAY`. `today-error` keeps its 500 for the day.

- [ ] **Step 1: Write the failing tests**

`diary-contract.test.ts`: extend `nutrients()` to all 15 codes, then add these tests:
- `maps all fifteen nutrient blocks in Nutrition's order`: `Object.keys(d.nutrients)` deep-equals `DAY_NUTRIENTS`, and the `iron_mg` block maps known, status and target.
- `rejects a day missing one of the fifteen`: delete `dha_g`; it throws `/dha_g/`.
- `withFacts lists the headline nutrients the food data has`: `nutrients_per_100g: { energy_kcal: '52', protein_g: '0.3' }` gives `['energy_kcal', 'protein_g']`, and `facts: null` gives `[]`.
- `rejects facts whose nutrients_per_100g is not an object`.

`period-contract.test.ts` gets two tests:
- `maps fifteen nutrients per day and sixteen averages`;
- `rejects a period missing the iodine_ug average`.

`test-support/nutrition-fixtures.test.mjs`, which imports the `.ts` contracts directly:

```js
test('every day fixture parses with the real day mapper', () => {
  for (const day of [EMPTY_DAY, PARTIAL_DAY, NO_PROFILE_DAY, PREGNANCY_DAY]) assert.doesNotThrow(() => parseDayWire(day));
});
test('every period fixture parses, and the pregnancy week ends today with 7 days', () => {
  for (const p of [PERIOD_THREE, PERIOD_NO_PROFILE, PERIOD_WEEK_PREGNANCY, PERIOD_FOURTEEN]) assert.doesNotThrow(() => parsePeriodWire(p));
  assert.equal(parsePeriodWire(PERIOD_WEEK_PREGNANCY).days.length, 7);
  assert.equal(parsePeriodWire(PERIOD_FOURTEEN).days.length, 14);
});
test('every profile fixture parses', ...);   // parseProfileWire(PRESENT|MODE_ONLY|LONG_TEXT)
test('a percent appears exactly where a known value and a target both do', ...);   // every day block and period day block
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd apps/home-hub && npm test -- src/integration/nutrition/diary-contract.test.ts src/integration/nutrition/period-contract.test.ts test-support/nutrition-fixtures.test.mjs`
Expected: FAIL (`DAY_NUTRIENTS` is not exported; the fixtures module is missing).

- [ ] **Step 3: Implement the widened contracts and loaders, the fixtures module and the fake's routing**

`fake-nutrition.mjs` imports every body from `nutrition-fixtures.mjs` and keeps only the routing and the call log.

- [ ] **Step 4: Run `CHECKS`, then `E2E`**

Expected: all green with no e2e change. This proves every existing scenario still emits valid wire.

- [ ] **Step 5: Commit**

```bash
git add apps/home-hub/src apps/home-hub/test-support
git commit -m "feat(hub): map all fifteen nutrients and share synthetic fixtures"
```

---

### Task 3: Status tokens and contrast

**Files:**
- Modify: `apps/home-hub/src/styles/tokens.css` (all six theme blocks)
- Create: `apps/home-hub/src/styles/status-tokens.test.ts`
- Modify: `apps/home-hub/src/components/slots/default/DefaultSlots.module.css` (`.defaultChip*`)
- Modify: `apps/home-hub/src/app/nutrition/page.module.css` (`.pageLinks`)
- Modify: `apps/home-hub/src/app/globals.css` (adds `.visually-hidden`)

**Interfaces:**
- Produces:
  - the tokens `--olin-status-caution`, `--olin-status-unknown` and `--olin-status-progress` in each theme;
  - the global class `visually-hidden` (the standard clip pattern), used by Tasks 7–9.

The values are the builder's call, under the tests below. Tokens are hex. Fix `--olin-status-success` in any theme where it fails (Family Canvas's `#0bb579` will). Shared-switcher chips get these fixes:

| Element | Fix |
| --- | --- |
| Active chip | `--olin-badge-bg` fill, `--olin-badge-text` text, weight 600 and an inset 2 px ring: `--olin-accent`; `#8b5cf6` for care mode (the existing literal); `--olin-surface-border-strong` for family |
| Inactive chip | `--olin-text-muted` on the card track |
| Nutrition page links | `--olin-text-main` for every link; the current one adds weight 700 and a 3 px `--olin-accent` underline (more than colour) |

- [ ] **Step 1: Write the failing test**

`status-tokens.test.ts`:
- It reads `tokens.css` and takes each `[data-olin-theme="<id>"] { … }` block.
- It parses `#rgb`, `#rrggbb` and `rgba()` values.
- It composites `--olin-surface-card` over `--olin-bg-canvas` to get "card", and `--olin-badge-bg` over card to get "track".
- Contrast follows WCAG 2.x relative luminance.

```ts
const THEMES = ['warm-household', 'ambient-future', 'premium-hardware', 'editorial-ledger', 'colorful-canvas', 'organic-calm'];
const STATUS = ['--olin-status-success', '--olin-status-caution', '--olin-status-unknown', '--olin-status-progress'];
test('all six themes are defined', () => assert.deepEqual(Object.keys(themes).sort(), [...THEMES].sort()));
test('every status colour reads at 4.5:1 on the card, in every theme', ...);       // used for the state words
test('status fills keep 3:1 against the bar track', ...);
test('the four status colours differ within each theme', ...);
test('text-main reads at 4.5:1 on the canvas (tabs, header, Actualizado)', ...);
test('person chips: badge-text on badge-bg and text-muted on the card read at 4.5:1', ...);
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd apps/home-hub && npm test -- src/styles/status-tokens.test.ts`
Expected: FAIL (the caution, unknown and progress tokens are missing).

- [ ] **Step 3: Add the tokens and fix the chip and link CSS**

- [ ] **Step 4: Run `CHECKS`, then `E2E`**

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add apps/home-hub/src
git commit -m "feat(hub): status tokens for all six themes; readable tabs and person chips"
```

---

### Task 4: Routes, navigation and Ajustes

**Files:**
- Create: `apps/home-hub/src/integration/nutrition/nutrition-href.ts`, `nutrition-href.test.ts`
- Create: `apps/home-hub/src/components/layout/live-routes.ts`, `live-routes.test.ts`
- Modify: `apps/home-hub/src/app/nutrition/page.tsx` (redirect)
- Create: `apps/home-hub/src/app/nutrition/perfil/page.tsx`
- Move: `src/app/nutrition/LiveProfilePanel.tsx` → `src/app/nutrition/perfil/LiveProfilePanel.tsx`
- Create: `apps/home-hub/src/app/nutrition/ayuda/page.tsx`
- Modify:
  - `apps/home-hub/src/app/nutrition/hoy/page.tsx` (drops `NutritionActions`);
  - `NutritionHeader.tsx` (the Perfil tab points to `/nutrition/perfil`; the `Acciones en Telegram` link goes; a new `help` view marks no tab);
  - `src/components/features/nutrition/NutritionActions.tsx` (`title` prop; intro `…vuelve y toca Actualizar.`).
- Modify: `apps/home-hub/src/components/layout/AppShell.tsx`, `BottomNav.tsx`, `Sidebar.tsx`, `src/app/layout.tsx` (`liveRoutes`)
- Modify: `apps/home-hub/src/app/settings/appearance/AppearanceScreen.tsx`, `src/app/settings/privacy/page.tsx`
- Modify: `apps/home-hub/test-support/verify-adapter-callers.mjs`, `verify-adapter-callers.test.mjs` (profile path)
- Create: `apps/home-hub/e2e/nutrition-support.ts`, `e2e/nutrition-routes.spec.ts`
- Modify: `apps/home-hub/e2e/nutrition-profile.spec.ts`, `nutrition-today.spec.ts`, `nutrition-days.spec.ts`, `bootstrap.spec.ts`, `person-context.spec.ts`

**Interfaces:**
- Produces:

```ts
// nutrition-href.ts
export function nutritionPath(path: string, person: string | null, query?: Record<string, string>): string; // no basePath; person first
export function nutritionHref(path: string, person: string | null, query?: Record<string, string>): string; // HUB_BASE_PATH + nutritionPath
export function hoyRedirectPath(searchParams: Record<string, string | string[] | undefined>): string;    // keeps every `person` value, drops the rest
// live-routes.ts
export function isLiveRoute(route: string, liveRoutes: readonly string[]): boolean; // exact match; an entry ending in '/' matches by prefix
// NutritionActions
export function NutritionActions({ title }: { title?: string }): JSX.Element;      // default 'Acciones en Telegram'
// e2e/nutrition-support.ts: HUB, BFF, NUTRITION, newRun(), signIn(page, scenario, run, variant = ''),
//   observed(request, run) -> { mints, calls, bootstraps }, berlinDaysAgo(back), captureHubBodies(page),
//   trackCspViolations(page), expectNoSecrets(text, cookieValue)   (moved from nutrition-profile.spec.ts)
```

Behaviour decided here:
- `/nutrition` (`page.tsx`):
  - MOCK keeps `NutritionDemoCluster`;
  - LIVE awaits `getBootstrapForRequest()`, which is cached and shared with the layout, and calls `redirect(hoyRedirectPath(params))` only when it is `READY`; otherwise it returns `null`.

  So a dead session still gets the layout's single redirect to `/login`. Read `node_modules/next/dist/docs/01-app/03-api-reference/04-functions/redirect.md` and confirm `redirect()` adds the `/app` basePath.
- `/nutrition/perfil` is today's Perfil page, keyed and logged as today. MOCK renders `ProfilePanel` `NOT_CONFIGURED`.
- `/nutrition/ayuda`, in both modes, renders `NutritionHeader view="help"` and `NutritionActions title="¿Cómo anoto?"`. It makes no Nutrition read. `/` keeps `NutritionActions` with its default title.
- `liveRoutes`: `['/', '/nutrition', '/nutrition/hoy', '/nutrition/dias', '/nutrition/perfil', '/nutrition/ayuda', '/nutrition/nutriente/']`. `/nutrition/pregnancy` keeps its demo banner.
- Navigation:
  - `BottomNav` labels are `Inicio`, `Memoria`, `Nutrición`, `Salud`, `Ajustes`;
  - `Sidebar` uses the same labels and `Calendario`. The spec names `BottomNav`, but the desktop nav shows the same icon and labels, so it changes too;
  - the Nutrition icon in both is `ForkKnife`. `AppleLogo` stays everywhere else.
- Both settings tab rows gain `<Link href={`/nutrition/perfil?person=…`} prefetch={false}>Perfil de nutrición</Link>`.
- `PAIRS` profile `allowed` and the test constant `ALLOWED` become `src/app/nutrition/perfil/LiveProfilePanel.tsx`.

- [ ] **Step 1: Write the failing unit tests**

```ts
test('nutritionHref puts person first and keeps the basePath', () => {
  assert.equal(nutritionHref('/nutrition/nutriente/iron_mg', 'PSN-00007', { rango: '7' }), '/app/nutrition/nutriente/iron_mg?person=PSN-00007&rango=7');
  assert.equal(nutritionHref('/nutrition/ayuda', null), '/app/nutrition/ayuda');
  assert.equal(nutritionPath('/nutrition/dias', 'PSN-00001', { dias: '3' }), '/nutrition/dias?person=PSN-00001&dias=3');
});
test('hoyRedirectPath keeps every person value and drops the rest', () => {
  assert.equal(hoyRedirectPath({}), '/nutrition/hoy');
  assert.equal(hoyRedirectPath({ person: 'PSN-00007', dias: '3' }), '/nutrition/hoy?person=PSN-00007');
  assert.equal(hoyRedirectPath({ person: ['a', 'b'] }), '/nutrition/hoy?person=a&person=b');
});
test('isLiveRoute: exact entries, and prefix entries ending in /', () => {
  assert.equal(isLiveRoute('/nutrition/nutriente/iron_mg', ['/nutrition/nutriente/']), true);
  assert.equal(isLiveRoute('/nutrition/nutriente', ['/nutrition/nutriente/']), false);
  assert.equal(isLiveRoute('/nutrition/pregnancy', ['/nutrition', '/nutrition/hoy']), false);
});
```

- [ ] **Step 2: Run them to see them fail; then implement the two pure modules until they pass**

Run: `cd apps/home-hub && npm test -- src/integration/nutrition/nutrition-href.test.ts src/components/layout/live-routes.test.ts`

- [ ] **Step 3: Write the e2e tests**

Create `e2e/nutrition-support.ts`, and switch `nutrition-profile.spec.ts` to import from it. Then make these updates:
- `nutrition-profile.spec.ts`: every `/app/nutrition` URL, in `goto` and in direct `request.get` calls, becomes `/app/nutrition/perfil`. The hover test uses `Nutrición` and `Inicio`.
- `nutrition-today.spec.ts`:
  - the Telegram copy test moves to `/app/nutrition/ayuda`;
  - `the Nutrition page links to Hoy…` is deleted (replaced below);
  - the mobile-Home test clicks `Nutrición`, drops the `Acciones en Telegram` link step, and expects the Perfil tab to land on `/app/nutrition/perfil?person=PSN-00001`.
- `nutrition-days.spec.ts`: the tabs test expects Perfil at `/nutrition/perfil?person=PSN-00001`, and no `Acciones en Telegram`. Its last step opens `/app/nutrition/perfil`, not `/app/nutrition`.
- `bootstrap.spec.ts`: `Memory` becomes `Memoria`. Both prototype-route loops use `/app/nutrition/perfil` instead of `/app/nutrition`. The 401 loop keeps `/app/nutrition` and adds `/app/nutrition/perfil`.
- `person-context.spec.ts`: `Nutrition` becomes `Nutrición`.

New `e2e/nutrition-routes.spec.ts`:

```ts
test('/app/nutrition redirects to Hoy keeping ?person=, before any Nutrition read', async ({ page, request }) => {
  const run = newRun();
  await signIn(page, 'today-partial', run);
  const response = await page.request.get(`${HUB}/app/nutrition?person=PSN-00007&dias=3`, { maxRedirects: 0 });
  expect(response.status()).toBe(307);
  expect(response.headers().location).toMatch(/\/app\/nutrition\/hoy\?person=PSN-00007$/);
  expect((await observed(request, run)).mints).toBe(0);
});
test('Perfil lives at /app/nutrition/perfil with no demo banner', ...);
test('¿Cómo anoto? holds the Telegram actions and reads nothing from Nutrition', ...);  // heading '¿Cómo anoto?', 'Registrar una comida', mints 0, calls []
test('the bottom nav reads Inicio, Memoria, Nutrición, Salud, Ajustes; Nutrición opens Hoy', ...); // 390×844; href /app/nutrition/hoy?person=PSN-00001
test('Ajustes lists Perfil de nutrición, never prefetched; it opens Perfil', ...);
// /app/settings/appearance: link href '/app/nutrition/perfil?person=PSN-00001'; hover; mints 0; click -> profile-panel visible
```

- [ ] **Step 4: Implement the routes, navigation, settings links and boundary update**

- [ ] **Step 5: Run `CHECKS`, then `E2E`**

Expected: all green. `test:server-boundary` proves `profile.server` is reachable only from `perfil/LiveProfilePanel.tsx`.

- [ ] **Step 6: Commit**

```bash
git add apps/home-hub
git commit -m "feat(hub): Perfil and ¿Cómo anoto? routes, /nutrition redirects to Hoy, Spanish nav"
```

---

### Task 5: Shared header with the profile chip

**Files:**
- Create: `apps/home-hub/src/integration/nutrition/profile-chip.ts`, `profile-chip.test.ts`
- Modify: `apps/home-hub/src/app/nutrition/NutritionHeader.tsx`, `page.module.css`
- Modify: `apps/home-hub/src/app/nutrition/hoy/{page,LiveTodayPanel}.tsx`, `dias/{page,LivePeriodPanel}.tsx`, `perfil/{page,LiveProfilePanel}.tsx`, `ayuda/page.tsx`
- Create: `apps/home-hub/e2e/nutrition-header.spec.ts`; modify `e2e/nutrition-days.spec.ts` (the tabs test)

**Interfaces:**
- Consumes: `DiaryDay`, `PeriodSummary`, `ProfileRead`, `TRIMESTERS`, `nutritionHref`, `berlinClock`.
- Produces:

```ts
// profile-chip.ts
export type ProfileChip = { kind: 'MODE'; label: string } | { kind: 'PROFILE' } | { kind: 'NONE' };
export const UNKNOWN_CHIP: ProfileChip;                                  // { kind: 'PROFILE' }
export function chipFrom(mode: 'GENERAL' | 'PREGNANCY', trimester: 1 | 2 | 3 | null, hasProfile: boolean): ProfileChip;
export function chipFromDay(day: DiaryDay): ProfileChip;                 // hasProfile = profileVersion !== null
export function chipFromPeriod(summary: PeriodSummary): ProfileChip;     // the last day's mode and trimester; hasProfile = summary.hasProfile
export function chipFromProfile(read: ProfileRead): ProfileChip;         // PRESENT -> chipFrom(mode, trimester, true); ABSENT -> NONE
// NutritionHeader.tsx ('use client')
export type NutritionView = 'home' | 'diary' | 'days' | 'profile' | 'detail' | 'help';
export function NutritionHeader(p: { view: NutritionView; chip?: ProfileChip; updatedAt?: string | null }): JSX.Element;
```

Header, top to bottom, for every view except `home`. The `home` view keeps today's greeting and switcher.
1. `<h1>Nutrición</h1>`, with the chip on the same row at its right.
   - The chip is `data-testid="profile-chip"` and links to `nutritionHref('/nutrition/perfil', person)`, followed by `CaretRight`.
   - Its label: `MODE` → `label`; `PROFILE` → `Perfil`; `NONE` → `Crear perfil` for the subject, or a plain `<span>` `Sin perfil` for a viewer.
   - On `view="profile"` it carries `aria-current="page"`.
2. The person switcher, only when `availableContexts.length > 1`. Its chips are ≥ 44 px tall: a scoped rule in `page.module.css`, so other pages are untouched.
3. `<nav aria-label="Nutrición">` with the links `Hoy` (`/nutrition/hoy`) and `Días` (`/nutrition/dias`). Each keeps `?person=`; the current one has `aria-current="page"`. Perfil is no longer a tab.
4. On `diary` and `days`, when `updatedAt` is not null: `Actualizado HH:MM` and `RetryButton label="Actualizar" pendingLabel="Actualizando…"`.

Placement:
- Each primary Live panel renders `<NutritionHeader …/>` above its panel: `LiveTodayPanel` (not when `compact`), `LivePeriodPanel` and `LiveProfilePanel`.
  - The chip comes from that panel's payload: `chipFromDay`, `chipFromPeriod` or `chipFromProfile`; on any error kind it is `UNKNOWN_CHIP`.
  - `updatedAt` is `berlinClock(new Date())`.
- Each page's Suspense fallback renders the same header with `UNKNOWN_CHIP` and `updatedAt={null}`.
- `/nutrition/ayuda` renders `view="help"` with `UNKNOWN_CHIP`.

- [ ] **Step 1: Write the failing unit tests**

```ts
test('chipFrom: pregnancy shows the trimester; a profile is Perfil; none is NONE', () => {
  assert.deepEqual(chipFrom('PREGNANCY', 2, true), { kind: 'MODE', label: 'Embarazo · 2.º trimestre' });
  assert.deepEqual(chipFrom('PREGNANCY', null, false), { kind: 'MODE', label: 'Embarazo' });
  assert.deepEqual(chipFrom('GENERAL', null, true), { kind: 'PROFILE' });
  assert.deepEqual(chipFrom('GENERAL', null, false), { kind: 'NONE' });
});
test('chips from the three payloads', ...);   // parseDayWire(PREGNANCY_DAY) -> MODE; parsePeriodWire(PERIOD_NO_PROFILE) -> NONE; ABSENT -> NONE
```

- [ ] **Step 2: Run them to see them fail; then implement `profile-chip.ts` until they pass**

Run: `cd apps/home-hub && npm test -- src/integration/nutrition/profile-chip.test.ts`

- [ ] **Step 3: Write the e2e tests**

New file `e2e/nutrition-header.spec.ts`:

```ts
test('the chip reads the mode from the page's own payload with no extra read', async ({ page, request }) => {
  const run = newRun();
  await signIn(page, 'days-pregnancy', run);
  await page.goto('/app/nutrition/dias');
  await expect(page.getByTestId('profile-chip')).toHaveText('Embarazo · 2.º trimestre');
  await expect(page.getByTestId('profile-chip')).toHaveAttribute('href', '/app/nutrition/perfil');
  const { mints, calls } = await observed(request, run);
  expect(mints).toBe(1);
  expect(calls).toHaveLength(1);
});
test('without a profile: "Crear perfil" for the person, "Sin perfil" without a link for a viewer', ...);
// days-no-profile: self -> link 'Crear perfil'; ?person=PSN-00007 -> text 'Sin perfil', getByRole('link', { name: 'Sin perfil' }) count 0
test('Perfil marks the chip as current; the Hoy · Días tabs keep ?person= and mark the current one', ...);
test('one person sees no switcher; two see it with chips at least 44 px tall', ...);   // signIn variant '-self-only'
test('Actualizado HH:MM and Actualizar on Hoy and Días, not on Perfil', ...);           // /Actualizado \d{2}:\d{2}/
test('the header at 390 px never scrolls sideways', ...);
```

In `nutrition-days.spec.ts`, rewrite `tabs Perfil · Hoy · Días…` to match the two tabs plus the chip.

- [ ] **Step 4: Implement the header and its placement in the three Live panels and four pages**

- [ ] **Step 5: Run `CHECKS`, then `E2E`**

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add apps/home-hub
git commit -m "feat(hub): one nutrition header with the profile chip, two tabs and Actualizado"
```

---

### Task 6: Weekly status panel for vitamins and minerals

**Files:**
- Modify: `apps/home-hub/src/integration/nutrition/live-subject.ts`, `live-subject.server.ts`, `live-subject.test.ts`
- Create: `apps/home-hub/src/components/features/nutrition/panel-error.ts`
- Create: `apps/home-hub/src/components/features/nutrition/weekly-model.ts`, `weekly-model.test.ts`
- Create: `apps/home-hub/src/components/features/nutrition/WeeklyStatus.tsx`, `WeeklyPanel.tsx`, `WeeklyPanel.module.css`
- Create: `apps/home-hub/src/app/nutrition/hoy/LiveWeeklyPanel.tsx`
- Modify: `apps/home-hub/src/app/nutrition/hoy/page.tsx`, `LiveTodayPanel.tsx`, `src/components/features/nutrition/TodayPanel.tsx` (the `weekly` slot only)
- Modify: `apps/home-hub/test-support/verify-adapter-callers.mjs`, `verify-adapter-callers.test.mjs`
- Modify: `apps/home-hub/e2e/nutrition-today.spec.ts`

**Interfaces:**
- Consumes:
  - `weeklyState`, `latestTarget`, `groupWeekly` and `WeeklyGroup` (Task 1);
  - `MICRONUTRIENTS` and `PeriodSummary` (Task 2);
  - `nutritionHref` (Task 4);
  - `readDiaryPeriod` and `RangeDays`.
- Produces:

```ts
// live-subject.ts: pickSubject's result gains
//   self: boolean                 // activeContext.personId === bootstrap.viewer.personId
//   linkPerson: string | null     // activeContext.personId when the URL carries `person`, else null
// panel-error.ts
export function panelError(code: SafeUIErrorCode | undefined): 'DENIED' | 'SESSION' | 'NOT_CONFIGURED' | 'INVALID' | 'UNAVAILABLE';
// weekly-model.ts
export interface WeeklyRow { code: Micronutrient; name: string; average: string; target: string | null; state: NutrientState; href: string }
export function microGroups(summary: PeriodSummary, range: RangeDays, person: string | null): WeeklyGroup<WeeklyRow>[];
export type WeeklyPanelModel =
  | { kind: 'LOADING' | 'DENIED' | 'SESSION' | 'UNAVAILABLE' | 'INVALID' | 'NOT_CONFIGURED' }
  | { kind: 'WEEK'; groups: WeeklyGroup<WeeklyRow>[] };
export function toWeeklyPanelModel(envelope: DataEnvelope<PeriodSummary>, person: string | null): WeeklyPanelModel; // range 7
export function weeklyOutcome(model: WeeklyPanelModel): string;   // model.kind
// WeeklyStatus.tsx (server): WeeklyStatus({ groups }: { groups: WeeklyGroup<WeeklyRow>[] })
// WeeklyPanel.tsx  (server): WeeklyPanel({ model, title }: { model: WeeklyPanelModel; title: string })
// LiveTodayPanel gains weekly?: ReactNode; TodayPanel gains weekly?: ReactNode, rendered after the day content.
```

Row content:
- `name` = `nutrientLabel(code)`.
- `average` = `amount(averageKnown, unit)` plus a space and `unitLabel(unit)`, where `unit` is the latest target's unit or `unitOf(code)`. It is `sin dato` when `averageKnown` is null.
- `target` = `targetValue(kind, displayValue, unit)`, or null.
- `state` = `weeklyState(average, latestTarget(days, code))`.
- `href` = `nutritionHref('/nutrition/nutriente/<code>', person, { rango: String(range) })`.

Rendering:
- Each group is a `<details>` whose `<summary>` (≥ 44 px) shows the group summary and `CaretRight`.
- When open, each row is a link holding the name, `media <average>`, `objetivo <target>` (left out when null), the state word and `detail`.
- `WeeklyPanel` is a `<section data-testid="weekly-panel" lang="es">` whose title is the `title` prop. Hoy passes `Vitaminas y minerales · últimos 7 días`.

Error copy:
- `LOADING`: `Cargando la semana…`
- `DENIED`: `No tienes acceso a este resumen.`
- `SESSION`: `Inicia sesión para ver el resumen.`
- `UNAVAILABLE`: `El resumen de la semana no responde ahora.`, with `RetryButton`
- `INVALID`: `No se pudo leer el resumen de la semana.`

`LiveWeeklyPanel`:
- It mirrors `LivePeriodPanel`: `resolveLiveSubject`, `readDiaryPeriod(subject.context, 7)`, one log line `nutrition.week outcome=<kind>`, catch-all to `UNAVAILABLE`.
- `hoy/page.tsx` passes it into `LiveTodayPanel` as `weekly={<Suspense fallback={<WeeklyPanel model={{ kind: 'LOADING' }} …/>}><LiveWeeklyPanel searchParams={params} /></Suspense>}`. The page imports the Live panel, never the adapter.

`PAIRS`: the period pair's `allowed` gains `src/app/nutrition/hoy/LiveWeeklyPanel.tsx`.

- [ ] **Step 1: Write the failing unit tests**

`live-subject.test.ts`: `self is true only for the viewer; linkPerson only when the URL names a person`.

`verify-adapter-callers.test.mjs`: `LiveWeeklyPanel may import period.server; LiveTodayPanel still may not`.

`weekly-model.test.ts` builds `summary = parsePeriodWire(PERIOD_WEEK_PREGNANCY)`:

```ts
test('the pregnancy week groups as Corto (4), Bien (3), Faltan datos (3)', () => {
  const g = microGroups(summary, 7, 'PSN-00007');
  assert.deepEqual(g.map((x) => x.summary), ['Corto: hierro, folato, vitamina D, colina', 'Bien: 3', 'Faltan datos: 3']);
  assert.deepEqual(g[0].items[0], { code: 'iron_mg', name: 'Hierro', average: '9,8 mg', target: '≥ 27 mg',
    state: { tone: 'caution', word: 'corto', detail: 'con 4 días' }, href: '/app/nutrition/nutriente/iron_mg?person=PSN-00007&rango=7' });
  assert.deepEqual(g[2].items.map((r) => r.state.word), ['faltan datos', 'pocos días (2)', 'pocos días (1)']); // B12, iodine, DHA
});
test('no targets at all: one Sin objetivo group with values only', ...);   // parsePeriodWire(PERIOD_THREE) -> ['Sin objetivo: 10'], average 'sin dato'
test('an unknown average reads sin dato, never 0', ...);
test('errors map to panel kinds', ...);   // 403 -> DENIED, 401 -> SESSION, INVALID_RESPONSE -> INVALID, other -> UNAVAILABLE
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd apps/home-hub && npm test -- src/components/features/nutrition/weekly-model.test.ts src/integration/nutrition/live-subject.test.ts test-support/verify-adapter-callers.test.mjs`
Expected: FAIL.

- [ ] **Step 3: Implement `panelError`, the `pickSubject` fields, the model, the components, `LiveWeeklyPanel`, the slot and the `PAIRS` entry**

- [ ] **Step 4: Write the e2e tests in `nutrition-today.spec.ts`**

Update the two existing trust tests: a Hoy render now makes two mints, and two calls sorted by path.

```ts
test('Hoy: two panels, two mints, one day GET and one 7-day period GET, no cookie, one bootstrap', async ({ page, request }) => {
  const run = newRun();
  await signIn(page, 'today-pregnancy', run);
  await page.goto('/app/nutrition/hoy');
  await expect(page.getByTestId('weekly-panel')).toContainText('Corto: hierro, folato, vitamina D, colina');
  const { mints, calls, bootstraps } = await observed(request, run);
  expect(mints).toBe(2);
  expect(bootstraps).toBe(1);
  expect([...calls].sort((a, b) => a.path.localeCompare(b.path))).toEqual([
    { path: '/diary/PSN-00001/days/today', hasCookie: false },
    { path: `/diary/PSN-00001/period?start=${berlinDaysAgo(6)}`, hasCookie: false },
  ]);
});
test('a vitamin group opens inline and each nutrient links to its detail', ...);   // click 'Corto…'; link /Hierro/ href '/app/nutrition/nutriente/iron_mg?rango=7'
test('each panel degrades on its own', ...);
// today-week-error: today-panel still shows 'Pan integral'; weekly-panel 'El resumen de la semana no responde ahora.'
// today-error: today-panel shows the day error; weekly-panel shows its groups
test('the weekly panel at 390 px never scrolls sideways', ...);
```

Change the refresh test (`today-updated`) to expect 4 mints after `Actualizar`.

- [ ] **Step 5: Run `CHECKS`, then `E2E`**

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add apps/home-hub
git commit -m "feat(hub): Hoy shows vitamins and minerals as a grouped weekly status"
```

---

### Task 7: Hoy day panel

**Files:**
- Modify: `apps/home-hub/src/components/features/nutrition/today-panel-model.ts`, `today-panel-model.test.ts` (rewrite)
- Modify: `apps/home-hub/src/components/features/nutrition/TodayPanel.tsx`, `TodayPanel.module.css` (rewrite)
- Create: `apps/home-hub/src/components/features/nutrition/StatusBar.tsx`, `StatusBar.module.css`
- Modify: `apps/home-hub/src/app/nutrition/hoy/LiveTodayPanel.tsx` (passes `subject.self` and `subject.linkPerson`), `src/app/page.tsx` (fallback only)
- Modify: `apps/home-hub/e2e/nutrition-today.spec.ts`

**Interfaces:**
- Consumes: `dayPhase`, `dayState`, `limitTarget`, `barFor`, `verdict`, `Bar`, `NutrientState` (Task 1); `HEADLINE_NUTRIENTS`, `DiaryItem.withFacts` (Task 2); `nutritionHref` (Task 4); the header wiring in `LiveTodayPanel` (Task 5); the `weekly` slot (Task 6).
- Produces:

```ts
export type HeadlineCode = HeadlineNutrient | 'free_sugars_g';
export interface HeadlineRow { code: HeadlineCode; name: string; amount: string | null; bar: Bar | null; state: NutrientState }
export interface MealLine { time: string; summary: string; items: { text: string; sugar: string; note: string | null }[] }
export type TodayPanelModel =
  | { kind: 'LOADING' | 'DENIED' | 'SESSION' | 'UNAVAILABLE' | 'INVALID' | 'NOT_CONFIGURED' }
  | { kind: 'TODAY'; verdict: string; rows: HeadlineRow[]; quietLine: string | null;
      profileHint: 'SELF' | 'VIEWER' | null; prenatalNote: string | null; meals: MealLine[];
      sources: { reference: string | null; attribution: string[] } };   // the chip stays in LiveTodayPanel (Task 5)
export function toTodayPanelModel(envelope: DataEnvelope<DiaryDay>, self: boolean): TodayPanelModel;
export function todayOutcome(model: TodayPanelModel): string;   // unchanged
// StatusBar.tsx: StatusBar({ bar, tone }: { bar: Bar; tone: Tone }), aria-hidden;
//   the track spans 0–150 %; tick at 100 %, band 90–110 %, cap line at 100 %;
//   the fill width is min(100%, calc(var(--bar-value) / var(--bar-scale) * 100% / 1.5)), and a null value draws no fill;
//   data-tone holds the tone and colours the fill from --olin-status-*.
// TodayPanel({ model, signInHref, compact?, weekly?, person? })
```

The model, decided here:
- Phase: `dayPhase(day.dayStatus, true)`; Hoy is always today.
- `rows`: energy, protein, fiber, then free sugars, always four.
  - Headline blocks use `dayState(block, phase)` and `barFor(block.target, block.known, phase)`.
  - Free sugars use `{ known: freeSugarsKnownG, status: sugarStatus, target: limit ? limitTarget(limit.valueG) : null, percent: null }`.
  - `amount`:
    - null on `NO_ENTRIES`;
    - `sin dato` when known is null;
    - `<amount(known)> de <amount(display)> <unitLabel>` with a target;
    - `<amount(known)> <unitLabel(unitOf(code))>` without one.
- `verdict`:
  - its `uncounted` is the largest `itemsUncounted` among the three headline blocks and the day's free-sugar `itemsUncounted`, when any of them is `PARTIAL`; otherwise 0;
  - the free-sugar `Headline` kind is `MAX`.
- `quietLine`: `Grasa <x> · Carbohidratos <y>`, where `<x>` is `amount + ' g'` or `sin dato`. It is null on `NO_ENTRIES`.
- `profileHint`: when `nutrients.energy_kcal.target` is null, `SELF` if `self`, else `VIEWER`.
  - `SELF` renders `ChatPrompt label="Copiar «Quiero crear mi perfil»" prompt="Quiero crear mi perfil" lead="Crea tu perfil en el chat para ver energía, proteína y fibra frente a tus objetivos."`.
  - `VIEWER` renders `Todavía no hay perfil completo.`
- `prenatalNote` (`PREGNANCY` only):
  - self: `Tu prenatal aún no se cuenta: folato, yodo, vitamina D y DHA pueden estar cubiertos.`;
  - viewer: `El prenatal aún no se cuenta: folato, yodo, vitamina D y DHA pueden estar cubiertos.`
- `meals`:
  - each entry gives `time` (the Berlin clock of `consumedAt`) and `summary`: `<time> · <labels joined with ', '>`.
  - Items keep today's `<label>, <portion>` text and `Azúcares libres: <x>` / `sin dato`.
  - `note`:
    - `facts: null` → `sin coincidencia en la base de alimentos`;
    - otherwise `sin datos de <spanishList of the missing names>`, where the missing names are the headline nutrients not in `withFacts`, plus `azúcares libres` when `freeSugarsG` is null;
    - else null.
- `sources`: today's reference line and attribution.

Screen, inside `data-testid="today-panel"` (`aria-label="Hoy"`):
1. Verdict `<p data-testid="verdict">`.
2. Four `data-testid="headline-row"` rows (`data-code`, `data-tone`), each with the name, the `amount`, `StatusBar` and the state word. A row without a bar keeps its height.
3. The quiet line.
4. The profile hint.
5. `{weekly}`.
6. The prenatal note.
7. `Comidas de hoy`. Each meal is a `<details>` whose summary is the meal summary (one line, ellipsis, ≥ 44 px); it opens to the items.
8. Footer: the link `¿Cómo anoto?` to `nutritionHref('/nutrition/ayuda', person)`, then `<details><summary>Fuentes</summary>` with the reference and attribution.

`compact` (the home card) renders only items 1–2 and `RetryButton label="Actualizar" pendingLabel="Actualizando…"`. Error kinds keep today's Spanish copy.

- [ ] **Step 1: Write the failing model tests**

`today-panel-model.test.ts` (rewrite) builds `day = parseDayWire(PREGNANCY_DAY)`:

```ts
test('four rows in fixed order with amounts, bars and words', () => {
  const m = today(toTodayPanelModel(ready(day), true));
  assert.deepEqual(m.rows.map((r) => r.code), ['energy_kcal', 'protein_g', 'fiber_g', 'free_sugars_g']);
  assert.deepEqual(m.rows[0], { code: 'energy_kcal', name: 'Energía', amount: '1.640 de 2.250 kcal',
    bar: { value: '1640.3', scale: '2241.6', mark: 'band' }, state: { tone: 'progress', word: 'en curso · faltan ~610 kcal', detail: null } });
  assert.equal(m.rows[2].state.word, 'bien');
  assert.deepEqual(m.rows[3], { code: 'free_sugars_g', name: 'Azúcares libres', amount: '12 de 50 g',
    bar: { value: '12.0', scale: '50', mark: 'cap' }, state: { tone: 'unknown', word: 'faltan datos', detail: null } });
  assert.equal(m.verdict, 'Vas en camino. Te falta proteína. Faltan datos de 2 alimentos.');
  assert.equal(m.quietLine, 'Grasa 58 g · Carbohidratos 190 g');
});
test('meals: one line per entry; notes for unmatched food and missing nutrients', () => {
  const m = today(toTodayPanelModel(ready(day), true));
  assert.deepEqual(m.meals.map((x) => x.summary), ['08:10 · Avena con leche, Plátano', '13:30 · Lentejas con arroz, Tarta casera']);
  assert.equal(m.meals[0].items[1].note, 'sin datos de fibra');
  assert.equal(m.meals[1].items[1].note, 'sin coincidencia en la base de alimentos');
});
test('an empty day keeps four rows with empty tracks and never shows 0', ...);   // EMPTY_DAY: 'Aún no has anotado nada hoy.', words 'Sin registros', bar.value null, quietLine null
test('without an energy target: values only, SELF hint for the person and VIEWER for others', ...); // NO_PROFILE_DAY: amount '436 kcal', bar null, verdict 'Día abierto. Faltan datos de 1 alimento.'
test('a consent viewer reads neutral copy and the neutral prenatal note', ...);   // 'Va en camino. Le falta proteína. Faltan datos de 2 alimentos.'
test('free sugars over the limit lead the verdict', ...);   // freeSugarsKnownG '55.0' -> 'Hoy te has pasado de azúcares libres. …'
test('energy far above its target: the real value, a raw bar value, an amber word', ...); // known '3400.0', percent '152' -> '3.400 de 2.250 kcal', 'por encima'
test('a GENERAL day has no prenatal note', ...);
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd apps/home-hub && npm test -- src/components/features/nutrition/today-panel-model.test.ts`
Expected: FAIL.

- [ ] **Step 3: Implement the model, `StatusBar`, `TodayPanel` and the `LiveTodayPanel` wiring**

- [ ] **Step 4: Rewrite the Hoy e2e tests in `nutrition-today.spec.ts`**

Keep Task 6's tests. Replace the remaining old-copy tests with these:

```ts
test('the first screen at 390×844 answers the day above the bottom nav', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await signIn(page, 'today-pregnancy', newRun());
  await page.goto('/app/nutrition/hoy');
  await expect(page.getByTestId('verdict')).toHaveText('Vas en camino. Te falta proteína. Faltan datos de 2 alimentos.');
  const rows = page.getByTestId('headline-row');
  await expect(rows).toContainText(['Energía', 'Proteína', 'Fibra', 'Azúcares libres']);
  await expect(rows.nth(0)).toContainText('1.640 de 2.250 kcal');
  await expect(rows.nth(0)).toContainText('en curso · faltan ~610 kcal');
  await expect(rows.nth(3)).toHaveAttribute('data-tone', 'unknown');
  const last = await rows.nth(3).boundingBox();
  expect(last!.y + last!.height).toBeLessThanOrEqual(844 - 60);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
});
test('a partial GENERAL day: words, no 0 anywhere', ...);   // today-partial: 'Te faltan proteína y fibra.', '12 de 60 g', not /(^|\D)0 (g|kcal)/
test('an empty day: four rows say Sin registros', ...);
test('a consent viewer sees neutral copy and no prompt', ...);
// today-no-profile ?person=PSN-00007: 'Todavía no hay perfil completo.', no button 'Copiar «Quiero crear mi perfil»'
// today-pregnancy ?person=PSN-00007: verdict starts 'Va en camino.', 'El prenatal aún no se cuenta'
test('pregnancy shows the prenatal note; a GENERAL day does not', ...);
test('a meal opens inline to its items and notes', ...);   // click '13:30 · Lentejas con arroz, Tarta casera'; 'sin coincidencia en la base de alimentos'
test('Fuentes is collapsed and holds the reference and the BLS attribution', ...);
test('¿Cómo anoto? links to /ayuda keeping ?person=', ...);
test('mobile Home shows the verdict and four rows, and reads only the day', ...); // /app at 390: calls == [day path], no 'Zumo'
```

Keep the denied, 500-retry and no-demo-banner tests with their existing copy.

- [ ] **Step 5: Run `CHECKS`, then `E2E`**

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add apps/home-hub
git commit -m "feat(hub): Hoy answers the day with a verdict and four fixed bars"
```

---

### Task 8: Días status grid

**Files:**
- Modify: `apps/home-hub/src/components/features/nutrition/period-panel-model.ts`, `period-panel-model.test.ts` (rewrite)
- Modify: `apps/home-hub/src/components/features/nutrition/PeriodPanel.tsx`, `PeriodPanel.module.css`
- Modify: `apps/home-hub/src/app/nutrition/dias/LivePeriodPanel.tsx` (passes `linkPerson`)
- Modify: `apps/home-hub/e2e/nutrition-days.spec.ts` (rewrite the content tests)

**Interfaces:**
- Consumes: `dayPhase`, `dayState`, `limitTarget`, `Tone` (Task 1); `weekdayInitial`, `dayOfMonth`, `weekdayDay`; `microGroups`, `WeeklyRow`, `WeeklyStatus` (Task 6); `HeadlineCode` (Task 7); `nutritionHref`.
- Produces:

```ts
export interface GridCell { tone: Tone; text: string }   // text: the state word, or the value for 'plain', for assistive tech
export interface GridRow { code: HeadlineCode; name: string; href: string; cells: GridCell[]; average: string | null } // average null when the grid has no Media column
export interface Grid { columns: { initial: string; day: string; date: string }[]; rows: GridRow[] }
export type PeriodPanelModel =
  | { kind: 'LOADING' | 'DENIED' | 'SESSION' | 'UNAVAILABLE' | 'INVALID' | 'NOT_CONFIGURED' }
  | { kind: 'PERIOD'; range: RangeDays; title: string; grids: Grid[]; micro: WeeklyGroup<WeeklyRow>[];
      profileHint: boolean };   // the chip stays in LivePeriodPanel (Task 5)
export function toPeriodPanelModel(envelope: DataEnvelope<PeriodSummary>, range: RangeDays, person: string | null): PeriodPanelModel;
export function periodOutcome(model: PeriodPanelModel): string;   // unchanged
```

The Días content, decided here:
- `title`: `Últimos N días`.
- The day whose `date === summary.end` is today, so its phase is `dayPhase(status, date === end)`.
- Rows are Energía, Proteína, Fibra and Azúcares libres. Free sugars use `limitTarget(freeSugars.limitG)` when `limitG` is not null.
- Each cell is `{ tone, text: state.word ?? <the value with its unit> }`; a plain cell with no value reads `sin dato`.
- Days are split into grids of 7 in date order (14 → 2 grids). Only the last grid carries the `Media` column.
  - `average` is `<amount> <unit>` (energy: `kcal`), or `sin dato` when `daysUsed` is 0.
- Row `href`: `nutritionHref('/nutrition/nutriente/<code>', person, { rango: String(range) })`.
- `micro`: `microGroups(summary, range, person)`, rendered by `WeeklyStatus` under the heading `Vitaminas y minerales · media`.
- Under the grids, keep only `La media usa solo días cerrados y completos.` The `Actividad y partidos` and `Patrones` cards and every "proyecto" text are removed.
- The no-profile hint and the error copy are unchanged.

Rendering:
- Each grid is a `<table>` with `<caption class="visually-hidden">`.
- Column headers show the initial over the day number. `Media` is the last header on the last grid.
- Row headers are links (the name, ≥ 44 px) to the detail page.
- Each cell is a status dot: `progress` → a neutral ring; `unclosed` → a grey ring; `empty` → a grey dash; `plain` → a hollow dot. Each cell also holds a `visually-hidden` span with `text`.
- No wrapper scrolls: the 7 day columns plus the name and `Media` fit 358 px.

- [ ] **Step 1: Write the failing model tests**

`period-panel-model.test.ts` (rewrite), built from the fixtures:

```ts
test('one 7-day grid: initials, day numbers, tones by phase, Media on the last grid', () => {
  const m = period(toPeriodPanelModel(ready(parsePeriodWire(PERIOD_WEEK_PREGNANCY)), 7, null));
  assert.equal(m.grids.length, 1);
  assert.deepEqual(m.grids[0].columns.map((c) => `${c.initial} ${c.day}`), ['X 18', 'J 19', 'V 20', 'S 21', 'D 22', 'L 23', 'M 24']);
  assert.deepEqual(m.grids[0].rows[0].cells.map((c) => c.tone), ['ok', 'caution', 'ok', 'caution', 'unclosed', 'empty', 'progress']);
  assert.deepEqual(m.grids[0].rows[0].cells.map((c) => c.text),
    ['bien', 'bajo', 'bien', 'por encima', 'sin cerrar', 'Sin registros', 'en curso · faltan ~610 kcal']);
  assert.equal(m.grids[0].rows[0].average, '2.246 kcal');
  assert.deepEqual(m.grids[0].rows[3].cells.slice(0, 4).map((c) => c.text), ['bien', 'pasado del límite', 'bien', 'faltan datos']);
});
test('14 days: two stacked grids, Media only on the second', ...);   // PERIOD_FOURTEEN: grids[0].rows[0].average null; grids[1] '2.246 kcal'
test('rows link to the nutrient detail for the same range, keeping the person', ...); // '/app/nutrition/nutriente/fiber_g?person=PSN-00007&rango=14'
test('the micronutrient groups follow the range', ...);
test('no profile: plain cells carry their values and the hint shows', ...);   // PERIOD_NO_PROFILE: tone 'plain', text '2.510 kcal', profileHint true
```

- [ ] **Step 2: Run them to see them fail; then implement the model and the panel until they pass**

Run: `cd apps/home-hub && npm test -- src/components/features/nutrition/period-panel-model.test.ts`

- [ ] **Step 3: Rewrite the Días e2e content tests**

Keep:
- the default-range trust test (one mint, one call with `start`, no cookie);
- the range-link test;
- the denied and error tests.

Replace the rest with:

```ts
test('the grid: four rows, a dot per day with its word for assistive tech, and the Media column', ...);
// days-pregnancy: columnheaders end with 'Media'; row 'Energía' cells text ['bien','bajo',…]; 'Media' cell '2.246 kcal'
test('an unclosed past day is a grey ring with "sin cerrar"; today open is a neutral ring', ...);
test('14 days at 390 px: two stacked grids, Media once, no sideways scroll', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await signIn(page, 'days-fourteen', newRun());
  await page.goto('/app/nutrition/dias?dias=14');
  await expect(page.getByTestId('period-panel').getByRole('table')).toHaveCount(2);
  await expect(page.getByRole('columnheader', { name: 'Media' })).toHaveCount(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
});
test('a row opens the nutrient detail for the same range', ...);   // link 'Fibra' href …/nutriente/fiber_g?rango=7
test('vitamins and minerals · media groups follow the selected range', ...);
test('no roadmap text: nothing mentions proyecto', ...);
```

- [ ] **Step 4: Run `CHECKS`, then `E2E`**

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add apps/home-hub
git commit -m "feat(hub): Días shows a status grid with averages and the weekly vitamins"
```

---

### Task 9: Nutrient detail page

**Files:**
- Create: `apps/home-hub/src/app/nutrition/nutriente/[code]/page.tsx`, `src/app/nutrition/nutriente/LiveNutrientPanel.tsx`
- Create: `apps/home-hub/src/components/features/nutrition/nutrient-detail-model.ts`, `nutrient-detail-model.test.ts`, `NutrientPanel.tsx`, `NutrientPanel.module.css`
- Modify: `apps/home-hub/src/components/features/nutrition/PeriodPanel.tsx` (`RangeLinks` signature), `src/app/nutrition/dias/page.tsx`
- Modify: `apps/home-hub/test-support/verify-adapter-callers.mjs`, `verify-adapter-callers.test.mjs`
- Create: `apps/home-hub/e2e/nutrition-nutrient.spec.ts`

**Interfaces:**
- Consumes: `dayPhase`, `dayState`, `weeklyState`, `latestTarget`, `limitTarget`, `barFor`, `StatusBar`, `panelError`, `parseRange`, `readDiaryPeriod`, `chipFromPeriod`, `nutritionHref`.
- Produces:

```ts
export const DETAIL_CODES: readonly (DayNutrient | 'free_sugars_g')[];   // DAY_NUTRIENTS then 'free_sugars_g'
export type DetailCode = (typeof DETAIL_CODES)[number];
export function detailCode(raw: string): DetailCode | null;
export interface DetailDay { day: string; value: string | null; bar: Bar | null; tone: Tone; note: string | null }
export type NutrientDetailModel =
  | { kind: 'LOADING' | 'DENIED' | 'SESSION' | 'UNAVAILABLE' | 'INVALID' | 'NOT_CONFIGURED' }
  | { kind: 'DETAIL'; name: string; average: string; target: string | null; state: NutrientState;
      days: DetailDay[]; targetLine: string | null; profileLink: { text: string; href: string } };   // LiveNutrientPanel renders the header with chipFromPeriod
export function toNutrientDetailModel(envelope: DataEnvelope<PeriodSummary>, code: DetailCode, self: boolean, person: string | null): NutrientDetailModel;
// RangeLinks({ range, path, param, person }: { range: RangeDays; path: string; param: 'dias' | 'rango'; person: string | null })
```

The detail content, decided here:
- `average`: `<amount> <unit>` or `sin dato`.
- `target`: `targetValue(…)` from `latestTarget`, or from `limitTarget` of the last non-null `freeSugars.limitG`.
- `state`: `weeklyState(averages[code], target)`.
- Each day (`day` = `weekdayDay(date)`), by phase:
  - `CLOSED` with known and a target → `bar = barFor(…)`, the tone of `dayState`, and `note` null;
  - `CLOSED` with known null → no bar, note `faltan datos`;
  - `OPEN_TODAY` → no bar, note `abierto`, value shown;
  - `OPEN_PAST` → no bar, note `sin cerrar`, value shown;
  - `NO_ENTRIES` → no bar, note `sin registros`, value null;
  - no target → no bar, note null, value shown.
- `targetLine`: MIN `Objetivo diario: al menos 27 mg.`; ABOUT `Objetivo diario: alrededor de 2.250 kcal.`; MAX `Límite diario: como máximo 50 g.`; null without a target.
- `profileLink`: `Ver de dónde sale en tu perfil` (self) or `Ver de dónde sale en su perfil`, linking to `nutritionHref('/nutrition/perfil', person)`. The period payload carries no source, so the link always shows.

Page:
- `params: Promise<{ code: string }>`; `detailCode(code) ?? notFound()`; `parseRange(searchParams.rango)`.
- The header uses `view="detail"`, rendered by `LiveNutrientPanel` (fallback: `UNKNOWN_CHIP`).
- `RangeLinks path="/nutrition/nutriente/<code>" param="rango"`. Días passes `path="/nutrition/dias" param="dias"`, so its links are unchanged.
- The Suspense key is `[person, code, range]`.
- MOCK renders `NutrientPanel` `NOT_CONFIGURED` (`La vista de nutriente solo funciona con datos reales.`). Other errors use Días's copy.
- Log: `nutrition.nutrient outcome=<kind>`.

`PAIRS`: the period pair's `allowed` gains `src/app/nutrition/nutriente/LiveNutrientPanel.tsx`.

- [ ] **Step 1: Write the failing tests**

```ts
test('energy over the pregnancy week: average, target, state; bars only on closed days', () => {
  const m = detail(toNutrientDetailModel(ready(parsePeriodWire(PERIOD_WEEK_PREGNANCY)), 'energy_kcal', true, null));
  assert.equal(m.name, 'Energía');
  assert.equal(m.average, '2.246 kcal');
  assert.equal(m.target, '≈ 2.250 kcal');
  assert.deepEqual(m.state, { tone: 'ok', word: 'bien', detail: 'con 4 días' });
  assert.deepEqual(m.days.map((d) => d.note), [null, null, null, null, 'sin cerrar', 'sin registros', 'abierto']);
  assert.deepEqual(m.days[0].bar, { value: '2105', scale: '2241.6', mark: 'band' });
  assert.equal(m.days[6].value, '1.640 kcal');
  assert.equal(m.targetLine, 'Objetivo diario: alrededor de 2.250 kcal.');
});
test('iron reads corto con 4 días against ≥ 27 mg', ...);
test('free sugars use the limit: cap marks and the Límite line', ...);   // 'Límite diario: como máximo 50 g.'
test('a viewer gets "Ver de dónde sale en su perfil"', ...);
test('detailCode accepts the 15 codes and free sugars only', ...);      // 'magnesium_mg' -> null, '../x' -> null
```

`verify-adapter-callers.test.mjs`: `LiveNutrientPanel may import period.server`.

- [ ] **Step 2: Run them to see them fail; then implement the model, panel, route and `PAIRS` entry until they pass**

Run: `cd apps/home-hub && npm test -- src/components/features/nutrition/nutrient-detail-model.test.ts test-support/verify-adapter-callers.test.mjs`

- [ ] **Step 3: Write the e2e tests in `e2e/nutrition-nutrient.spec.ts`**

```ts
test('detail: one mint, one period GET for the range, no cookie, no demo banner', ...); // ?rango=14 -> start berlinDaysAgo(13)
test('top: name, average against target with the state word; range links keep the person', ...);
test('a bar per closed day with the target mark; other days labelled by reason', ...);
test('an unknown nutrient code is 404', ...);   // request.get('/app/nutrition/nutriente/magnesium_mg') -> 404
test('free sugars show the limit line', ...);
test('the detail at 390 px never scrolls sideways', ...);
```

- [ ] **Step 4: Run `CHECKS`, then `E2E`**

Expected: all green. `test:server-boundary` proves `period.server` is reachable only from its three Live panels.

- [ ] **Step 5: Commit**

```bash
git add apps/home-hub
git commit -m "feat(hub): a detail page per nutrient with daily bars and the target mark"
```

---

### Task 10: Perfil restyle

**Files:**
- Modify: `apps/home-hub/src/integration/nutrition/profile-panel-model.ts`, `profile-panel-model.test.ts`
- Modify: `apps/home-hub/src/components/features/nutrition/ProfilePanel.tsx`, `ProfilePanel.module.css`
- Modify: `apps/home-hub/test-support/nutrition-fixtures.mjs` (`PRESENT.food.intolerances` becomes `lactosa; frutos secos`)
- Modify: `apps/home-hub/e2e/nutrition-profile.spec.ts`

**Interfaces:**
- Consumes: `ProfileRead`, `longDate`, `ChatPrompt`.
- Produces: the `PROFILE` variant changes:
  - it gains `dueDate: string | null` (`longDate`), and the `Fecha prevista de parto` row leaves `basics`;
  - `food` becomes `{ label: string; chips: string[] }[]`: the text is split on `,` and `;`, trimmed, and empty parts dropped; null gives `[]`.

  Every other field and every error kind is unchanged.

Screen, inside `data-testid="profile-panel"`:
1. Top: `Perfil de <name>`, the mode pill, and `Fecha prevista de parto` with its value when present.
2. `Objetivos diarios`: one row per target, with the label and the value (`≈`, `≥`, `≤`). Each row ends with a `<details>`:
   - its summary is an `Info` icon with the accessible name `De dónde sale: <label>`, ≥ 44 px;
   - its body is `source`, closed by default.
3. `targetsSince`, then `Faltan datos para…` followed by the `missing` lines (only when there are any), then `note`.
4. `Datos`: a `<dl>` with each label above its value at every width.
5. `Comida`: the three labels, each with its chips; `—` when there are none.
6. `Historial`: a `<details>` that is closed by default.
7. One `ChatPrompt label="Cambiar en el chat"` at the bottom, with the prompt `Quiero cambiar mi perfil: [dato] ahora es [valor]. Si es sobre la comida: [lo que me gusta, lo que no me gusta o intolerancias]. Muéstrame los objetivos nuevos antes de guardar.` It replaces the two per-card prompts.

There are no cards inside cards. The onboarding offer, `ABSENT` and every error state keep today's copy.

- [ ] **Step 1: Write the failing model tests**

`profile-panel-model.test.ts`:
- `the due date moves to the top and out of Datos`: `dueDate` `1 mar 2027`, and no `Fecha prevista de parto` in `basics`.
- `food text becomes chips split on commas and semicolons`: `['lactosa', 'frutos secos']`.
- `a 500-character food text without separators stays one chip`.

- [ ] **Step 2: Run them to see them fail; then implement the model and the panel until they pass**

Run: `cd apps/home-hub && npm test -- src/integration/nutrition/profile-panel-model.test.ts`

- [ ] **Step 3: Update the e2e tests in `nutrition-profile.spec.ts`**

- PRESENT:
  - `Fecha prevista de parto` and `1 mar 2027` appear before `Objetivos diarios`;
  - the energy source is hidden until `De dónde sale: Energía` is clicked;
  - `24 nov: perfil creado por chat` is hidden until `Historial` is opened;
  - exactly one `Cambiar en el chat` button;
  - chips `lactosa` and `frutos secos`;
  - every trust and secrets assertion is kept.
- `another subject's Perfil shows no chat prompts` is kept, now with the single button.
- `Perfil at 390 px never scrolls sideways` is kept.

- [ ] **Step 4: Run `CHECKS`, then `E2E`**

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add apps/home-hub
git commit -m "feat(hub): a readable Perfil with disclosures, chips and one chat prompt"
```

---

### Task 11: Finish: detector, screenshots, DESIGN.md, runbook, full chain

**Files:**
- Create: `apps/home-hub/e2e/review-capture.spec.ts`
- Modify: `apps/home-hub/.gitignore` (adds `/.impeccable/review/`)
- Modify: `apps/home-hub/DESIGN.md`
- Modify: `docs/runbooks/nutrition-profile-rollout.md` (section C6 and its checklist line)

**Interfaces:**
- Consumes: every route and scenario above.
- Produces:
  - screenshots in `apps/home-hub/.impeccable/review/`, which the controller passes to the finish reviewer;
  - the `detect --json` findings that remain.

- [ ] **Step 1: Run the detector**

From `apps/home-hub`:

`& "$IMP\scripts\impeccable.cmd" detect --json src/app/nutrition src/components/features/nutrition src/components/layout src/app/settings src/styles/tokens.css`

Fix the mechanical findings in files this plan changed. List the rest, each with one line on why it stays, in the task report.

- [ ] **Step 2: Write `e2e/review-capture.spec.ts`**

It is skipped unless `CAPTURE_REVIEW=1`. It sets the theme through `localStorage['olin.appearance.theme.v1']` in `addInitScript`, and writes:

| File | Scenario and route | Viewport |
| --- | --- | --- |
| `mobile.png` | `today-pregnancy`, `/app/nutrition/hoy` | 390×844, viewport only |
| `desktop.png` | `today-pregnancy`, `/app/nutrition/hoy` | 1440×900 |
| `hoy-<theme>-mobile.png` | `today-pregnancy`, Hoy, for each of the six theme ids | 390×844 |
| `dias-mobile.png` | `days-pregnancy` | 390, full page |
| `dias-14-mobile.png` | `days-fourteen`, `?dias=14` | 390, full page |
| `nutriente-mobile.png` | `days-pregnancy`, `/app/nutrition/nutriente/iron_mg` | 390, full page |
| `perfil-mobile.png` | `present` | 390, full page |
| `ayuda-mobile.png` | — | 390, full page |
| `hoy-desktop-full.png` | `today-pregnancy` | 1440, full page |

Run: `cd apps/home-hub && <build as in E2E> && CAPTURE_REVIEW=1 npx playwright test e2e/review-capture.spec.ts`
Expected: all the files above exist, and no screenshot shows a demo banner or a real name.

- [ ] **Step 3: Refresh `DESIGN.md` from the built code**

1. Frontmatter `colors`: add `status-caution`, `status-unknown` and `status-progress` (Warm values), and the changed `status-success` value if it changed.
2. `Colors > Role tokens`: list the three new tokens with their jobs (amber short or over, grey incomplete, neutral in progress). Add the named rule "Status words always carry a word; status colours reach 4.5:1 on the card, proved by `src/styles/status-tokens.test.ts`".
3. `Components`:
   - "Meters and progress" describes the status bar (0–150 % track, tick, band or cap, toned fill, CSS ratio);
   - "Chips and switchers" describes the badge-pair active chip with its ring;
   - "Navigation" lists the Spanish labels, the `ForkKnife` icon, and the current tab in text-main at 700 with a 3 px accent underline.
4. "Observed divergence": the live nutrition routes are now `/nutrition/hoy`, `/dias`, `/perfil`, `/nutriente/<code>` and `/ayuda`, and `/nutrition` redirects to Hoy.

- [ ] **Step 4: Update runbook C6**

Keep the runbook's existing person references, and add no new identifiers.
1. Intro: the routes above, and `SHA` = the merge commit of this redesign, which includes plan 3.
2. Step 5: also expect 307 for anonymous `/app/nutrition/hoy` and `/app/nutrition/nutriente/iron_mg`.
3. Step 6, phone checks:
   - the Home Screen shortcut opens Hoy;
   - the verdict and four bars fit the first screen;
   - the vitamins group opens and links to the detail page;
   - Días 7 and 14;
   - the detail page for one nutrient;
   - Perfil through the chip and through Ajustes;
   - an old `/app/nutrition` link lands on Hoy;
   - the cross-person check uses `/app/nutrition/hoy?person=` and `/app/nutrition/perfil?person=`.
4. Step 7: the outcome lines include `nutrition.week` and `nutrition.nutrient`.
5. Update the checklist line to match.

- [ ] **Step 5: Run the full chain**

Run: `cd apps/home-hub && npm test && npm run lint && node node_modules/typescript/bin/tsc --noEmit && npm run test:server-boundary`, then `E2E`.
Expected: all green; the e2e count is 70 plus this plan's tests, with `review-capture` skipped.

- [ ] **Step 6: Commit**

```bash
git add apps/home-hub/e2e/review-capture.spec.ts apps/home-hub/.gitignore apps/home-hub/DESIGN.md docs/runbooks/nutrition-profile-rollout.md
git commit -m "docs: status tokens in DESIGN.md, C6 phone checks for the redesigned nutrition pages"
```

Hand the screenshot paths, the remaining detector findings and the surface-brief path to the controller for the finish review.
