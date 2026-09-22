import 'server-only';
import { validateEnvironmentMode, EnvironmentMode } from './Environment';

/**
 * Server-only wrapper that reads process.env.
 * Note: production startup enforcement will be activated when the live integration runtime is wired in F2.
 */
export function getEnvironmentMode(): EnvironmentMode {
  return validateEnvironmentMode(
    process.env.HOME_HUB_DATA_MODE,
    process.env.NODE_ENV === 'production'
  );
}

export type { EnvironmentMode };
