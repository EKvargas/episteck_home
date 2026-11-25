import { expect, test, type Locator, type Page } from '@playwright/test';
import { berlinDaysAgo, expectTouchTarget, newRun, observed, signIn } from './nutrition-support';

const panel = (page: Page) => page.getByTestId('period-panel');
const row = (page: Page, name: string) => page.getByRole('row').filter({ has: page.getByRole('rowheader', { name }) });
const dots = (r: Locator) => r.getByRole('img');

/** Whether a tap at the centre of `target` reaches it, not something laid over it. */
const tapReaches = (target: Locator) => target.evaluate((el) => {
  el.scrollIntoView({ block: 'center' });
  const r = el.getBoundingClientRect();
  return document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)?.closest('a, summary, button') === el;
});

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
  // The active pill wears the person chip's proven pair (badge text on the badge fill), never white on the accent.
  const colour = (l: Locator) => l.evaluate((el) => getComputedStyle(el).color);
  expect(await colour(links.getByRole('link', { name: '7 días' }))).toBe(await colour(page.getByRole('tab', { selected: true })));
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
  await expect(items).toHaveText(['bien', 'corto o bajo', 'por encima o pasado del límite', 'en curso', 'sin cerrar', 'faltan datos', 'Sin registros']);
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

test('under and over share amber but not the shape, and each dot says its own word', async ({ page }) => {
  await signIn(page, 'days-pregnancy', newRun());
  await page.goto('/app/nutrition/dias');
  const energy = dots(row(page, 'Energía'));
  await expect(energy.nth(1)).toHaveAttribute('data-mark', 'under');
  await expect(energy.nth(1)).toHaveAttribute('aria-label', /: bajo$/);
  await expect(energy.nth(3)).toHaveAttribute('data-mark', 'over');
  await expect(energy.nth(3)).toHaveAttribute('aria-label', /: por encima$/);
  await expect(dots(row(page, 'Proteína')).nth(1)).toHaveAttribute('aria-label', /: corto$/);
  await expect(dots(row(page, 'Azúcares libres')).nth(1)).toHaveAttribute('data-mark', 'over');
  const shape = (dot: Locator) => dot.evaluate((el) => {
    const css = getComputedStyle(el);
    return { clip: css.clipPath, colour: css.backgroundColor };
  });
  const [under, over] = [await shape(energy.nth(1)), await shape(energy.nth(3))];
  expect(under.colour).toBe(over.colour);
  expect(under.clip).toBe('none');
  expect(over.clip).toMatch(/^polygon/);
  // The legend draws the same two shapes beside their own words.
  const legend = panel(page).getByTestId('legend-item');
  await expect(legend.filter({ hasText: 'corto o bajo' }).locator('[data-mark="under"]')).toHaveCount(1);
  await expect(legend.filter({ hasText: 'por encima o pasado del límite' }).locator('[data-mark="over"]')).toHaveCount(1);
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
  // Each Media value keeps its number and unit on one line ("2.246 kcal", never "2.246" over "kcal").
  const media = await table.locator('tbody td:last-child').evaluateAll((cells) => cells.map((cell) => {
    const range = document.createRange();
    range.selectNodeContents(cell);
    return { text: cell.textContent ?? '', lines: new Set([...range.getClientRects()].map((r) => Math.round(r.top))).size };
  }));
  expect(media.map((m) => m.text)).toEqual(['2.246 kcal', '65 g', '27 g', '31 g']);
  for (const m of media) expect(m.lines, m.text).toBe(1);
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

// WebKit before Safari 27 ignores `position: relative` on a table row, so a row's tap area could
// escape to the page and catch every tap. The second pass forces rows static to stand in for it.
for (const rows of ['as drawn', 'with rows that cannot be positioned']) {
  test(`a row's tap area stays in its row (${rows})`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await signIn(page, 'days-pregnancy', newRun());
    await page.goto('/app/nutrition/dias?person=PSN-00001');
    await expect(panel(page).getByRole('table')).toHaveCount(1);
    if (rows !== 'as drawn') {
      // Through the CSSOM: the Hub's CSP refuses an injected <style>.
      await page.evaluate(() => document.querySelectorAll('tr').forEach((tr) => {
        tr.style.setProperty('position', 'static', 'important');
        tr.style.setProperty('transform', 'none', 'important');
      }));
    }
    const range = page.getByRole('navigation', { name: 'Rango de días' });
    const tabs = page.getByRole('navigation', { name: 'Nutrición', exact: true });
    const targets: Array<[string, Locator]> = [
      ['3 días', range.getByRole('link', { name: '3 días' })],
      ['14 días', range.getByRole('link', { name: '14 días' })],
      ['Hoy tab', tabs.getByRole('link', { name: 'Hoy', exact: true })],
      ['profile chip', page.getByTestId('profile-chip')],
      ['Actualizar', page.getByRole('button', { name: 'Actualizar' })],
      ['vitamin group', panel(page).locator('details summary').first()],
    ];
    for (const [name, target] of targets) expect(await tapReaches(target), name).toBe(true);
    // Each row still answers for itself, dots included.
    for (const name of ['Energía', 'Fibra', 'Azúcares libres']) {
      const hit = await dots(row(page, name)).nth(2).evaluate((el) => {
        el.scrollIntoView({ block: 'center' });
        const r = el.getBoundingClientRect();
        return document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2)?.closest('a')?.textContent ?? '';
      });
      expect(hit, name).toBe(name);
    }
  });
}

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
