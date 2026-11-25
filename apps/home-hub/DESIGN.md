---
name: Olin Home Hub
description: A themeable family app whose six visual worlds share one set of --olin-* tokens; the default is the warm, paper-and-terracotta Warm Household.
colors:
  warm-canvas: "#f5ede4"
  warm-card: "#fffdfa"
  warm-card-hover: "#ffffff"
  warm-border: "#e0d0bf"
  warm-ink: "#2b1f1a"
  warm-ink-muted: "#79675b"
  terracotta: "#c4643c"
  terracotta-border-strong: "#c26941"
  terracotta-deep-text: "#923f1e"
  terracotta-wash: "#fae7db"
  sage: "#57704e"
  status-success: "#2a5d3b"
  status-caution: "#a5640d"
  status-unknown: "#66605b"
  status-progress: "#1f406b"
  status-attention: "#c4643c"
  status-error: "#a83232"
  ambient-canvas: "#02070f"
  ambient-accent: "#5eb2f8"
  ambient-accent-secondary: "#f6ab63"
  hardware-canvas: "#08090b"
  hardware-accent: "#f58e2a"
  editorial-canvas: "#f7f5ed"
  editorial-ink: "#141414"
  editorial-oxblood: "#781c22"
  canvas-canvas: "#fcf9f2"
  canvas-accent: "#2e66f6"
  canvas-accent-secondary: "#0bb579"
  organic-canvas: "#eef4ed"
  organic-accent: "#49714c"
  organic-accent-secondary: "#8f77a5"
typography:
  headline:
    fontFamily: "Fraunces, Plus Jakarta Sans, sans-serif"
    fontSize: "1.75rem"
    fontWeight: 700
    lineHeight: 1.2
  title:
    fontFamily: "var(--olin-font-headline)"
    fontSize: "1.05rem"
    fontWeight: 700
  body:
    fontFamily: "Plus Jakarta Sans, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
  label-mono:
    fontFamily: "Fira Code, monospace"
    fontSize: "0.72rem"
    fontWeight: 600
    letterSpacing: "0.04em"
rounded:
  card-warm: "1.6rem"
  card-ambient: "1.85rem"
  card-hardware: "1.25rem"
  card-editorial: "0.35rem"
  card-canvas: "2.1rem"
  card-organic: "1.85rem"
  pill: "9999px"
spacing:
  space-1: "4px"
  space-2: "8px"
  space-3: "12px"
  space-4: "16px"
  space-6: "24px"
  space-8: "32px"
  space-10: "40px"
  space-12: "48px"
  space-16: "64px"
components:
  card:
    backgroundColor: "{colors.warm-card}"
    textColor: "{colors.warm-ink}"
    rounded: "{rounded.card-warm}"
    padding: "1.5rem"
  card-hover:
    backgroundColor: "{colors.warm-card-hover}"
  badge:
    backgroundColor: "{colors.terracotta-wash}"
    textColor: "{colors.terracotta-deep-text}"
    rounded: "0.375rem"
    padding: "0.375rem 0.75rem"
  button-retry:
    backgroundColor: "{colors.terracotta}"
    textColor: "#ffffff"
    rounded: "8px"
    padding: "0.625rem 1.25rem"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.warm-ink}"
    rounded: "0.5rem"
    height: "44px"
    padding: "0 0.75rem"
  chip-active:
    backgroundColor: "{colors.terracotta}"
    textColor: "#ffffff"
    rounded: "{rounded.pill}"
    padding: "0.35rem 0.75rem"
---

# Design System: Olin Home Hub

Documented from the code on branch `feature/nutrition-ui-redesign`. Everything here exists in the repository today; items marked (inferred) are a reading of the code, not a stated rule. Token source of truth: `apps/home-hub/src/styles/tokens.css`. The frontmatter lists the default theme (Warm Household) in full and one signature accent per other theme; each theme's complete value set is in `tokens.css`.

## Overview

**Creative North Star: "One Home, Six Rooms"** (inferred; the code names no metaphor)

The Hub is a family operating surface. Every screen is written against a fixed vocabulary of `--olin-*` CSS custom properties, and a theme is nothing more than a different set of values for that vocabulary, switched by a `data-olin-theme` attribute on `<html>`. Six themes ship: Warm Household (default), Ambient Future, Nordic Hardware (`premium-hardware`), Editorial Ledger, Family Canvas (`colorful-canvas`) and Organic Calm. The user picks one at Settings > Appearance; the choice is stored in `localStorage` and applied before hydration by `ThemeInitScript`.

