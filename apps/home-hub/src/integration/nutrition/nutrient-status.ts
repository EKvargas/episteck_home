// The one status language for nutrition: states, bars, verdict, weekly grouping. Pure.
// Never computes nutrition figures; the only arithmetic is "faltan X" (target minus known, both as displayed).
import type { NutrientBlock } from './diary-contract.ts';
import { amount, nutrientName, spanishList, unitLabel } from './nutrition-format.ts';

export type Tone = 'ok' | 'caution' | 'unknown' | 'progress' | 'unclosed' | 'empty' | 'plain';
export interface NutrientState { tone: Tone; word: string | null; detail: string | null }
export type DayPhase = 'NO_ENTRIES' | 'OPEN_TODAY' | 'OPEN_PAST' | 'CLOSED';
export type Target = NutrientBlock['target'];
export type Mark = 'tick' | 'band' | 'cap';
export interface Bar { value: string | null; scale: string; mark: Mark }
export interface DayInput { known: string | null; status: 'NONE' | 'KNOWN' | 'PARTIAL'; target: Target; percent: string | null }
export interface WeeklyInput { averageKnown: string | null; averagePercent: string | null; daysUsed: number }
export interface Headline { code: string; kind: 'ABOUT' | 'MIN' | 'MAX' | null; state: NutrientState }
export type GroupKey = 'short' | 'fine' | 'missing' | 'plain';
export interface WeeklyGroup<T> { key: GroupKey; summary: string; items: T[] }

const state = (tone: Tone, word: string | null, detail: string | null = null): NutrientState => ({ tone, word, detail });
const NO_DATA = (): NutrientState => state('unknown', 'faltan datos');

const ONE_DECIMAL = new Intl.NumberFormat('es-ES', { maximumFractionDigits: 1, useGrouping: 'always' });

export function dayPhase(dayStatus: 'NO_ENTRIES' | 'OPEN' | 'COMPLETE', isToday: boolean): DayPhase {
  if (dayStatus === 'NO_ENTRIES') return 'NO_ENTRIES';
  if (dayStatus === 'COMPLETE') return 'CLOSED';
  return isToday ? 'OPEN_TODAY' : 'OPEN_PAST';
}

export function limitTarget(limitG: string): NonNullable<Target> {
  return { value: limitG, displayValue: limitG, unit: 'g', kind: 'MAX' };
}

/** Parses a number formatted by `amount` (es-ES: '.' groups, ',' decimal). */
function parseDisplayed(text: string): number {
  return Number(text.replace(/\./g, '').replace(',', '.'));
}

/** Target minus known, both as displayed; null when it is not above zero or either side is not a number. */
export function missingAmount(targetDisplay: string, known: string, unit: string): string | null {
  const t = parseDisplayed(amount(targetDisplay, unit));
  const k = parseDisplayed(amount(known, unit));
  if (!Number.isFinite(t) || !Number.isFinite(k)) return null;
  const diff = t - k;
  if (!(diff > 0)) return null;
  return ONE_DECIMAL.format(diff);
}

function progressWord(target: NonNullable<Target>, known: string, approx: boolean): string {
  const missing = missingAmount(target.displayValue, known, target.unit);
  if (missing === null) return 'en curso';
  return `en curso · faltan ${approx ? '~' : ''}${missing} ${unitLabel(target.unit)}`;
}

function aboutClosed(percent: number, partial: boolean): NutrientState {
  if (percent > 110) return state('caution', 'por encima');
  if (partial) return NO_DATA();
  if (percent >= 90) return state('ok', 'bien');
  return state('caution', 'bajo');
}

export function dayState(input: DayInput, phase: DayPhase): NutrientState {
  const { known, status, target, percent } = input;
  if (phase === 'NO_ENTRIES') return state('empty', 'Sin registros');
  if (target === null) return state('plain', null);
  if (known === null) return NO_DATA();
  if (phase === 'OPEN_PAST') return state('unclosed', 'sin cerrar');
  const partial = status === 'PARTIAL';
  if (target.kind === 'MIN') {
    if (Number(known) >= Number(target.value)) return state('ok', 'bien');
    if (phase === 'OPEN_TODAY') return state('progress', progressWord(target, known, false));
    return partial ? NO_DATA() : state('caution', 'corto');
  }
  if (target.kind === 'ABOUT') {
    const p = percent === null ? NaN : Number(percent);
    if (!Number.isFinite(p)) return NO_DATA();
    if (phase === 'OPEN_TODAY') {
      return p > 110 ? state('caution', 'por encima') : state('progress', progressWord(target, known, true));
    }
    return aboutClosed(p, partial);
  }
  if (Number(known) > Number(target.value)) return state('caution', 'pasado del límite');
  return partial ? NO_DATA() : state('ok', 'bien');
}

