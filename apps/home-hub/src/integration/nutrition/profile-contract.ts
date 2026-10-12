export type ProfileSummary =
  | { presence: 'PRESENT'; context: string; targetSource: string; targetCount: number }
  | { presence: 'ABSENT' };

export class ProfileContractError extends Error {}

const CODE = /^[A-Z_]{1,32}$/;
const NUMERIC = /^-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?$/;
const MAX_TARGETS = 64;
const MAX_TARGET_TEXT = 32;

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object'
    && value !== null
    && !Array.isArray(value)
    && Object.getPrototypeOf(value) === Object.prototype;
}

function isTargetValue(value: unknown): boolean {
  if (typeof value === 'number') return Number.isFinite(value);
  return typeof value === 'string'
    && value.length <= MAX_TARGET_TEXT
    && NUMERIC.test(value)
    && Number.isFinite(Number(value));
}

/**
 * Strict, minimizing mapper for Nutrition's GET /profile/{id} 200 body.
 * Reads exactly three facts; preferences, dislikes, intolerances, pregnancy fields and
 * any unknown field are never copied. Any violation rejects the whole payload.
 */
export function parseProfileWire(body: unknown): ProfileSummary {
  if (!isPlainObject(body)) throw new ProfileContractError('profile must be an object');
  const { context, target_source: targetSource, targets } = body;
  if (typeof context !== 'string' || !CODE.test(context)) throw new ProfileContractError('invalid context');
  if (typeof targetSource !== 'string' || !CODE.test(targetSource)) throw new ProfileContractError('invalid target source');
  if (!isPlainObject(targets)) throw new ProfileContractError('invalid targets');
  const keys = Object.keys(targets);
  if (keys.length > MAX_TARGETS) throw new ProfileContractError('too many targets');
  if (!keys.every((key) => isTargetValue(targets[key]))) throw new ProfileContractError('invalid target value');
  return { presence: 'PRESENT', context, targetSource, targetCount: keys.length };
}

/** True only for Nutrition's authorized no-profile body, exactly {"detail":"no profile"}. */
export function isAbsentProfileBody(body: unknown): boolean {
  return isPlainObject(body) && Object.keys(body).length === 1 && body.detail === 'no profile';
}
