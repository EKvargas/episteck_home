import { expect, test } from '@playwright/test';

const SANS = /Plus[ _]Jakarta[ _]Sans/i;
const SERIF = /Fraunces/i;

test.beforeEach(async ({ page }) => {
  await page.context().addCookies([{
    name: 'episteck_home_session',
    value: 'authenticated',
    url: 'http://127.0.0.1:3322',
    httpOnly: true,
    sameSite: 'Lax',
  }]);
});

test('Olin pages use the next/font families, not the browser default serif', async ({ page }) => {
  await page.goto('/app/nutrition/hoy');
  const heading = page.getByRole('heading').first();
  await expect(heading).toBeVisible();

  const fonts = await page.evaluate(() => {
    const heading = document.querySelector('h1, h2, h3') as HTMLElement;
    return {
      body: getComputedStyle(document.body).fontFamily,
      heading: getComputedStyle(heading).fontFamily,
      sansToken: getComputedStyle(document.documentElement).getPropertyValue('--ep-font-sans').trim(),
      serifToken: getComputedStyle(document.documentElement).getPropertyValue('--ep-font-serif').trim(),
    };
  });

  expect(fonts.sansToken).toMatch(SANS);
  expect(fonts.serifToken).toMatch(SERIF);
  expect(fonts.body).toMatch(SANS);
  expect(fonts.heading).toMatch(SERIF);
});

test('the next/font faces are actually loaded in the document', async ({ page }) => {
  await page.goto('/app/nutrition/hoy');
  await expect(page.getByRole('heading').first()).toBeVisible();
  await page.evaluate(() => document.fonts.ready);

  await expect.poll(async () => page.evaluate(() => {
    const loaded = Array.from(document.fonts).filter((face) => face.status === 'loaded').map((face) => face.family);
    return {
      sans: loaded.some((family) => /Plus[ _]Jakarta[ _]Sans/i.test(family)),
      serif: loaded.some((family) => /Fraunces/i.test(family)),
    };
  })).toEqual({ sans: true, serif: true });
});
