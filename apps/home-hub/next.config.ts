import type { NextConfig } from "next";
import { getHomeHubServerConfiguration } from './src/integration/home/server-config.ts';

// Build-time validation catches invalid build settings. The standalone
// prelisten entrypoint calls the same validator against runtime values.
getHomeHubServerConfiguration();

const nextConfig: NextConfig = {
  basePath: '/app',
  // The bare basePath must execute the root layout directly so a bootstrap
  // 401 can hand off to the trusted origin-root login in one redirect.
  skipTrailingSlashRedirect: true,
  poweredByHeader: false,
  output: 'standalone',
};

export default nextConfig;
