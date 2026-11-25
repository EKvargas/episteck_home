import { expect, test, type Page } from '@playwright/test';
import { berlinDaysAgo, expectTouchTarget, newRun, observed, signIn } from './nutrition-support';

const panel = (page: Page) => page.getByTestId('nutrient-panel');
const days = (page: Page) => page.getByTestId('detail-day');

test('detail: one mint, one period GET for the range, no cookie, no demo banner', async ({ page, request }) => {
  const run = newRun();
  await signIn(page, 'days-fourteen', run);
  await page.goto('/app/nutrition/nutriente/energy_kcal?rango=14');
  await expect(panel(page)).toHaveAttribute('lang', 'es');
  await expect(days(page)).toHaveCount(14);
  await expect(page.getByRole('note', { name: 'Demo mock data' })).toHaveCount(0);
  await expect(page.getByText(/^Actualizado \d\d:\d\d$/)).toBeVisible();
  const { mints, calls } = await observed(request, run);
  expect(mints).toBe(1);
  expect(calls).toEqual([{ path: `/diary/PSN-00001/period?start=${berlinDaysAgo(13)}`, hasCookie: false }]);
});

test('top: name, average against target with the state word; range links keep the person', async ({ page }) => {
  await signIn(page, 'days-pregnancy', newRun());
  await page.goto('/app/nutrition/nutriente/iron_mg?person=PSN-00001');
  await expect(panel(page).getByRole('heading', { name: 'Hierro' })).toBeVisible();
  await expect(panel(page)).toContainText('Media 9,8 mg · objetivo ≥ 27 mg');
  await expect(page.getByTestId('detail-state')).toHaveText('corto · con 4 días');
  const links = page.getByRole('navigation', { name: 'Rango de días' });
  await expect(links.getByRole('link', { name: '7 días' })).toHaveAttribute('aria-current', 'page');
  await expect(links.getByRole('link', { name: '3 días' })).toHaveAttribute('href', /\/nutrition\/nutriente\/iron_mg\?person=PSN-00001&rango=3$/);
  await expect(page.getByRole('navigation', { name: 'Nutrición', exact: true }).getByRole('link', { name: 'Días', exact: true }))
    .toHaveAttribute('aria-current', 'page');
  await expect(panel(page).getByText('Objetivo diario: al menos 27 mg.')).toBeVisible();
});

test('a bar per closed day with the target mark; other days labelled by reason', async ({ page }) => {
  await signIn(page, 'days-pregnancy', newRun());
  await page.goto('/app/nutrition/nutriente/energy_kcal');
  await expect(days(page)).toHaveCount(7);
  await expect(panel(page).locator('[data-mark="band"]')).toHaveCount(4);
  const text = (await days(page).allInnerTexts()).map((t) => t.replace(/\s+/g, ' ').trim());
  // Every closed day names its state beside the bar; every other day names its reason.
  expect(text[0]).toContain('bien');
  expect(text[1]).toContain('bajo');
  expect(text[3]).toContain('por encima');
  expect(text[4]).toContain('sin cerrar');
  expect(text[5]).toContain('sin registros');
  expect(text[6]).toContain('abierto');
  expect(text[6]).toContain('1.640 kcal');
  for (const i of [4, 5, 6]) await expect(days(page).nth(i).locator('[data-mark]')).toHaveCount(0);
  await expect(panel(page).getByText('Objetivo diario: alrededor de 2.250 kcal.')).toBeVisible();
});

test('an unknown nutrient code shows the not-found content', async ({ page, request }) => {
  const run = newRun();
  await signIn(page, 'days-pregnancy', run);
  await page.goto('/app/nutrition/nutriente/magnesium_mg');
  await expect(page.getByText('No existe ese nutriente.')).toBeVisible();
  await expect(page.getByRole('link', { name: 'Ver Días' })).toHaveAttribute('href', '/app/nutrition/dias');
  await expect(page.locator('main, body').first()).not.toContainText('This page could not be found');
  await expect(panel(page)).toHaveCount(0);
  await page.goto('/app/nutrition/nutriente/..%2Fx');
  await expect(page.getByText('No existe ese nutriente.')).toBeVisible();
  // It never reads: no period call for a code that is not a nutrient.
  expect((await observed(request, run)).calls).toEqual([]);
});

test('free sugars show the limit line', async ({ page }) => {
  await signIn(page, 'days-pregnancy', newRun());
  await page.goto('/app/nutrition/nutriente/free_sugars_g');
  await expect(panel(page).getByRole('heading', { name: 'Azúcares libres' })).toBeVisible();
  await expect(panel(page).getByText('Límite diario: como máximo 50 g.')).toBeVisible();
  await expect(panel(page).locator('[data-mark="cap"]').first()).toBeVisible();
  await expect(days(page).nth(1)).toContainText('pasado del límite');
});

test('the source link points at the profile, keeps the person and does not prefetch', async ({ page, request }) => {
  const run = newRun();
  await signIn(page, 'days-pregnancy', run);
  await page.goto('/app/nutrition/nutriente/protein_g?person=PSN-00001');
  const link = panel(page).getByRole('link', { name: 'Ver de dónde sale en tu perfil' });
  await expect(link).toHaveAttribute('href', '/app/nutrition/perfil?person=PSN-00001');
  await page.waitForLoadState('networkidle');
  expect((await observed(request, run)).mints).toBe(1);
});

test('without a profile there is no target line and no bars', async ({ page }) => {
  await signIn(page, 'days-no-profile', newRun());
  await page.goto('/app/nutrition/nutriente/calcium_mg');
  await expect(panel(page)).not.toContainText('Objetivo diario');
  await expect(panel(page).locator('[data-mark]')).toHaveCount(0);
  // No row is empty: every day carries a word.
  for (const text of await days(page).allInnerTexts()) expect(text).toMatch(/sin objetivo|abierto|sin cerrar|sin registros/);
});

test('an error reads in Spanish and offers Reintentar', async ({ page }) => {
  await signIn(page, 'days-error', newRun());
  await page.goto('/app/nutrition/nutriente/iron_mg');
  await expect(panel(page)).toContainText('El historial de días no responde ahora. Inténtalo de nuevo.');
  await expect(page.getByRole('button', { name: 'Reintentar' })).toBeVisible();
  await expect(page.getByText(/Actualizado/)).toHaveCount(0);
});

test('the detail at 390 px never scrolls sideways and its targets are 44 px', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await signIn(page, 'days-pregnancy', newRun());
  await page.goto('/app/nutrition/nutriente/energy_kcal?person=PSN-00001');
  await expect(days(page)).toHaveCount(7);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  for (const link of await page.getByRole('navigation', { name: 'Rango de días' }).getByRole('link').all()) {
    expectTouchTarget(await link.boundingBox());
  }
  expectTouchTarget(await panel(page).getByRole('link', { name: /Ver de dónde sale/ }).boundingBox());
  await page.screenshot({ path: '../../.superpowers/sdd/2026-11-24-nutrition-ui-redesign/task-9-nutriente.png', fullPage: true });
});
