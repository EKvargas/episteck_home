# Nutrition UI redesign (Hub): design

Status: draft for owner approval, 2026-11-24.

- Owner choices (2026-11-24):
  - approach A;
  - Hoy uses structure A, with D's grouping for vitamins and minerals;
  - checked mainly on a phone.
- Product truth lives in `apps/home-hub/PRODUCT.md`.
- The visual system lives in `apps/home-hub/DESIGN.md`.
- The Impeccable critique of the current pages scored Perfil 20/40, Hoy 21/40 and Días 25/40.

## Why

The owner finds the nutrition pages hard to read:
- Perfil is a wall of text.
- Hoy leads with a large free-sugar line.
- The vitamins and minerals in the profile never appear day to day.
- The meal list is dense text.
- A help block sits at the same level as Hoy and Días.

The pages exist so the primary user, a pregnant household member, can see on her phone in a few seconds whether she is on track today. Detail is one tap away. Everything is read-only; logging and changes happen in chat with her agent.

## Goals

- **Answer "am I on track today?" in the first screen of Hoy on a 390 px phone.** That means a one-line verdict and four equal bars: energy, protein, fiber and free sugars.
- **Show every tracked nutrient the backend reports, without overload.** The ten vitamins and minerals appear as a grouped weekly status (short / fine / not enough data), each one reachable in detail.
- **One status language everywhere:** green = fine, amber = short or over a limit, grey = data incomplete, and a neutral fill for a day still in progress. No red.
- **Make Perfil readable on a phone.** Move it out of the tab bar behind a header chip, and list it in Ajustes.
- **Turn the Telegram how-to into a small "¿Cómo anoto?" page.**
- **Fix what the critique found app-wide:**
  - the Nutrition nav icon (it is the Apple company logo);
  - the contrast of the active tab and of the person chips;
  - the roadmap text ("proyecto 2") on Días.

## Non-goals

- Backend changes of any kind. The Nutrition service already returns:
  - for each day, all 15 nutrients (energy, protein, fat, carbohydrate, fiber, calcium, iron, folate, vitamin B12, vitamin D, iodine, zinc, selenium, choline, DHA) plus free sugars, each with its known total, completeness, target and percent;
  - for each period, averages for the same set.
- Tracking supplements. That is the next, separate step (backend + agent + UI). This design only leaves room for it (see Hoy).
- Editing in the app; per-theme slot variants; the Olin home page redesign; new themes.

## Anti-goals (fail even if it looks polished)

- Red alarms, or any judgment of a nutrient whose data is incomplete.
- Unknown shown as zero or as "low".
- A first screen that needs scrolling or tapping to say whether the day is on track.
- Layout that moves day to day. The same nutrient is always in the same place on Hoy.
- Weakening the trust model: one delegation mint and one Nutrition GET per panel, no cookie to Nutrition, adapters called only from their Live panel.
- Another person's data or chat prompts shown to someone without the right to them.

## Constraints

- **Stack:**
  - Next.js 16.3.5, React 19 and CSS modules over `--olin-*` tokens. Read `apps/home-hub/AGENTS.md`.
  - One implementation follows whichever of the six themes is active.
  - Spanish copy (`lang="es"`), and everything under the `/app` basePath.
- **Phone first:**
  - one column at 390 px, no horizontal scrolling;
  - touch targets ≥ 44 px;
  - text contrast ≥ 4.5:1;
  - states never shown by colour alone (each has a word).
- **The app does no nutrition maths:**
  - totals, averages and percentages come from the backend;
  - one exception: "faltan X" is the target minus the known total, both as displayed (rounded), so the numbers on screen add up.
  - Status comparisons (≥, ≤) are allowed.
- **Consent:**
  - a viewer with consent sees the data but no chat prompts (ruling R7 of plan 3);
  - `?person=` keeps its current meaning on every route.
- **Logs:** outcome lines only (`nutrition.<view> outcome=<KIND>`), no IDs or numbers.

## Approaches considered

