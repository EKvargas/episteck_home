import type { NutrientBlock } from '../../../integration/nutrition/diary-contract.ts';
import { amount, weekdayDay } from '../../../integration/nutrition/nutrition-format.ts';
import type { PeriodAverage, PeriodDay, PeriodSummary } from '../../../integration/nutrition/period-contract.ts';
import type { RangeDays } from '../../../integration/nutrition/period-range.ts';
import type { DataEnvelope } from '../../../integration/state/DataEnvelope.ts';
import type { SafeUIErrorCode } from '../../../integration/state/SafeUIErrorCode.ts';

export type Cell = { value: string; detail: string | null; unknown: boolean };
export type PeriodRow = {
  day: string;
  status: string | null;
  tone: 'ok' | 'open' | 'none' | null;
  cells: [Cell, Cell, Cell, Cell];
};
export type PeriodPanelModel =
  | { kind: 'LOADING' | 'DENIED' | 'SESSION' | 'UNAVAILABLE' | 'INVALID' | 'NOT_CONFIGURED' }
  | { kind: 'PERIOD'; range: RangeDays; title: string; rows: PeriodRow[]; average: PeriodRow; profileHint: boolean };

const UNKNOWN: Cell = { value: 'sin dato', detail: null, unknown: true };
const NO_ENTRIES: Cell = { value: '—', detail: null, unknown: false };
const STATUS: Record<PeriodDay['dayStatus'], { label: string; tone: 'ok' | 'open' | 'none' }> = {
  COMPLETE: { label: 'Cerrado', tone: 'ok' },
  OPEN: { label: 'Abierto', tone: 'open' },
  NO_ENTRIES: { label: 'Sin registros', tone: 'none' },
};

/** `<percent> %`, then `parcial` when the figure leaves food out. */
function dayCell(known: string | null, percent: string | null, partial: boolean, unit: string): Cell {
  if (known === null) return { ...UNKNOWN };
  const parts = [percent === null ? null : `${percent} %`, partial ? 'parcial' : null].filter((p) => p !== null);
  return { value: withUnit(known, unit), detail: parts.length > 0 ? parts.join(' · ') : null, unknown: false };
}

function withUnit(decimal: string, unit: string): string {
  const text = amount(decimal, unit);
  return unit === 'kcal' ? text : `${text} ${unit}`;
}

function blockCell(block: NutrientBlock, unit: string): Cell {
  return dayCell(block.known, block.percent, block.status === 'PARTIAL', unit);
}

function averageCell(a: PeriodAverage, unit: string): Cell {
  if (a.daysUsed === 0 || a.averageKnown === null) return { ...UNKNOWN };
  const days = `${a.daysUsed} ${a.daysUsed === 1 ? 'día' : 'días'}`;
  return {
    value: withUnit(a.averageKnown, unit),
    detail: a.averagePercent === null ? days : `${a.averagePercent} % · ${days}`,
    unknown: false,
  };
}

function toRow(day: PeriodDay): PeriodRow {
  const status = STATUS[day.dayStatus];
  const cells: [Cell, Cell, Cell, Cell] = day.dayStatus === 'NO_ENTRIES'
    ? [{ ...NO_ENTRIES }, { ...NO_ENTRIES }, { ...NO_ENTRIES }, { ...NO_ENTRIES }]
    : [
        blockCell(day.nutrients.energy_kcal, 'kcal'),
        blockCell(day.nutrients.protein_g, 'g'),
        blockCell(day.nutrients.fiber_g, 'g'),
        dayCell(day.freeSugars.known, day.freeSugars.percent, day.freeSugars.status === 'PARTIAL', 'g'),
      ];
  return { day: weekdayDay(day.date), status: status.label, tone: status.tone, cells };
}

function toPeriod(summary: PeriodSummary, range: RangeDays): PeriodPanelModel {
  const a = summary.averages;
  return {
    kind: 'PERIOD',
    range,
    title: `Últimos ${range} días`,
    rows: summary.days.map(toRow),
    average: {
      day: 'Media', status: null, tone: null,
      cells: [
        averageCell(a.energy_kcal, 'kcal'), averageCell(a.protein_g, 'g'),
        averageCell(a.fiber_g, 'g'), averageCell(a.free_sugars_g, 'g'),
      ],
    },
    profileHint: !summary.hasProfile,
  };
}

function errorModel(code: SafeUIErrorCode | undefined): PeriodPanelModel {
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
export function periodOutcome(model: PeriodPanelModel): string {
  return model.kind;
}

/** Map one adapter envelope to exactly one deliberate panel. Pure; formats, never calculates. */
export function toPeriodPanelModel(envelope: DataEnvelope<PeriodSummary>, range: RangeDays): PeriodPanelModel {
  switch (envelope.delivery) {
    case 'LOADING':
      return { kind: 'LOADING' };
    case 'ERROR':
      return errorModel(envelope.errorCode);
    case 'READY':
      if (envelope.environment !== 'LIVE' || envelope.authorization !== 'GRANTED' || !envelope.data) {
        return { kind: 'NOT_CONFIGURED' };
      }
      return toPeriod(envelope.data, range);
    default:
      return { kind: 'UNAVAILABLE' };
  }
}
