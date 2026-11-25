import { expect, test, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { newRun, signIn } from './nutrition-support';

// Screenshots for the finish review. Skipped unless CAPTURE_REVIEW=1. Synthetic fixtures only.
test.skip(process.env.CAPTURE_REVIEW !== '1', 'set CAPTURE_REVIEW=1 to capture review screenshots');
test.use({ reducedMotion: 'reduce' });

const OUT = join(process.cwd(), '.impeccable', 'review');
const THEME_KEY = 'olin.appearance.theme.v1';
const PHONE = { width: 390, height: 844 };
const DESKTOP = { width: 1440, height: 900 };
// One dark and one other light theme besides the default.
const OTHER_THEMES = ['ambient-future', 'editorial-ledger'];

async function shoot(
  page: Page,
  o: { scenario: string; path: string; file: string; viewport: { width: number; height: number }; full?: boolean; theme?: string; ready?: string },
) {
  mkdirSync(OUT, { recursive: true });
  await page.setViewportSize(o.viewport);
  if (o.theme) {
    await page.addInitScript(([key, id]) => localStorage.setItem(key, id), [THEME_KEY, o.theme]);
  }
  await signIn(page, o.scenario, newRun());
  await page.goto(o.path);
  if (o.ready) await expect(page.getByTestId(o.ready)).toBeVisible();
  await page.waitForLoadState('networkidle');
  await expect(page.getByRole('note', { name: 'Demo mock data' })).toHaveCount(0);
  await page.screenshot({ path: join(OUT, o.file), fullPage: o.full ?? false });
}

test('mobile.png: Hoy at 390', async ({ page }) => {
  await shoot(page, { scenario: 'today-pregnancy', path: '/app/nutrition/hoy', file: 'mobile.png', viewport: PHONE, ready: 'today-panel' });
});

test('desktop.png: Hoy at 1440', async ({ page }) => {
  await shoot(page, { scenario: 'today-pregnancy', path: '/app/nutrition/hoy', file: 'desktop.png', viewport: DESKTOP, ready: 'today-panel' });
});

test('hoy-desktop-full.png: Hoy at 1440, full page', async ({ page }) => {
  await shoot(page, { scenario: 'today-pregnancy', path: '/app/nutrition/hoy', file: 'hoy-desktop-full.png', viewport: DESKTOP, full: true, ready: 'today-panel' });
});

test('hoy-mobile-full.png: Hoy at 390, full page', async ({ page }) => {
  await shoot(page, { scenario: 'today-pregnancy', path: '/app/nutrition/hoy', file: 'hoy-mobile-full.png', viewport: PHONE, full: true, ready: 'today-panel' });
});

for (const theme of OTHER_THEMES) {
  test(`hoy-${theme}-mobile.png`, async ({ page }) => {
    await shoot(page, { scenario: 'today-pregnancy', path: '/app/nutrition/hoy', file: `hoy-${theme}-mobile.png`, viewport: PHONE, theme, ready: 'today-panel' });
  });
}

test('dias-mobile.png: 7 days', async ({ page }) => {
  await shoot(page, { scenario: 'days-pregnancy', path: '/app/nutrition/dias', file: 'dias-mobile.png', viewport: PHONE, full: true, ready: 'period-panel' });
});

test('dias-14-mobile.png: 14 days', async ({ page }) => {
  await shoot(page, { scenario: 'days-fourteen', path: '/app/nutrition/dias?dias=14', file: 'dias-14-mobile.png', viewport: PHONE, full: true, ready: 'period-panel' });
});

test('nutriente-mobile.png: iron detail', async ({ page }) => {
  await shoot(page, { scenario: 'days-pregnancy', path: '/app/nutrition/nutriente/iron_mg', file: 'nutriente-mobile.png', viewport: PHONE, full: true, ready: 'nutrient-panel' });
});

test('perfil-mobile.png: Perfil', async ({ page }) => {
  await shoot(page, { scenario: 'present', path: '/app/nutrition/perfil', file: 'perfil-mobile.png', viewport: PHONE, full: true, ready: 'profile-panel' });
});

test('ayuda-mobile.png: ayuda', async ({ page }) => {
  await shoot(page, { scenario: 'today-pregnancy', path: '/app/nutrition/ayuda', file: 'ayuda-mobile.png', viewport: PHONE, full: true });
});
