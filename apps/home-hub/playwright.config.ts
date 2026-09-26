import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  use: {
    ...devices['Desktop Chrome'],
    baseURL: 'http://127.0.0.1:3322',
  },
  webServer: [
    {
      command: 'node test-support/fake-bff.mjs',
      url: 'http://127.0.0.1:3323/health',
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command: 'npm run start -- --hostname 127.0.0.1 --port 3322',
      port: 3322,
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        HOME_HUB_DATA_MODE: 'LIVE',
        HOME_HUB_BFF_BASE_URL: 'http://127.0.0.1:3323',
        HOME_HUB_PUBLIC_ORIGIN: 'http://127.0.0.1:3322',
      },
    },
  ],
});
