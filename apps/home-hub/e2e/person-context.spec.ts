import { randomUUID } from 'node:crypto';
import { expect, test } from '@playwright/test';

async function authenticate(page: import('@playwright/test').Page, value = 'authenticated') {
  await page.context().addCookies([{
    name: 'episteck_home_session', value,
    url: 'http://127.0.0.1:3322', httpOnly: true, sameSite: 'Lax',
  }]);
}

test('a care Person survives refresh and child navigation after validation', async ({ page }) => {
  await authenticate(page);
  await page.goto('/app?person=PSN-00007');
  await expect(page.getByRole('tab', { name: /Synthetic Care Context/ })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('tab', { name: /Synthetic Care Context/ })).toBeVisible();
  await page.getByRole('link', { name: 'Nutrition', exact: true }).first().click();
  await expect(page).toHaveURL(/\/app\/nutrition\/hoy\?person=PSN-00007$/);
  await expect(page.getByRole('tab', { name: /Synthetic Care Context/ })).toBeVisible();
});

test('stale and malformed Person URLs canonicalize to self with a notice', async ({ page }) => {
  await authenticate(page);
  for (const person of ['PSN-00999', 'CIR-00001', 'broken']) {
    await page.goto(`/app?person=${person}`);
    await expect(page).toHaveURL(/\/app\/?\?person=PSN-00001$/);
    await expect(page.getByRole('status').filter({ hasText: 'Context changed' })).toBeVisible();
    await expect(page.getByRole('tab', { name: /Synthetic Viewer/ })).toBeVisible();
  }
});

test('two tabs keep separate URL selections and actor query noise has no effect', async ({ page, context }) => {
  await authenticate(page);
  const second = await context.newPage();
  await page.goto('/app?person=PSN-00001');
  await second.goto('/app?person=PSN-00007&actorPersonId=PSN-00999');
  await expect(page.getByRole('tab', { name: /Synthetic Viewer/ })).toBeVisible();
  await expect(second.getByRole('tab', { name: /Synthetic Care Context/ })).toBeVisible();
  await expect(second.getByRole('heading', { name: 'Good afternoon, Synthetic Viewer' })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('tab', { name: /Synthetic Viewer/ })).toBeVisible();
  await expect(second.getByRole('tab', { name: /Synthetic Care Context/ })).toBeVisible();
});

test('Person selection changes no browser persistence or BFF session cookie', async ({ page }) => {
  const run = randomUUID().replace(/-/g, '');
  const session = `authenticated-run${run}`;
  await authenticate(page, session);
  await page.goto('/app');
  await expect(page.getByRole('tab', { name: /Synthetic Viewer/ })).toBeVisible();
  const before = await page.evaluate(() => ({
    local: { ...localStorage }, session: { ...sessionStorage },
    cookie: document.cookie,
  }));
  await page.getByRole('tab', { name: /Synthetic Care Context/ }).click();
  await expect(page.getByRole('tab', { name: /Synthetic Care Context/ })).toBeVisible();
  const after = await page.evaluate(() => ({
    local: { ...localStorage }, session: { ...sessionStorage },
    cookie: document.cookie,
  }));
  expect(after).toEqual(before);
  const forwarded = await page.request.get(`http://127.0.0.1:3323/__test/last-cookie/${run}`).then((response) => response.json());
  expect(forwarded.cookie).toBe(`episteck_home_session=${session}`);
});

test('an open tab clears an obsolete subject when focus revalidates its session', async ({ page }) => {
  await authenticate(page);
  await page.goto('/app?person=PSN-00007');
  await expect(page.getByRole('tab', { name: /Synthetic Care Context/ })).toBeVisible();
  await page.context().addCookies([{
    name: 'episteck_home_session', value: 'authenticated-self-only',
    url: 'http://127.0.0.1:3322', httpOnly: true, sameSite: 'Lax',
  }]);
  await page.evaluate(() => window.dispatchEvent(new Event('focus')));
  await expect(page).toHaveURL(/\/app\/?\?person=PSN-00001$/);
  await expect(page.getByRole('status').filter({ hasText: 'Context changed' })).toBeVisible();
  await expect(page.getByRole('tab', { name: /Synthetic Care Context/ })).toHaveCount(0);
});

