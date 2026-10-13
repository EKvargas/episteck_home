import type { DataEnvelope } from '../state/DataEnvelope.ts';
import { isSafeUIErrorCode, type SafeUIErrorCode } from '../state/SafeUIErrorCode.ts';
import type { ProfileSummary } from './profile-contract.ts';

export type ProfilePanelModel =
  | { kind: 'LOADING'; subjectName: string | null }
  | { kind: 'PRESENT'; subjectName: string | null; contextLabel: string; targetSourceLabel: string; targetCount: number }
  | { kind: 'ABSENT'; subjectName: string | null }
  | { kind: 'DENIED'; subjectName: string | null }
  | { kind: 'SESSION' }
  | { kind: 'UNAVAILABLE'; subjectName: string | null }
  | { kind: 'INVALID'; subjectName: string | null }
  | { kind: 'NOT_CONFIGURED' };

const CONTEXT_LABELS: Record<string, string> = { PREGNANCY: 'Pregnancy', GENERAL: 'General' };
const TARGET_SOURCE_LABELS: Record<string, string> = {
  REFERENCE_TARGET: 'Reference targets',
  USER_CONFIGURED: 'Personalized targets',
};

/** Fixed-vocabulary label for the one log line per read. Never IDs, names, or body content. */
export function outcomeLabel(envelope: DataEnvelope<ProfileSummary>): string {
  if (envelope.delivery === 'READY' && envelope.data) return envelope.data.presence;
  if (envelope.delivery === 'ERROR' && isSafeUIErrorCode(envelope.errorCode)) return envelope.errorCode;
  return 'UNEXPECTED';
}

/** SOME_CODE → "Some code". Used for codes the UI does not know yet. */
export function humanizeCode(code: string): string {
  const words = code.toLowerCase().replace(/_/g, ' ');
  return code.length === 0 ? code : words.charAt(0).toUpperCase() + words.slice(1);
}

function label(table: Record<string, string>, code: string): string {
  return Object.hasOwn(table, code) ? table[code] : humanizeCode(code);
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
  envelope: DataEnvelope<ProfileSummary>,
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
      return {
        kind: 'PRESENT',
        subjectName,
        contextLabel: label(CONTEXT_LABELS, data.context),
        targetSourceLabel: label(TARGET_SOURCE_LABELS, data.targetSource),
        targetCount: data.targetCount,
      };
    }
    default: {
      const unmapped: never = envelope.delivery;
      void unmapped;
      return { kind: 'UNAVAILABLE', subjectName };
    }
  }
}
