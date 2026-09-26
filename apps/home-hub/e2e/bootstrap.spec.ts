import { expect, test } from '@playwright/test';

async function setSessionCookie(page: import('@playwright/test').Page, value: string) {
  await page.context().addCookies([{
    name: 'episteck_home_session',
    value,
    url: 'http://127.0.0.1:3322',
    httpOnly: true,
    sameSite: 'Lax',
  }]);
}

test('authenticated bootstrap shows the BFF viewer and discoverable contexts', async ({ page }) => {
  await setSessionCookie(page, 'authenticated');
  await page.goto('/app');
  await expect(page.getByRole('heading', { name: 'Good afternoon, Synthetic Viewer' })).toBeVisible();
  await expect(page.getByRole('tab', { name: 'Synthetic Care Context' })).toBeVisible();
  await expect(page.getByRole('tab', { name: 'Synthetic Circle' })).toBeVisible();
});

test('generated internal navigation stays under /app', async ({ page }) => {
  await setSessionCookie(page, 'authenticated');
  await page.goto('/app');
  await page.getByRole('link', { name: 'Memory' }).click();
  await expect(page).toHaveURL(/\/app\/memory$/);
  await expect(page.getByRole('heading', { name: 'Memory' })).toBeVisible();
});

test('prototype Nutrition content is clearly marked as demo mock data', async ({ page }) => {
  await setSessionCookie(page, 'authenticated');
  await page.goto('/app/nutrition');
  await expect(page.getByText('DEMO · MOCK DATA')).toBeVisible();
  await expect(page.getByText('svc-nutrition', { exact: true })).toHaveCount(0);
});

test('prototype routes label domain content and make no consent or live-source claims', async ({ page }) => {
  await setSessionCookie(page, 'authenticated');
  const forbiddenClaims = /Consent Granted|Consent required|Full Clinical Consent|authorized|Active care consent|Care Circle Access|Home Secure|Source: FHIR Gateway|Source: Device Gateway|Provenance: svc-nutrition|Live Status|live data|Active Care Link|Shared with you/i;
  for (const path of [
    '/app', '/app/health', '/app/nutrition', '/app/nutrition/pregnancy',
    '/app/calendar', '/app/memory', '/app/ask', '/app/kiosk', '/app/settings/privacy',
  ]) {
    await page.goto(path);
    await expect(page.getByRole('note', { name: 'Demo mock data' })).toBeVisible();
    const visibleText = await page.locator('body').innerText();
    expect(visibleText, path).not.toMatch(forbiddenClaims);
  }
  for (const path of ['/app', '/app/health', '/app/nutrition']) {
    await page.goto(path);
    const careTab = page.getByRole('tab', { name: 'Synthetic Care Context' });
    await careTab.click();
    await expect(page.getByRole('note', { name: 'Demo mock data' })).toBeVisible();
    expect(await page.locator('body').innerText(), `${path} care context`).not.toMatch(forbiddenClaims);
    if (path === '/app/nutrition') {
      await page.getByRole('link', { name: 'View Dashboard' }).click();
      await expect(page).toHaveURL(/\/app\/nutrition\/pregnancy$/);
      await expect(page.getByRole('note', { name: 'Demo mock data' })).toBeVisible();
      expect(await page.locator('body').innerText(), 'pregnancy care context').not.toMatch(forbiddenClaims);
    }
  }
});

test('mock assistant actions do not claim live device or domain writes', async ({ page }) => {
  await setSessionCookie(page, 'authenticated');
  await page.goto('/app');
  await page.getByRole('button', { name: /Ask Olin/ }).click();
  const dialog = page.getByRole('dialog', { name: 'Ask Olin' });
  await expect(dialog.getByText('Mock assistant conversation')).toBeVisible();
  await dialog.getByRole('button', { name: 'Lock front door' }).click();
  await expect(dialog.getByText('No device command was sent.', { exact: false })).toBeVisible();
  await dialog.getByRole('button', { name: 'Log lunch (420 kcal)' }).click();
  await expect(dialog.getByText('no nutrition or health record was updated.', { exact: false })).toBeVisible();
  expect(await dialog.innerText()).not.toMatch(/commanded the Home Assistant|via Nutrition domain service|live data/i);
});

test('calendar source manager identifies fictional accounts', async ({ page }) => {
  await setSessionCookie(page, 'authenticated');
  await page.goto('/app/calendar');
  await page.getByRole('button', { name: 'Demo Sources (5)' }).click();
  await expect(page.getByText('Fictional Google, Apple iCloud, and Work entries; no accounts are connected.')).toBeVisible();
  expect(await page.locator('body').innerText()).not.toMatch(/Connected Calendars|Federated multi-account synchronization|Synchronized with Family Circle|synced with iOS/i);
});

