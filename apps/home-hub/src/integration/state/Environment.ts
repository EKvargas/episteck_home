export type EnvironmentMode = 'MOCK' | 'LIVE';

export function validateEnvironmentMode(
  modeValue: string | undefined,
  isProduction: boolean
): EnvironmentMode {
  if (modeValue !== undefined && modeValue !== 'MOCK' && modeValue !== 'LIVE') {
    throw new Error('FATAL: HOME_HUB_DATA_MODE must be MOCK or LIVE.');
  }
  if (isProduction && modeValue !== 'LIVE') {
    throw new Error('FATAL: HOME_HUB_DATA_MODE must be LIVE in production environment.');
  }
  return modeValue === 'LIVE' ? 'LIVE' : 'MOCK';
}
