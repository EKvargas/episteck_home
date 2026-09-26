import type { NextConfig } from "next";

if (process.env.NODE_ENV === 'production' && process.env.HOME_HUB_DATA_MODE !== 'LIVE') {
  throw new Error('FATAL: HOME_HUB_DATA_MODE must be LIVE in production environment.');
}

const nextConfig: NextConfig = {
  basePath: '/app',
  poweredByHeader: false,
};

export default nextConfig;
