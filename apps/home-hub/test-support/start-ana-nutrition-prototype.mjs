// Local-only runner for the disposable, synthetic visual study.
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

if (process.env.NODE_ENV === 'production') {
  throw new Error('The Ana visual prototype only runs in local development.');
}
const root = fileURLToPath(new URL('../', import.meta.url));
const port = process.env.ANA_NUTRITION_PROTOTYPE_PORT ?? '3015';
if (!/^\d+$/.test(port) || Number(port) < 1024 || Number(port) > 65535) {
  throw new Error('Choose a local prototype port between 1024 and 65535.');
}
console.log(`Visual study: http://127.0.0.1:${port}/app/nutrition?prototype=ana&variant=A`);
const child = spawn(process.execPath, [
  fileURLToPath(new URL('../node_modules/next/dist/bin/next', import.meta.url)),
  'dev', '--hostname', '127.0.0.1', '--port', port,
], {
  cwd: root,
  stdio: 'inherit',
  env: { ...process.env, NODE_ENV: 'development', HOME_HUB_DATA_MODE: 'MOCK', HOME_HUB_PUBLIC_ORIGIN: `http://127.0.0.1:${port}` },
});
process.on('SIGINT', () => child.kill('SIGINT'));
process.on('SIGTERM', () => child.kill('SIGTERM'));
child.on('error', error => { console.error(error.message); process.exitCode = 1; });
child.on('exit', code => { process.exitCode = code ?? 1; });
