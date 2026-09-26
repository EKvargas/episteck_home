import type { NextConfig } from "next";
import { getHomeHubServerConfiguration } from './src/integration/home/server-config.ts';

// next.config is evaluated for both production builds and `next start`, before
// route handling begins. Keep the same check in instrumentation for standalone.
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
