# Nutrition profile, plan 3 of 3: Hub views (Perfil, Hoy, Días) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ana and Erick see in the Home app everything their agent reads about their nutrition: the full profile with targets and sources (Perfil), today against the day's targets (Hoy), and several days side by side with averages (Días).

**Architecture:** Front end only. Nutrition (plan 1, live since 2026-11-24 on SHA 2ed0637) already returns the full profile (`GET /profile/{id}`, structured targets under `target_set`), per-day nutrient blocks (`GET /diary/{id}/days/today`, field `nutrients`) and periods (`GET /diary/{id}/period?start=`). The Hub widens two strict mappers, adds a third for periods, and renders three read-only pages. Each page render keeps today's trust model: one delegation minted at the BFF, one Nutrition call, no retries, the cookie never leaves for Nutrition.

**Tech Stack:** Next.js 16.3.5 (App Router, server components), React 19.2, TypeScript 5, CSS modules, `node --test` with `--experimental-strip-types`, Playwright with the fake BFF and fake Nutrition in `apps/home-hub/test-support/`.

**Spec:** `docs/superpowers/specs/2026-11-23-nutrition-profile-onboarding-design.md`, sections 6.10 (views), 6.11 (privacy), 7 (Hub tests and acceptance 2–6). Mockups (approved 2026-11-23): https://claude.ai/code/artifact/201a1534-dde6-4121-a878-f30c3f9b4b4a (private to the owner; example numbers). The controller reads it; the screens below carry its decisions.

## Global Constraints

- Read the guide in `apps/home-hub/node_modules/next/dist/docs/` before writing page or component code (`apps/home-hub/AGENTS.md`: this Next.js has breaking changes).
- Spanish labels, `lang="es"` on every new panel. Number format `es-ES`, thousands always grouped: `1.640`, `2.250` (es-ES does not group four-digit numbers by default; set grouping explicitly).
- Read-only. The Hub sends only `GET` to Nutrition. No form, no write.
- Per panel render: exactly one `POST /delegation?audience=svc-nutrition` to the BFF and one Nutrition `GET`, never retried. The `episteck_home_session` cookie goes only to the BFF.
- Every figure comes from Nutrition. The Hub sums, averages and calculates nothing; it only formats, clamps a `<meter>` to its maximum, and picks today's date in Europe/Berlin for the Días range.
- Unknown is never 0: no `0 g`, `0 kcal` or `0 %` for an unknown value. Unknown reads `sin dato`; a day without entries reads `sin registros todavía` (Hoy) or `—` (Días).
- References, not orders: no scores, grades, "debes", red/green judgement or "por encima" language for nutrients other than the existing free-sugar line.
- Mappers are strict: any malformed required field rejects the whole body (`INVALID` panel); unknown fields are ignored; a mapper copies exactly the fields its view shows.
- Logs: one line per panel render, fixed vocabulary (`nutrition.<view> outcome=<KIND>`), never IDs, names, dates, values or food text.
- Micronutrient targets appear in Perfil only, never in Hoy or Días.
- "Cambiar en el chat" and every copy-ready prompt appear only when the viewer is the subject (`activeContext.personId === viewer.id`, as `NutritionActions` does). Someone viewing another person's data through a consent grant sees no prompt.
- Phone width 390 px: the page never scrolls sideways; the Días table scrolls inside its own `overflow-x: auto` wrapper.
- Look: the existing warm Hub theme and per-component CSS modules (`ProfilePanel.module.css`, `TodayPanel.module.css` are the reference); layout as in the mockups (cards, tabs `Perfil · Hoy · Días`, pregnancy pill).
- Checks before every commit, from `apps/home-hub`: `npm test`, `npm run lint`, `npx tsc --noEmit`, `npm run test:server-boundary`. Before a task that touches e2e is done: `npm run build` then `npm run test:e2e`.

## Review Focus

1. A pregnancy-mode person who has not onboarded (only a `MODE` version: `onboarded: false`, mode and due date set, no energy or protein target). Perfil shows the mode, due date and trimester plus the onboarding offer, never "no profile"; Hoy shows the profile hint, not an energy line. Ana was in exactly this state for two hours on 2026-11-24. Tests: Task 2 (`a mode-only pregnancy profile…`), Task 4 (`no energy target shows the hint…`).
2. A viewer looking at someone else's data through a consent grant. No "Cambiar en el chat" and no copy-ready prompt: those would go to the viewer's own bot. Test: Task 3 e2e (`another subject's Perfil shows no chat prompts`).
3. Late evening in Berlin while the server runs in UTC. At 00:30 Berlin the Días range starts from the Berlin date, not the UTC one. Test: Task 5 (`periodStart uses the Berlin date after midnight`).
4. A known value far above its target (3.400 of 2.250 kcal). The text shows the real value, the meter is clamped, nothing says "too much". Test: Task 4 (`a value above its target…`).
5. Long free text in the profile (500-character preferences, a 120-character training note) on a 390 px phone, and a target for a nutrient the Hub has no label for. Text wraps without sideways scroll; the unknown nutrient gets a readable fallback label instead of an error. Tests: Task 2 (`an unknown nutrient…`), Task 3 e2e (`Perfil at 390 px…`), Task 1 (`text over the limits is rejected`).

---

### Task 1: Full profile contract and loader

**Files:**
- Modify: `apps/home-hub/src/integration/nutrition/profile-contract.ts`
- Modify: `apps/home-hub/src/integration/nutrition/profile-loader.ts` (type changes only)
- Modify: `apps/home-hub/src/integration/nutrition/profile.server.ts` (type changes only)
- Test: `apps/home-hub/src/integration/nutrition/profile-contract.test.ts`, `apps/home-hub/src/integration/nutrition/profile-loader.test.ts`

**Interfaces:**
- Produces (used by Tasks 2 and 3):

```ts
export type Mode = 'GENERAL' | 'PREGNANCY';
export type TargetKind = 'ABOUT' | 'MIN' | 'MAX';
export interface ProfileTarget {
  nutrient: string; value: string; displayValue: string; unit: string; kind: TargetKind;
  sourceOrg: string; sourceRef: string; explanation: string;
}
export interface ProfileInputsView {
  birthDate: string | null; age: number | null; sex: 'MALE' | 'FEMALE' | null;
  heightCm: string | null; weightKg: string | null; weightMeasuredOn: string | null;
  activityPal: string | null; trainingSessionsPerWeek: number | null; trainingNote: string | null;
  goal: 'MAINTAIN' | 'LOSE_FAT' | 'BUILD_MUSCLE' | 'PERFORMANCE' | null;
  prePregnancyWeightKg: string | null;
}
export interface NutritionProfile {
  version: number | null; validFrom: string; origin: string; onboarded: boolean;
  mode: Mode; dueDate: string | null; trimester: 1 | 2 | 3 | null;
  inputs: ProfileInputsView;
  food: { preferences: string | null; dislikes: string | null; intolerances: string | null };
  targets: { method: string; on: string; items: ProfileTarget[]; missing: { nutrient: string; fields: string[] }[] };
  history: { version: number; validFrom: string; origin: string; changed: string[] }[];
}
export type ProfileRead = { presence: 'PRESENT'; profile: NutritionProfile } | { presence: 'ABSENT' };
export function parseProfileWire(body: unknown): ProfileRead; // throws ProfileContractError
export function isAbsentProfileBody(body: unknown): boolean;  // unchanged
```

