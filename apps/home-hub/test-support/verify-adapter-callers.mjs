import { readdir, readFile } from 'node:fs/promises';
import { join, relative, sep } from 'node:path';
import { pathToFileURL } from 'node:url';

export const ALLOWED_ADAPTER_IMPORTERS = ['src/app/nutrition/perfil/LiveProfilePanel.tsx'];
/** Each Nutrition read is a pair: one server adapter, one loader only that adapter may reach. */
const PAIRS = [
  {
    name: 'profile',
    adapter: 'src/integration/nutrition/profile.server.ts',
    loader: 'src/integration/nutrition/profile-loader.ts',
    adapterPattern: /profile\.server/,
    loaderPattern: /profile-loader/,
    allowed: ALLOWED_ADAPTER_IMPORTERS,
  },
  {
    name: 'diary',
    adapter: 'src/integration/nutrition/diary.server.ts',
    loader: 'src/integration/nutrition/diary-loader.ts',
    adapterPattern: /diary\.server/,
    loaderPattern: /diary-loader/,
    allowed: ['src/app/nutrition/hoy/LiveTodayPanel.tsx'],
  },
  {
    name: 'period',
    adapter: 'src/integration/nutrition/period.server.ts',
    loader: 'src/integration/nutrition/period-loader.ts',
    adapterPattern: /period\.server/,
    loaderPattern: /period-loader/,
    allowed: [
      'src/app/nutrition/dias/LivePeriodPanel.tsx',
      'src/app/nutrition/hoy/LiveWeeklyPanel.tsx',
      'src/app/nutrition/nutriente/LiveNutrientPanel.tsx',
    ],
  },
];
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

/**
 * Static proof that readNutritionProfile is reachable only from its one server component,
 * and that loadNutritionProfile is reachable only through readNutritionProfile's context check.
 */
export async function findViolations(root) {
  const violations = [];
  const seenAdapters = new Set();
  for (const file of await walk(join(root, 'src'))) {
    const rel = relative(root, file).split(sep).join('/');
    if (/\.test\.(ts|tsx)$/.test(rel)) continue;
    const text = await readFile(file, 'utf8');

    const ownPair = PAIRS.find((pair) => pair.adapter === rel);
    if (ownPair) {
      seenAdapters.add(ownPair.name);
      const guard = text.indexOf('assertIssuedContext(');
      const cookies = text.indexOf('cookies()');
      if (guard === -1 || (cookies !== -1 && cookies < guard)) {
        violations.push(`${rel}: must call assertIssuedContext(...) before reading cookies`);
      }
      continue;
    }

    for (const pair of PAIRS) {
      const mentionsAdapter = pair.adapterPattern.test(text);
      const adapterName = pair.adapter.split('/').pop().replace(/\.ts$/, '');
      if (mentionsAdapter && !pair.allowed.includes(rel)) {
        violations.push(`${rel}: imports ${adapterName} but is not an allowed importer`);
      }
      if (mentionsAdapter && USE_CLIENT.test(text)) {
        violations.push(`${rel}: a client component must never import ${adapterName}`);
      }
      if (rel !== pair.loader && pair.loaderPattern.test(text)) {
        const loaderName = pair.loader.split('/').pop().replace(/\.ts$/, '');
        violations.push(`${rel}: imports ${loaderName}; only ${adapterName} may, after assertIssuedContext`);
      }
    }
    if (USE_SERVER.test(text) && NUTRITION_SPECIFIER.test(text)) {
      violations.push(`${rel}: a 'use server' module must not import the Nutrition integration`);
    }
    if (/\/route\.(ts|tsx|js)$/.test(rel) && NUTRITION_SPECIFIER.test(text)) {
      violations.push(`${rel}: a route handler must not import the Nutrition integration`);
    }
  }
  if (seenAdapters.size === 0) {
    // Nothing at all to verify: one violation (the original behaviour), naming the first adapter.
    violations.push(`${PAIRS[0].adapter}: not found, so there is nothing to verify`);
  } else {
    for (const pair of PAIRS) {
      if (!seenAdapters.has(pair.name)) violations.push(`${pair.adapter}: not found, so there is nothing to verify`);
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
  process.stdout.write('Adapter callers verified: only the allowed server component reaches profile.server, and only profile.server, diary.server and period.server reach their loaders.\n');
}
