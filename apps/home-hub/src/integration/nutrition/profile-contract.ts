export type Mode = 'GENERAL' | 'PREGNANCY';
export type TargetKind = 'ABOUT' | 'MIN' | 'MAX';

export interface ProfileTarget {
  nutrient: string;
  value: string;
  displayValue: string;
  unit: string;
  kind: TargetKind;
  sourceOrg: string;
  sourceRef: string;
  explanation: string;
}

export interface ProfileInputsView {
  birthDate: string | null;
  age: number | null;
  sex: 'MALE' | 'FEMALE' | null;
  heightCm: string | null;
  weightKg: string | null;
  weightMeasuredOn: string | null;
  activityPal: string | null;
  trainingSessionsPerWeek: number | null;
  trainingNote: string | null;
  goal: 'MAINTAIN' | 'LOSE_FAT' | 'BUILD_MUSCLE' | 'PERFORMANCE' | null;
  prePregnancyWeightKg: string | null;
}

export interface NutritionProfile {
  version: number | null;
  validFrom: string;
  origin: string;
  onboarded: boolean;
  mode: Mode;
  dueDate: string | null;
  trimester: 1 | 2 | 3 | null;
  inputs: ProfileInputsView;
  food: { preferences: string | null; dislikes: string | null; intolerances: string | null };
  targets: { method: string; on: string; items: ProfileTarget[]; missing: { nutrient: string; fields: string[] }[] };
  history: { version: number; validFrom: string; origin: string; changed: string[] }[];
}

export type ProfileRead = { presence: 'PRESENT'; profile: NutritionProfile } | { presence: 'ABSENT' };

export class ProfileContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ProfileContractError';
  }
}

const DATE = /^\d{4}-\d{2}-\d{2}$/;
const DECIMAL = /^\d+(\.\d+)?$/;
const NUTRIENT = /^[a-z0-9_]{1,40}$/;
const ORIGIN = /^[A-Z_]{1,32}$/;
const METHOD = /^[A-Za-z0-9_-]{1,40}$/;
const FIELD = /^[a-z0-9_]{1,40}$/;
const MAX_FOOD_TEXT = 500;
const MAX_TRAINING_NOTE = 120;
const MAX_TARGET_TEXT = 300;
const MAX_SHORT = 40;
const MAX_ITEMS = 64;
const MAX_MISSING = 64;
const MAX_FIELDS = 64;
const MAX_HISTORY = 200;
const MAX_CHANGED = 64;

type Obj = Record<string, unknown>;

function isPlainObject(value: unknown): value is Obj {
  return typeof value === 'object'
    && value !== null
    && !Array.isArray(value)
    && Object.getPrototypeOf(value) === Object.prototype;
}

function fail(what: string): never {
  throw new ProfileContractError(`invalid ${what}`);
}

function obj(value: unknown, what: string): Obj {
  return isPlainObject(value) ? value : fail(what);
}

function arr(value: unknown, max: number, what: string): unknown[] {
  return Array.isArray(value) && value.length <= max ? value : fail(what);
}

function patterned(value: unknown, pattern: RegExp, what: string): string {
  return typeof value === 'string' && pattern.test(value) ? value : fail(what);
}

function text(value: unknown, max: number, what: string): string {
  return typeof value === 'string' && [...value].length <= max ? value : fail(what);
}

function nullable<T>(value: unknown, read: (v: unknown) => T): T | null {
  return value === null ? null : read(value);
}

function count(value: unknown, what: string): number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : fail(what);
}

function oneOf<T extends string>(value: unknown, allowed: readonly T[], what: string): T {
  return typeof value === 'string' && (allowed as readonly string[]).includes(value) ? (value as T) : fail(what);
}

const date = (v: unknown, what: string) => patterned(v, DATE, what);
const decimal = (v: unknown, what: string) => patterned(v, DECIMAL, what);

function mapInputs(raw: unknown): ProfileInputsView {
  const i = obj(raw, 'inputs');
  return {
    birthDate: nullable(i.birth_date, (v) => date(v, 'birth_date')),
    age: nullable(i.age, (v) => count(v, 'age')),
    sex: nullable(i.sex, (v) => oneOf(v, ['MALE', 'FEMALE'] as const, 'sex')),
    heightCm: nullable(i.height_cm, (v) => decimal(v, 'height_cm')),
    weightKg: nullable(i.weight_kg, (v) => decimal(v, 'weight_kg')),
    weightMeasuredOn: nullable(i.weight_measured_on, (v) => date(v, 'weight_measured_on')),
    activityPal: nullable(i.activity_pal, (v) => decimal(v, 'activity_pal')),
    trainingSessionsPerWeek: nullable(i.training_sessions_per_week, (v) => count(v, 'training_sessions_per_week')),
    trainingNote: nullable(i.training_note, (v) => text(v, MAX_TRAINING_NOTE, 'training_note')),
    goal: nullable(i.goal, (v) => oneOf(v, ['MAINTAIN', 'LOSE_FAT', 'BUILD_MUSCLE', 'PERFORMANCE'] as const, 'goal')),
    prePregnancyWeightKg: nullable(i.pre_pregnancy_weight_kg, (v) => decimal(v, 'pre_pregnancy_weight_kg')),
  };
}

