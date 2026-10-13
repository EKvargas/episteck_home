import { readdir, readFile } from 'node:fs/promises';
import { join, relative, sep } from 'node:path';
import { pathToFileURL } from 'node:url';

export const ALLOWED_ADAPTER_IMPORTERS = ['src/app/nutrition/LiveProfilePanel.tsx'];
const ADAPTER_MODULE = 'src/integration/nutrition/profile.server.ts';
const USE_SERVER = /^\s*['"]use server['"]/m;
const USE_CLIENT = /^\s*['"]use client['"]/m;
/** Any module specifier that reaches into a nutrition/ directory, by alias or relative path. */
const NUTRITION_SPECIFIER = /['"][^'"\n]*\bnutrition\/[^'"\n]*['"]/;

async function walk(directory) {
  const entries = await readdir(directory, { withFileTypes: true }).catch(() => []);
  const files = [];
  for (const entry of entries) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) files.push(...await walk(path));
    else if (/\.(ts|tsx|js|jsx|mjs)$/.test(entry.name)) files.push(path);
  }
  return files;
}

/** Static proof that readNutritionProfile is reachable only from its one server component. */
export async function findViolations(root) {
  const violations = [];
  for (const file of await walk(join(root, 'src'))) {
    const rel = relative(root, file).split(sep).join('/');
    if (/\.test\.(ts|tsx)$/.test(rel)) continue;
    const text = await readFile(file, 'utf8');

    if (rel === ADAPTER_MODULE) {
      const guard = text.indexOf('assertIssuedContext(');
      const cookies = text.indexOf('cookies()');
      if (guard === -1 || (cookies !== -1 && cookies < guard)) {
        violations.push(`${rel}: must call assertIssuedContext(...) before reading cookies`);
      }
      continue;
    }

    const mentionsAdapter = /profile\.server/.test(text);
    if (mentionsAdapter && !ALLOWED_ADAPTER_IMPORTERS.includes(rel)) {
      violations.push(`${rel}: imports profile.server but is not an allowed importer`);
    }
    if (mentionsAdapter && USE_CLIENT.test(text)) {
      violations.push(`${rel}: a client component must never import profile.server`);
    }
    if (USE_SERVER.test(text) && NUTRITION_SPECIFIER.test(text)) {
      violations.push(`${rel}: a 'use server' module must not import the Nutrition integration`);
    }
    if (/\/route\.(ts|tsx|js)$/.test(rel) && NUTRITION_SPECIFIER.test(text)) {
      violations.push(`${rel}: a route handler must not import the Nutrition integration`);
    }
  }
  return violations;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const violations = await findViolations(process.cwd());
  if (violations.length > 0) {
    process.stderr.write(`${violations.join('\n')}\n`);
    process.exit(1);
  }
  process.stdout.write('Adapter callers verified: only the allowed server component reaches profile.server.\n');
}
