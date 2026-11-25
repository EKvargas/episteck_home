import assert from 'node:assert/strict';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { findViolations } from './verify-adapter-callers.mjs';

const APP_ROOT = fileURLToPath(new URL('..', import.meta.url));
const GOOD_SERVER = "import 'server-only';\nimport { loadNutritionProfile } from './profile-loader';\nexport async function readNutritionProfile(context) {\n  assertIssuedContext(context);\n  return cookies();\n}\n";
const ALLOWED = 'src/app/nutrition/perfil/LiveProfilePanel.tsx';
const GOOD_DIARY_SERVER = "import 'server-only';\nimport { loadDiaryToday } from './diary-loader';\nexport async function readDiaryToday(context) {\n  assertIssuedContext(context);\n  return cookies();\n}\n";
const GOOD_PERIOD_SERVER = "import 'server-only';\nimport { loadDiaryPeriod } from './period-loader';\nexport async function readDiaryPeriod(context) {\n  assertIssuedContext(context);\n  return cookies();\n}\n";
const PERIOD_ALLOWED = 'src/app/nutrition/dias/LivePeriodPanel.tsx';
const DIARY_ALLOWED = 'src/app/nutrition/hoy/LiveTodayPanel.tsx';

async function tree(files) {
  const root = await mkdtemp(join(tmpdir(), 'adapter-callers-'));
  for (const [path, text] of Object.entries(files)) {
    await mkdir(dirname(join(root, path)), { recursive: true });
    await writeFile(join(root, path), text);
  }
  return root;
}

async function violationsFor(files) {
  const root = await tree({
    'src/integration/nutrition/profile.server.ts': GOOD_SERVER,
    'src/integration/nutrition/diary.server.ts': GOOD_DIARY_SERVER,
    'src/integration/nutrition/period.server.ts': GOOD_PERIOD_SERVER,
    ...files,
  });
  try { return await findViolations(root); } finally { await rm(root, { recursive: true, force: true }); }
}

test('the single allowed server importer is clean', async () => {
  assert.deepEqual(await violationsFor({
    [ALLOWED]: "import { readNutritionProfile } from '@/integration/nutrition/profile.server';\nexport async function LiveProfilePanel() { return readNutritionProfile(); }\n",
  }), []);
});

test('any other importer is a violation', async () => {
  const v = await violationsFor({ 'src/app/other/page.tsx': "import { readNutritionProfile } from '@/integration/nutrition/profile.server';\n" });
  assert.equal(v.length, 1);
  assert.match(v[0], /src\/app\/other\/page\.tsx/);
});

test('a route handler that touches the nutrition integration is a violation', async () => {
  const v = await violationsFor({ 'src/app/api/profile/route.ts': "import { parseProfileWire } from '@/integration/nutrition/profile-contract';\n" });
  assert.equal(v.length, 1);
});

test("a 'use server' module that imports the Nutrition integration is a violation", async () => {
  const v = await violationsFor({ 'src/actions.ts': "'use server';\nimport { resolveLiveSubject } from '@/integration/nutrition/live-subject.server';\n" });
  assert.equal(v.length, 1);
});

test("a 'use server' module reaching Nutrition through a relative path is a violation", async () => {
  const v = await violationsFor({ 'src/integration/home/actions.ts': "'use server';\nimport { parseProfileWire } from '../nutrition/profile-contract';\n" });
  assert.equal(v.length, 1);
});

test("a 'use server' module may use other server modules (the rule is scoped to Nutrition)", async () => {
  assert.deepEqual(await violationsFor({ 'src/actions.ts': "'use server';\nimport { getBootstrapForRequest } from '@/integration/home/bootstrap.server';\n" }), []);
});

test('the allowed importer must not be a client component', async () => {
  const v = await violationsFor({ [ALLOWED]: "'use client';\nimport { readNutritionProfile } from '@/integration/nutrition/profile.server';\n" });
  assert.equal(v.length, 1);
});

test('profile.server.ts must verify the context before reading cookies', async () => {
  const root = await tree({ 'src/integration/nutrition/diary.server.ts': GOOD_DIARY_SERVER, 'src/integration/nutrition/period.server.ts': GOOD_PERIOD_SERVER, 'src/integration/nutrition/profile.server.ts': "export async function readNutritionProfile(context) {\n  const c = cookies();\n  assertIssuedContext(context);\n}\n" });
  try { assert.equal((await findViolations(root)).length, 1); } finally { await rm(root, { recursive: true, force: true }); }
});

test('the allowed server component must not reach profile-loader past the context check', async () => {
  const v = await violationsFor({ [ALLOWED]: "import { loadNutritionProfile } from '@/integration/nutrition/profile-loader';\n" });
  assert.equal(v.length, 1);
  assert.match(v[0], /profile-loader/);
});

test('a sibling module importing profile-loader by relative path is a violation', async () => {
  const v = await violationsFor({ 'src/integration/nutrition/shortcut.ts': "import { loadNutritionProfile } from './profile-loader';\n" });
  assert.equal(v.length, 1);
  assert.match(v[0], /src\/integration\/nutrition\/shortcut\.ts/);
});

test('a tree without profile.server.ts is a violation, not a vacuous pass', async () => {
  const root = await tree({ 'src/app/page.tsx': 'export default function Page() { return null; }\n' });
  try { assert.equal((await findViolations(root)).length, 1); } finally { await rm(root, { recursive: true, force: true }); }
});

test('the Home Hub source tree has no adapter-caller violations', async () => {
  assert.deepEqual(await findViolations(APP_ROOT), []);
});

