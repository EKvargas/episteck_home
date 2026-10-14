import { randomUUID } from 'node:crypto';
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

const HUB = 'http://127.0.0.1:3322';
const BFF = 'http://127.0.0.1:3323';
const NUTRITION = 'http://127.0.0.1:9930';
const newRun = () => randomUUID().replace(/-/g, '');

/** Sets the scenario cookie and returns its value, so tests can assert the value never leaks. */
async function signIn(page: Page, scenario: string, run: string, variant = '') {
  const value = `authenticated${variant}-nutr-${scenario}-run${run}`;
  await page.context().addCookies([{
    name: 'episteck_home_session', value, url: HUB, httpOnly: true, sameSite: 'Lax',
  }]);
  return value;
}

async function observed(request: APIRequestContext, run: string) {
  const mints = (await (await request.get(`${BFF}/__test/mints/${run}`)).json()).count as number;
  const calls = (await (await request.get(`${NUTRITION}/__test/calls/${run}`)).json()).calls as Array<{ path: string; hasCookie: boolean }>;
  return { mints, calls };
}

async function bootstrapReads(request: APIRequestContext, run: string) {
  return (await (await request.get(`${BFF}/__test/bootstraps/${run}`)).json()).count as number;
}

/** Every document and fetch body (RSC payloads, /api/context) the browser receives from the Hub. */
function captureHubBodies(page: Page) {
  const pending: Array<Promise<string>> = [];
  page.on('response', (response) => {
    const type = response.request().resourceType();
    if (response.url().startsWith(`${HUB}/`) && (type === 'document' || type === 'fetch')) {
      pending.push(response.text().catch(() => ''));
    }
  });
  return async () => (await Promise.all(pending)).join('\n');
}

async function trackCspViolations(page: Page) {
  await page.addInitScript(() => {
    const w = window as typeof window & { __cspViolations?: string[] };
    w.__cspViolations = [];
    window.addEventListener('securitypolicyviolation', (event) => {
      w.__cspViolations?.push(`${event.violatedDirective}: ${event.blockedURI}`);
    });
  });
  return () => page.evaluate(() => (window as typeof window & { __cspViolations?: string[] }).__cspViolations ?? []);
}

const panel = (page: Page) => page.getByTestId('profile-panel');
const MOCK_STRINGS = /kcal|Protein|Carbs|Mealie|View Dashboard|Pregnancy Nutrition|Consent required/i;
const SECRETS = ['DELEGATION_SENTINEL', 'COOKIE_SENTINEL', 'PRIVATE_PREF_SENTINEL', 'PRIVATE_DISLIKE_SENTINEL', 'episteck_home_session'];

function expectNoSecrets(text: string, cookieValue: string) {
  for (const secret of [...SECRETS, cookieValue]) expect(text, secret).not.toContain(secret);
}

test('PRESENT: one mint, one call, minimized, no-store, no mock, no secrets, no CSP violations, no demo banner', async ({ page, request }) => {
  const run = newRun();
  const cookieValue = await signIn(page, 'present', run, '-self-only');
  const cspViolations = await trackCspViolations(page);
  const hubBodies = captureHubBodies(page);
  const response = await page.goto('/app/nutrition');
  await expect(panel(page)).toContainText('Nutrition profile on file');
  await expect(panel(page)).toContainText('Pregnancy');
  await expect(panel(page)).toContainText('Reference targets');
  await expect(panel(page)).toContainText('2 configured');
  await expect(panel(page)).toContainText('Source: Nutrition service');

  const { mints, calls } = await observed(request, run);
  expect(mints).toBe(1);
  expect(calls).toEqual([{ path: '/profile/PSN-00001', hasCookie: false }]);

  expect(response?.headers()['cache-control']).toContain('no-store');
  const html = (await response?.text()) ?? '';
  expect(new Set(html.match(/PSN-\d{5,}/g) ?? [])).toEqual(new Set(html.includes('PSN-00001') ? ['PSN-00001'] : []));
  expectNoSecrets(await hubBodies(), cookieValue);
  expect(await page.locator('body').innerText()).not.toMatch(MOCK_STRINGS);
  await expect(page.getByRole('note', { name: 'Demo mock data' })).toHaveCount(0);
  await expect.poll(cspViolations).toEqual([]);
});

test('one document render: layout and panel share one bootstrap, one mint, one Nutrition call', async ({ page, request }) => {
  const run = newRun();
  await signIn(page, 'absent', run);
  // Document only: no hydration and no /api/context, so the counters see the server render alone.
  const response = await page.request.get(`${HUB}/app/nutrition`);
  expect(response.status()).toBe(200);
  expect(await response.text()).toContain('No nutrition profile');
  expect(await bootstrapReads(request, run)).toBe(1);
  const { mints, calls } = await observed(request, run);
  expect(mints).toBe(1);
  expect(calls).toHaveLength(1);
});

test('other pages never prefetch or render the Nutrition read', async ({ page, request }) => {
  const run = newRun();
  await signIn(page, 'present', run);
  await page.goto('/app');
  await expect(page.getByRole('tab', { name: /Synthetic Viewer/ })).toBeVisible();
  await page.getByRole('link', { name: 'Nutrition', exact: true }).first().hover();
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(1_000);
  expect(await observed(request, run)).toEqual({ mints: 0, calls: [] });
});

test('the demo banner still shows on other routes in LIVE', async ({ page }) => {
  await signIn(page, 'absent', newRun());
  await page.goto('/app/health');
  await expect(page.getByRole('note', { name: 'Demo mock data' })).toBeVisible();
});

