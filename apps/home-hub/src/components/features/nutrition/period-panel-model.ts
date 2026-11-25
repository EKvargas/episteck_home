import { amount, dayOfMonth, nutrientLabel, unitLabel, unitOf, weekdayInitial } from '../../../integration/nutrition/nutrition-format.ts';
import { nutritionHref } from '../../../integration/nutrition/nutrition-href.ts';
import {
  dayPhase, dayState, limitTarget, type DayInput, type Tone, type WeeklyGroup,
} from '../../../integration/nutrition/nutrient-status.ts';
import type { AveragedNutrient, PeriodDay, PeriodSummary } from '../../../integration/nutrition/period-contract.ts';
import type { RangeDays } from '../../../integration/nutrition/period-range.ts';
import type { DataEnvelope } from '../../../integration/state/DataEnvelope.ts';
import { panelError, type PanelErrorKind } from './panel-error.ts';
import type { HeadlineCode } from './today-panel-model.ts';
import { microGroups, type WeeklyRow } from './weekly-model.ts';

export interface GridCell { tone: Tone; text: string }
export interface GridRow { code: HeadlineCode; name: string; href: string; cells: GridCell[]; average: string | null }
export interface LegendItem { tone: Tone; words: string }
export interface Grid { columns: { initial: string; day: string; date: string }[]; rows: GridRow[] }
export type PeriodPanelModel =
  | { kind: 'LOADING' | PanelErrorKind }
  | {
      kind: 'PERIOD';
      range: RangeDays;
      title: string;
      grids: Grid[];
      legend: LegendItem[];
      micro: WeeklyGroup<WeeklyRow>[];
      profileHint: boolean;
    };

const GRID_DAYS = 7;
const ROWS: HeadlineCode[] = ['energy_kcal', 'protein_g', 'fiber_g', 'free_sugars_g'];

function withUnit(decimal: string, unit: string): string {
  return `${amount(decimal, unit)} ${unitLabel(unit)}`;
}

function inputFor(day: PeriodDay, code: HeadlineCode): DayInput {
  if (code !== 'free_sugars_g') return day.nutrients[code];
  const { freeSugars } = day;
  return {
    known: freeSugars.known,
    status: freeSugars.status,
    target: freeSugars.limitG === null ? null : limitTarget(freeSugars.limitG),
    percent: null,
  };
}

function cellFor(day: PeriodDay, code: HeadlineCode, isToday: boolean): GridCell {
  const input = inputFor(day, code);
  const state = dayState(input, dayPhase(day.dayStatus, isToday));
  if (state.word !== null) return { tone: state.tone, text: state.word };
  return { tone: state.tone, text: input.known === null ? 'sin dato' : withUnit(input.known, unitOf(code)) };
}

function averageFor(summary: PeriodSummary, code: HeadlineCode): string {
  const a = summary.averages[code as AveragedNutrient];
  if (a.daysUsed === 0 || a.averageKnown === null) return 'sin dato';
  return withUnit(a.averageKnown, unitOf(code));
}

const LEGEND_ORDER: Tone[] = ['ok', 'caution', 'progress', 'unclosed', 'unknown', 'empty', 'plain'];
const CAUTION_WORDS = ['corto', 'bajo', 'por encima', 'pasado del límite'];

/** The states the grids actually show, in status-language order, each with the words its dot stands for. */
export function legendFor(grids: Grid[]): LegendItem[] {
  const seen = new Map<Tone, Set<string>>();
  for (const grid of grids) {
    for (const row of grid.rows) {
      for (const cell of row.cells) {
        // A dot's word: the state word, with "en curso · faltan X" cut to "en curso"; a plain cell has none.
        const word = cell.tone === 'plain' ? 'sin objetivo' : cell.text.split(' · ')[0];
        seen.set(cell.tone, (seen.get(cell.tone) ?? new Set()).add(word));
      }
    }
  }
  return LEGEND_ORDER.filter((tone) => seen.has(tone)).map((tone) => {
    const words = [...seen.get(tone)!];
    if (tone === 'caution') words.sort((a, b) => CAUTION_WORDS.indexOf(a) - CAUTION_WORDS.indexOf(b));
    return { tone, words: words.join(' · ') };
  });
}

function toPeriod(summary: PeriodSummary, range: RangeDays, person: string | null): PeriodPanelModel {
  const grids: Grid[] = [];
  for (let from = 0; from < summary.days.length; from += GRID_DAYS) {
    const days = summary.days.slice(from, from + GRID_DAYS);
    const last = from + GRID_DAYS >= summary.days.length;
    grids.push({
      columns: days.map((d) => ({ initial: weekdayInitial(d.date), day: dayOfMonth(d.date), date: d.date })),
      rows: ROWS.map((code) => ({
        code,
        name: nutrientLabel(code),
        href: nutritionHref(`/nutrition/nutriente/${code}`, person, { rango: String(range) }),
        cells: days.map((d) => cellFor(d, code, d.date === summary.end)),
        average: last ? averageFor(summary, code) : null,
      })),
    });
  }
  return {
    kind: 'PERIOD',
    range,
    title: `Últimos ${range} días`,
    grids,
    legend: legendFor(grids),
    micro: microGroups(summary, range, person),
    profileHint: !summary.hasProfile,
  };
}

/** Fixed-vocabulary label for the one log line per read. */
export function periodOutcome(model: PeriodPanelModel): string {
  return model.kind;
}

/** Map one adapter envelope to exactly one deliberate panel. Pure; formats, never calculates. */
export function toPeriodPanelModel(
  envelope: DataEnvelope<PeriodSummary>, range: RangeDays, person: string | null,
): PeriodPanelModel {
  switch (envelope.delivery) {
    case 'LOADING':
      return { kind: 'LOADING' };
    case 'ERROR':
      return { kind: panelError(envelope.errorCode) };
    case 'READY':
      if (envelope.environment !== 'LIVE' || envelope.authorization !== 'GRANTED' || !envelope.data) {
        return { kind: 'NOT_CONFIGURED' };
      }
      return toPeriod(envelope.data, range, person);
    default:
      return { kind: 'UNAVAILABLE' };
  }
}
