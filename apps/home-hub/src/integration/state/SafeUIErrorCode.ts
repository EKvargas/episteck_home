export type SafeUIErrorCode =
  | 'SESSION_REQUIRED'
  | 'SESSION_INVALID'
  | 'ACCESS_DENIED'
  | 'RESOURCE_NOT_AVAILABLE'
  | 'NOT_CONFIGURED'
  | 'SERVICE_UNAVAILABLE'
  | 'OFFLINE'
  | 'INVALID_RESPONSE';

const validCodes: Set<string> = new Set([
  'SESSION_REQUIRED',
  'SESSION_INVALID',
  'ACCESS_DENIED',
  'RESOURCE_NOT_AVAILABLE',
  'NOT_CONFIGURED',
  'SERVICE_UNAVAILABLE',
  'OFFLINE',
  'INVALID_RESPONSE'
]);

export function isSafeUIErrorCode(value: unknown): value is SafeUIErrorCode {
  return typeof value === 'string' && validCodes.has(value);
}

export function normalizeSafeUIErrorCode(value: unknown): SafeUIErrorCode {
  if (isSafeUIErrorCode(value)) {
    return value;
  }
  return 'INVALID_RESPONSE';
}
