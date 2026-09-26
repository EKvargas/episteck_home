import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { resolve } from 'node:path';

test('production build configuration fails closed when data mode is MOCK', () => {
  const configPath = resolve('next.config.ts');
  const result = spawnSync(process.execPath, [
    '--experimental-strip-types',
    '--input-type=module',
    '-e',
    `await import(${JSON.stringify(new URL(`file:///${configPath.replaceAll('\\', '/')}`).href)})`,
  ], {
    encoding: 'utf8',
    env: { ...process.env, NODE_ENV: 'production', HOME_HUB_DATA_MODE: 'MOCK' },
  });
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /HOME_HUB_DATA_MODE must be LIVE/);
});
