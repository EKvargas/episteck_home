import type { SafeUIErrorCode } from '../../../integration/state/SafeUIErrorCode.ts';

/** The panel kinds every Live nutrition model shares for a failed read. */
export type PanelErrorKind = 'DENIED' | 'SESSION' | 'NOT_CONFIGURED' | 'INVALID' | 'UNAVAILABLE';

/**
 * The one mapping from a safe error code to the panel a reader sees. Models spread the result
 * into their own union (`{ kind: panelError(code) }`), so no panel repeats this switch.
 */
export function panelError(code: SafeUIErrorCode | undefined): PanelErrorKind {
  switch (code) {
    case 'ACCESS_DENIED':
      return 'DENIED';
    case 'SESSION_INVALID':
    case 'SESSION_REQUIRED':
      return 'SESSION';
    case 'NOT_CONFIGURED':
      return 'NOT_CONFIGURED';
    case 'INVALID_RESPONSE':
      return 'INVALID';
    default:
      return 'UNAVAILABLE';
  }
}
