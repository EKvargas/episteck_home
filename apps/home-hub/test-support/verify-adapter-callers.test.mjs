import assert from 'node:assert/strict';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import test from 'node:test';
import { findViolations } from './verify-adapter-callers.mjs';

const GOOD_SERVER = "import 'server-only';\nexport async function readNutritionProfile(context) {\n  assertIssuedContext(context);\n  return cookies();\n}\n";
const ALLOWED = 'src/app/nutrition/LiveProfilePanel.tsx';

async function tree(files) {
  const root = await mkdtemp(join(tmpdir(), 'adapter-callers-'));
  for (const [path, text] of Object.entries(files)) {
    await mkdir(dirname(join(root, path)), { recursive: true });
    await writeFile(join(root, path), text);
  }
  return root;
}

async function violationsFor(files) {
  const root = await tree({ 'src/integration/nutrition/profile.server.ts': GOOD_SERVER, ...files });
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
  const v = await violationsFor({ 'src/app/api/profile/route.ts': "import { loadNutritionProfile } from '@/integration/nutrition/profile-loader';\n" });
  assert.equal(v.length, 1);
});

test("a 'use server' module that imports the Nutrition integration is a violation", async () => {
  const v = await violationsFor({ 'src/actions.ts': "'use server';\nimport { resolveLiveSubject } from '@/integration/nutrition/live-subject.server';\n" });
  assert.equal(v.length, 1);
});

test("a 'use server' module reaching Nutrition through a relative path is a violation", async () => {
  const v = await violationsFor({ 'src/integration/home/actions.ts': "'use server';\nimport { loadNutritionProfile } from '../nutrition/profile-loader';\n" });
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
  const root = await tree({ 'src/integration/nutrition/profile.server.ts': "export async function readNutritionProfile(context) {\n  const c = cookies();\n  assertIssuedContext(context);\n}\n" });
  try { assert.equal((await findViolations(root)).length, 1); } finally { await rm(root, { recursive: true, force: true }); }
});