- `loadNutritionProfile(...)` and `readNutritionProfile(...)` now return `DataEnvelope<ProfileRead>` (was `DataEnvelope<ProfileSummary>`; `ProfileSummary` is removed). MOCK still returns `{ presence: 'ABSENT' }`.

Wire mapping (snake_case on the wire, from `services/nutrition/app/profile/service.py` `_view` and `app/main.py` `get_profile`): targets come from `target_set` (`method`, `on`, `items[]` with `nutrient`, `value`, `display_value`, `unit`, `kind`, `source_org`, `source_ref`, `explanation`; `missing[]` with `nutrient`, `fields`). The flat `targets` map, `context` and `target_source` are ignored from now on. `inputs.*`, `food.*`, `history[]` (`version`, `valid_from`, `origin`, `changed`) map one to one.

Validation rules (reject the whole body on any violation):
- dates `YYYY-MM-DD` (`/^\d{4}-\d{2}-\d{2}$/`); decimals as strings matching `/^\d+(\.\d+)?$/`; integers non-negative.
- `mode` in `GENERAL | PREGNANCY`; `trimester` in `1 | 2 | 3 | null`; `kind` in `ABOUT | MIN | MAX`; `sex`, `goal` in their enums or null; `origin` and `nutrient` codes match `/^[a-z0-9_]{1,40}$/` (nutrient) or `/^[A-Z_]{1,32}$/` (origin), so an unknown code passes and gets a fallback label later.
- text limits: `preferences`, `dislikes`, `intolerances` ≤ 500 chars; `training_note` ≤ 120; `explanation`, `source_org`, `source_ref` ≤ 300; at most 64 target items, 64 missing rows, 200 history rows.

- [ ] **Step 1: Rewrite the contract tests**

