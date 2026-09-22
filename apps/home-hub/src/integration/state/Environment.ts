/**
 * Safe mock/live configuration primitive.
 * Configuration is server/build environment based.
 * Browser cannot switch it.
 * Note: production startup enforcement will be activated when the live integration runtime is wired in F2.
 */
export type EnvironmentMode = 'MOCK' | 'LIVE';

export function getEnvironmentMode(): EnvironmentMode {
  const mode = process.env.HOME_HUB_DATA_MODE;
  
  if (process.env.NODE_ENV === 'production' && mode !== 'LIVE') {
    throw new Error('FATAL: HOME_HUB_DATA_MODE must be LIVE in production environment.');
  }

  return mode === 'LIVE' ? 'LIVE' : 'MOCK';
}