export function weeklyState(input: WeeklyInput, target: Target): NutrientState {
  if (target === null) return state('plain', null);
  const { daysUsed, averagePercent } = input;
  if (daysUsed === 0) return NO_DATA();
  if (daysUsed <= 2) return state('unknown', `pocos días (${daysUsed})`);
  const p = averagePercent === null ? NaN : Number(averagePercent);
  if (!Number.isFinite(p)) return NO_DATA();
  const detail = `con ${daysUsed} días`;
  if (target.kind === 'MIN') return p < 100 ? state('caution', 'corto', detail) : state('ok', 'bien', detail);
  if (target.kind === 'MAX') return p > 100 ? state('caution', 'pasado del límite', detail) : state('ok', 'bien', detail);
  const judged = aboutClosed(p, false);
  return { ...judged, detail };
}

const MARKS = { MIN: 'tick', ABOUT: 'band', MAX: 'cap' } as const;

export function barFor(target: Target, known: string | null, phase: DayPhase): Bar | null {
  if (target === null) return null;
  const mark = MARKS[target.kind];
  if (phase === 'NO_ENTRIES' || known === null) return { value: null, scale: target.value, mark };
  return { value: known, scale: target.value, mark };
}

export function latestTarget(days: readonly { nutrients: Record<string, { target: Target }> }[], code: string): Target {
  for (let i = days.length - 1; i >= 0; i--) {
    const block = days[i].nutrients[code];
    if (block && block.target !== null) return block.target;
  }
  return null;
}

const ENERGY = 'energy_kcal';
const PROTEIN = 'protein_g';
const FIBER = 'fiber_g';
const SUGARS = 'free_sugars_g';

export function verdict(v: { phase: DayPhase; headline: Headline[]; uncounted: number; self: boolean }): string {
  const { phase, headline, uncounted, self } = v;
  if (phase === 'NO_ENTRIES') return self ? 'Aún no has anotado nada hoy.' : 'Aún no hay nada anotado hoy.';
  const suffix = uncounted > 0 ? ` Faltan datos de ${uncounted === 1 ? '1 alimento' : `${uncounted} alimentos`}.` : '';
  const sugars = headline.find((x) => x.code === SUGARS);
  if (sugars && sugars.state.tone === 'caution') {
    return (self ? 'Hoy te has pasado de azúcares libres.' : 'Hoy se ha pasado de azúcares libres.') + suffix;
  }
  const names = (pick: (h: Headline) => boolean) => headline.filter(pick).map((h) => nutrientName(h.code));
  if (phase === 'OPEN_TODAY') {
    const core = headline.filter((h) => h.code === ENERGY || h.code === PROTEIN || h.code === FIBER);
    let text: string;
    if (core.length > 0 && core.every((h) => h.state.tone === 'plain')) {
      text = 'Día abierto.';
    } else {
      const above = core.filter((h) => h.state.tone === 'caution').map((h) => nutrientName(h.code));
      if (above.length > 0) text = `${self ? 'Vas' : 'Va'} por encima en ${spanishList(above)}.`;
      else text = self ? 'Vas en camino.' : 'Va en camino.';
      const lacking = names((h) => h.kind === 'MIN' && h.state.tone === 'progress');
      if (lacking.length === 1) text += ` ${self ? 'Te falta' : 'Le falta'} ${lacking[0]}.`;
      else if (lacking.length > 1) text += ` ${self ? 'Te faltan' : 'Le faltan'} ${spanishList(lacking)}.`;
    }
    return text + suffix;
  }
  if (phase === 'OPEN_PAST') return `Día sin cerrar.${suffix}`;
  const parts: string[] = [];
  const ok = names((h) => h.state.tone === 'ok');
  const short = names((h) => h.state.word === 'corto' || h.state.word === 'bajo');
  const over = names((h) => h.state.word === 'por encima');
  if (ok.length > 0) parts.push(`bien en ${spanishList(ok)}`);
  if (short.length > 0) parts.push(`corto en ${spanishList(short)}`);
  if (over.length > 0) parts.push(`por encima en ${spanishList(over)}`);
  return (parts.length > 0 ? `Día cerrado: ${parts.join('; ')}.` : 'Día cerrado.') + suffix;
}

const GROUP_ORDER: GroupKey[] = ['short', 'fine', 'missing', 'plain'];

function groupOf(tone: Tone): GroupKey {
  if (tone === 'caution') return 'short';
  if (tone === 'ok') return 'fine';
  if (tone === 'plain') return 'plain';
  return 'missing';
}

export function groupWeekly<T extends { code: string; state: NutrientState }>(items: T[]): WeeklyGroup<T>[] {
  return GROUP_ORDER.flatMap((key) => {
    const inGroup = items.filter((i) => groupOf(i.state.tone) === key);
    if (inGroup.length === 0) return [];
    const summary = key === 'short' ? `Corto: ${inGroup.map((i) => nutrientName(i.code)).join(', ')}`
      : key === 'fine' ? `Bien: ${inGroup.length}`
      : key === 'missing' ? `Faltan datos: ${inGroup.length}`
      : `Sin objetivo: ${inGroup.length}`;
    return [{ key, summary, items: inGroup }];
  });
}