test('public kiosk images resolve beneath /app', async ({ page }) => {
  await setSessionCookie(page, 'authenticated');
  await page.goto('/app/kiosk');
  const imageSrc = await page.locator('img').first().getAttribute('src');
  expect(imageSrc).toContain('/app/_next/image');
  expect(decodeURIComponent(imageSrc ?? '')).toContain('/app/family-photos/');
});

test('Hub CSP is nonce-bound and includes current same-origin assets', async ({ page }) => {
  await page.addInitScript(() => {
    const w = window as typeof window & { __cspViolations?: string[] };
    w.__cspViolations = [];
    window.addEventListener('securitypolicyviolation', (event) => {
      w.__cspViolations?.push(`${event.violatedDirective}: ${event.blockedURI}`);
    });
  });
  await setSessionCookie(page, 'authenticated');
  const response = await page.goto('/app');
  const csp = response?.headers()['content-security-policy'] ?? '';
  expect(csp).toContain("script-src 'self' 'nonce-");
  expect(csp).toContain("style-src-attr 'unsafe-inline'");
  expect(csp).toContain("font-src 'self'");
  const inlineThemeScript = page.locator('script').first();
  const nonce = await inlineThemeScript.evaluate((script) => (script as HTMLScriptElement).nonce);
  expect(nonce).toBeTruthy();
  expect(csp).toContain(`'nonce-${nonce}'`);
  await expect.poll(() => page.evaluate(() => (window as typeof window & { __cspViolations?: string[] }).__cspViolations)).toEqual([]);
});

test('serialized client bootstrap props contain no upstream secrets or raw response', async ({ page }) => {
  await setSessionCookie(page, 'authenticated');
  const response = await page.goto('/app');
  const renderedFlight = await response?.text() ?? '';
  for (const sentinel of [
    'COOKIE_SENTINEL', 'BFF_URL_SENTINEL', 'ACCESS_TOKEN_SENTINEL',
    'REFRESH_TOKEN_SENTINEL', 'HOME_SESSION_ID_SENTINEL', 'DELEGATION_SENTINEL',
    'USER_NAME_SENTINEL', 'USER_EMAIL_SENTINEL', 'PRINCIPAL_SENTINEL',
    'GRANT_SENTINEL', 'RAW_UPSTREAM_SENTINEL',
  ]) {
    expect(renderedFlight).not.toContain(sentinel);
  }
  expect(renderedFlight).toContain('Synthetic Viewer');
  expect(renderedFlight).toContain('PSN-00001');
});

test('only the Hub session cookie reaches the BFF', async ({ page, request }) => {
  await setSessionCookie(page, 'authenticated');
  await page.context().addCookies([{
    name: 'unrelated', value: 'do-not-forward', url: 'http://127.0.0.1:3322',
  }]);
  await page.goto('/app');
  const forwarded = await request.get('http://127.0.0.1:3323/__test/last-cookie').then((r) => r.json());
  expect(forwarded.cookie).toBe('episteck_home_session=authenticated');
});

test('401 redirects once to the origin root /login', async ({ request }) => {
  for (const path of [
    '/app', '/app/', '/app/nutrition', '/app/nutrition/pregnancy',
    '/app/kiosk', '/app/a/b/c/d/e/f/g',
  ]) {
    const response = await request.get(`http://127.0.0.1:3322${path}?next=https%3A%2F%2Fevil.example`, {
      maxRedirects: 0,
      headers: {
        host: 'evil.example',
        'x-forwarded-host': 'evil.example',
        origin: 'https://evil.example',
        referer: 'https://evil.example/attacker',
      },
    });
    expect(response.status()).toBe(307);
    expect(response.headers().location).toBe('http://127.0.0.1:3322/login');
  }
});

test('502, 503, and malformed 200 render safe boundaries without redirect', async ({ page }) => {
  for (const value of ['authenticated-status-502', 'authenticated-status-503', 'authenticated-malformed']) {
    await setSessionCookie(page, value);
    await page.goto('/app');
    await expect(page.getByText('Service is currently unavailable. Please try again later.')).toBeVisible();
    await expect(page).toHaveURL(/\/app\/?$/);
  }
});

test('BFF POST /logout clears the browser session before the next /app request', async ({ page }) => {
  await setSessionCookie(page, 'authenticated');
  await page.goto('/app');
  await expect(page.getByRole('heading', { name: 'Good afternoon, Synthetic Viewer' })).toBeVisible();
  const logout = await page.request.post('http://127.0.0.1:3323/logout');
  expect(logout.ok()).toBeTruthy();
  expect(logout.headers()['set-cookie']).toContain('Max-Age=0');
  const response = await page.request.get('http://127.0.0.1:3322/app', { maxRedirects: 0 });
  expect(response.status()).toBe(307);
  expect(response.headers().location).toBe('http://127.0.0.1:3322/login');
});
