import {
  arr, count, DAY_NUTRIENTS, decimalOrNull, obj, parseNutrientBlock,
  type DayNutrient, type NutrientBlock,
} from './diary-contract.ts';

export interface PeriodDay {
  date: string;
  dayStatus: 'NO_ENTRIES' | 'OPEN' | 'COMPLETE';
  mode: 'GENERAL' | 'PREGNANCY';
  trimester: 1 | 2 | 3 | null;
  nutrients: Record<DayNutrient, NutrientBlock>;
  freeSugars: {
    known: string | null; itemsUncounted: number; status: 'NONE' | 'KNOWN' | 'PARTIAL';
    limitG: string | null; percent: string | null;
  };
}
export interface PeriodAverage {
  averageKnown: string | null;
  averagePercent: string | null;
  daysUsed: number;
  leftOut: { open: number; noEntries: number; partial: number };
}
export type AveragedNutrient = DayNutrient | 'free_sugars_g';
export interface PeriodSummary {
  start: string; end: string; hasProfile: boolean; days: PeriodDay[];
  averages: Record<AveragedNutrient, PeriodAverage>;
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const DAY_STATUSES: readonly string[] = ['NO_ENTRIES', 'OPEN', 'COMPLETE'];
const MODES: readonly string[] = ['GENERAL', 'PREGNANCY'];
const STATUSES: readonly string[] = ['NONE', 'KNOWN', 'PARTIAL'];
const AVERAGED: readonly AveragedNutrient[] = [...DAY_NUTRIENTS, 'free_sugars_g'];
const MAX_DAYS = 31;

function bad(what: string): never {
  throw new TypeError(`period: invalid ${what}`);
}

function isoDate(value: unknown, what: string): string {
  if (typeof value !== 'string' || !ISO_DATE.test(value)) bad(what);
  return value as string;
}

function oneOf(value: unknown, allowed: readonly string[], what: string): string {
  if (typeof value !== 'string' || !allowed.includes(value)) bad(what);
  return value as string;
}

function parseDay(raw: unknown): PeriodDay {
  const day = obj(raw, 'day');
  const trimester = day.trimester ?? null;
  if (trimester !== null && trimester !== 1 && trimester !== 2 && trimester !== 3) bad('trimester');
  const wire = obj(day.nutrients, 'nutrients');
  const nutrients = {} as Record<DayNutrient, NutrientBlock>;
  for (const code of DAY_NUTRIENTS) nutrients[code] = parseNutrientBlock(wire[code], code);
  const sugars = obj(day.free_sugars, 'free_sugars');
  return {
    date: isoDate(day.date, 'date'),
    dayStatus: oneOf(day.day_status, DAY_STATUSES, 'day_status') as PeriodDay['dayStatus'],
    mode: oneOf(day.mode, MODES, 'mode') as PeriodDay['mode'],
    trimester: trimester as PeriodDay['trimester'],
    nutrients,
    freeSugars: {
      known: decimalOrNull(sugars.known, 'free_sugars known'),
      itemsUncounted: count(sugars.items_uncounted, 'free_sugars items_uncounted'),
      status: oneOf(sugars.status, STATUSES, 'free_sugars status') as PeriodDay['freeSugars']['status'],
      limitG: decimalOrNull(sugars.limit_g, 'free_sugars limit_g'),
      percent: decimalOrNull(sugars.percent, 'free_sugars percent'),
    },
  };
}

function parseAverage(raw: unknown, what: string): PeriodAverage {
  const a = obj(raw, what);
  const left = obj(a.left_out, `${what} left_out`);
  return {
    averageKnown: decimalOrNull(a.average_known, `${what} average_known`),
    averagePercent: decimalOrNull(a.average_percent, `${what} average_percent`),
    daysUsed: count(a.days_used, `${what} days_used`),
    leftOut: {
      open: count(left.open, `${what} left_out open`),
      noEntries: count(left.no_entries, `${what} left_out no_entries`),
      partial: count(left.partial, `${what} left_out partial`),
    },
  };
}

/**
 * Strict mapper for Nutrition's GET /diary/{id}/period 200 body: 1 to 31 days, fifteen nutrients
 * per day and sixteen averages. Throws TypeError on any malformed required field; unknown wire fields are
 * ignored.
 */
export function parsePeriodWire(body: unknown): PeriodSummary {
  const period = obj(body, 'period');
  if (typeof period.has_profile !== 'boolean') bad('has_profile');
  const days = arr(period.days, 'days');
  if (days.length < 1 || days.length > MAX_DAYS) bad('days length');
  const wire = obj(period.averages, 'averages');
  const averages = {} as Record<AveragedNutrient, PeriodAverage>;
  for (const code of AVERAGED) averages[code] = parseAverage(wire[code], `average ${code}`);
  return {
    start: isoDate(period.start, 'start'),
    end: isoDate(period.end, 'end'),
    hasProfile: period.has_profile,
    days: days.map(parseDay),
    averages,
  };
}