- **A. Rebuild the three pages on the Olin token system.** One implementation for all themes. **Chosen.**
- **B. Themed variants per theme,** like the demo home's slots. Most distinctive, but about six times the work and testing. Rejected for now.
- **C. Cleanup only:** fonts, colours, more rows. Cheap, but it does not fix structure and readability. Rejected.

For the Hoy structure, Impeccable dealt three alternatives to the owner-approved structure (`seed:54d5b8d57a485594`):
- B, meals adding up to totals;
- C, a tile mosaic;
- D, a list sorted by need.

The owner kept A for the phone, for three reasons: the verdict comes first, positions are stable, and everything is in one readable column. From D, the owner took the grouped weekly status. B's per-meal contribution may come back later inside a meal's detail.

## Routes

| Route | Page |
| --- | --- |
| `/app/nutrition/hoy` | Hoy. The Nutrition nav already lands here in LIVE mode. The iPhone Home Screen shortcut points here. |
| `/app/nutrition/dias` | Días |
| `/app/nutrition/perfil` | Perfil (moves from `/app/nutrition`) |
| `/app/nutrition` | Redirects to `/app/nutrition/hoy`, keeping `?person=` |
| `/app/nutrition/nutriente/<code>` | Nutrient detail: one nutrient over a range (`?rango=3\|7\|14`, default 7) |
| `/app/nutrition/ayuda` | "¿Cómo anoto?": today's "Acciones en Telegram" content, unchanged in substance |

Every link between these pages carries `?person=`.

## Shared header (Hoy, Días, Perfil, detail, ayuda)

1. **The heading "Nutrición".**
2. **The person switcher, only when the viewer can see more than one person.** It uses today's component with its contrast fixed.
3. **A profile chip linking to Perfil.**
   - It reads "Embarazo · 2.º trimestre ›" when the page's own payload carries mode and trimester, and "Perfil ›" otherwise.
   - No extra mint or GET just for the chip.
   - With no profile, it reads "Crear perfil ›" for the person themselves and "Sin perfil" (no link) for a viewer.