In `profile-contract.test.ts`, replace the "reads exactly three facts" tests with these (a `wire()` helper builds Ana's live body: PREGNANCY, trimester 2, `onboarded: true`, versions 1 `MODE` and 2 `PROFILE`, energy item `{nutrient:'energy_kcal', value:'2241.6', display_value:'2250', unit:'kcal', kind:'ABOUT', source_org:'Mifflin-St Jeor (1990); DGE/D-A-CH', source_ref:'Am J Clin Nutr 51(2):241-247', explanation:'Gasto en reposo (Mifflin-St Jeor) por actividad, más 250 kcal por el trimestre 2.'}`, plus `UNKNOWN_FIELD_SENTINEL: 'x'` at top level and inside `inputs`):

```ts
test('maps the full profile from target_set and ignores the flat targets map', () => {
  const read = parseProfileWire(wire());
  assert.equal(read.presence, 'PRESENT');
  const p = (read as Extract<ProfileRead, { presence: 'PRESENT' }>).profile;
  assert.equal(p.mode, 'PREGNANCY');
  assert.equal(p.trimester, 2);
  assert.equal(p.onboarded, true);
  assert.deepEqual(p.targets.items[0], { nutrient: 'energy_kcal', value: '2241.6', displayValue: '2250', unit: 'kcal',
    kind: 'ABOUT', sourceOrg: 'Mifflin-St Jeor (1990); DGE/D-A-CH', sourceRef: 'Am J Clin Nutr 51(2):241-247',
    explanation: 'Gasto en reposo (Mifflin-St Jeor) por actividad, más 250 kcal por el trimestre 2.' });
  assert.deepEqual(p.history.map((h) => h.origin), ['MODE', 'PROFILE']);
  assert.ok(!JSON.stringify(read).includes('UNKNOWN_FIELD_SENTINEL'));
});
test('a mode-only body (onboarded false, no energy target) is PRESENT, not ABSENT', ...);
test('an unknown target nutrient code passes the mapper', ...);           // nutrient 'magnesium_mg'
test('text over the limits is rejected', ...);                             // preferences 'a'.repeat(501), training_note 121 chars
test('malformed bodies are rejected', ...);                                // one case each: mode 'pregnancy', trimester 4,
                                                                           // kind 'TARGET', value '12,5', valid_from '24.11.2026',
                                                                           // missing target_set, history not an array
test('the no-profile body is ABSENT only when it is exactly {"detail":"no profile"}', ...); // keep the existing test
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd apps/home-hub && npm test -- src/integration/nutrition/profile-contract.test.ts`
Expected: FAIL (`profile` is undefined on the old `ProfileSummary`).

- [ ] **Step 3: Implement `parseProfileWire` and the types above in `profile-contract.ts`**

Keep `ProfileContractError`, `isPlainObject` and `isAbsentProfileBody`. Replace the file's header comment: the mapper now reads exactly the fields Perfil shows (spec 6.10 "Contract change").

- [ ] **Step 4: Update the loader and adapter types; update `profile-loader.test.ts`**

`profile-loader.ts` and `profile.server.ts` change only their types (`ProfileSummary` → `ProfileRead`). In `profile-loader.test.ts`, every fixture body becomes the new wire shape and every `{ presence: 'PRESENT', context, ... }` expectation becomes `{ presence: 'PRESENT', profile: ... }`. Status handling (200, 404 absent, 401, 403, 5xx, hang) and the one-mint-one-call assertions stay as they are.

- [ ] **Step 5: Keep the current panel compiling**

In `profile-panel-model.ts` only, switch the import to `ProfileRead` and map `PRESENT` to the existing `PRESENT` kind: `contextLabel` from `profile.mode`, `targetSourceLabel` `'Reference targets'`, `targetCount` = `profile.targets.items.length`. Adapt its test fixtures the same way. Task 2 replaces this file; this step only keeps every commit green.

- [ ] **Step 6: Run every check**

Run: `cd apps/home-hub && npm test && npm run lint && npx tsc --noEmit && npm run test:server-boundary`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add apps/home-hub/src/integration/nutrition
git commit -m "feat(hub): map the full nutrition profile body"
```

---

### Task 2: Perfil view model and shared Spanish formatting

**Files:**
- Create: `apps/home-hub/src/integration/nutrition/nutrition-format.ts`
- Create: `apps/home-hub/src/integration/nutrition/nutrition-format.test.ts`
- Modify: `apps/home-hub/src/integration/nutrition/profile-panel-model.ts`
- Modify: `apps/home-hub/src/components/features/nutrition/ProfilePanel.tsx` (a minimal `PROFILE` case only; Task 3 rewrites it)
- Test: `apps/home-hub/src/integration/nutrition/profile-panel-model.test.ts`

**Interfaces:**
- Consumes: `ProfileRead`, `NutritionProfile` (Task 1).
- Produces, in `nutrition-format.ts` (used by Tasks 2, 4, 5):

```ts
export function amount(decimal: string, unit: string): string;      // kcal: whole number; others: whole when >= 10, else 1 decimal
export function unitLabel(unit: string): string;                     // 'ug' -> 'µg'; others unchanged
export function nutrientLabel(code: string): string;                 // table below; unknown -> humanized ('magnesium_mg' -> 'Magnesium')
export function targetValue(kind: 'ABOUT' | 'MIN' | 'MAX', displayValue: string, unit: string): string; // '≈ 2.250 kcal', '≥ 60 g', '≤ 50 g'
export function fieldLabel(field: string): string;                   // table below; unknown -> humanized
export function shortDate(iso: string): string;                      // '2026-11-24' -> '24 nov'
export function longDate(iso: string): string;                       // '2027-04-12' -> '12 abr 2027'
export function weekdayDay(iso: string): string;                     // '2026-11-20' -> 'Jue 20'
export const TRIMESTERS: Record<1 | 2 | 3, string>;                  // '1.er trimestre', '2.º trimestre', '3.er trimestre'
```

Nutrient labels: `energy_kcal` Energía, `protein_g` Proteína, `fat_g` Grasa, `carb_g` Carbohidratos, `fiber_g` Fibra, `free_sugars_g` Azúcares libres, `calcium_mg` Calcio, `iron_mg` Hierro, `folate_ug` Folato, `vitamin_b12_ug` Vitamina B12, `vitamin_d_ug` Vitamina D, `iodine_ug` Yodo, `zinc_mg` Zinc, `selenium_ug` Selenio, `choline_mg` Colina, `dha_g` DHA.
Field labels: `birth_date` fecha de nacimiento, `sex` sexo, `height_cm` altura, `weight_kg` peso, `weight_measured_on` fecha del peso, `activity_pal` actividad diaria, `training_sessions_per_week` entrenamiento, `training_note` entrenamiento, `goal` objetivo, `pre_pregnancy_weight_kg` peso antes del embarazo, `due_date` fecha prevista de parto, `mode` modo, `preferences` preferencias, `dislikes` lo que no le gusta, `intolerances` intolerancias.
Dates are calendar dates: format them as UTC dates (`timeZone: 'UTC'`) so no zone shifts them by a day. `shortDate` and `longDate` drop the trailing period es-ES puts after month abbreviations; `weekdayDay` capitalises the weekday.

- Produces, in `profile-panel-model.ts` (used by Task 3):

```ts
export type ProfilePanelModel =
  | { kind: 'LOADING' | 'ABSENT' | 'DENIED' | 'UNAVAILABLE' | 'INVALID'; subjectName: string | null }
  | { kind: 'SESSION' } | { kind: 'NOT_CONFIGURED' }
  | {
      kind: 'PROFILE'; subjectName: string | null;
      modePill: string | null;                      // 'Embarazo · 2.º trimestre' | 'Embarazo' | null
      onboarded: boolean;
      basics: { label: string; value: string }[];
      food: { label: string; value: string }[];
      targets: { label: string; value: string; source: string }[];
      targetsSince: string;                         // 'vigentes desde 24 nov'
      missing: string[];                            // 'Energía: falta fecha de nacimiento, altura'
      note: string;
      history: string[];                            // newest first, at most 5
    };
export function toProfilePanelModel(envelope: DataEnvelope<ProfileRead>, subjectName: string | null): ProfilePanelModel;
export function outcomeLabel(envelope: DataEnvelope<ProfileRead>): string; // PRESENT | ABSENT | <error code> | UNEXPECTED
```

The `PROFILE` content, decided here:
- `basics`, in this order, a row only where it applies; a missing value reads `falta`:
  - `Edad` → `34 años`
  - `Sexo` (GENERAL only) → `Hombre` / `Mujer`
  - `Altura` → `165 cm`
  - `Peso` → `64 kg (20 nov)` (the date is `weightMeasuredOn`)
  - `Peso antes del embarazo` (PREGNANCY only) → `58 kg`
  - `Fecha prevista de parto` (PREGNANCY only) → `12 abr 2027`
  - `Actividad diaria` → `1.4` `Sobre todo sentado, poca actividad (1,4)`, `1.6` `Sentado, con algo de caminar o estar de pie (1,6)`, `1.8` `Sobre todo de pie o caminando (1,8)`, `2.0` `Trabajo físico intenso (2,0)`
  - `Entrenamiento` → `0` `Sin entrenamiento`; `1` `1 sesión por semana`; `n` `n sesiones por semana`; with a note, ` · <note>` is appended
  - `Objetivo` (GENERAL only) → `Mantener`, `Perder grasa`, `Ganar músculo`, `Rendimiento`
  - `Modo` → `General` / `Embarazo`
- `food`: `Preferencias`, `No le gusta`, `Intolerancias`; null reads `—`; text is shown as given.
- `targets`: in `DAY_NUTRIENTS` order with `free_sugars_g` after `fiber_g` (energy, protein, fat, carb, fiber, free sugars, then the micronutrients); unknown nutrients last. `value` = `targetValue(kind, displayValue, unit)`. `source` = the explanation without its final period, then ` · `, then `sourceOrg`; just `sourceOrg` when the explanation is empty. `sourceRef` is not shown (my call: it is a citation or URL that clutters a phone card; the explanation and organisation carry the "where from").
- `missing`: one line per missing row: `<nutrientLabel>: falta <fieldLabel, fieldLabel>`.
- `note`: GENERAL, or PREGNANCY in trimester 3 or unknown → `Si cambias tu peso o tu objetivo, los valores nuevos rigen desde ese día. Los días pasados se miden con los objetivos que tenían entonces.` PREGNANCY trimester 1 → `Al entrar en el 2.º trimestre, la energía sube sola (+250 kcal, DGE).` Trimester 2 → `Al entrar en el 3.er trimestre, la energía sube sola (+500 kcal, DGE).`
- `history`: `<shortDate>: <text>`, newest first, at most 5. The text:
  - the oldest `PROFILE` row → `perfil creado por chat`
  - a later `PROFILE` row → `perfil actualizado por chat (<up to 3 field labels, deduplicated>)`, plus `…` when more fields changed
  - `MODE` → `modo cambiado por chat`
  - `MIGRATED` → `perfil anterior importado`
  - any other origin → `cambio`
- Error kinds keep today's mapping (`ACCESS_DENIED` → `DENIED`, session codes → `SESSION`, etc.).

- [ ] **Step 1: Write the failing tests**

`nutrition-format.test.ts`:

```ts
test('amount groups thousands and rounds by unit', () => {
  assert.equal(amount('1640.3', 'kcal'), '1.640');
  assert.equal(amount('2250', 'kcal'), '2.250');
  assert.equal(amount('72.4', 'g'), '72');
  assert.equal(amount('2.35', 'mg'), '2,4');
  assert.equal(amount('17.0', 'g'), '17');
});
test('targetValue signs by kind and spells µg', () => {
  assert.equal(targetValue('ABOUT', '2250', 'kcal'), '≈ 2.250 kcal');
  assert.equal(targetValue('MIN', '60', 'g'), '≥ 60 g');
  assert.equal(targetValue('MAX', '50', 'g'), '≤ 50 g');
  assert.equal(targetValue('MIN', '550', 'ug'), '≥ 550 µg');
});
test('dates never shift by a day', () => {
  assert.equal(shortDate('2026-11-24'), '24 nov');
  assert.equal(longDate('2027-04-12'), '12 abr 2027');
  assert.equal(weekdayDay('2026-11-20'), 'Jue 20');
});
test('labels fall back to a readable form', () => {
  assert.equal(nutrientLabel('iodine_ug'), 'Yodo');
  assert.equal(nutrientLabel('magnesium_mg'), 'Magnesium');
  assert.equal(fieldLabel('pre_pregnancy_weight_kg'), 'peso antes del embarazo');
});
```

`profile-panel-model.test.ts` (replace the old tests; keep the error-mapping tests, adapted to `ProfileRead`). Fixtures `ana()` (PREGNANCY, trimester 2, onboarded, Ana-like inputs, history MODE then PROFILE both `2026-11-24`) and `erick()` (GENERAL, worked example of spec 6.3: 1984 birth, MALE, 180 cm, 82 kg measured 2026-11-23, PAL 1.6, 3 sessions, note `fútbol: 2 entrenos + 1 partido`, goal PERFORMANCE):

```ts
test('Ana: pregnancy pill, pregnancy rows, no goal or sex row, the trimester-2 note', () => {
  const m = profile(toProfilePanelModel(ready(ana()), 'Ana'));
  assert.equal(m.modePill, 'Embarazo · 2.º trimestre');
  assert.deepEqual(m.basics.map((b) => b.label),
    ['Edad', 'Altura', 'Peso', 'Peso antes del embarazo', 'Fecha prevista de parto', 'Actividad diaria', 'Entrenamiento', 'Modo']);
  assert.deepEqual(m.targets[0], { label: 'Energía', value: '≈ 2.250 kcal',
    source: 'Gasto en reposo (Mifflin-St Jeor) por actividad, más 250 kcal por el trimestre 2 · Mifflin-St Jeor (1990); DGE/D-A-CH' });
  assert.equal(m.note, 'Al entrar en el 3.er trimestre, la energía sube sola (+500 kcal, DGE).');
  assert.deepEqual(m.history, ['24 nov: perfil creado por chat', '24 nov: modo cambiado por chat']);
  assert.equal(m.targetsSince, 'vigentes desde 24 nov');
});
test('Erick: sex and goal rows, training with its note, no pill', () => {
  const m = profile(toProfilePanelModel(ready(erick()), 'Erick'));
  assert.equal(m.modePill, null);
  assert.ok(m.basics.some((b) => b.label === 'Objetivo' && b.value === 'Rendimiento'));
  assert.ok(m.basics.some((b) => b.label === 'Entrenamiento' && b.value === '3 sesiones por semana · fútbol: 2 entrenos + 1 partido'));
  assert.ok(m.basics.some((b) => b.label === 'Peso' && b.value === '82 kg (23 nov)'));
});
test('a mode-only pregnancy profile shows mode and due date, falta rows, missing targets and onboarded false', () => {
  // inputs all null except mode/due date; target_set: fiber + free sugars only; missing energy_kcal [birth_date, height_cm, pre_pregnancy_weight_kg, activity_pal]
  const m = profile(toProfilePanelModel(ready(modeOnly()), 'Ana'));
  assert.equal(m.onboarded, false);
  assert.equal(m.modePill, 'Embarazo · 2.º trimestre');
  assert.ok(m.basics.some((b) => b.label === 'Altura' && b.value === 'falta'));
  assert.deepEqual(m.missing, ['Energía: falta fecha de nacimiento, altura, peso antes del embarazo, actividad diaria']);
});
test('an unknown nutrient is listed last with a fallback label', ...);  // 'magnesium_mg' -> label 'Magnesium'
test('a later PROFILE version reads "perfil actualizado por chat (peso)"', ...);
test('food fields: null reads —, text is kept as given', ...);
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd apps/home-hub && npm test -- src/integration/nutrition/nutrition-format.test.ts src/integration/nutrition/profile-panel-model.test.ts`
Expected: FAIL (module `nutrition-format.ts` not found; `PROFILE` kind unknown).

- [ ] **Step 3: Implement `nutrition-format.ts`**

- [ ] **Step 4: Implement the new `profile-panel-model.ts`**

- [ ] **Step 5: Keep the panel compiling**

In `ProfilePanel.tsx`, replace the old `PRESENT` case with a minimal `PROFILE` case that renders the heading and the `basics` list; Task 3 rewrites the panel. The e2e profile tests go red here on purpose (English copy, old content) and Task 3 updates them; do not run e2e in this task.

- [ ] **Step 6: Run every check**

Run: `cd apps/home-hub && npm test && npm run lint && npx tsc --noEmit && npm run test:server-boundary`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add apps/home-hub/src/integration/nutrition apps/home-hub/src/components/features/nutrition/ProfilePanel.tsx
git commit -m "feat(hub): model Perfil in Spanish with shared nutrition formatting"
```

---

### Task 3: Perfil page

**Files:**
- Modify: `apps/home-hub/src/components/features/nutrition/ProfilePanel.tsx`, `ProfilePanel.module.css`
- Create: `apps/home-hub/src/components/features/nutrition/ChatPrompt.tsx` (client), `ChatPrompt.module.css`
- Modify: `apps/home-hub/src/components/features/nutrition/NutritionActions.tsx` (use `ChatPrompt`'s copy logic; behaviour unchanged)
- Modify: `apps/home-hub/test-support/fake-nutrition.mjs`
- Modify: `apps/home-hub/e2e/nutrition-profile.spec.ts`

**Interfaces:**
- Consumes: `ProfilePanelModel` (Task 2).
- Produces: `ChatPrompt({ label, prompt }: { label: string; prompt: string })`, a client component. It renders nothing unless `activeContext.personId === viewer.id` (from `useAppContext()`), otherwise a button that copies `prompt` to the clipboard and announces `Mensaje copiado. Pégalo en tu chat de Nutrición.` or, when the clipboard refuses, `Selecciona el texto para copiarlo.` with the prompt shown as selectable text. Task 4 uses it too.

Screen (mockup "Perfil"), top to bottom inside `data-testid="profile-panel"`, `lang="es"`:
- `<h2>`: `Perfil de <name>` (null name: `Perfil`) plus the `modePill` as a pill when not null.
- When `onboarded` is false, before the cards: the text `Todavía no hay perfil completo. Tu bot te hace unas ocho preguntas y calcula tus objetivos.` and `ChatPrompt` with label `Copiar «Quiero crear mi perfil»` and prompt `Quiero crear mi perfil`.
- Card `Datos básicos` (a `<dl>` of `basics`) with `ChatPrompt` label `Cambiar en el chat`, prompt `Quiero cambiar mi perfil: [dato] ahora es [valor]. Muéstrame los objetivos nuevos antes de guardar.`
- Card `Comida` (a `<dl>` of `food`) with `ChatPrompt` label `Cambiar en el chat`, prompt `Quiero cambiar mis preferencias de comida: [lo que me gusta, lo que no me gusta o intolerancias]. Muéstramelo antes de guardar.`
- Card `Objetivos diarios` with `targetsSince` at the right; one row per target: label, value (tabular figures, right-aligned), source line below; then each `missing` line; then `note`.
- Card `Historial` with the `history` lines.
- `ABSENT`: `<h2>` `Sin perfil de nutrición`, the text `Tu bot te hace unas ocho preguntas y calcula tus objetivos.` and the same `Quiero crear mi perfil` `ChatPrompt`.
- Error and loading kinds in Spanish:
  - `LOADING` → `Cargando el perfil…`
  - `DENIED` → `Acceso restringido` / `No tienes acceso al perfil de nutrición de <name or esta persona>.`
  - `SESSION` → `Tu sesión ha caducado` with the link `Iniciar sesión`
  - `UNAVAILABLE` → `Nutrición no responde ahora` / `No se muestra nada antes que adivinar.` with `RetryButton label="Reintentar" pendingLabel="Reintentando…"`
  - `INVALID` → `No se pudo mostrar el perfil con seguridad` with the same retry
  - `NOT_CONFIGURED` → `Nutrición no está configurada en este Hub`

The fake Nutrition's `present` scenario returns Ana's full view body (Task 1's `wire()` shape, including `targets` flat map, `context`, `target_source` and `UNKNOWN_FIELD_SENTINEL`). Add a `mode-only` scenario (Review Focus 1) and a `long-text` scenario (500-character preferences, 120-character training note). The fake BFF's existing two-subject scenario gives a second person the viewer may see (Review Focus 2); if it has none, add one following the pattern of `today-two-subjects`.

- [ ] **Step 1: Update the e2e tests**

In `e2e/nutrition-profile.spec.ts`:
- Every English assertion moves to the Spanish copy above (`Access restricted` → `Acceso restringido`, `Try again` → `Reintentar`, and so on).
- The minimization test becomes:

```ts
test('PRESENT shows the full profile, nothing unknown, one mint, one call, no secrets', async ({ page, request }) => {
  // ...same sign-in, observed() and CSP/no-store checks as today...
  await expect(panel(page)).toContainText('Embarazo · 2.º trimestre');
  await expect(panel(page)).toContainText('≈ 2.250 kcal');
  await expect(panel(page)).toContainText('vigentes desde 24 nov');
  await expect(panel(page)).toContainText('24 nov: perfil creado por chat');
  expect(await page.content()).not.toContain('UNKNOWN_FIELD_SENTINEL');
  expect(mints).toBe(1);
  expect(calls).toEqual([{ path: '/profile/PSN-00001', hasCookie: false }]);
});
```

- New tests:
  - `a mode-only profile offers onboarding and still shows the due date`
  - `ABSENT offers the copy-ready "Quiero crear mi perfil"` (click the button, read the clipboard with `context.grantPermissions(['clipboard-read','clipboard-write'])`)
  - `another subject's Perfil shows no chat prompts`: no button named `Cambiar en el chat` or `Copiar «Quiero crear mi perfil»`
  - `Perfil at 390 px never scrolls sideways`: `long-text` scenario, viewport 390×844, `document.scrollingElement.scrollWidth <= document.scrollingElement.clientWidth`
  - The `PRIVATE_PREF_SENTINEL` and `PRIVATE_DISLIKE_SENTINEL` fixture values are now shown on purpose. Remove them from `SECRETS` and assert they appear under `Comida`.

- [ ] **Step 2: Build and run to see them fail**

Run: `cd apps/home-hub && npm run build && npx playwright test e2e/nutrition-profile.spec.ts`
Expected: FAIL on the new Spanish copy and the new content.

- [ ] **Step 3: Implement `ChatPrompt`, the new `ProfilePanel` and its CSS; switch `NutritionActions` to `ChatPrompt`'s copy logic**

- [ ] **Step 4: Run every check**

Run: `cd apps/home-hub && npm test && npm run lint && npx tsc --noEmit && npm run test:server-boundary && npm run build && npm run test:e2e`
Expected: all pass, including the unchanged `nutrition-today.spec.ts`.

- [ ] **Step 5: Commit**

```bash
git add apps/home-hub
git commit -m "feat(hub): Perfil shows the whole nutrition profile with targets and sources"
```

---

### Task 4: Hoy against the day's targets

**Files:**
- Modify: `apps/home-hub/src/integration/nutrition/diary-contract.ts`, `diary-contract.test.ts`, `diary-loader.ts` (`emptyDay()` only), `diary-loader.test.ts` (fixtures)
- Modify: `apps/home-hub/src/components/features/nutrition/today-panel-model.ts`, `today-panel-model.test.ts`, `TodayPanel.tsx`, `TodayPanel.module.css`
- Modify: `apps/home-hub/test-support/fake-nutrition.mjs`, `apps/home-hub/e2e/nutrition-today.spec.ts`

**Interfaces:**
- Consumes: `amount`, `nutrientLabel`, `unitLabel` (Task 2); `ChatPrompt` (Task 3).
- Produces, in `diary-contract.ts` (used by Task 5):

```ts
export type DayNutrient = 'energy_kcal' | 'protein_g' | 'fiber_g';
export const DAY_NUTRIENTS_SHOWN: readonly DayNutrient[] = ['energy_kcal', 'protein_g', 'fiber_g'];
export interface NutrientBlock {
  known: string | null; itemsTotal: number; itemsUncounted: number; status: 'NONE' | 'KNOWN' | 'PARTIAL';
  target: { value: string; displayValue: string; unit: string; kind: 'ABOUT' | 'MIN' | 'MAX' } | null;
  percent: string | null;
}
export function parseNutrientBlock(raw: unknown, what: string): NutrientBlock;
// DiaryDay gains:
//   profileVersion: number | null;                      // profile_version
//   nutrients: Record<DayNutrient, NutrientBlock>;      // the three shown, from day.nutrients
```

Wire: `nutrients.<code>` = `{known, items_total, items_uncounted, status, target: {value, display_value, unit, kind} | null, percent}` (`services/nutrition/app/diary/nutrients.py` `nutrient_blocks`). `nutrients` and its three keys are required; other nutrient keys are ignored (micronutrients stay out of Hoy).

`TodayPanelModel`'s `TODAY` variant gains:

```ts
nutrientLines: { label: string; line: string; meter: { value: number; max: number } | null }[];
profileHint: boolean; // true when the energy target is null
```

- One line per shown nutrient whose `target` is not null, in the order energy, protein, fiber:
  - `NO_ENTRIES` day → `<Label>: sin registros todavía`, no meter
  - `known` null → `<Label>: sin dato`, no meter
  - otherwise `<Label>: <amount(known)> de <amount(target.displayValue)> <unitLabel(unit)>`, with ` (<n> sin contar)` appended when `PARTIAL`; meter `{ value: min(Number(known), Number(target.value)), max: Number(target.value) }`
- The free-sugar line, meter, status line and meal list stay exactly as today.
- With `profileHint`, the panel shows `Crea tu perfil en el chat para ver energía, proteína y fibra frente a tus objetivos.` and `ChatPrompt` `Copiar «Quiero crear mi perfil»`.

- [ ] **Step 1: Write the failing tests**

`diary-contract.test.ts`: `maps the three shown nutrient blocks and profile_version`; `rejects a day without nutrients or with a bad block` (missing `nutrients`; `status: 'UNKNOWN'`; `known: '1,5'`; `target.kind: 'GOAL'`).

`today-panel-model.test.ts` (extend the `day()` fixture with `profileVersion: 2` and three blocks; energy target `{value:'2241.6', displayValue:'2250', unit:'kcal', kind:'ABOUT'}`):

```ts
test('energy, protein and fiber read against the day target', () => {
  const m = today(toTodayPanelModel(ready(day({ nutrients: blocks({ energy: '1640.3', protein: '72.4', fiber: '14.0' }) }))));
  assert.deepEqual(m.nutrientLines.map((l) => l.line),
    ['Energía: 1.640 de 2.250 kcal', 'Proteína: 72 de 60 g', 'Fibra: 14 de 30 g']);
  assert.deepEqual(m.nutrientLines[0].meter, { value: 1640.3, max: 2241.6 });
  assert.equal(m.profileHint, false);
});
test('a value above its target shows the real value and clamps the meter', () => {
  const m = today(toTodayPanelModel(ready(day({ nutrients: blocks({ energy: '3400.0' }) }))));
  assert.equal(m.nutrientLines[0].line, 'Energía: 3.400 de 2.250 kcal');
  assert.deepEqual(m.nutrientLines[0].meter, { value: 2241.6, max: 2241.6 });
  assert.ok(!/por encima|demasiado|debes/i.test(JSON.stringify(m.nutrientLines)));
});
test('partial and unknown nutrients never read 0', ...);   // PARTIAL -> 'Energía: 1.640 de 2.250 kcal (1 sin contar)'; known null -> 'Energía: sin dato'
test('an empty day reads "sin registros todavía" per nutrient', ...);
test('no energy target shows the hint and no energy line', ...); // energy and protein target null, fiber target present -> only the fiber line, profileHint true
```

`e2e/nutrition-today.spec.ts`: the fake's day fixtures gain `profile_version` and `nutrients` (EMPTY_DAY with null knowns; PARTIAL_DAY energy `436.0` of target `2250`, fiber `PARTIAL`). New assertions: `Energía: 436 de 2.250 kcal`; no `0 kcal` or `0 g`; a `today-no-profile` scenario shows the hint and no `Energía:` line.

- [ ] **Step 2: Run them to see them fail**

Run: `cd apps/home-hub && npm test -- src/integration/nutrition/diary-contract.test.ts src/components/features/nutrition/today-panel-model.test.ts`
Expected: FAIL (`nutrients` not mapped; `nutrientLines` undefined).

- [ ] **Step 3: Implement the contract, the model and the panel**

The nutrient lines go under the free-sugar line inside the existing overview, each a `<p>` with a `<meter>` like the sugar meter (meter `aria-label` = the line). Compact mode (the home page card) shows them too.

- [ ] **Step 4: Run every check**

Run: `cd apps/home-hub && npm test && npm run lint && npx tsc --noEmit && npm run test:server-boundary && npm run build && npm run test:e2e`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add apps/home-hub
git commit -m "feat(hub): Hoy shows energy, protein and fiber against the day's targets"
```

---

### Task 5: Días page, tabs and range

**Files:**
- Create: `apps/home-hub/src/integration/nutrition/period-contract.ts`, `period-contract.test.ts`
- Create: `apps/home-hub/src/integration/nutrition/period-range.ts`, `period-range.test.ts`
- Create: `apps/home-hub/src/integration/nutrition/period-loader.ts`, `period-loader.test.ts`
- Create: `apps/home-hub/src/integration/nutrition/period.server.ts`
- Create: `apps/home-hub/src/components/features/nutrition/period-panel-model.ts`, `period-panel-model.test.ts`, `PeriodPanel.tsx`, `PeriodPanel.module.css`
- Create: `apps/home-hub/src/app/nutrition/dias/page.tsx`, `apps/home-hub/src/app/nutrition/dias/LivePeriodPanel.tsx`
- Modify: `apps/home-hub/src/app/nutrition/NutritionHeader.tsx` (tabs), `apps/home-hub/src/app/nutrition/page.module.css`
- Modify: `apps/home-hub/src/app/layout.tsx:78` (`liveRoutes` gains `'/nutrition/dias'`)
- Modify: `apps/home-hub/test-support/verify-adapter-callers.mjs` (a third pair)
- Modify: `apps/home-hub/test-support/fake-nutrition.mjs`
- Create: `apps/home-hub/e2e/nutrition-days.spec.ts`

**Interfaces:**
- Consumes: `parseNutrientBlock`, `NutrientBlock`, `DayNutrient`, `DAY_NUTRIENTS_SHOWN` (Task 4); `amount`, `unitLabel`, `weekdayDay` (Task 2); `mintNutritionDelegation`, `readJson`, `readyEnvelope`, `failedEnvelope`, `DELEGATION_HEADER`, `PERSON_ID` (`nutrition-delegation.ts`); `resolveLiveSubject` (`live-subject.server.ts`).
- Produces:

```ts
// period-contract.ts
export interface PeriodDay {
  date: string; dayStatus: 'NO_ENTRIES' | 'OPEN' | 'COMPLETE'; mode: 'GENERAL' | 'PREGNANCY'; trimester: 1 | 2 | 3 | null;
  nutrients: Record<DayNutrient, NutrientBlock>;
  freeSugars: { known: string | null; itemsUncounted: number; status: 'NONE' | 'KNOWN' | 'PARTIAL'; limitG: string | null; percent: string | null };
}
export interface PeriodAverage {
  averageKnown: string | null; averagePercent: string | null; daysUsed: number;
  leftOut: { open: number; noEntries: number; partial: number };
}
export type AveragedNutrient = DayNutrient | 'free_sugars_g';
export interface PeriodSummary { start: string; end: string; hasProfile: boolean; days: PeriodDay[]; averages: Record<AveragedNutrient, PeriodAverage> }
export function parsePeriodWire(body: unknown): PeriodSummary;   // throws TypeError; 1..31 days

// period-range.ts
export type RangeDays = 3 | 7 | 14;
export function parseRange(raw: string | string[] | undefined): RangeDays;   // '3' | '7' | '14', else 7
export function berlinDate(now: Date): string;                              // 'YYYY-MM-DD' in Europe/Berlin
export function periodStart(days: RangeDays, now: Date): string;            // berlinDate(now) minus (days - 1) days

// period-loader.ts (same option shape as LoadDiaryTodayOptions, plus start)
export async function loadDiaryPeriod(o: LoadDiaryTodayOptions & { start: string }): Promise<DataEnvelope<PeriodSummary>>;
// GET /diary/{id}/period?start=<start>; status mapping as loadDiaryToday (400 -> INVALID_RESPONSE); MOCK -> NOT_CONFIGURED envelope

// period.server.ts
export async function readDiaryPeriod(context: F3ActiveContext, days: RangeDays): Promise<DataEnvelope<PeriodSummary>>;
// assertIssuedContext(context) first, then cookies(), exactly like diary.server.ts; start = periodStart(days, new Date())

// period-panel-model.ts
export type Cell = { value: string; detail: string | null; unknown: boolean };
export type PeriodRow = { day: string; status: string | null; tone: 'ok' | 'open' | 'none' | null; cells: [Cell, Cell, Cell, Cell] };
export type PeriodPanelModel =
  | { kind: 'LOADING' | 'DENIED' | 'SESSION' | 'UNAVAILABLE' | 'INVALID' | 'NOT_CONFIGURED' }
  | { kind: 'PERIOD'; range: RangeDays; title: string; rows: PeriodRow[]; average: PeriodRow; profileHint: boolean };
export function toPeriodPanelModel(envelope: DataEnvelope<PeriodSummary>, range: RangeDays): PeriodPanelModel;
```

The Días content, decided here:
- `title` is `Últimos <n> días`. Rows are in date order, as Nutrition returns them.
- Columns: `Día`, `Energía`, `Prot.`, `Fibra`, `Azúcares`. The cells follow the column order.
- Day cell: `weekdayDay(date)`, plus a status pill:
  - `COMPLETE` → `Cerrado`, tone `ok`
  - `OPEN` → `Abierto`, tone `open`
  - `NO_ENTRIES` → `Sin registros`, tone `none`
- Nutrient cells:
  - `NO_ENTRIES` day → `{ value: '—', detail: null, unknown: false }`
  - `known` null → `{ value: 'sin dato', detail: null, unknown: true }`
  - otherwise the value is `amount(known, unit)`: no unit for energy (`2.510`), ` g` after grams (`98 g`)
  - `detail` is `<percent> %` when `percent` is not null, plus ` · parcial` when `PARTIAL` (just `parcial` without a percent)
- The free-sugar cell uses the `freeSugars` block the same way.
- The average row has day `Media`, status null, tone null. Per cell:
  - `daysUsed` 0 → `{ value: 'sin dato', detail: null, unknown: true }`
  - otherwise the value is `amount(averageKnown)` with the same unit rule
  - `detail` is `<averagePercent> % · ` when present, then `<n> día` or `<n> días` (days used)
- Under the table, always: `La media usa solo días cerrados y completos. Un día abierto o un dato que falta se muestra tal cual, nunca como 0.`
- `profileHint` (`!hasProfile`) shows `Sin perfil no hay objetivos con que comparar.` and the `Quiero crear mi perfil` `ChatPrompt`.
- Range links `3 días`, `7 días`, `14 días` go to `?dias=<n>` and keep `person` when it is in the URL. The active one has `aria-current="page"`.
- Two dashed placeholder cards after the table, always:
  - `Actividad y partidos` — `Llega con el registro de salud (proyecto 2).`
  - `Patrones` — `Llega en el proyecto 3, para que los confirmes o descartes.`
- MOCK mode: `PeriodPanel` `NOT_CONFIGURED` reads `La vista Días solo funciona con datos reales.` (as Hoy does). Other error kinds use Hoy's Spanish copy with `diario` → `historial de días`.
- Log line: `nutrition.period outcome=<kind>`.
- The page is keyed like Hoy: `<Suspense key={JSON.stringify([params.person ?? null, range])}>`.

Tabs: `NutritionHeader` takes `view: 'home' | 'profile' | 'diary' | 'days'`. For the three nutrition views the heading is `Nutrición`, and a `nav aria-label="Nutrición"` holds the links `Perfil` (`/nutrition`), `Hoy` (`/nutrition/hoy`) and `Días` (`/nutrition/dias`). Each link keeps `?person=` as today, and the current one has `aria-current="page"`. The `Acciones en Telegram` link stays, on Hoy only. Tests and selectors that relied on the old heading `Perfil y objetivos` move to `Nutrición`.

Boundary check: add `{ name: 'period', adapter: 'src/integration/nutrition/period.server.ts', loader: 'src/integration/nutrition/period-loader.ts', adapterPattern: /period\.server/, loaderPattern: /period-loader/, allowed: ['src/app/nutrition/dias/LivePeriodPanel.tsx'] }` to `PAIRS`.

- [ ] **Step 1: Write the failing unit tests**

```ts
// period-range.test.ts
test('parseRange accepts 3, 7, 14 and falls back to 7', () => {
  assert.equal(parseRange('3'), 3); assert.equal(parseRange('14'), 14);
  assert.equal(parseRange('30'), 7); assert.equal(parseRange(['3', '14']), 7); assert.equal(parseRange(undefined), 7);
});
test('periodStart uses the Berlin date after midnight', () => {
  const now = new Date('2026-11-24T23:30:00Z'); // 00:30 on the 25th in Berlin
  assert.equal(berlinDate(now), '2026-11-25');
  assert.equal(periodStart(3, now), '2026-11-23');
  assert.equal(periodStart(7, new Date('2026-03-29T12:00:00Z')), '2026-03-23'); // across the DST change
});

// period-panel-model.test.ts (fixture: 3 days, 20 COMPLETE, 21 COMPLETE with free sugars unknown, 22 OPEN; averages energy 2 days 85 %)
test('rows, cells and the average row', () => {
  const m = period(toPeriodPanelModel(ready(threeDays()), 3));
  assert.equal(m.title, 'Últimos 3 días');
  assert.deepEqual(m.rows.map((r) => [r.day, r.status]), [['Jue 20', 'Cerrado'], ['Vie 21', 'Cerrado'], ['Sáb 22', 'Abierto']]);
  assert.deepEqual(m.rows[0].cells[0], { value: '2.510', detail: '90 %', unknown: false });
  assert.deepEqual(m.rows[1].cells[3], { value: 'sin dato', detail: null, unknown: true });
  assert.deepEqual(m.average.cells[0], { value: '2.375', detail: '85 % · 2 días', unknown: false });
});
test('a day without entries shows — and never 0', ...);
test('without a profile: no percentages and the hint', ...);
```

`period-contract.test.ts`: `maps days, averages and has_profile`; `rejects more than 31 days, an unknown day_status, a missing average key`. `period-loader.test.ts`: one mint, one `GET /diary/PSN-00001/period?start=2026-11-18` without a cookie; 401/403/5xx/400/hang mapping as in `diary-loader.test.ts`.

- [ ] **Step 2: Run them to see them fail**

Run: `cd apps/home-hub && npm test -- src/integration/nutrition/period-range.test.ts src/integration/nutrition/period-contract.test.ts src/integration/nutrition/period-loader.test.ts src/components/features/nutrition/period-panel-model.test.ts`
Expected: FAIL (modules not found).

- [ ] **Step 3: Implement contract, range, loader, adapter and model**

- [ ] **Step 4: Run the unit tests**

Run: `cd apps/home-hub && npm test`
Expected: PASS.

- [ ] **Step 5: Write the e2e tests in `e2e/nutrition-days.spec.ts`**

The fake Nutrition answers `GET /diary/{id}/period` with these scenarios:
- `days-three`: the unit fixture, as wire
- `days-no-profile`: `has_profile: false`, every `target` null
- `days-denied`: 403
- `days-error`: 500

It records the full path, query included, so the test can read `start`.

```ts
test('7 days by default: one mint, one period call with a start, no cookie, no demo banner', ...);
test('the 3-day link keeps the person and marks itself current', ...);
test('rows and the average read as in the model; nothing reads 0', ...);
test('without a profile the hint shows and no % appears', ...);
test('denied and error states are in Spanish; error offers Reintentar', ...);
test('Días at 390 px: the page never scrolls sideways; the table scrolls inside its wrapper', ...);
test('tabs Perfil · Hoy · Días link to each other and keep ?person=', ...);
```

- [ ] **Step 6: Build and run every check**

Run: `cd apps/home-hub && npm run lint && npx tsc --noEmit && npm run test:server-boundary && npm run test:startup-config && npm run build && npm run test:e2e`
Expected: all pass (`test:server-boundary` now also proves `readDiaryPeriod` is reachable only from `LivePeriodPanel.tsx`).

- [ ] **Step 7: Commit**

```bash
git add apps/home-hub
git commit -m "feat(hub): Días compares several days against each day's targets"
```

---

### Task 6: Rollout section and evidence

**Files:**
- Modify: `docs/runbooks/nutrition-profile-rollout.md` (new section `## C6. Hub (plan 3)` after C5, plus a checklist line)
- Modify: `deploy/home-hub/README.md` (one line under the existing rollout notes: the three nutrition routes and that `/app/nutrition/dias` is live in LIVE mode)

**Interfaces:**
- Consumes: the `ROLL` helper and `$SSH` defined at the top of the runbook; `SHA` = this plan's merge commit.

The section's steps:
1. `[PREP]` `ROLL home-hub baseline` (record the running image; on 2026-11-24 it is the Hub at `1ff95d8`; no Hub change landed on main since).
2. `[OPERATOR]` `ROLL home-hub build $SHA`.
3. `[CLAUDE VERIFY]` `ROLL home-hub preview $SHA`: the `Image=` line is the only difference.
4. `[OPERATOR]` `ROLL home-hub apply $SHA`. Keep the printed backup directory.
5. `[CLAUDE VERIFY]` `ROLL home-hub verify` is `PASS`, and anonymous `/app/nutrition/dias` returns 307: `$SSH 'curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:9940/app/nutrition/dias'`.
6. `[OPERATOR INPUT]` Phone checks (spec 7, acceptance 2–6):
   - Ana's Perfil shows `Embarazo · 2.º trimestre`, `≈ 2.250 kcal` with its source line, and `24 nov: perfil creado por chat`.
   - Ana's Hoy shows `Energía: … de 2.250 kcal`.
   - Ana's Días (7 days) matches what her bot says for the same days.
   - Erick's Perfil shows the onboarding offer until he onboards (C3), then his targets.
   - Erick, without a consent grant, gets `Acceso restringido` on Ana's Perfil and Días, and the reverse.
7. `[CLAUDE VERIFY]` The Hub logs carry only `nutrition.<view> outcome=<KIND>` lines for these pages (counts per outcome; no IDs, names or numbers).

**Rollback:** `ROLL home-hub rollback <backup dir>`. Nutrition and the agents are untouched by this stage.

Checklist line: `- [ ] C6: ROLL home-hub verify PASS; anonymous /app/nutrition/dias 307; Ana's Perfil, Hoy and Días checked on her phone; access refused across people without consent.`

- [ ] **Step 1: Write the section and the README line**

- [ ] **Step 2: Verify the runbook renders and links resolve**

Run: `grep -n "## C6" docs/runbooks/nutrition-profile-rollout.md && grep -n "nutrition/dias" deploy/home-hub/README.md`
Expected: one match each.

- [ ] **Step 3: Commit**

```bash
git add docs/runbooks/nutrition-profile-rollout.md deploy/home-hub/README.md
git commit -m "docs: roll out the Hub nutrition views (plan 3)"
```
