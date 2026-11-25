import { HEADLINE_NUTRIENTS, type DiaryDay, type DiaryItem, type HeadlineNutrient } from '../../../integration/nutrition/diary-contract.ts';
import {
  amount, berlinClock, measurement, nutrientLabel, nutrientName, spanishList, unitLabel, unitOf,
} from '../../../integration/nutrition/nutrition-format.ts';
import {
  barFor, dayPhase, dayState, limitTarget, verdict,
  type Bar, type DayInput, type DayPhase, type Headline, type NutrientState,
} from '../../../integration/nutrition/nutrient-status.ts';
import type { DataEnvelope } from '../../../integration/state/DataEnvelope.ts';
import { panelError, type PanelErrorKind } from './panel-error.ts';

export type HeadlineCode = HeadlineNutrient | 'free_sugars_g';
export interface HeadlineRow { code: HeadlineCode; name: string; amount: string | null; bar: Bar | null; state: NutrientState }
export interface MealLine { time: string; summary: string; items: { text: string; sugar: string; note: string | null }[] }
export type TodayPanelModel =
  | { kind: 'LOADING' | PanelErrorKind }
  | {
      kind: 'TODAY';
      verdict: string;
      rows: HeadlineRow[];
      quietLine: string | null;
      profileHint: 'SELF' | 'VIEWER' | null;
      prenatalNote: string | null;
      meals: MealLine[];
      sources: { reference: string | null; attribution: string[] };
    };

const SUGARS = 'free_sugars_g';

/** "15.9" -> "15,9 g"; "1250" -> "1.250 g". The wire decimal is only formatted, never calculated. */
const grams = (decimal: string) => `${measurement(decimal)} g`;

const UNIT_LABELS: Record<string, [string, string]> = {
  serving: ['porción del envase', 'porciones del envase'],
  small_glass: ['vaso pequeño', 'vasos pequeños'],
  glass: ['vaso', 'vasos'],
  large_glass: ['vaso grande', 'vasos grandes'],
  cup: ['taza', 'tazas'],
  can: ['lata', 'latas'],
  tablespoon: ['cucharada', 'cucharadas'],
  teaspoon: ['cucharadita', 'cucharaditas'],
  piece: ['unidad', 'unidades'],
  slice: ['rebanada', 'rebanadas'],
  plate: ['plato', 'platos'],
  portion: ['porción', 'porciones'],
};

function portion(item: DiaryItem): string {
  const count = measurement(item.amount);
  if (item.method === 'USER_STATED' && (item.unit === 'g' || item.unit === 'ml')) return `${count} ${item.unit}`;
  const names = Object.hasOwn(UNIT_LABELS, item.unit) ? UNIT_LABELS[item.unit] : null;
  const unit = names ? names[Number(item.amount) === 1 ? 0 : 1] : item.unit;
  const approx = item.method === 'PRESET' || item.method === 'AGENT_ESTIMATE' ? '~' : '';
  return `${count} ${unit} (${approx}${grams(item.grams)})`;
}

/** What the recorded food lacks: no match at all, or the headline nutrients and free sugars it has no value for. */
function itemNote(item: DiaryItem): string | null {
  if (item.source === null) return 'sin coincidencia en la base de alimentos';
  const missing = HEADLINE_NUTRIENTS.filter((code) => !item.withFacts.includes(code)).map(nutrientName);
  if (item.freeSugarsG === null) missing.push(nutrientName(SUGARS));
  return missing.length > 0 ? `sin datos de ${spanishList(missing)}` : null;
}

function meals(day: DiaryDay): MealLine[] {
  return day.entries.map((entry) => {
    const time = berlinClock(new Date(entry.consumedAt));
    return {
      time,
      summary: `${time} · ${entry.items.map((item) => item.label).join(', ')}`,
      items: entry.items.map((item) => ({
        text: `${item.label}, ${portion(item)}`,
        sugar: item.freeSugarsG === null ? 'sin dato' : grams(item.freeSugarsG),
        note: itemNote(item),
      })),
    };
  });
}