Themes go beyond color. The home dashboard resolves a per-theme "slot" component for each region (relationship switcher, today header, schedule, attention tasks, wellbeing/nutrition, physical home, Ask Olin trigger) through `src/components/slots/resolver.ts`. Each theme therefore carries its own markup and CSS module for those seven regions, plus a theme-neutral `default` set. The default theme is warm: parchment canvas, near-white cards, terracotta accent, serif headlines, soft long shadows, very round corners.

The product is used by household members across ordinary home tasks, so the register is calm and domestic rather than clinical or dashboard-like. Copy in the nutrition area is Spanish and speaks in short, direct instructions.

**Key Characteristics:**
- One token vocabulary (`--olin-*`), six value sets, switched by `data-olin-theme`.
- Cards are the only container: bordered, rounded by theme, lifted by a theme-defined shadow.
- Headline font is a theme token; body font is a theme token. Pages never name a font family directly.
- Radius and shadow carry most of each theme's personality (0.35rem and a hard offset shadow vs 2.1rem and a soft one).
- Motion is gentle and always honors `prefers-reduced-motion`.

## Colors

The palette is theme-relative. Always consume a role token, never a hex. Roles are the same in every theme.

### Role tokens (all themes)
- `--olin-bg-canvas` / `--olin-bg-gradient`: page ground. `body` paints `--olin-bg-gradient`, falling back to the canvas color.
- `--olin-ambient-overlay`: a fixed full-viewport radial wash (`.ambient-light-field`, z-index 0, pointer-events none). `none` in Editorial.
- `--olin-surface-card`, `--olin-surface-card-hover`: card fill and its hover fill.
- `--olin-surface-border`, `--olin-surface-border-strong`: resting hairline and the emphasized/hover border.
- `--olin-surface-blur`: backdrop blur on cards and nav (`none` on opaque themes).
- `--olin-text-main`, `--olin-text-muted`: primary and secondary text.
- `--olin-accent`, `--olin-accent-glow`, `--olin-accent-secondary`: the single action/identity color, its glow shadow, and a supporting hue.
- `--olin-badge-bg`, `--olin-badge-text`: tinted label pair; also reused as the track color for meters and skeletons.
- `--olin-status-success` (on track, green), `--olin-status-caution` (short, low, over or past a limit, amber), `--olin-status-unknown` (data incomplete, day not closed, no entries, grey) and `--olin-status-progress` (day still open, neutral blue): the nutrition status language, with no red. Also `--olin-status-attention`, `--olin-status-error`, and `--olin-kiosk-time-color` for the large clock.

