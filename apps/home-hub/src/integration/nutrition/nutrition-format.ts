// Shared Spanish formatting for the Nutrition views. Pure; formats only, never calculates a figure.

const PLAIN_DECIMAL = /^\d+(\.\d+)?$/;

const WHOLE = new Intl.NumberFormat('es-ES', { maximumFractionDigits: 0, useGrouping: 'always' });
const ONE_DECIMAL = new Intl.NumberFormat('es-ES', { maximumFractionDigits: 1, useGrouping: 'always' });

/** kcal: whole number; other units: whole when >= 10, else one decimal. Non-decimal text is shown as given. */
export function amount(decimal: string, unit: string): string {
  if (!PLAIN_DECIMAL.test(decimal)) return decimal;
  const n = Number(decimal);
  return unit === 'kcal' || n >= 10 ? WHOLE.format(n) : ONE_DECIMAL.format(n);
}

export function unitLabel(unit: string): string {
  return unit === 'ug' ? 'µg' : unit;
}

/** SOME_CODE or some_code → "Some code". */
function humanize(code: string): string {
  const words = code.toLowerCase().replace(/_/g, ' ');
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** 'magnesium_mg' → 'Magnesium': drops a trailing unit segment. */
function humanizeNutrient(code: string): string {
  return humanize(code.replace(/_(kcal|g|mg|ug)$/, ''));
}

const NUTRIENT_LABELS: Record<string, string> = {
  energy_kcal: 'Energía',
  protein_g: 'Proteína',
  fat_g: 'Grasa',
  carb_g: 'Carbohidratos',
  fiber_g: 'Fibra',
  free_sugars_g: 'Azúcares libres',
  calcium_mg: 'Calcio',
  iron_mg: 'Hierro',
  folate_ug: 'Folato',
  vitamin_b12_ug: 'Vitamina B12',
  vitamin_d_ug: 'Vitamina D',
  iodine_ug: 'Yodo',
  zinc_mg: 'Zinc',
  selenium_ug: 'Selenio',
  choline_mg: 'Colina',
  dha_g: 'DHA',
};

const FIELD_LABELS: Record<string, string> = {
  birth_date: 'fecha de nacimiento',
  sex: 'sexo',
  height_cm: 'altura',
  weight_kg: 'peso',
  weight_measured_on: 'fecha del peso',
  activity_pal: 'actividad diaria',
  training_sessions_per_week: 'entrenamiento',
  training_note: 'entrenamiento',
  goal: 'objetivo',
  pre_pregnancy_weight_kg: 'peso antes del embarazo',
  due_date: 'fecha prevista de parto',
  mode: 'modo',
  preferences: 'preferencias',
  dislikes: 'lo que no le gusta',
  intolerances: 'intolerancias',
};

export function nutrientLabel(code: string): string {
  return Object.hasOwn(NUTRIENT_LABELS, code) ? NUTRIENT_LABELS[code] : humanizeNutrient(code);
}

export function fieldLabel(field: string): string {
  return Object.hasOwn(FIELD_LABELS, field) ? FIELD_LABELS[field] : humanize(field);
}

const SIGNS = { ABOUT: '≈', MIN: '≥', MAX: '≤' } as const;

export function targetValue(kind: 'ABOUT' | 'MIN' | 'MAX', displayValue: string, unit: string): string {
  return `${SIGNS[kind]} ${amount(displayValue, unit)} ${unitLabel(unit)}`;
}

function utcDate(iso: string): Date {
  return new Date(`${iso}T00:00:00Z`);
}

function parts(iso: string, options: Intl.DateTimeFormatOptions): Record<string, string> {
  const out: Record<string, string> = {};
  for (const p of new Intl.DateTimeFormat('es-ES', { ...options, timeZone: 'UTC' }).formatToParts(utcDate(iso))) {
    out[p.type] = p.value.replace(/\.$/, '');
  }
  return out;
}

export function shortDate(iso: string): string {
  const p = parts(iso, { day: 'numeric', month: 'short' });
  return `${p.day} ${p.month}`;
}

export function longDate(iso: string): string {
  const p = parts(iso, { day: 'numeric', month: 'short', year: 'numeric' });
  return `${p.day} ${p.month} ${p.year}`;
}

export function weekdayDay(iso: string): string {
  const p = parts(iso, { weekday: 'short', day: 'numeric' });
  return `${p.weekday.charAt(0).toUpperCase()}${p.weekday.slice(1)} ${p.day}`;
}

export const TRIMESTERS: Record<1 | 2 | 3, string> = {
  1: '1.er trimestre',
  2: '2.º trimestre',
  3: '3.er trimestre',
};
