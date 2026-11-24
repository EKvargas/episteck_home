import type { DataEnvelope } from '../state/DataEnvelope.ts';
import { isSafeUIErrorCode, type SafeUIErrorCode } from '../state/SafeUIErrorCode.ts';
import type { NutritionProfile, ProfileRead } from './profile-contract.ts';
import {
  TRIMESTERS, fieldLabel, longDate, nutrientLabel, shortDate, targetValue,
} from './nutrition-format.ts';

export type ProfilePanelModel =
  | { kind: 'LOADING' | 'ABSENT' | 'DENIED' | 'UNAVAILABLE' | 'INVALID'; subjectName: string | null }
  | { kind: 'SESSION' }
  | { kind: 'NOT_CONFIGURED' }
  | {
      kind: 'PROFILE';
      subjectName: string | null;
      modePill: string | null;
      onboarded: boolean;
      basics: { label: string; value: string }[];
      food: { label: string; value: string }[];
      targets: { label: string; value: string; source: string }[];
      targetsSince: string;
      missing: string[];
      note: string;
      history: string[];
    };

type Profile = Extract<ProfilePanelModel, { kind: 'PROFILE' }>;
type Row = { label: string; value: string };

const MISSING = 'falta';
const PAL_LABELS: Record<string, string> = {
  '1.4': 'Sobre todo sentado, poca actividad (1,4)',
  '1.6': 'Sentado, con algo de caminar o estar de pie (1,6)',
  '1.8': 'Sobre todo de pie o caminando (1,8)',
  '2.0': 'Trabajo físico intenso (2,0)',
};
const GOAL_LABELS = { MAINTAIN: 'Mantener', LOSE_FAT: 'Perder grasa', BUILD_MUSCLE: 'Ganar músculo', PERFORMANCE: 'Rendimiento' } as const;
const NUTRIENT_ORDER = [
  'energy_kcal', 'protein_g', 'fat_g', 'carb_g', 'fiber_g', 'free_sugars_g', 'calcium_mg', 'iron_mg', 'folate_ug',
  'vitamin_b12_ug', 'vitamin_d_ug', 'iodine_ug', 'zinc_mg', 'selenium_ug', 'choline_mg', 'dha_g',
];
const GENERAL_NOTE = 'Si cambias tu peso o tu objetivo, los valores nuevos rigen desde ese día. Los días pasados se miden con los objetivos que tenían entonces.';
const HISTORY_LIMIT = 5;
const HISTORY_FIELDS = 3;

function trainingValue(sessions: number | null, note: string | null): string {
  if (sessions === null) return MISSING;
  const base = sessions === 0 ? 'Sin entrenamiento'
    : sessions === 1 ? '1 sesión por semana' : `${sessions} sesiones por semana`;
  return note ? `${base} · ${note}` : base;
}

function basicsOf(p: NutritionProfile): Row[] {
  const i = p.inputs;
  const pregnancy = p.mode === 'PREGNANCY';
  const rows: Row[] = [{ label: 'Edad', value: i.age === null ? MISSING : `${i.age} años` }];
  if (!pregnancy) rows.push({ label: 'Sexo', value: i.sex === null ? MISSING : i.sex === 'MALE' ? 'Hombre' : 'Mujer' });
  rows.push({ label: 'Altura', value: i.heightCm === null ? MISSING : `${i.heightCm} cm` });
  rows.push({
    label: 'Peso',
    value: i.weightKg === null ? MISSING
      : `${i.weightKg} kg${i.weightMeasuredOn ? ` (${shortDate(i.weightMeasuredOn)})` : ''}`,
  });
  if (pregnancy) {
    rows.push({ label: 'Peso antes del embarazo', value: i.prePregnancyWeightKg === null ? MISSING : `${i.prePregnancyWeightKg} kg` });
    rows.push({ label: 'Fecha prevista de parto', value: p.dueDate === null ? MISSING : longDate(p.dueDate) });
  }
  rows.push({
    label: 'Actividad diaria',
    value: i.activityPal === null ? MISSING : Object.hasOwn(PAL_LABELS, i.activityPal) ? PAL_LABELS[i.activityPal] : i.activityPal,
  });
  rows.push({ label: 'Entrenamiento', value: trainingValue(i.trainingSessionsPerWeek, i.trainingNote) });
  if (!pregnancy) rows.push({ label: 'Objetivo', value: i.goal === null ? MISSING : GOAL_LABELS[i.goal] });
  rows.push({ label: 'Modo', value: pregnancy ? 'Embarazo' : 'General' });
  return rows;
}

function targetsOf(p: NutritionProfile): Profile['targets'] {
  const rank = (code: string) => {
    const at = NUTRIENT_ORDER.indexOf(code);
    return at === -1 ? NUTRIENT_ORDER.length : at;
  };
  return p.targets.items
    .map((t, index) => ({ t, index }))
    .sort((a, b) => rank(a.t.nutrient) - rank(b.t.nutrient) || a.index - b.index)
    .map(({ t }) => {
      const explanation = t.explanation.replace(/\.$/, '');
      return {
        label: nutrientLabel(t.nutrient),
        value: targetValue(t.kind, t.displayValue, t.unit),
        source: explanation === '' ? t.sourceOrg : `${explanation} · ${t.sourceOrg}`,
      };
    });
}

