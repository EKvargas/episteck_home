import { expect, test, type Page } from '@playwright/test';
import { berlinDaysAgo, expectTouchTarget, newRun, observed, signIn } from './nutrition-support';

const panel = (page: Page) => page.getByTestId('period-panel');
const row = (page: Page, name: string) => page.getByRole('row').filter({ has: page.getByRole('rowheader', { name }) });
const dots = (r: import('@playwright/test').Locator) => r.getByRole('img');

test('7 days by default: one mint, one period call with a start, no cookie, no demo banner', async ({ page, request }) => {
  const run = newRun();
  await signIn(page, 'days-three', run);
  const response = await page.goto('/app/nutrition/dias');
  await expect(panel(page)).toContainText('Últimos 7 días');
  await expect(panel(page)).toHaveAttribute('lang', 'es');
  expect(response?.headers()['cache-control']).toContain('no-store');
  await expect(page.getByRole('note', { name: 'Demo mock data' })).toHaveCount(0);
  const { mints, calls } = await observed(request, run);
  expect(mints).toBe(1);
  expect(calls).toEqual([{ path: `/diary/PSN-00001/period?start=${berlinDaysAgo(6)}`, hasCookie: false }]);
});

test('the 3-day link keeps the person and marks itself current', async ({ page, request }) => {
  const run = newRun();
  await signIn(page, 'days-three', run);
  await page.goto('/app/nutrition/dias?person=PSN-00001');
  const links = page.getByRole('navigation', { name: 'Rango de días' });
  await expect(links.getByRole('link', { name: '7 días' })).toHaveAttribute('aria-current', 'page');
  const three = links.getByRole('link', { name: '3 días' });
  await expect(three).toHaveAttribute('href', /\/nutrition\/dias\?person=PSN-00001&dias=3$/);
  await expect(three).not.toHaveAttribute('aria-current', 'page');
  await three.click();
  await expect(page).toHaveURL(/dias=3/);
  await expect(panel(page)).toContainText('Últimos 3 días');
  await expect(three).toHaveAttribute('aria-current', 'page');
  await expect(links.getByRole('link', { name: '14 días' })).toHaveAttribute('href', /person=PSN-00001&dias=14$/);
  const { calls } = await observed(request, run);
  expect(calls.at(-1)?.path).toBe(`/diary/PSN-00001/period?start=${berlinDaysAgo(2)}`);
});

test('the grid: four rows, a dot per day with its word for assistive tech, and the Media column', async ({ page }) => {
  await signIn(page, 'days-pregnancy', newRun());
  await page.goto('/app/nutrition/dias');
  const table = panel(page).getByRole('table');
  await expect(table).toHaveCount(1);
  const heads = await table.getByRole('columnheader').allInnerTexts();
  expect(heads.at(-1)).toBe('Media');
  expect(heads.slice(1, 8).map((h) => h.replace(/\s+/g, ' '))).toEqual(['X 18', 'J 19', 'V 20', 'S 21', 'D 22', 'L 23', 'M 24']);
  for (const name of ['Energía', 'Proteína', 'Fibra', 'Azúcares libres']) await expect(row(page, name)).toHaveCount(1);
  const energy = dots(row(page, 'Energía'));
  await expect(energy).toHaveCount(7);
  await expect(energy.nth(0)).toHaveAttribute('aria-label', /^Energía, 18 nov: bien$/);
  await expect(energy.nth(1)).toHaveAttribute('aria-label', /: bajo$/);
  await expect(energy.nth(3)).toHaveAttribute('aria-label', /: por encima$/);
  await expect(row(page, 'Energía').getByRole('cell').last()).toHaveText('2.246 kcal');
  await expect(dots(row(page, 'Azúcares libres')).nth(1)).toHaveAttribute('aria-label', /: pasado del límite$/);
  const text = await panel(page).innerText();
  expect(text).not.toMatch(/(^|\D)0 (g|kcal|%)/);
  await expect(panel(page)).toContainText('La media usa solo días cerrados y completos.');
});