test('LiveTodayPanel may import diary.server', async () => {
  assert.deepEqual(await violationsFor({
    [DIARY_ALLOWED]: "import { readDiaryToday } from '@/integration/nutrition/diary.server';\n",
  }), []);
});

test('the guard rejects diary.server imported outside LiveTodayPanel and diary-loader imported outside diary.server', async () => {
  const a = await violationsFor({ 'src/app/other/page.tsx': "import { readDiaryToday } from '@/integration/nutrition/diary.server';\n" });
  assert.equal(a.length, 1);
  assert.match(a[0], /diary\.server/);
  const b = await violationsFor({ 'src/integration/nutrition/shortcut.ts': "import { loadDiaryToday } from './diary-loader';\n" });
  assert.equal(b.length, 1);
  assert.match(b[0], /diary-loader/);
  const c = await violationsFor({ [DIARY_ALLOWED]: "'use client';\nimport { readDiaryToday } from '@/integration/nutrition/diary.server';\n" });
  assert.equal(c.length, 1);
});

test('diary.server.ts must verify the context before reading cookies', async () => {
  const v = await violationsFor({ 'src/integration/nutrition/diary.server.ts': "export async function readDiaryToday(context) {\n  const c = cookies();\n  assertIssuedContext(context);\n}\n" });
  assert.equal(v.length, 1);
});

test('each panel may import only its own adapter', async () => {
  assert.equal((await violationsFor({ [DIARY_ALLOWED]: "import { readNutritionProfile } from '@/integration/nutrition/profile.server';\n" })).length, 1);
  assert.equal((await violationsFor({ [ALLOWED]: "import { readDiaryToday } from '@/integration/nutrition/diary.server';\n" })).length, 1);
});

test('a tree with only profile.server.ts reports diary.server.ts as missing', async () => {
  const root = await tree({ 'src/integration/nutrition/profile.server.ts': GOOD_SERVER });
  try {
    const v = await findViolations(root);
    assert.equal(v.length, 2);
    assert.match(v.join(' '), /diary\.server\.ts: not found/);
  } finally { await rm(root, { recursive: true, force: true }); }
});

test('a tree with only diary.server.ts reports profile.server.ts as missing', async () => {
  const root = await tree({ 'src/integration/nutrition/diary.server.ts': GOOD_DIARY_SERVER });
  try {
    const v = await findViolations(root);
    assert.equal(v.length, 2);
    assert.match(v.join(' '), /profile\.server\.ts: not found/);
  } finally { await rm(root, { recursive: true, force: true }); }
});

test('LivePeriodPanel may import period.server; no other panel may', async () => {
  assert.deepEqual(await violationsFor({
    [PERIOD_ALLOWED]: "import { readDiaryPeriod } from '@/integration/nutrition/period.server';\n",
  }), []);
  assert.equal((await violationsFor({ [DIARY_ALLOWED]: "import { readDiaryPeriod } from '@/integration/nutrition/period.server';\n" })).length, 1);
  assert.equal((await violationsFor({ [PERIOD_ALLOWED]: "import { readDiaryToday } from '@/integration/nutrition/diary.server';\n" })).length, 1);
});

test('period-loader is reachable only through period.server, which checks the context first', async () => {
  const v = await violationsFor({ 'src/app/nutrition/dias/page.tsx': "import { loadDiaryPeriod } from '@/integration/nutrition/period-loader';\n" });
  assert.equal(v.length, 1);
  assert.match(v[0], /period-loader/);
  const bad = await violationsFor({ 'src/integration/nutrition/period.server.ts': "export async function readDiaryPeriod(context) {\n  const c = cookies();\n  assertIssuedContext(context);\n}\n" });
  assert.equal(bad.length, 1);
});

test('a tree with only profile.server.ts and diary.server.ts reports period.server.ts as missing', async () => {
  const root = await tree({
    'src/integration/nutrition/profile.server.ts': GOOD_SERVER,
    'src/integration/nutrition/diary.server.ts': GOOD_DIARY_SERVER,
  });
  try {
    const v = await findViolations(root);
    assert.equal(v.length, 1);
    assert.match(v[0], /period\.server\.ts: not found/);
  } finally { await rm(root, { recursive: true, force: true }); }
});

test('LiveWeeklyPanel may import period.server; LiveTodayPanel still may not', async () => {
  const WEEKLY_ALLOWED = 'src/app/nutrition/hoy/LiveWeeklyPanel.tsx';
  assert.deepEqual(await violationsFor({
    [WEEKLY_ALLOWED]: "import { readDiaryPeriod } from '@/integration/nutrition/period.server';\n",
  }), []);
  const today = await violationsFor({ [DIARY_ALLOWED]: "import { readDiaryPeriod } from '@/integration/nutrition/period.server';\n" });
  assert.equal(today.length, 1);
  assert.match(today[0], /LiveTodayPanel/);
  // the weekly panel may not read the day or the profile
  assert.equal((await violationsFor({ [WEEKLY_ALLOWED]: "import { readDiaryToday } from '@/integration/nutrition/diary.server';\n" })).length, 1);
});

test('LiveNutrientPanel may import period.server; the profile and day adapters stay closed to it', async () => {
  const NUTRIENT_ALLOWED = 'src/app/nutrition/nutriente/LiveNutrientPanel.tsx';
  assert.deepEqual(await violationsFor({
    [NUTRIENT_ALLOWED]: "import { readDiaryPeriod } from '@/integration/nutrition/period.server';\n",
  }), []);
  assert.equal((await violationsFor({ [NUTRIENT_ALLOWED]: "import { readDiaryToday } from '@/integration/nutrition/diary.server';\n" })).length, 1);
});
