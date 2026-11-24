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
export type DayNutrient = 'energy_kcal' | 'protein_g' | 'fiber_g';
/** The nutrients Hoy shows, in display order. Others on the wire are ignored. */
export const DAY_NUTRIENTS_SHOWN: readonly DayNutrient[] = ['energy_kcal', 'protein_g', 'fiber_g'];
export interface NutrientBlock {
  /** Sum of the known amounts; null means unknown, never zero. */
  known: string | null;
  itemsTotal: number;
  itemsUncounted: number;
  status: 'NONE' | 'KNOWN' | 'PARTIAL';
  target: { value: string; displayValue: string; unit: string; kind: 'ABOUT' | 'MIN' | 'MAX' } | null;
  percent: string | null;
}
export interface DiaryDay {
  /** profile_version; null when the person has no profile version yet. */
  profileVersion: number | null;
  /** The three nutrients Hoy shows, from day.nutrients. */
  nutrients: Record<DayNutrient, NutrientBlock>;
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

export function obj(value: unknown, what: string): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) bad(what);
  return value as Record<string, unknown>;
}

export function arr(value: unknown, what: string): unknown[] {
  if (!Array.isArray(value)) bad(what);
  return value as unknown[];
}

export function str(value: unknown, what: string): string {
  if (typeof value !== 'string' || value.length === 0) bad(what);
  return value as string;
}

function decimal(value: unknown, what: string): string {
  if (typeof value !== 'string' || !DECIMAL.test(value)) bad(what);
  return value as string;
}

export function decimalOrNull(value: unknown, what: string): string | null {
  return value === null || value === undefined ? null : decimal(value, what);
}

export function count(value: unknown, what: string): number {
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

const NUTRIENT_STATUSES: readonly string[] = ['NONE', 'KNOWN', 'PARTIAL'];
const TARGET_KINDS: readonly string[] = ['ABOUT', 'MIN', 'MAX'];

function parseTarget(raw: unknown, what: string): NutrientBlock['target'] {
  if (raw === null || raw === undefined) return null;
  const target = obj(raw, what);
  const display = target.display_value;
  // Free text: str(Decimal) may emit exponent form, so only length is checked.
  if (typeof display !== 'string' || display.length === 0 || display.length > 40) bad(`${what} display_value`);
  const kind = target.kind;
  if (typeof kind !== 'string' || !TARGET_KINDS.includes(kind)) bad(`${what} kind`);
  return {
    value: decimal(target.value, `${what} value`),
    displayValue: display as string,
    unit: str(target.unit, `${what} unit`),
    kind: kind as 'ABOUT' | 'MIN' | 'MAX',
  };
}

export function parseNutrientBlock(raw: unknown, what: string): NutrientBlock {
  const block = obj(raw, what);
  const status = block.status;
  if (typeof status !== 'string' || !NUTRIENT_STATUSES.includes(status)) bad(`${what} status`);
  return {
    known: decimalOrNull(block.known, `${what} known`),
    itemsTotal: count(block.items_total, `${what} items_total`),
    itemsUncounted: count(block.items_uncounted, `${what} items_uncounted`),
    status: status as NutrientBlock['status'],
    target: parseTarget(block.target, `${what} target`),
    percent: decimalOrNull(block.percent, `${what} percent`),
  };
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
  const wireNutrients = obj(day.nutrients, 'nutrients');
  const profileVersion = day.profile_version === undefined ? null : day.profile_version;
  const nutrients = {} as Record<DayNutrient, NutrientBlock>;
  for (const code of DAY_NUTRIENTS_SHOWN) nutrients[code] = parseNutrientBlock(wireNutrients[code], code);
  return {
    profileVersion: profileVersion === null ? null : count(profileVersion, 'profile_version'),
    nutrients,
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