test('structured context requests reject actor fields', async ({ page }) => {
  await authenticate(page);
  const response = await page.request.post('/app/api/context', {
    data: { person: ['PSN-00001'], actorPersonId: 'PSN-00999' },
  });
  expect(response.status()).toBe(400);
  expect(await response.text()).not.toContain('PSN-00001');
});

test('a subject is carried through an internal detail link', async ({ page }) => {
  await authenticate(page);
  await page.goto('/app?person=PSN-00007');
  await page.getByRole('link', { name: 'Abrir diario de nutrición' }).click();
  await expect(page).toHaveURL(/\/app\/nutrition\/hoy\?person=PSN-00007$/);
});

test('browser Back during a pending selection restores the previous Person', async ({ page }) => {
  await authenticate(page);
  await page.goto('/app?person=PSN-00001');
  await expect(page.getByRole('tab', { name: /Synthetic Viewer/ })).toBeVisible();
  await page.route('**/app/api/context', async (route) => {
    const body = route.request().postDataJSON();
    if (body.person?.[0] === 'PSN-00007') await new Promise((resolve) => setTimeout(resolve, 1500));
    await route.continue();
  });
  await page.getByRole('tab', { name: /Synthetic Care Context/ }).click();
  await expect(page).toHaveURL(/person=PSN-00007$/);
  await page.goBack();
  await expect(page).toHaveURL(/person=PSN-00001$/);
  await expect(page.getByRole('tab', { name: /Synthetic Viewer/ })).toBeVisible();
});

test('changing the Home context clears the previous diary and runs the new access check', async ({ page }) => {
  await page.context().addCookies([{
    name: 'episteck_home_session', value: 'authenticated-nutr-today-two-subjects-runcontextswapping',
    url: 'http://127.0.0.1:3322', httpOnly: true, sameSite: 'Lax',
  }]);
  await page.goto('/app');
  const diary = page.getByTestId('today-panel');
  await expect(diary).toContainText('Azúcares libres: 17 g de 50 g');
  await page.getByRole('tab', { name: /Synthetic Care Context/ }).click();
  await expect(page).toHaveURL(/\/app\/?\?person=PSN-00007$/);
  await expect(diary).toContainText('No tienes acceso a este diario.');
  await expect(diary).not.toContainText('17 g');
  await expect(page.getByText('Telegram usa tu propio diario.')).toBeVisible();
  await expect(page.getByText('Registrar una comida', { exact: true })).toHaveCount(0);
  await page.getByRole('tab', { name: /Synthetic Viewer/ }).click();
  await expect(page).toHaveURL(/\/app\/?\?person=PSN-00001$/);
  await expect(diary).toContainText('Azúcares libres: 17 g de 50 g');
});

test('context route rejects unavailable bootstrap without mock identity', async ({ request }) => {
  const response = await request.post('/app/api/context', { data: { person: ['PSN-00001'] } });
  expect(response.status()).toBe(401);
  expect(await response.text()).not.toContain('Synthetic Viewer');
});

test('Person navigation keeps no-referrer and no-store response headers', async ({ page }) => {
  await authenticate(page);
  const response = await page.goto('/app?person=PSN-00007');
  expect(response?.headers()['referrer-policy']).toBe('no-referrer');
  const contextResponse = await page.request.post('/app/api/context', { data: { person: ['PSN-00007'] } });
  expect(contextResponse.headers()['cache-control']).toBe('no-store');
  expect(contextResponse.headers()['referrer-policy']).toBe('no-referrer');
});
