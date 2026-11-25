import { DAY_NUTRIENTS, type DayNutrient } from '../../../integration/nutrition/diary-contract.ts';
import {
  amount, nutrientLabel, targetValue, unitLabel, unitOf, weekdayDay,
} from '../../../integration/nutrition/nutrition-format.ts';
import { nutritionHref } from '../../../integration/nutrition/nutrition-href.ts';
import {
  barFor, dayPhase, dayState, latestTarget, limitTarget, weeklyState,
  type Bar, type DayInput, type NutrientState, type Target, type Tone,
} from '../../../integration/nutrition/nutrient-status.ts';
import type { AveragedNutrient, PeriodDay, PeriodSummary } from '../../../integration/nutrition/period-contract.ts';
import type { DataEnvelope } from '../../../integration/state/DataEnvelope.ts';
import { panelError, type PanelErrorKind } from './panel-error.ts';

/** The fifteen day nutrients, then free sugars: the codes the detail page accepts. */
export const DETAIL_CODES: readonly (DayNutrient | 'free_sugars_g')[] = [...DAY_NUTRIENTS, 'free_sugars_g'];
export type DetailCode = (typeof DETAIL_CODES)[number];

/** A route segment to a known code; anything else (including prototype names) is null. */
export function detailCode(raw: string): DetailCode | null {
  return DETAIL_CODES.find((code) => code === raw) ?? null;
}

export interface DetailDay {
  day: string;
  /** Displayed amount, or null when nothing is known. */
  value: string | null;
  bar: Bar | null;
  tone: Tone;
  /** The state word beside a bar (closed days only). */
  word: string | null;
  /** The reason a day has no bar; null when it has one, or when there is no target to judge by. */
  note: string | null;
}

export type NutrientDetailModel =
  | { kind: 'LOADING' | PanelErrorKind }
  | {
      kind: 'DETAIL';
      name: string;
      average: string;
      target: string | null;
      state: NutrientState;
      days: DetailDay[];
      targetLine: string | null;
      profileLink: { text: string; href: string };
    };

function inputFor(day: PeriodDay, code: DetailCode): DayInput {
  if (code !== 'free_sugars_g') return day.nutrients[code];
  const { freeSugars } = day;
  return {
    known: freeSugars.known,
    status: freeSugars.status,
    target: freeSugars.limitG === null ? null : limitTarget(freeSugars.limitG),
    percent: null,
  };
}

/** The most recent target: a day's nutrient target, or for free sugars the last limit. */
function latestFor(days: PeriodDay[], code: DetailCode): Target {
  if (code !== 'free_sugars_g') return latestTarget(days, code);
  for (let i = days.length - 1; i >= 0; i--) {
    const limit = days[i].freeSugars.limitG;
    if (limit !== null) return limitTarget(limit);
  }
  return null;
}

function targetLineFor(target: Target): string | null {
  if (target === null) return null;
  const shown = `${amount(target.displayValue, target.unit)} ${unitLabel(target.unit)}`;
  if (target.kind === 'MIN') return `Objetivo diario: al menos ${shown}.`;
  if (target.kind === 'ABOUT') return `Objetivo diario: alrededor de ${shown}.`;
  return `Límite diario: como máximo ${shown}.`;
}

function dayFor(day: PeriodDay, code: DetailCode, isToday: boolean, unit: string): DetailDay {
  const input = inputFor(day, code);
  const phase = dayPhase(day.dayStatus, isToday);
  const state = dayState(input, phase);
  const value = input.known === null ? null : `${amount(input.known, unit)} ${unitLabel(unit)}`;
  const base = { day: weekdayDay(day.date), tone: state.tone };
  if (phase === 'NO_ENTRIES') return { ...base, value: null, bar: null, word: null, note: 'sin registros' };
  if (phase === 'OPEN_TODAY') return { ...base, value, bar: null, word: null, note: 'abierto' };
  if (phase === 'OPEN_PAST') return { ...base, value, bar: null, word: null, note: 'sin cerrar' };
  if (input.target === null) return { ...base, value, bar: null, word: null, note: null };
  if (input.known === null) return { ...base, value: null, bar: null, word: null, note: 'faltan datos' };
  return { ...base, value, bar: barFor(input.target, input.known, phase), word: state.word, note: null };
}

function toDetail(summary: PeriodSummary, code: DetailCode, self: boolean, person: string | null): NutrientDetailModel {
  const target = latestFor(summary.days, code);
  const unit = target?.unit ?? unitOf(code);
  const average = summary.averages[code as AveragedNutrient];
  return {
    kind: 'DETAIL',
    name: nutrientLabel(code),
    average: average.averageKnown === null ? 'sin dato' : `${amount(average.averageKnown, unit)} ${unitLabel(unit)}`,
    target: target === null ? null : targetValue(target.kind, target.displayValue, target.unit),
    state: weeklyState(average, target),
    days: summary.days.map((d) => dayFor(d, code, d.date === summary.end, unit)),
    targetLine: targetLineFor(target),
    profileLink: {
      text: self ? 'Ver de dónde sale en tu perfil' : 'Ver de dónde sale en su perfil',
      href: nutritionHref('/nutrition/perfil', person),
    },
  };
}

/** Fixed-vocabulary label for the one log line per read. */
export function nutrientDetailOutcome(model: NutrientDetailModel): string {
  return model.kind;
}

/** Map one adapter envelope to exactly one deliberate panel. Pure; formats, never calculates. */
export function toNutrientDetailModel(
  envelope: DataEnvelope<PeriodSummary>, code: DetailCode, self: boolean, person: string | null,
): NutrientDetailModel {
  switch (envelope.delivery) {
    case 'LOADING':
      return { kind: 'LOADING' };
    case 'ERROR':
      return { kind: panelError(envelope.errorCode) };
    case 'READY':
      if (envelope.environment !== 'LIVE' || envelope.authorization !== 'GRANTED' || !envelope.data) {
        return { kind: 'NOT_CONFIGURED' };
      }
      return toDetail(envelope.data, code, self, person);
    default:
      return { kind: 'UNAVAILABLE' };
  }
}
