import { expect, test, type Page } from '@playwright/test';
import { berlinDaysAgo, newRun, observed, signIn } from './nutrition-support';

const panel = (page: Page) => page.getByTestId('period-panel');
const row = (page: Page, day: string) => page.getByRole('row').filter({ has: page.getByRole('rowheader', { name: new RegExp(`^${day}`) }) });

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

test('rows and the average read as in the model; nothing reads 0', async ({ page }) => {
  await signIn(page, 'days-three', newRun());
  await page.goto('/app/nutrition/dias');
  await expect(page.getByRole('columnheader')).toHaveText(['Día', 'Energía', 'Prot.', 'Fibra', 'Azúcares']);
  const friday = row(page, 'Vie 20');
  await expect(friday).toContainText('Cerrado');
  await expect(friday).toContainText('2.510');
  await expect(friday).toContainText('90 %');
  await expect(friday).toContainText('98 g');
  await expect(friday).toContainText('17 g');
  await expect(row(page, 'Sáb 21')).toContainText('sin dato');
  const open = row(page, 'Dom 22');
  await expect(open).toContainText('Abierto');
  await expect(open).toContainText('parcial');
  await expect(open).toContainText('sin dato');
  const average = row(page, 'Media');
  await expect(average).toContainText('2.375');
  await expect(average).toContainText('85 % · 2 días');
  await expect(average).toContainText('sin dato');
  await expect(panel(page)).toContainText('La media usa solo días cerrados y completos. Un día abierto o un dato que falta se muestra tal cual, nunca como 0.');
  await expect(panel(page)).toContainText('Actividad y partidos');
  await expect(panel(page)).toContainText('Llega con el registro de salud (proyecto 2).');
  await expect(panel(page)).toContainText('Patrones');
  await expect(panel(page)).toContainText('Llega en el proyecto 3, para que los confirmes o descartes.');
  const text = await panel(page).innerText();
  expect(text).not.toMatch(/(^|\D)0 (g|kcal|%)/);
  expect(text).not.toContain('Sin perfil completo no hay objetivos');
});

test('without a profile the hint shows and no % appears', async ({ page }) => {
  await signIn(page, 'days-no-profile', newRun());
  await page.goto('/app/nutrition/dias');
  await expect(panel(page)).toContainText('Sin perfil completo no hay objetivos de energía ni proteína con que comparar.');
  await expect(panel(page).getByRole('button', { name: /Quiero crear mi perfil/ })).toBeVisible();
  await expect(row(page, 'Vie 20')).toContainText('2.510');
  // No profile: no percent for Energía, Prot. or Fibra (Media row included); the free-sugar limit still gives Azúcares a percent.
  for (const r of [row(page, 'Vie 20'), row(page, 'Sáb 21'), row(page, 'Dom 22'), row(page, 'Media')]) {
    for (const index of [1, 2, 3]) expect(await r.getByRole('cell').nth(index - 1).innerText()).not.toContain('%');
  }
  expect(await row(page, 'Vie 20').getByRole('cell').nth(3).innerText()).toContain('%');
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

test('Días at 390 px: the page never scrolls sideways; the table scrolls inside its wrapper', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await signIn(page, 'days-three', newRun());
  await page.goto('/app/nutrition/dias');
  await expect(panel(page)).toContainText('Últimos 7 días');
  const sizes = await page.evaluate(() => {
    const scroller = document.querySelector('[data-testid="period-panel"] [role="region"]') as HTMLElement;
    return {
      pageScrolls: document.documentElement.scrollWidth > document.documentElement.clientWidth,
      wrapperScrolls: scroller.scrollWidth > scroller.clientWidth,
      overflowX: getComputedStyle(scroller).overflowX,
    };
  });
  expect(sizes.pageScrolls).toBe(false);
  expect(sizes.wrapperScrolls).toBe(true);
  expect(sizes.overflowX).toBe('auto');
});

test('tabs Perfil · Hoy · Días link to each other and keep ?person=', async ({ page }) => {
  await signIn(page, 'days-three', newRun());
  await page.goto('/app/nutrition/dias?person=PSN-00001');
  await expect(page.getByRole('heading', { level: 1, name: 'Nutrición' })).toBeVisible();
  const tabs = page.getByRole('navigation', { name: 'Nutrición' });
  await expect(tabs.getByRole('link', { name: 'Días', exact: true })).toHaveAttribute('aria-current', 'page');
  await expect(tabs.getByRole('link', { name: 'Perfil', exact: true })).toHaveAttribute('href', /\/nutrition\/perfil\?person=PSN-00001$/);
  await expect(tabs.getByRole('link', { name: 'Hoy', exact: true })).toHaveAttribute('href', /\/nutrition\/hoy\?person=PSN-00001$/);
  await expect(tabs.getByRole('link', { name: 'Días', exact: true })).toHaveAttribute('href', /\/nutrition\/dias\?person=PSN-00001$/);
  await expect(tabs.getByRole('link', { name: 'Acciones en Telegram' })).toHaveCount(0);

  await page.goto('/app/nutrition/perfil');
  await expect(tabs.getByRole('link', { name: 'Perfil', exact: true })).toHaveAttribute('aria-current', 'page');
  await expect(tabs.getByRole('link', { name: 'Días', exact: true })).toHaveAttribute('href', /\/nutrition\/dias$/);
});