function mapFood(raw: unknown): NutritionProfile['food'] {
  const f = obj(raw, 'food');
  return {
    preferences: nullable(f.preferences, (v) => text(v, MAX_FOOD_TEXT, 'preferences')),
    dislikes: nullable(f.dislikes, (v) => text(v, MAX_FOOD_TEXT, 'dislikes')),
    intolerances: nullable(f.intolerances, (v) => text(v, MAX_FOOD_TEXT, 'intolerances')),
  };
}

function mapTarget(raw: unknown): ProfileTarget {
  const t = obj(raw, 'target');
  return {
    nutrient: patterned(t.nutrient, NUTRIENT, 'nutrient'),
    value: decimal(t.value, 'target value'),
    displayValue: text(t.display_value, MAX_SHORT, 'target display value'),
    unit: text(t.unit, MAX_SHORT, 'unit'),
    kind: oneOf(t.kind, ['ABOUT', 'MIN', 'MAX'] as const, 'kind'),
    sourceOrg: text(t.source_org, MAX_TARGET_TEXT, 'source_org'),
    sourceRef: text(t.source_ref, MAX_TARGET_TEXT, 'source_ref'),
    explanation: text(t.explanation, MAX_TARGET_TEXT, 'explanation'),
  };
}

function mapTargetSet(raw: unknown): NutritionProfile['targets'] {
  const s = obj(raw, 'target_set');
  return {
    method: patterned(s.method, METHOD, 'method'),
    on: date(s.on, 'target day'),
    items: arr(s.items, MAX_ITEMS, 'target items').map(mapTarget),
    missing: arr(s.missing, MAX_MISSING, 'missing targets').map((row) => {
      const m = obj(row, 'missing target');
      return {
        nutrient: patterned(m.nutrient, NUTRIENT, 'missing nutrient'),
        fields: arr(m.fields, MAX_FIELDS, 'missing fields').map((f) => patterned(f, FIELD, 'missing field')),
      };
    }),
  };
}

function mapHistory(raw: unknown): NutritionProfile['history'] {
  return arr(raw, MAX_HISTORY, 'history').map((row) => {
    const h = obj(row, 'history row');
    return {
      version: count(h.version, 'history version'),
      validFrom: date(h.valid_from, 'history valid_from'),
      origin: patterned(h.origin, ORIGIN, 'history origin'),
      changed: arr(h.changed, MAX_CHANGED, 'changed').map((f) => patterned(f, FIELD, 'changed field')),
    };
  });
}

/**
 * Strict mapper for Nutrition's GET /profile/{id} 200 body. Reads exactly the fields Perfil
 * shows: mode, pregnancy facts, inputs, food notes, the structured target_set and the version
 * history. The flat targets map, context, target_source and any unknown field are never copied.
 * Any violation rejects the whole payload.
 */
export function parseProfileWire(body: unknown): ProfileRead {
  const b = obj(body, 'profile');
  const trimester = b.trimester;
  if (trimester !== null && trimester !== 1 && trimester !== 2 && trimester !== 3) fail('trimester');
  if (typeof b.onboarded !== 'boolean') fail('onboarded');
  return {
    presence: 'PRESENT',
    profile: {
      version: nullable(b.version, (v) => count(v, 'version')),
      validFrom: date(b.valid_from, 'valid_from'),
      origin: patterned(b.origin, ORIGIN, 'origin'),
      onboarded: b.onboarded,
      mode: oneOf(b.mode, ['GENERAL', 'PREGNANCY'] as const, 'mode'),
      dueDate: nullable(b.due_date, (v) => date(v, 'due_date')),
      trimester,
      inputs: mapInputs(b.inputs),
      food: mapFood(b.food),
      targets: mapTargetSet(b.target_set),
      history: mapHistory(b.history),
    },
  };
}

/** True only for Nutrition's authorized no-profile body, exactly {"detail":"no profile"}. */
export function isAbsentProfileBody(body: unknown): boolean {
  return isPlainObject(body) && Object.keys(body).length === 1 && body.detail === 'no profile';
}