function noteOf(p: NutritionProfile): string {
  if (p.mode === 'PREGNANCY' && p.trimester === 1) return 'Al entrar en el 2.º trimestre, la energía sube sola (+250 kcal, DGE).';
  if (p.mode === 'PREGNANCY' && p.trimester === 2) return 'Al entrar en el 3.er trimestre, la energía sube sola (+500 kcal, DGE).';
  return GENERAL_NOTE;
}

function historyOf(p: NutritionProfile): string[] {
  const rows = [...p.history].sort((a, b) => b.version - a.version);
  const oldestProfile = rows.filter((r) => r.origin === 'PROFILE').at(-1);
  return rows.slice(0, HISTORY_LIMIT).map((r) => {
    let text = 'cambio';
    if (r.origin === 'PROFILE') {
      if (r === oldestProfile) text = 'perfil creado por chat';
      else {
        const labels = [...new Set(r.changed.map(fieldLabel))];
        const shown = labels.slice(0, HISTORY_FIELDS).join(', ');
        text = `perfil actualizado por chat (${shown}${labels.length > HISTORY_FIELDS ? '…' : ''})`;
      }
    } else if (r.origin === 'MODE') text = 'modo cambiado por chat';
    else if (r.origin === 'MIGRATED') text = 'perfil anterior importado';
    return `${shortDate(r.validFrom)}: ${text}`;
  });
}

function profileModel(p: NutritionProfile, subjectName: string | null): Profile {
  const orNone = (v: string | null) => v ?? '—';
  return {
    kind: 'PROFILE',
    subjectName,
    modePill: p.mode === 'PREGNANCY' ? (p.trimester === null ? 'Embarazo' : `Embarazo · ${TRIMESTERS[p.trimester]}`) : null,
    onboarded: p.onboarded,
    basics: basicsOf(p),
    food: [
      { label: 'Preferencias', value: orNone(p.food.preferences) },
      { label: 'No le gusta', value: orNone(p.food.dislikes) },
      { label: 'Intolerancias', value: orNone(p.food.intolerances) },
    ],
    targets: targetsOf(p),
    targetsSince: `vigentes desde ${shortDate(p.validFrom)}`,
    missing: p.targets.missing.map((m) => `${nutrientLabel(m.nutrient)}: falta ${m.fields.map(fieldLabel).join(', ')}`),
    note: noteOf(p),
    history: historyOf(p),
  };
}

/** Fixed-vocabulary label for the one log line per read. Never IDs, names, or body content. */
export function outcomeLabel(envelope: DataEnvelope<ProfileRead>): string {
  if (envelope.delivery === 'READY' && envelope.data) return envelope.data.presence;
  if (envelope.delivery === 'ERROR' && isSafeUIErrorCode(envelope.errorCode)) return envelope.errorCode;
  return 'UNEXPECTED';
}

/** SOME_CODE → "Some code". Used for codes the UI does not know yet. */
export function humanizeCode(code: string): string {
  const words = code.toLowerCase().replace(/_/g, ' ');
  return code.length === 0 ? code : words.charAt(0).toUpperCase() + words.slice(1);
}

function errorModel(code: SafeUIErrorCode | undefined, subjectName: string | null): ProfilePanelModel {
  if (code === undefined) return { kind: 'UNAVAILABLE', subjectName };
  switch (code) {
    case 'ACCESS_DENIED':
      return { kind: 'DENIED', subjectName };
    case 'SESSION_INVALID':
    case 'SESSION_REQUIRED':
      return { kind: 'SESSION' };
    case 'NOT_CONFIGURED':
      return { kind: 'NOT_CONFIGURED' };
    case 'INVALID_RESPONSE':
      return { kind: 'INVALID', subjectName };
    case 'SERVICE_UNAVAILABLE':
    case 'OFFLINE':
    case 'RESOURCE_NOT_AVAILABLE':
      return { kind: 'UNAVAILABLE', subjectName };
    default: {
      const unmapped: never = code;
      void unmapped;
      return { kind: 'UNAVAILABLE', subjectName };
    }
  }
}

/** Map one adapter envelope to exactly one deliberate panel. Pure; no React, no server imports. */
export function toProfilePanelModel(
  envelope: DataEnvelope<ProfileRead>,
  subjectName: string | null,
): ProfilePanelModel {
  switch (envelope.delivery) {
    case 'LOADING':
      return { kind: 'LOADING', subjectName };
    case 'ERROR':
      return errorModel(envelope.errorCode, subjectName);
    case 'READY': {
      const data = envelope.data;
      // A non-LIVE READY envelope is never shown on the live path: no mock in LIVE, structurally.
      if (envelope.environment !== 'LIVE' || envelope.authorization !== 'GRANTED' || !data) {
        return { kind: 'UNAVAILABLE', subjectName };
      }
      if (data.presence === 'ABSENT') return { kind: 'ABSENT', subjectName };
      return profileModel(data.profile, subjectName);
    }
    default: {
      const unmapped: never = envelope.delivery;
      void unmapped;
      return { kind: 'UNAVAILABLE', subjectName };
    }
  }
}
