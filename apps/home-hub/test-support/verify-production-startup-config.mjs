import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';

function startupFailure(overrides) {
  const env = {
    ...process.env,
    NODE_ENV: 'production',
    HOME_HUB_DATA_MODE: 'LIVE',
    PORT: '3339',
    ...overrides,
  };
  const result = spawnSync(process.execPath, ['node_modules/next/dist/bin/next', 'start'], {
    cwd: process.cwd(),
    env,
    encoding: 'utf8',
    timeout: 10_000,
  });
  return { result, output: `${result.stdout ?? ''}\n${result.stderr ?? ''}` };
}

for (const [config, error] of [
  [{ HOME_HUB_BFF_BASE_URL: undefined, HOME_HUB_PUBLIC_ORIGIN: undefined }, /HOME_HUB_BFF_BASE_URL is required/],
  [{ HOME_HUB_BFF_BASE_URL: 'https://remote.example.test', HOME_HUB_PUBLIC_ORIGIN: 'https://home.example.test' }, /HOME_HUB_BFF_BASE_URL must be a trusted HTTP origin/],
]) {
  const { result, output } = startupFailure(config);
  assert.notEqual(result.status, 0, 'standalone server unexpectedly accepted invalid production config');
  assert.notEqual(result.error?.code, 'ETIMEDOUT', output);
  assert.match(output, error, output.slice(-5000));
}

process.stdout.write('Production Next server rejected missing and untrusted LIVE config before listening.\n');
