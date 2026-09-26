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

test('public kiosk images resolve beneath /app', async ({ page }) => {
  await setSessionCookie(page, 'authenticated');
  await page.goto('/app/kiosk');
  const imageSrc = await page.locator('img').first().getAttribute('src');
  expect(imageSrc).toContain('/app/_next/image');
  expect(decodeURIComponent(imageSrc ?? '')).toContain('/app/family-photos/');
});

test('Hub CSP is nonce-bound and includes current same-origin assets', async ({ page }) => {
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
  for (const path of ['/app', '/app/memory', '/app/nutrition/pregnancy']) {
    const response = await request.get(`http://127.0.0.1:3322${path}`, { maxRedirects: 0 });
    expect(response.status()).toBe(307);
    expect(new URL(response.headers().location ?? '', `http://127.0.0.1:3322${path}`).pathname).toBe('/login');
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

test('cleared session on a later /app request returns to root login', async ({ page }) => {
  await setSessionCookie(page, 'authenticated');
  await page.goto('/app');
  await expect(page.getByRole('heading', { name: 'Good afternoon, Synthetic Viewer' })).toBeVisible();
  await page.context().clearCookies();
  const response = await page.request.get('http://127.0.0.1:3322/app', { maxRedirects: 0 });
  expect(response.status()).toBe(307);
  expect(new URL(response.headers().location ?? '', 'http://127.0.0.1:3322/app').pathname).toBe('/login');
});