/** "known de target unit", or the value alone without a target; null when nothing was recorded today. */
function rowAmount(code: HeadlineCode, input: DayInput, phase: DayPhase): string | null {
  if (phase === 'NO_ENTRIES') return null;
  if (input.known === null) return 'sin dato';
  const { target } = input;
  if (target !== null) {
    return `${amount(input.known, target.unit)} de ${amount(target.displayValue, target.unit)} ${unitLabel(target.unit)}`;
  }
  const unit = unitOf(code);
  return `${amount(input.known, unit)} ${unitLabel(unit)}`;
}

function row(code: HeadlineCode, input: DayInput, phase: DayPhase): HeadlineRow {
  return {
    code,
    name: nutrientLabel(code),
    amount: rowAmount(code, input, phase),
    bar: barFor(input.target, input.known, phase),
    state: dayState(input, phase),
  };
}

function quiet(day: DiaryDay, code: 'fat_g' | 'carb_g'): string {
  const known = day.nutrients[code].known;
  return `${nutrientLabel(code)} ${known === null ? 'sin dato' : `${amount(known, 'g')} g`}`;
}

function toToday(day: DiaryDay, self: boolean): TodayPanelModel {
  const phase = dayPhase(day.dayStatus, true); // Hoy is always today
  const sugars: DayInput = {
    known: day.freeSugarsKnownG,
    status: day.sugarStatus,
    target: day.limit === null ? null : limitTarget(day.limit.valueG),
    percent: null,
  };
  const inputs: [HeadlineCode, DayInput][] = [
    ...HEADLINE_NUTRIENTS.map((code): [HeadlineCode, DayInput] => [code, day.nutrients[code]]),
    [SUGARS, sugars],
  ];
  const rows = inputs.map(([code, input]) => row(code, input, phase));
  const headline: Headline[] = inputs.map(([code, input], i) => ({
    code,
    kind: code === SUGARS ? 'MAX' : input.target?.kind ?? null,
    state: rows[i].state,
  }));
  // The foods the day could not count: the largest uncounted figure among the four rows. A row is
  // KNOWN only when nothing is uncounted, so this also covers a row with no data at all (NONE).
  const uncounted = Math.max(0, ...HEADLINE_NUTRIENTS.map((code) => day.nutrients[code].itemsUncounted), day.itemsUncounted);
  const pregnant = day.mode === 'PREGNANCY';
  return {
    kind: 'TODAY',
    verdict: verdict({ phase, headline, uncounted, self }),
    rows,
    quietLine: phase === 'NO_ENTRIES' ? null : `${quiet(day, 'fat_g')} · ${quiet(day, 'carb_g')}`,
    profileHint: day.nutrients.energy_kcal.target !== null ? null : self ? 'SELF' : 'VIEWER',
    prenatalNote: !pregnant
      ? null
      : `${self ? 'Tu' : 'El'} prenatal aún no se cuenta: folato, yodo, vitamina D y DHA pueden estar cubiertos.`,
    meals: meals(day),
    sources: {
      reference: day.limit === null
        ? null
        : `Referencia general: ${grams(day.limit.valueG)} de azúcares libres al día (OMS, DGE). No es una indicación médica.`,
      attribution: day.attribution,
    },
  };
}

/** Fixed-vocabulary label for the one log line per read. */
export function todayOutcome(model: TodayPanelModel): string {
  return model.kind;
}

/**
 * Map one adapter envelope to exactly one deliberate panel. `self` is true when the viewer is the
 * subject: only then is copy addressed to the reader. Pure; no React, no server imports.
 */
export function toTodayPanelModel(envelope: DataEnvelope<DiaryDay>, self: boolean): TodayPanelModel {
  switch (envelope.delivery) {
    case 'LOADING':
      return { kind: 'LOADING' };
    case 'ERROR':
      return { kind: panelError(envelope.errorCode) };
    case 'READY':
      // A non-LIVE READY envelope (MOCK) is never shown: its empty day carries no real date.
      if (envelope.environment !== 'LIVE' || envelope.authorization !== 'GRANTED' || !envelope.data) {
        return { kind: 'NOT_CONFIGURED' };
      }
      return toToday(envelope.data, self);
    default:
      return { kind: 'UNAVAILABLE' };
  }
}
