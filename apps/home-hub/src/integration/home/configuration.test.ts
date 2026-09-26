import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { resolve } from 'node:path';
import { getHomeHubServerConfiguration } from './server-config.ts';

function importNextConfig(env: NodeJS.ProcessEnv) {
  const configPath = resolve('next.config.ts');
  return spawnSync(process.execPath, [
    '--experimental-strip-types',
    '--input-type=module',
    '-e',
    `await import(${JSON.stringify(new URL(`file:///${configPath.replaceAll('\\', '/')}`).href)})`,
  ], { encoding: 'utf8', env: { ...process.env, ...env } });
}

test('production build configuration fails closed when data mode is MOCK', () => {
  const result = importNextConfig({ NODE_ENV: 'production', HOME_HUB_DATA_MODE: 'MOCK' });
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /HOME_HUB_DATA_MODE must be LIVE/);
});

test('production configuration import fails before server startup without valid origins', () => {
  const valid: NodeJS.ProcessEnv = {
    NODE_ENV: 'production',
    HOME_HUB_DATA_MODE: 'LIVE',
    HOME_HUB_BFF_BASE_URL: 'http://127.0.0.1:9933',
    HOME_HUB_PUBLIC_ORIGIN: 'https://home.example.test',
  };
  for (const [env, error] of [
    [{ ...valid, HOME_HUB_BFF_BASE_URL: undefined }, /HOME_HUB_BFF_BASE_URL/],
    [{ ...valid, HOME_HUB_BFF_BASE_URL: 'https://remote.example.test' }, /HOME_HUB_BFF_BASE_URL/],
    [{ ...valid, HOME_HUB_PUBLIC_ORIGIN: undefined }, /HOME_HUB_PUBLIC_ORIGIN/],
    [{ ...valid, HOME_HUB_PUBLIC_ORIGIN: 'http://remote.example.test' }, /HOME_HUB_PUBLIC_ORIGIN/],
  ] as const) {
    const result = importNextConfig(env);
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, error);
  }
});

test('production LIVE requires a valid local BFF origin and public origin', () => {
  const base: NodeJS.ProcessEnv = {
    NODE_ENV: 'production',
    HOME_HUB_DATA_MODE: 'LIVE',
    HOME_HUB_PUBLIC_ORIGIN: 'https://home.example.test',
  };

  for (const bffUrl of [undefined, 'not a URL', 'ftp://127.0.0.1:9933', 'http://user:pass@127.0.0.1:9933', 'https://remote.example.test']) {
    assert.throws(
      () => getHomeHubServerConfiguration({ ...base, HOME_HUB_BFF_BASE_URL: bffUrl }),
      /HOME_HUB_BFF_BASE_URL/,
    );
  }

  assert.throws(
    () => getHomeHubServerConfiguration({ ...base, HOME_HUB_BFF_BASE_URL: 'http://127.0.0.1:9933', HOME_HUB_PUBLIC_ORIGIN: undefined }),
    /HOME_HUB_PUBLIC_ORIGIN/,
  );
  assert.throws(
    () => getHomeHubServerConfiguration({ ...base, HOME_HUB_BFF_BASE_URL: 'http://127.0.0.1:9933', HOME_HUB_PUBLIC_ORIGIN: 'http://remote.example.test' }),
    /HOME_HUB_PUBLIC_ORIGIN/,
  );
});

test('development MOCK remains available without production-only config', () => {
  assert.deepEqual(
    getHomeHubServerConfiguration({ NODE_ENV: 'development', HOME_HUB_DATA_MODE: 'MOCK' }),
    { mode: 'MOCK', bffBaseUrl: undefined, publicOrigin: 'http://127.0.0.1:3000' },
  );
});