4. **Two tabs, Hoy and Días.** The active one is marked by more than colour.
5. **Quiet "Actualizado HH:MM" text and a small "Actualizar" control** (today's refresh), on Hoy and Días.

## Status language (all pages)

Inputs per nutrient: known total (or none), completeness (complete / partial / none), uncounted items, and target value and kind. Free sugars carry a limit instead of a target.

| Target kind | Day still open | Day closed, or weekly average |
| --- | --- | --- |
| Minimum (protein, fiber, vitamins, minerals) | known ≥ target: **green "bien"**; else **neutral "en curso · faltan X"** | known ≥ target: **green "bien"**; partial and below: **grey "faltan datos"**; complete and below: **amber "corto"** |
| About (energy, fat) | above 110 %: **amber "por encima"**; else **neutral "en curso · faltan ~X"** | 90–110 %: **green "bien"**; below 90 % (complete): **amber "bajo"**; above 110 %: **amber "por encima"**; partial and not above 110 %: **grey "faltan datos"** |
| Limit (free sugars) | known > limit: **amber "pasado del límite"**; partial: **grey "faltan datos"**; else **green "bien"** | same |

Further rules:
- **No data at all** for a nutrient on a day with entries: **grey "faltan datos"**. With no entries: grey track, "Sin registros".
- **Today versus past days.** A day closes only when its person confirms the evening check-in ("¿Eso fue todo hoy?" → "Sí") or asks the agent to close it. Nothing closes days automatically.
  - "Day still open" in the table means **today** only.
  - A **past day that was never closed** reads "sin cerrar": values shown, no judgment, and a grey ring in the Días grid.
- **Weekly averages** come from the period endpoint. The backend averages only complete, closed days; `left_out` counts the open, empty and partial days it skipped.
  - `days_used` = 0: grey "faltan datos".
  - `days_used` 1–2: grey "pocos días (N)".
  - `days_used` ≥ 3: judge `average_percent` (the backend's, computed against each day's own target) by the kind. Below a minimum is amber "corto", with "con N días" beside it. `left_out` matters only through `days_used`.
  - The averages carry no target, so the **kind and the displayed target value** come from the most recent day in the range that has a target for that nutrient. No such day: value only.
- **No target** (no profile, or no target for that nutrient): show the value only, with no bar or state.
- **Bars:**
  - the track covers 0–150 % of the target;
  - a minimum target shows a tick at 100 %, an about target a band at 90–110 %, a limit a cap line at 100 %;
  - the fill is clipped at 150 %.

The owner confirmed the 90–110 % band and the 3-day minimum.

## Hoy (first screen, then scroll)

1. **The shared header.**
2. **Verdict, one line**, from the day's states:
   - no entries: "Aún no has anotado nada hoy.";
   - free sugars over the limit: "Hoy te has pasado de azúcares libres.";
   - day open: "Vas en camino." when nothing is "faltan", else "Vas en camino. Te faltan proteína y fibra." (listing the minimum nutrients still short);
   - day closed: "Día cerrado: bien en …; corto en …" (fine, short and amber names only);
   - any partial: append " Faltan datos de N alimentos."
3. **Four equal bars, always in this order:** Energía, Proteína, Fibra, Azúcares libres. Each row shows:
   - name;
   - "known de target unit" (e.g. "48 de 65 g");
   - the bar;
   - the state word.
4. **One quiet line without bars:** "Grasa 58 g · Carbohidratos 190 g".
5. **"Vitaminas y minerales · últimos 7 días"**, the D-style grouping. Each group is a row that opens inline into the list of its nutrients:
   - "Corto: hierro, folato, vitamina D, colina ›";
   - "Bien: 3 ›";
   - "Faltan datos: 3 ›".

   Each nutrient in an opened list shows its average and target and links to its detail. Groups with no members are hidden.
6. **Prenatal note.** In pregnancy mode, one calm line under the group: "Tu prenatal aún no se cuenta: folato, yodo, vitamina D y DHA pueden estar cubiertos." It is removed when supplements are tracked. No placeholder controls.
7. **"Comidas de hoy".**
   - One line per diary entry: time and food names, single line with ellipsis.
   - It opens inline to the items as recorded: text and portion, free sugar, notes such as "sin coincidencia" or "sin datos de fibra".
   - No per-meal kcal: that would be maths in the app (Owner decision 3).
8. **Footer:** "¿Cómo anoto?" (to `/ayuda`) and "Fuentes" (collapsed: the reference line and source attribution shown today).

Profile hint: with no energy target (no or partial profile), the bars show values only. The person themselves sees the existing "Copiar «Quiero crear mi perfil»" prompt under the bars. A viewer sees "Todavía no hay perfil completo."

## Días

- **Range switch 3 / 7 / 14 days** (as today). The default is 7.
- **Grid:**
  - rows: Energía, Proteína, Fibra, Azúcares libres;
  - columns: days (weekday initial over day number);
  - cells: a status dot in the status language, with an open day as a neutral ring;
  - a last column, "Media", holds the average value.
- **Fit:** 7 days fit at 390 px. For 14 days, show two stacked 7-day grids, never horizontal scrolling.
- **Row tap:** a row opens that nutrient's detail for the same range.
- **Below the grid:** "Vitaminas y minerales · media" with the same grouping and rows as Hoy, for the selected range.
- **Removed:** the "proyecto 2" roadmap text.

## Nutrient detail (`/app/nutrition/nutriente/<code>`)

- **Top:** the nutrient name, the average against its target with the state word, and the range switch.
- **A bar per day with the target mark,** drawn with HTML/CSS or inline SVG. No chart library.
- **Days with no bar are labelled by reason:** "abierto" (still open), "faltan datos" or "sin registros".
- **One line on what the target means** (kind and value). Where the payload carries the source, it is shown; otherwise a link reads "Ver de dónde sale en tu perfil".

## Perfil (`/app/nutrition/perfil`)

- **Top:**
  - the name;
  - the mode pill ("Embarazo · 2.º trimestre");
  - "Fecha prevista de parto" when present.
- **"Objetivos diarios":** one row per target, with the name and the value marked ≈, ≥ or ≤. An ⓘ disclosure on each row reveals its explanation and source; they are not shown by default.
- **"Datos":** label above value on phones, never squeezed into a narrow column. No cards inside cards.
- **"Comida":** preferences, dislikes and intolerances as short chips.
- **"Faltan datos para…":** a calm note when inputs are missing.
- **"Historial":** collapsed by default.
- **One "Cambiar en el chat" prompt at the bottom,** for the person themselves only. It reuses today's label and prompt text, merged from the per-card prompts into one.
- **States:** no-profile, mode-only, denied, session, unavailable and invalid states keep today's meaning and copy, restyled.

## Ajustes

Ajustes has no index page today; the nav opens `/settings/appearance`. Add a "Perfil de nutrición" entry where the settings screens link to each other, pointing to `/app/nutrition/perfil`. The builder chooses the exact placement inside the existing settings navigation.

## App-wide fixes

- **Nav icon:** replace the Nutrition nav icon (`AppleLogo`) in `BottomNav` with a food icon from the same library (`ForkKnife` or `BowlFood`). Other uses of that icon, such as the calendar's Apple source, stay. The nav labels become Spanish: Inicio, Memoria, Nutrición, Salud, Ajustes.
- **Contrast:** fix the active tab and the person chips to ≥ 4.5:1 in all six themes.
- **Status tokens:** `--olin-status-success` exists today. Add the missing status tokens for each theme (amber "caution", grey "unknown", neutral "in progress"), with contrast checked. This is an approved system change: refresh DESIGN.md at the finish.

## Data and trust

- **Hoy has two Live panels:**
  - the day (existing day adapter, now parsing all 15 nutrients);
  - the weekly status (period adapter, 7 days).
- **Other pages:**
  - Días: one panel (period);
  - nutrient detail: one panel (period);
  - Perfil: one panel (profile).
- Each panel does exactly one delegation mint and one Nutrition GET, with no retry, and degrades on its own: one panel failing never blanks the other.
- New adapter–panel pairs join `test-support/verify-adapter-callers.mjs`.
- Mappers stay strict on known fields and ignore unknown ones, as today.

## Testing and finish

- **Unit:**
  - the status rules table, row by row, including partial, none, no target and the open/closed day;
  - the verdict sentence;
  - weekly grouping;
  - each panel model.
- **E2E:**
  - update the three nutrition specs for the new routes;
  - add fake scenarios for a pregnancy-mode day with all 15 nutrients, and a period with micronutrient averages (including partial and few-days cases);
  - keep every trust assertion (mint and GET counts per panel, no cookie to Nutrition, no secrets in Hub responses);
  - check that a consent viewer sees no chat prompts, and that `/app/nutrition` redirects with `?person=`.
- **Impeccable:**
  - run `detect --json` on the changed UI;
  - run the finish reviewer with screenshots at 390×844 and 1440 wide, against this design and the direction contract recorded in the surface brief;
  - have the documenter refresh DESIGN.md (status tokens).
- **Existing checks:** lint, tsc, the boundary check, build, startup-config and the full e2e suite stay green.

## Rollout

- Hub image only (`ROLL home-hub` with the merge SHA). No backend, agent or env changes.
- Update runbook C6's phone checks for the new routes.
- The Home Screen shortcut (`/app/nutrition/hoy`) keeps working, and old `/app/nutrition` links redirect.

## Owner decisions (2026-11-24)

1. **Only closed days count in weekly averages.** This is the backend rule. Days the person never closes show "sin cerrar", and the weekly status says "pocos días (N)" instead of judging. Auto-closing past days is out of scope.
2. **Bottom nav labels switch to Spanish app-wide:** Inicio, Memoria, Nutrición, Salud, Ajustes. Text inside the other prototype pages is untouched.
3. **No per-meal kcal in this redesign.** It needs per-entry totals from the backend and comes with the supplements step.
4. **Thresholds:** "bien" is 90–110 % for "about" targets, and weekly judgments need at least 3 closed days.

## Left to the builder

- Component and file structure.
- The exact inline-open mechanics.
- The chart drawing technique.
- The placement of the Ajustes entry inside the existing settings navigation.
- The status token values per theme (contrast-checked).
- Copy for states not listed here, in the voice of the existing copy.
