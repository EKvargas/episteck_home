import { expect, test } from '@playwright/test';

// The Home Screen shortcut on an iPhone takes its picture from the page's
// apple-touch-icon link. Only /app reaches the Hub through nginx, and the
// phone may fetch the picture without the session, so both links must point
// under /app/ and must answer a logged-out request with the image itself.

const HUB = 'http://127.0.0.1:3322';

function pngSize(body: Buffer): { width: number; height: number } {
  expect(body.subarray(0, 8).toString('hex')).toBe('89504e470d0a1a0a');
  return { width: body.readUInt32BE(16), height: body.readUInt32BE(20) };
}

async function announcedIcons(page: import('@playwright/test').Page) {
  await page.context().addCookies([{
    name: 'episteck_home_session', value: 'authenticated', url: HUB, httpOnly: true, sameSite: 'Lax',
  }]);
  await page.goto('/app/nutrition/hoy');
  const touch = page.locator('head link[rel="apple-touch-icon"]');
  const tab = page.locator('head link[rel="icon"]');
  await expect(touch).toHaveCount(1);
  await expect(tab).toHaveCount(1);
  return {
    touchHref: await touch.getAttribute('href'),
    touchSizes: await touch.getAttribute('sizes'),
    tabHref: await tab.getAttribute('href'),
  };
}

test('the iPhone home-screen icon is announced under /app and served logged out as a 180x180 PNG', async ({ page, request }) => {
  const { touchHref, touchSizes } = await announcedIcons(page);
  expect(touchHref).toMatch(/^\/app\//);
  expect(touchSizes).toBe('180x180');
  const response = await request.get(`${HUB}${touchHref}`, { maxRedirects: 0 });
  expect(response.status()).toBe(200);
  expect(response.headers()['content-type']).toBe('image/png');
  expect(pngSize(await response.body())).toEqual({ width: 180, height: 180 });
});

test('the browser-tab icon is announced under /app and served logged out', async ({ page, request }) => {
  const { tabHref } = await announcedIcons(page);
  expect(tabHref).toMatch(/^\/app\/favicon\.ico(\?|$)/);
  const response = await request.get(`${HUB}${tabHref}`, { maxRedirects: 0 });
  expect(response.status()).toBe(200);
  expect(response.headers()['content-type']).toMatch(/^image\/(x-icon|vnd\.microsoft\.icon)$/);
});