test('a legend names every dot state in words, once for the page', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await signIn(page, 'days-fourteen', newRun());
  await page.goto('/app/nutrition/dias?dias=14');
  const items = panel(page).getByTestId('legend-item');
  await expect(panel(page).getByRole('list', { name: 'Leyenda' })).toHaveCount(1);
  await expect(items).toHaveText(['bien', 'corto · bajo · por encima · pasado del límite', 'en curso', 'sin cerrar', 'faltan datos', 'Sin registros']);
  for (const item of await items.all()) await expect(item).toBeVisible();
  expect(await panel(page).getByRole('list', { name: 'Leyenda' }).evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
  await expect(items.first().locator('[aria-hidden="true"]')).toHaveCount(1);
});

test('an unclosed past day is a grey ring with "sin cerrar"; today open is a neutral ring', async ({ page }) => {
  await signIn(page, 'days-pregnancy', newRun());
  await page.goto('/app/nutrition/dias');
  const energy = dots(row(page, 'Energía'));
  await expect(energy.nth(4)).toHaveAttribute('aria-label', /22 nov: sin cerrar$/);
  await expect(energy.nth(4)).toHaveAttribute('data-tone', 'unclosed');
  await expect(energy.nth(5)).toHaveAttribute('aria-label', /23 nov: Sin registros$/);
  await expect(energy.nth(6)).toHaveAttribute('aria-label', /24 nov: en curso/);
  await expect(energy.nth(6)).toHaveAttribute('data-tone', 'progress');
  const border = (i: number) => energy.nth(i).evaluate((el) => {
    const css = getComputedStyle(el);
    return { style: css.borderTopStyle, width: css.borderTopWidth };
  });
  expect((await border(4)).style).toBe('dashed');
  expect(await border(6)).toEqual({ style: 'solid', width: '2px' });
});

test('7 days at 390 px: the page never scrolls sideways and nothing needs a scroller', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await signIn(page, 'days-pregnancy', newRun());
  await page.goto('/app/nutrition/dias');
  const table = panel(page).getByRole('table');
  await expect(table).toHaveCount(1);
  const fits = await table.evaluate((el) =>
    el.scrollWidth <= el.clientWidth && document.documentElement.scrollWidth <= document.documentElement.clientWidth);
  expect(fits).toBe(true);
  await page.screenshot({ path: '../../.superpowers/sdd/2026-11-24-nutrition-ui-redesign/task-8-dias-7.png', fullPage: true });
});

test('14 days at 390 px: two stacked grids, Media once, no sideways scroll', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await signIn(page, 'days-fourteen', newRun());
  await page.goto('/app/nutrition/dias?dias=14');
  await expect(page.getByTestId('period-panel').getByRole('table')).toHaveCount(2);
  await expect(page.getByRole('columnheader', { name: 'Media' })).toHaveCount(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  const fits = await panel(page).getByRole('table').evaluateAll((els) => els.map((el) => el.scrollWidth <= el.clientWidth));
  expect(fits).toEqual([true, true]);
  await page.screenshot({ path: '../../.superpowers/sdd/2026-11-24-nutrition-ui-redesign/task-8-dias-14.png', fullPage: true });
});

test('a row opens the nutrient detail for the same range; the whole row is the target', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await signIn(page, 'days-pregnancy', newRun());
  await page.goto('/app/nutrition/dias?person=PSN-00001');
  const fiber = row(page, 'Fibra');
  const link = fiber.getByRole('link', { name: 'Fibra' });
  await expect(link).toHaveAttribute('href', '/app/nutrition/nutriente/fiber_g?person=PSN-00001&rango=7');
  expectTouchTarget(await fiber.boundingBox());
  expectTouchTarget(await link.boundingBox());
  // A tap in the middle of a day dot lands on the link overlay, not on the dot.
  const hit = await dots(fiber).nth(2).evaluate((el) => {
    const r = el.getBoundingClientRect();
    return document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)?.textContent ?? '';
  });
  expect(hit).toBe('Fibra');
});

