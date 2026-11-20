export type DayStatus = 'NO_ENTRIES' | 'OPEN' | 'COMPLETE';
export type SugarStatus = 'NONE' | 'KNOWN' | 'PARTIAL';
export type ConversionMethod = 'USER_STATED' | 'SOURCE_SERVING' | 'PRESET' | 'AGENT_ESTIMATE';

export interface DiaryItem {
  label: string;
  /** Keeps the wire value as text; never reformatted. */
  amount: string;
  unit: string;
  grams: string;
  /** conversion.method */
  method: ConversionMethod;
  /** facts.source, or null when no source knows the food. */
  source: string | null;
  /** free_sugars_g; null means unknown, never zero. */
  freeSugarsG: string | null;
}
/** consumed_at on the wire. */
export interface DiaryEntry { id: string; consumedAt: string; items: DiaryItem[] }
/** value_g on the wire. */
export interface DiaryLimit { valueG: string; sources: { title: string; url: string }[] }
export interface DiaryDay {
  date: string;
  mode: 'GENERAL' | 'PREGNANCY';
  trimester: 1 | 2 | 3 | null;
  /** day_status */
  dayStatus: DayStatus;
  /** sugar_status */
  sugarStatus: SugarStatus;
  /** free_sugars_known_g; null when nothing is known. */
  freeSugarsKnownG: string | null;
  /** items_total */
  itemsTotal: number;
  /** items_uncounted */
  itemsUncounted: number;
  limit: DiaryLimit | null;
  entries: DiaryEntry[];
  attribution: string[];
}

const DECIMAL = /^\d+(\.\d+)?$/;
const METHODS: readonly string[] = ['USER_STATED', 'SOURCE_SERVING', 'PRESET', 'AGENT_ESTIMATE'];
const DAY_STATUSES: readonly string[] = ['NO_ENTRIES', 'OPEN', 'COMPLETE'];
const SUGAR_STATUSES: readonly string[] = ['NONE', 'KNOWN', 'PARTIAL'];
const MODES: readonly string[] = ['GENERAL', 'PREGNANCY'];

function bad(what: string): never {
  throw new TypeError(`diary: invalid ${what}`);
}

function obj(value: unknown, what: string): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) bad(what);
  return value as Record<string, unknown>;
}

function arr(value: unknown, what: string): unknown[] {
  if (!Array.isArray(value)) bad(what);
  return value as unknown[];
}

function str(value: unknown, what: string): string {
  if (typeof value !== 'string' || value.length === 0) bad(what);
  return value as string;
}

function decimal(value: unknown, what: string): string {
  if (typeof value !== 'string' || !DECIMAL.test(value)) bad(what);
  return value as string;
}

function decimalOrNull(value: unknown, what: string): string | null {
  return value === null || value === undefined ? null : decimal(value, what);
}

function count(value: unknown, what: string): number {
  if (typeof value !== 'number' || !Number.isInteger(value) || value < 0) bad(what);
  return value as number;
}

function amount(value: unknown): string {
  if (typeof value === 'number') {
    if (!Number.isFinite(value) || value < 0) bad('amount');
    return String(value);
  }
  return decimal(value, 'amount');
}

function parseItem(raw: unknown): DiaryItem {
  const item = obj(raw, 'item');
  const method = obj(item.conversion, 'conversion').method;
  if (typeof method !== 'string' || !METHODS.includes(method)) bad('conversion method');
  let source: string | null = null;
  if (item.facts !== null && item.facts !== undefined) {
    const facts = obj(item.facts, 'facts');
    if (facts.source !== null && facts.source !== undefined) source = str(facts.source, 'facts source');
  }
  return {
    label: str(item.label, 'label'),
    amount: amount(item.amount),
    unit: str(item.unit, 'unit'),
    grams: decimal(item.grams, 'grams'),
    method: method as ConversionMethod,
    source,
    freeSugarsG: decimalOrNull(item.free_sugars_g, 'free_sugars_g'),
  };
}

function parseLimit(raw: unknown): DiaryLimit | null {
  if (raw === null || raw === undefined) return null;
  const limit = obj(raw, 'limit');
  return {
    valueG: decimal(limit.value_g, 'limit value'),
    sources: arr(limit.sources, 'limit sources').map((s) => {
      const source = obj(s, 'limit source');
      return { title: str(source.title, 'source title'), url: str(source.url, 'source url') };
    }),
  };
}

/**
 * Strict mapper for Nutrition's GET /diary/{id}/days/today 200 body.
 * Throws TypeError on any malformed required field; unknown wire fields are ignored.
 */
export function parseDayWire(body: unknown): DiaryDay {
  const day = obj(body, 'day');
  const mode = day.mode;
  if (typeof mode !== 'string' || !MODES.includes(mode)) bad('mode');
  const dayStatus = day.day_status;
  if (typeof dayStatus !== 'string' || !DAY_STATUSES.includes(dayStatus)) bad('day_status');
  const sugarStatus = day.sugar_status;
  if (typeof sugarStatus !== 'string' || !SUGAR_STATUSES.includes(sugarStatus)) bad('sugar_status');
  const trimester = day.trimester ?? null;
  if (trimester !== null && trimester !== 1 && trimester !== 2 && trimester !== 3) bad('trimester');
  return {
    date: str(day.date, 'date'),
    mode: mode as DiaryDay['mode'],
    trimester: trimester as DiaryDay['trimester'],
    dayStatus: dayStatus as DayStatus,
    sugarStatus: sugarStatus as SugarStatus,
    freeSugarsKnownG: decimalOrNull(day.free_sugars_known_g, 'free_sugars_known_g'),
    itemsTotal: count(day.items_total, 'items_total'),
    itemsUncounted: count(day.items_uncounted, 'items_uncounted'),
    limit: parseLimit(day.limit),
    entries: arr(day.entries, 'entries').map((raw) => {
      const entry = obj(raw, 'entry');
      return {
        id: str(entry.id, 'entry id'),
        consumedAt: str(entry.consumed_at, 'consumed_at'),
        items: arr(entry.items, 'items').map(parseItem),
      };
    }),
    attribution: arr(day.attribution, 'attribution').map((a) => str(a, 'attribution')),
  };
}