test('ABSENT renders an honest empty state, not zeros or mock', async ({ page, request }) => {
  const run = newRun();
  await signIn(page, 'absent', run);
  await page.goto('/app/nutrition');
  await expect(panel(page)).toContainText('No nutrition profile for Synthetic Viewer');
  expect(await page.locator('body').innerText()).not.toMatch(MOCK_STRINGS);
  expect((await observed(request, run)).mints).toBe(1);
});

test('DENIED shows Access restricted with no reason and keeps the subject', async ({ page }) => {
  await signIn(page, '403', newRun());
  await page.goto('/app/nutrition?person=PSN-00007');
  await expect(panel(page)).toContainText('Access restricted');
  await expect(panel(page)).toContainText('Synthetic Care Context');
  expect(await page.locator('body').innerText()).not.toContain('ACCESS_DENIED');
  await expect(page).toHaveURL(/person=PSN-00007$/);
});

test('a session that dies after the layout shows a sign-in panel', async ({ page }) => {
  await signIn(page, '401', newRun());
  await page.goto('/app/nutrition');
  await expect(panel(page)).toContainText('Your session has expired');
  await expect(page.getByRole('link', { name: 'Sign in again' })).toHaveAttribute('href', 'http://127.0.0.1:3322/login');
});

test('unavailable offers Try again; a retry mints a fresh delegation and leaks nothing', async ({ page, request }) => {
  const run = newRun();
  const cookieValue = await signIn(page, '503', run);
  const hubBodies = captureHubBodies(page);
  await page.goto('/app/nutrition');
  await expect(panel(page)).toContainText('temporarily unavailable');
  await page.getByRole('button', { name: 'Try again' }).click();
  await expect.poll(async () => (await observed(request, run)).mints).toBe(2);
  expect((await observed(request, run)).calls).toHaveLength(2);
  await expect(page.getByRole('button', { name: 'Try again' })).toBeEnabled();
  expectNoSecrets(await hubBodies(), cookieValue);
});

test('a failed mint shows unavailable and never calls Nutrition', async ({ page, request }) => {
  const run = newRun();
  await signIn(page, 'present', run, '-mint-503');
  await page.goto('/app/nutrition');
  await expect(panel(page)).toContainText('temporarily unavailable');
  expect((await observed(request, run)).calls).toEqual([]);
});

test('a malformed Nutrition body is shown as could-not-be-shown-safely', async ({ page }) => {
  await signIn(page, 'badbody', newRun());
  await page.goto('/app/nutrition');
  await expect(panel(page)).toContainText('could not be shown safely');
});

test('a hung Nutrition upstream streams a skeleton, then times out to unavailable', async ({ page }) => {
  test.setTimeout(30_000);
  await signIn(page, 'hang', newRun());
  await page.goto('/app/nutrition', { waitUntil: 'commit' });
  await expect(page.getByRole('heading', { name: 'Nutrition Hub' })).toBeVisible();
  await expect(panel(page)).toContainText('Checking Nutrition profile');
  await expect(panel(page)).toContainText('temporarily unavailable', { timeout: 15_000 });
});

for (const person of ['PSN-00999', 'CIR-00001', 'broken', '']) {
  test(`stale selection "${person}" makes no read for it; the canonical self URL makes exactly one`, async ({ page, request }) => {
    const run = newRun();
    await signIn(page, 'absent', run);
    await page.goto(`/app/nutrition?person=${person}`);
    await expect(page).toHaveURL(/person=PSN-00001$/);
    await expect(panel(page)).toContainText('No nutrition profile for Synthetic Viewer');
    const { mints, calls } = await observed(request, run);
    expect(mints).toBe(1);
    expect(calls).toEqual([{ path: '/profile/PSN-00001', hasCookie: false }]);
  });
}

test('actor-shaped query noise cannot change the subject', async ({ page, request }) => {
  const run = newRun();
  await signIn(page, 'absent', run);
  await page.goto('/app/nutrition?person=PSN-00001&actorPersonId=PSN-00999');
  await expect(panel(page)).toContainText('No nutrition profile for Synthetic Viewer');
  expect((await observed(request, run)).calls).toEqual([{ path: '/profile/PSN-00001', hasCookie: false }]);
});

test('switching subject re-reads for the new subject; Back restores the earlier panel without a new read', async ({ page, request }) => {
  const run = newRun();
  const cookieValue = await signIn(page, 'absent', run);
  const hubBodies = captureHubBodies(page);
  await page.goto('/app/nutrition?person=PSN-00007');
  await expect(panel(page)).toContainText('No nutrition profile for Synthetic Care Context');
  await page.getByRole('tab', { name: /Synthetic Viewer/ }).click();
  await expect(panel(page)).toContainText('No nutrition profile for Synthetic Viewer');
  await expect(panel(page)).not.toContainText('Synthetic Care Context');
  await page.goBack();
  await expect(page).toHaveURL(/person=PSN-00007$/);
  await expect(panel(page)).toContainText('No nutrition profile for Synthetic Care Context');
  await expect(panel(page)).not.toContainText('Synthetic Viewer');
  await page.waitForLoadState('networkidle');
  // Pinned (spec Invariants (b)): Next restores the history entry from its client router cache, so Back makes no new read.
  const paths = (await observed(request, run)).calls.map((call) => call.path);
  expect(paths).toEqual(['/profile/PSN-00007', '/profile/PSN-00001']);
  expectNoSecrets(await hubBodies(), cookieValue);
});