test('vitamins and minerals · media groups follow the selected range', async ({ page }) => {
  await signIn(page, 'days-pregnancy', newRun());
  await page.goto('/app/nutrition/dias?dias=7');
  await expect(page.getByRole('heading', { name: /Vitaminas y minerales\s+· media/ })).toBeVisible();
  const groups = panel(page).locator('details');
  await expect(groups.locator('summary')).toHaveText(['Corto: hierro, folato, vitamina D, colina', 'Bien: 3', 'Faltan datos: 3']);
  await groups.first().locator('summary').click();
  await expect(groups.first().getByRole('link', { name: /Hierro/ })).toHaveAttribute('href', /nutriente\/iron_mg\?rango=7$/);
  await page.goto('/app/nutrition/dias?dias=14');
  await panel(page).locator('details').first().locator('summary').click();
  await expect(panel(page).locator('details').first().getByRole('link', { name: /Hierro/ })).toHaveAttribute('href', /rango=14$/);
});

test('no roadmap text: nothing mentions proyecto', async ({ page }) => {
  await signIn(page, 'days-pregnancy', newRun());
  await page.goto('/app/nutrition/dias');
  const text = await page.locator('body').innerText();
  expect(text).not.toMatch(/proyecto/i);
  expect(text).not.toContain('Actividad y partidos');
  expect(text).not.toContain('Patrones');
});

test('without a profile the hint shows and the dots are plain', async ({ page }) => {
  await signIn(page, 'days-no-profile', newRun());
  await page.goto('/app/nutrition/dias');
  await expect(panel(page)).toContainText('Sin perfil completo no hay objetivos de energía ni proteína con que comparar.');
  await expect(panel(page).getByRole('button', { name: /Quiero crear mi perfil/ })).toBeVisible();
  await expect(dots(row(page, 'Energía')).first()).toHaveAttribute('data-tone', 'plain');
  await expect(dots(row(page, 'Energía')).first()).toHaveAttribute('aria-label', /2\.510 kcal$/);
});

test('denied and error states are in Spanish; error offers Reintentar', async ({ page, request }) => {
  await signIn(page, 'days-denied', newRun());
  await page.goto('/app/nutrition/dias');
  await expect(panel(page)).toContainText('No tienes acceso a este historial de días.');
  expect(await page.locator('body').innerText()).not.toContain('ACCESS_DENIED');

  const run = newRun();
  await signIn(page, 'days-error', run);
  await page.goto('/app/nutrition/dias');
  await expect(panel(page)).toContainText('El historial de días no responde ahora. Inténtalo de nuevo.');
  await page.getByRole('button', { name: 'Reintentar' }).click();
  await expect.poll(async () => (await observed(request, run)).mints).toBe(2);
});

test('tabs Hoy · Días and the profile chip link to each other and keep ?person=', async ({ page }) => {
  await signIn(page, 'days-three', newRun());
  await page.goto('/app/nutrition/dias?person=PSN-00001');
  await expect(page.getByRole('heading', { level: 1, name: 'Nutrición' })).toBeVisible();
  const tabs = page.getByRole('navigation', { name: 'Nutrición', exact: true });
  await expect(tabs.getByRole('link', { name: 'Días', exact: true })).toHaveAttribute('aria-current', 'page');
  await expect(tabs.getByRole('link', { name: 'Perfil' })).toHaveCount(0);
  await expect(page.getByTestId('profile-chip')).toHaveAttribute('href', /\/nutrition\/perfil\?person=PSN-00001$/);
  await expect(tabs.getByRole('link', { name: 'Hoy', exact: true })).toHaveAttribute('href', /\/nutrition\/hoy\?person=PSN-00001$/);
  await expect(tabs.getByRole('link', { name: 'Días', exact: true })).toHaveAttribute('href', /\/nutrition\/dias\?person=PSN-00001$/);
  await expect(tabs.getByRole('link', { name: 'Acciones en Telegram' })).toHaveCount(0);

  await page.goto('/app/nutrition/perfil');
  await expect(page.getByTestId('profile-chip')).toHaveAttribute('aria-current', 'page');
  await expect(tabs.getByRole('link', { name: 'Días', exact: true })).toHaveAttribute('href', /\/nutrition\/dias$/);
});
