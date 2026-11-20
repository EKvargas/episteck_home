import type { DiaryDay, DiaryItem } from '../../../integration/nutrition/diary-contract.ts';
import type { DataEnvelope } from '../../../integration/state/DataEnvelope.ts';
import type { SafeUIErrorCode } from '../../../integration/state/SafeUIErrorCode.ts';

export type TodayPanelModel =
  | { kind: 'LOADING' | 'DENIED' | 'SESSION' | 'UNAVAILABLE' | 'INVALID' | 'NOT_CONFIGURED' }
  | {
      kind: 'TODAY';
      heading: string;
      sugarLine: string;
      meter: { valueG: number; limitG: number } | null;
      statusLine: string;
      entries: { time: string; items: { text: string; sugar: string }[] }[];
      referenceLine: string | null;
      attribution: string[];
    };

const NUMBER = new Intl.NumberFormat('es-ES', { maximumFractionDigits: 1 });
const CLOCK = new Intl.DateTimeFormat('es-ES', { timeZone: 'Europe/Berlin', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });

/** "15.9" -> "15,9 g"; "17.0" -> "17 g". The wire decimal is parsed only to be displayed. */
const grams = (decimal: string) => `${NUMBER.format(Number(decimal))} g`;

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
  const amount = NUMBER.format(Number(item.amount));
  if (item.method === 'USER_STATED' && (item.unit === 'g' || item.unit === 'ml')) return `${amount} ${item.unit}`;
  const names = Object.hasOwn(UNIT_LABELS, item.unit) ? UNIT_LABELS[item.unit] : null;
  const unit = names ? names[Number(item.amount) === 1 ? 0 : 1] : item.unit;
  const approx = item.method === 'PRESET' || item.method === 'AGENT_ESTIMATE' ? '~' : '';
  return `${amount} ${unit} (${approx}${grams(item.grams)})`;
}

const TRIMESTERS: Record<1 | 2 | 3, string> = { 1: '1.er trimestre', 2: '2.º trimestre', 3: '3.er trimestre' };

function heading(day: DiaryDay): string {
  if (day.mode !== 'PREGNANCY') return 'Hoy';
  return day.trimester === null ? 'Hoy · Embarazo' : `Hoy · Embarazo, ${TRIMESTERS[day.trimester]}`;
}

function statusLine(day: DiaryDay): string {
  const base = day.dayStatus === 'NO_ENTRIES' ? 'Sin registros hoy' : day.dayStatus === 'OPEN' ? 'Día abierto' : 'Día cerrado';
  if (day.sugarStatus !== 'PARTIAL') return base;
  return `${base} · ${day.itemsUncounted === 1 ? '1 alimento sin contar' : `${day.itemsUncounted} alimentos sin contar`}`;
}

function sugarLine(day: DiaryDay): string {
  if (day.dayStatus === 'NO_ENTRIES') return 'Azúcares libres: sin registros todavía';
  if (day.freeSugarsKnownG === null) return 'Azúcares libres: sin dato';
  const known = grams(day.freeSugarsKnownG);
  if (day.limit === null) return `Azúcares libres: ${known}`;
  const over = Number(day.freeSugarsKnownG) > Number(day.limit.valueG) ? ' (por encima de la referencia)' : '';
  return `Azúcares libres: ${known} de ${grams(day.limit.valueG)}${over}`;
}

function toToday(day: DiaryDay): TodayPanelModel {
  const hasFigure = day.dayStatus !== 'NO_ENTRIES' && day.freeSugarsKnownG !== null && day.limit !== null;
  return {
    kind: 'TODAY',
    heading: heading(day),
    sugarLine: sugarLine(day),
    meter: hasFigure ? { valueG: Number(day.freeSugarsKnownG), limitG: Number(day.limit?.valueG) } : null,
    statusLine: statusLine(day),
    entries: day.entries.map((entry) => ({
      time: CLOCK.format(new Date(entry.consumedAt)),
      items: entry.items.map((item) => ({
        text: `${item.label}, ${portion(item)}`,
        sugar: item.freeSugarsG === null ? 'sin dato' : grams(item.freeSugarsG),
      })),
    })),
    referenceLine: day.limit === null
      ? null
      : `Referencia general: ${grams(day.limit.valueG)} de azúcares libres al día (OMS, DGE). No es una indicación médica.`,
    attribution: day.attribution,
  };
}

function errorModel(code: SafeUIErrorCode | undefined): TodayPanelModel {
  switch (code) {
    case 'ACCESS_DENIED':
      return { kind: 'DENIED' };
    case 'SESSION_INVALID':
    case 'SESSION_REQUIRED':
      return { kind: 'SESSION' };
    case 'NOT_CONFIGURED':
      return { kind: 'NOT_CONFIGURED' };
    case 'INVALID_RESPONSE':
      return { kind: 'INVALID' };
    default:
      return { kind: 'UNAVAILABLE' };
  }
}

/** Fixed-vocabulary label for the one log line per read. */
export function todayOutcome(model: TodayPanelModel): string {
  return model.kind;
}

/** Map one adapter envelope to exactly one deliberate panel. Pure; no React, no server imports. */
export function toTodayPanelModel(envelope: DataEnvelope<DiaryDay>): TodayPanelModel {
  switch (envelope.delivery) {
    case 'LOADING':
      return { kind: 'LOADING' };
    case 'ERROR':
      return errorModel(envelope.errorCode);
    case 'READY':
      // A non-LIVE READY envelope (MOCK) is never shown: its empty day carries no real date.
      if (envelope.environment !== 'LIVE' || envelope.authorization !== 'GRANTED' || !envelope.data) {
        return { kind: 'NOT_CONFIGURED' };
      }
      return toToday(envelope.data);
    default:
      return { kind: 'UNAVAILABLE' };
  }
}