### Default theme: Warm Household
- **Parchment** (#f5ede4) canvas under a 135deg gradient (#e8dacb, #f6eee5 at 45%, #ebdcd0) with a faint terracotta glow at the upper right.
- **Paper White** (#fffdfa) cards, #ffffff on hover; **Sand Line** (#e0d0bf) border; **Terracotta Edge** (#c26941) strong border.
- **Cocoa Ink** (#2b1f1a) text; **Clay Muted** (#79675b) secondary text.
- **Terracotta** (#c4643c) is the accent; **Sage** (#57704e) the secondary. Badge pair is #fae7db on #923f1e.
- Status: success #2a5d3b, caution #a5640d, unknown #66605b, progress #1f406b, attention #c4643c, error #a83232. The four nutrition status colours hold these values in every light theme (Warm, Editorial, Family Canvas, Organic); Ambient Future and Nordic Hardware use the lighter set success #57b476, caution #f4bf7b, unknown #b8b4af, progress #5b8dcf.

### Other themes (accent and ground only; full sets in tokens.css)
- **Ambient Future**: night-blue ground (#02070f to #10263f), sky accent #5eb2f8, amber secondary #f6ab63, translucent glass cards with a 28px blur.
- **Nordic Hardware**: graphite (#08090b to #1e2227), amber accent #f58e2a, mint secondary #10d290, 20px blur, inset top highlight.
- **Editorial Ledger**: flat paper #f7f5ed, ink #141414 borders, oxblood accent #781c22, no gradient, no overlay, no glow.
- **Family Canvas**: cream gradient to pale mint, blue accent #2e66f6, green secondary #0bb579, coral strong border #ff5c38.
- **Organic Calm**: sage ground #eef4ed, forest accent #49714c, lilac secondary #8f77a5.

### Named Rules
**The Role Token Rule.** Components read `--olin-*` roles. A hex literal in a component is a bug, because it will not follow the theme. (Observed violation: the Warm slot CSS hard-codes #c4643c, #fae8dc, #fbf7f2 and #ebdcd0 in places, so those slots do not re-theme.)

**The One Accent Rule.** Each theme has one accent. It marks the action, the active state, the focus ring and progress fills. Use `--olin-accent-secondary` sparingly as support, not as a second brand color.

**The Status Words Rule.** Status always carries a word (`bien`, `corto`, `faltan datos`, `sin cerrar`, `en curso`), and shape differs per state in the day dots, so colour never carries meaning alone. Status colours reach 4.5:1 on the card in every theme, proved by `src/styles/status-tokens.test.ts`.

**The Status Is Not Accent Rule.** Success, attention and error come from `--olin-status-*`, never from the accent, even when a theme's attention color equals its accent (Warm does).

## Typography

**Headline Font:** Fraunces (serif) in Warm Household, Editorial Ledger and Organic Calm; DM Sans in Ambient Future; Outfit in Nordic Hardware; Plus Jakarta Sans in Family Canvas. Delivered by `--olin-font-headline`.
**Body Font:** Plus Jakarta Sans by default (`--ep-font-sans`); DM Sans in Ambient Future and Organic Calm; Outfit in Nordic Hardware. Delivered by `--olin-font-body`.
**Label/Mono Font:** Fira Code (`--ep-font-mono`), used for small uppercase-ish tags, counts, clock and provenance badges.

All five families are loaded with `next/font/google` in `layout.tsx` (`display: swap`) and exposed as `--ep-font-*` variables on `<html>`.

**Character:** A warm serif headline over a friendly geometric sans in the default world; the other worlds swap the pairing wholesale (single-family sans in Ambient and Hardware, serif ledger in Editorial).

### Hierarchy (observed values)
- **Page title** (700, `clamp(1.5rem, 4vw, 2rem)`): `--olin-font-headline`; nutrition page header.
- **Settings title** (600, 2rem, line-height 1.1, letter-spacing -0.04em).
- **Greeting / hero** (700, 1.75rem): slot today headers.
- **Section title** (700, 1.5rem, line-height 1.25): action sections. Card titles in slots are 700 at about 1.05rem.
- **Hero number** (600, 2.25rem, letter-spacing -0.03em, `text-wrap: balance`): the daily-total line on the nutrition Today panel; 1.75rem under 768px. The older calorie ring uses 3.5rem / 700 / -0.04em.
- **Body** (400-600, 1rem): `--olin-font-body`; muted copy 0.875-0.9rem.
- **Label** (600, 0.72-0.75rem, +0.04em tracking, mono): tags and badges; the calorie label is 0.875rem uppercase with 0.05em tracking.

### Named Rules
**The Tabular Time Rule.** Times and quantities use `font-variant-numeric: tabular-nums` (the nutrition timeline does) so columns align.

**The Theme Font Rule.** Set `font-family` via `--olin-font-headline`, `--olin-font-body` or `--olin-font-mono`, never a literal family. (Slot CSS sometimes reaches for `--ep-font-mono` directly; prefer the olin alias.)

## Layout

Mobile-first. The shell (`AppShell`) is a flex row: a 240px sidebar (80px collapsed) from 768px up, and a fixed 60px bottom nav below 768px with 60px of bottom padding on the content. Page canvases pad 1.5rem, often 6rem at the bottom to clear the nav. Settings pages center a 900px container with `--ep-space-10` / `--ep-space-6` padding, growing to `--ep-space-16` / `--ep-space-12` at 768px.

Content grids are single column, becoming two equal columns at 768px, with `1.5rem` gaps; hero cards span all columns. Breakpoints in use: 640px (most common), 768px (shell switch), 900px, 1024px, 1600px.

Spacing scale (`--ep-space-*`): 4, 8, 12, 16, 24, 32, 40, 48, 64px. Slot and feature CSS mostly uses rem values (0.5, 0.75, 1, 1.25, 1.5rem) that fall on the same rhythm. Touch targets are at least 44px tall on the nutrition links, buttons and disclosure summaries.

## Elevation & Depth

Depth is theme-defined and comes from one token, `--olin-shadow-elevation`, plus an optional `--olin-surface-blur` for glass.

### Shadow Vocabulary
- **Warm** (`0 10px 30px -5px rgba(78,48,25,0.08), 0 2px 8px rgba(0,0,0,0.02)`): soft, warm-tinted lift.
- **Ambient** (`0 20px 45px -15px rgba(0,5,20,0.7)`): deep, with 28px backdrop blur on translucent cards.
- **Hardware** (`0 16px 40px -8px rgba(0,0,0,0.85), inset 0 1px 0 rgba(255,255,255,0.08)`): heavy with a bevel highlight.
- **Editorial** (`4px 4px 0 #141414`): hard offset, no blur; depth as ink.
- **Canvas** (`0 14px 34px -8px rgba(35,52,90,0.12)`) and **Organic** (`0 12px 28px -5px rgba(34,54,37,0.08)`): soft and cool.
- **Accent glow** (`--olin-accent-glow`): a colored shadow on accent elements; `none` in Editorial.

### Named Rules
**The Token Shadow Rule.** Cards take `box-shadow: var(--olin-shadow-elevation)`. Do not write a bespoke shadow on a card. (Observed exception: the nutrition `.provenanceBadge` uses `0 2px 8px rgba(0,0,0,0.1)` and the calorie ring `0 0 40px rgba(0,0,0,0.05)`.)

**The Glass Only Where Themed Rule.** Pair `backdrop-filter: var(--olin-surface-blur)` with the card fill; on opaque themes the token is `none`, so it costs nothing.

## Shapes

Corner radius is a theme token. Cards use `--olin-card-radius`: 1.6rem (Warm), 1.85rem (Ambient, Organic), 1.25rem (Hardware), 0.35rem (Editorial), 2.1rem (Canvas). Pills and nav items use `--olin-pill-radius`: 1.4rem (Warm), 9999px (Ambient, Canvas, Organic), 0.75rem (Hardware), 0.35rem (Editorial). Inner elements step down: task rows 0.85rem, checkboxes 0.35rem, tags 0.4rem, meters 4px, ghost buttons 0.5rem. Borders are 1px hairlines in `--olin-surface-border`; a 4px left border in `--olin-accent` marks a notice card.

Editorial Ledger adds a hand-drawn ink circle (`.ledger-ink-circle`, an irregular 54/46 radius with a 2px accent border) and Nordic Hardware a conic-gradient rotary knob (`.rotary-knob`); both are global utility classes in `globals.css`.

## Components

### Cards / Containers
- **Corner Style:** `var(--olin-card-radius)`.
- **Background:** `--olin-surface-card`; hover raises to `--olin-surface-card-hover` or switches the border to `--olin-surface-border-strong`.
- **Shadow Strategy:** `--olin-shadow-elevation`.
- **Border:** `1px solid var(--olin-surface-border)`.
- **Internal Padding:** 1.25rem to 1.5rem; hero cards 2.5rem 1.5rem.
- Slot cards use `transition: all 0.35s cubic-bezier(0.16, 1, 0.3, 1)`.

### Buttons
- **Primary / retry:** accent fill, white text, 8px radius, 0.625rem 1.25rem padding, weight 500.
- **Ghost / refresh:** transparent, 1px `--olin-surface-border`, 0.5rem radius, 44px min height, weight 600.
- **Focus:** `outline: 2px solid var(--olin-accent); outline-offset: 3px` on `:focus-visible`.
- **Disabled:** opacity 0.6 and `cursor: progress`.

### Chips and switchers
- Relationship switcher: a pill track (`--olin-surface-card`, 1px border, 9999px) holding chips; the active chip is the badge pair (`--olin-badge-bg` fill, `--olin-badge-text` text, weight 600) with a 2px inset ring in `--olin-accent`. The default set recolors only the ring by mode (care for another person: #8b5cf6; family: `--olin-surface-border-strong`). Each theme restyles this region in its own slot.

### Badges / tags
- Mono 0.72-0.75rem, weight 600, `--olin-badge-bg` fill, `--olin-badge-text` text, 1px border, 0.375-0.4rem radius.

### Navigation
- Spanish labels: Inicio, Memoria, Nutrición (`ForkKnife` icon), Salud, Calendario, Ajustes. In the bottom nav the current tab is text-main at weight 700.
- Sidebar items: pill radius, muted text, 0.95rem; hover fills `--olin-surface-card-hover`; active state is card fill, main text, weight 600, elevation shadow and 1px border. Brand motif is a 14px ring in the accent. Mobile bottom nav: 60px, card fill, blur, top hairline, icon over 0.75rem label.
- Page-level links on nutrition: underlined, 600, 44px tall, current page is text-main at 700 with a 3px accent underline (Hoy · Días tabs).

### Meters and progress
- Status bar (`StatusBar`): a 0–150 % track in `--olin-badge-bg`, 8px high, so the target (100 %) sits two thirds along. A tick marks a minimum, a 90–110 % band an "about" target, a heavier cap a limit. The fill takes its tone from the `--olin-status-*` token for the state; its width is a CSS ratio of raw wire decimals (`--bar-value` / `--bar-scale`), never a computed percentage.
- Status dots and legend (Días): one dot per day, shape per state (filled circle bien, rotated diamond caution, square unknown, ringed circle en curso, dashed ring sin cerrar, dash Sin registros), with a legend of the same words beneath.
- Other meters and skeletons reuse the badge fill and a 1.2s opacity pulse.

### Slot components (signature)
- Seven regions x seven sets (six themes plus default). Each takes the same typed props (`src/components/slots/types.ts`) so a theme can change structure freely while data and handlers stay identical.

### Motion
- Page entrance: `fadeIn` 0.4s `cubic-bezier(0.16, 1, 0.3, 1)`, 8px rise. Interaction transitions: `--ep-transition-fast` 150ms and `--ep-transition-normal` 250ms, both `cubic-bezier(0.4, 0, 0.2, 1)`. Theme switch: body background 0.5s, overlay 0.6s. Ambient glow: `stellarGlow` 3.5s infinite on the active constellation node.
- A global `prefers-reduced-motion: reduce` rule shortens all animation and transition durations to 0.01ms.

### Voice
- Nutrition copy is Spanish, imperative and plain ("Registrar una comida", "Anular un registro"); prompts use [bracketed placeholders] and ask the assistant to wait for confirmation before changing records. Tags and eyebrows are short and mono. The app name reads "Episteck Home - Olin Family OS".

### Observed divergence: live nutrition pages vs themed slots
- The live nutrition routes are `/nutrition/hoy`, `/nutrition/dias`, `/nutrition/perfil`, `/nutrition/nutriente/<code>` and `/nutrition/ayuda`; `/nutrition` redirects to Hoy. They render plain feature cards from `components/features/nutrition/*` and `app/nutrition/page.module.css`, not the themed slot components. They consume the `--olin-*` tokens, including the status tokens above, so color, font, card radius and shadow follow the active theme, but structure does not change per theme.
- Remaining fixed values: some panels still use literal radii (16px cards, 8px buttons) and rem paddings next to `--olin-card-radius`; the detector reports these as advisories.
- The nutrition canvas re-paints `--olin-bg-gradient` on its own wrapper, duplicating the body background.

## Do's and Don'ts

### Do:
- **Do** read color, font, radius, shadow and blur from `--olin-*` tokens so every theme works.
- **Do** keep one accent per screen region and use `--olin-status-*` for status: success, caution, unknown and progress (no red), each with its word.
- **Do** keep touch targets at least 44px and give every interactive element a 2px accent `:focus-visible` outline with 3px offset.
- **Do** honor `prefers-reduced-motion`; new animation must be covered by the global rule or its own media query.
- **Do** add a new themed region as a seven-file family (one component per theme plus default) behind the same props interface.
- **Do** write new nutrition copy in Spanish, short and imperative, matching existing labels.

### Don't:
- **Don't** hard-code hex colors, font families or pixel radii in component CSS (Warm slots already do; do not spread it).
- **Don't** put a person's name, health detail or identifier in design documentation, fixtures or screenshots.
- **Don't** introduce a new theme attribute value without adding its full `--olin-*` set to `tokens.css` and an entry in `src/theme/registry.ts`.
- **Don't** assume one theme's look (for example Editorial's hard shadow or Ambient's glass) applies to the others.
- **Don't** let a feature page restyle the shell's background or navigation.
