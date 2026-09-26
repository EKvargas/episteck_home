import { copyFile, mkdir } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';

const standalone = resolve('.next/standalone');
for (const file of [
  'prelisten.mjs',
  'src/integration/home/server-config.ts',
  'src/integration/state/Environment.ts',
]) {
  const target = resolve(standalone, file);
  await mkdir(dirname(target), { recursive: true });
  await copyFile(resolve(file), target);
}
