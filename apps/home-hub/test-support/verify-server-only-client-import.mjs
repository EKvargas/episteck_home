import assert from 'node:assert/strict';
import { mkdir, rm, writeFile } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import { resolve } from 'node:path';

const probeDirectory = resolve('src/app/server-only-client-import-probe');
const probeClient = resolve(probeDirectory, 'Probe.tsx');
const probePage = resolve(probeDirectory, 'page.tsx');
const env = {
  ...process.env,
  NODE_ENV: 'production',
  HOME_HUB_DATA_MODE: 'LIVE',
  HOME_HUB_BFF_BASE_URL: 'http://127.0.0.1:9933',
  HOME_HUB_PUBLIC_ORIGIN: 'http://127.0.0.1:3322',
};

let created = false;
try {
  await mkdir(probeDirectory);
  created = true;
  await writeFile(probeClient, "'use client';\nimport { getBootstrapForRequest } from '@/integration/home/bootstrap.server';\nexport function Probe() { return <button onClick={() => void getBootstrapForRequest()}>probe</button>; }\n");
  await writeFile(probePage, "import { Probe } from './Probe';\nexport default function Page() { return <Probe />; }\n");

  const result = spawnSync(process.execPath, ['node_modules/next/dist/bin/next', 'build'], {
    cwd: process.cwd(),
    env,
    encoding: 'utf8',
    timeout: 180_000,
  });
  const output = `${result.stdout ?? ''}\n${result.stderr ?? ''}`;
  assert.notEqual(result.status, 0, 'the client import unexpectedly built successfully');
  assert.match(output, /server-only|cannot be imported from a Client Component/i, output.slice(-5000));
  process.stdout.write('Next rejected a Client Component import of bootstrap.server.ts.\n');
} finally {
  if (created) await rm(probeDirectory, { recursive: true, force: true });
}
