import { expect, test, type Page } from '@playwright/test';
import { berlinDaysAgo, expectTouchTarget, HUB, newRun, observed, signIn } from './nutrition-support';

const panel = (page: Page) => page.getByTestId('today-panel');
const weekly = (page: Page) => page.getByTestId('weekly-panel');
const byPath = (calls: Array<{ path: string; hasCookie: boolean }>) => [...calls].sort((a, b) => a.path.localeCompare(b.path));

test('an empty day shows "Sin registros hoy" and never "0 g"; one mint and one diary call without a cookie', async ({ page, request }) => {
  const run = newRun();
  await signIn(page, 'today-empty', run);
  const response = await page.goto('/app/nutrition/hoy');
  await expect(panel(page)).toContainText('Sin registros hoy');
  await expect(panel(page)).toContainText('Azúcares libres: sin registros todavía');
  expect(await panel(page).innerText()).not.toMatch(/(^|\D)0 g/);
  await expect(panel(page).locator('meter')).toHaveCount(0);
  await expect(panel(page)).toHaveAttribute('lang', 'es');
  expect(response?.headers()['cache-control']).toContain('no-store');
  const { mints, calls } = await observed(request, run);
  expect(mints).toBe(2);
  expect(byPath(calls)).toEqual([
    { path: '/diary/PSN-00001/days/today', hasCookie: false },
    { path: `/diary/PSN-00001/period?start=${berlinDaysAgo(6)}`, hasCookie: false },
  ]);
});

test('a partial day lists entries with ~, "1 alimento sin contar" and the BLS attribution', async ({ page }) => {
  await signIn(page, 'today-partial', newRun());
  await page.goto('/app/nutrition/hoy');
  const text = () => panel(page).innerText();
  await expect(panel(page)).toContainText('Azúcares libres: 17 g de 50 g');
  await expect(panel(page)).toContainText('Día abierto · 1 alimento sin contar');
  await expect(panel(page)).toContainText('Zumo, 1 vaso (~200 g)');
  await expect(panel(page)).toContainText('Pan integral, 2 rebanadas (~60 g)');
  await expect(panel(page)).toContainText('sin dato');
  await expect(panel(page)).toContainText('Referencia general: 50 g de azúcares libres al día (OMS, DGE). No es una indicación médica.');
  await expect(panel(page)).toContainText('Bundeslebensmittelschlüssel (BLS)');
  await expect(panel(page).getByRole('meter', { name: 'Azúcares libres: 17 g de 50 g' })).toHaveAttribute('max', '50');
  await expect(panel(page).getByRole('meter', { name: 'Azúcares libres: 17 g de 50 g' })).toHaveAttribute('value', '17');
  expect(await text()).not.toMatch(/(^|\D)0 g/);
});

test('Hoy reads energy, protein and fiber against the day targets and never shows 0', async ({ page }) => {
  await signIn(page, 'today-partial', newRun());
  await page.goto('/app/nutrition/hoy');
  await expect(panel(page)).toContainText('Energía: 436 de 2.250 kcal');
  await expect(panel(page)).toContainText('Proteína: 12 de 60 g');
  await expect(panel(page)).toContainText('Fibra: 3 de 30 g (1 sin contar)');
  await expect(panel(page).getByRole('meter', { name: 'Energía: 436 de 2.250 kcal' })).toBeVisible();
  const text = await panel(page).innerText();
  expect(text).not.toMatch(/(^|\D)0 (g|kcal)/);
  expect(text).not.toContain('Crea tu perfil');

  await signIn(page, 'today-empty', newRun());
  await page.goto('/app/nutrition/hoy');
  await expect(panel(page)).toContainText('Energía: sin registros todavía');
  expect(await panel(page).innerText()).not.toMatch(/(^|\D)0 (g|kcal)/);
});

test('without a profile Hoy shows the hint and no Energía line', async ({ page }) => {
  await signIn(page, 'today-no-profile', newRun());
  await page.goto('/app/nutrition/hoy');
  await expect(panel(page)).toContainText('Crea tu perfil en el chat para ver energía, proteína y fibra frente a tus objetivos.');
  await expect(panel(page).getByRole('button', { name: 'Copiar «Quiero crear mi perfil»' })).toBeVisible();
  expect(await panel(page).innerText()).not.toContain('Energía:');
});

test('denied shows the Spanish denied copy; a 500 offers retry', async ({ page, request }) => {
  await signIn(page, 'today-denied', newRun());
  await page.goto('/app/nutrition/hoy');
  await expect(panel(page)).toContainText('No tienes acceso a este diario.');
  expect(await page.locator('body').innerText()).not.toContain('ACCESS_DENIED');

  const run = newRun();
  await signIn(page, 'today-error', run);
  await page.goto('/app/nutrition/hoy');
  await expect(panel(page)).toContainText('El diario no responde ahora. Inténtalo de nuevo.');
  await page.getByRole('button', { name: 'Reintentar' }).click();
  await expect.poll(async () => (await observed(request, run)).mints).toBe(4);
});

test('no demo banner on /app/nutrition/hoy in LIVE', async ({ page }) => {
  await signIn(page, 'today-empty', newRun());
  await page.goto('/app/nutrition/hoy');
  await expect(panel(page)).toBeVisible();
  await expect(page.getByRole('note', { name: 'Demo mock data' })).toHaveCount(0);
});

test('mobile Home shows the diary summary and opens the live diary in one tap', async ({ page, request }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const run = newRun();
  await signIn(page, 'today-partial', run);
  await page.goto('/app');
  await expect(panel(page)).toContainText('Azúcares libres: 17 g de 50 g');
  await expect(panel(page)).toContainText('Referencia general');
  await expect(panel(page)).toContainText('Bundeslebensmittelschlüssel (BLS)');
  await expect(panel(page).getByText('Zumo', { exact: false })).toHaveCount(0);
  await expect(page.getByRole('note', { name: 'Demo mock data' })).toHaveCount(0);
  await expect(page.getByRole('heading', { name: /Attention & Tasks/ })).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Acciones en Telegram' })).toBeVisible();
  expect((await observed(request, run)).calls).toEqual([{ path: '/diary/PSN-00001/days/today', hasCookie: false }]);

  const nutritionLink = page.getByRole('link', { name: 'Nutrición', exact: true });
  await nutritionLink.click();
  await expect(page).toHaveURL(/\/app\/nutrition\/hoy\?person=PSN-00001$/);
  await expect(nutritionLink).toHaveAttribute('aria-current', 'page');
  await expect(panel(page)).toContainText('Zumo');
  await page.getByRole('link', { name: 'Perfil', exact: true }).click();
  await expect(page).toHaveURL(/\/app\/nutrition\/perfil\?person=PSN-00001$/);
  await expect(nutritionLink).toHaveAttribute('aria-current', 'location');
  await expect(page.getByTestId('profile-panel')).toContainText('Sin perfil de nutrición');
});

test('a Telegram action copies a generic prompt without personal diary data', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await signIn(page, 'today-partial', newRun());
  await page.goto('/app/nutrition/ayuda');
  await page.getByText('Registrar una comida', { exact: true }).click();
  await page.getByRole('button', { name: 'Copiar ejemplo para registrar una comida' }).click();
  await expect(page.getByText('Ejemplo copiado.')).toBeVisible();
  const clipboard = await page.evaluate(() => navigator.clipboard.readText());
  expect(clipboard).toBe('Hoy a las [hora] comí [alimentos y porciones]. Prepara el borrador y espera a que confirme.');
});

test('refreshing Hoy fetches the latest diary after a meal changes in Telegram', async ({ page, request }) => {
  const run = newRun();
  await signIn(page, 'today-updated', run);
  await page.goto('/app/nutrition/hoy');
  await expect(panel(page)).toContainText('Sin registros hoy');
  await page.getByRole('button', { name: 'Actualizar diario' }).click();
  await expect(panel(page)).toContainText('Pan integral');
  expect((await observed(request, run)).mints).toBe(4);
});

test('Hoy: two panels, two mints, one day GET and one 7-day period GET, no cookie, one bootstrap', async ({ page, request }) => {
  const run = newRun();
  await signIn(page, 'today-pregnancy', run);
  // Document only: no hydration and no /api/context, so the counters see the server render alone.
  const response = await page.request.get(`${HUB}/app/nutrition/hoy`);
  expect(response.status()).toBe(200);
  const html = await response.text();
  expect(html).toContain('Corto: hierro, folato, vitamina D, colina');
  const { mints, calls, bootstraps } = await observed(request, run);
  expect(mints).toBe(2);
  expect(bootstraps).toBe(1);
  expect(byPath(calls)).toEqual([
    { path: '/diary/PSN-00001/days/today', hasCookie: false },
    { path: `/diary/PSN-00001/period?start=${berlinDaysAgo(6)}`, hasCookie: false },
  ]);

  // The same render in a browser: the week reads as three groups and no panel retried.
  const browserRun = newRun();
  await signIn(page, 'today-pregnancy', browserRun);
  await page.goto('/app/nutrition/hoy');
  await expect(weekly(page)).toContainText('Corto: hierro, folato, vitamina D, colina');
  await expect(weekly(page)).toContainText('Bien: 3');
  await expect(weekly(page)).toContainText('Faltan datos: 3');
  await expect(weekly(page)).toHaveAttribute('lang', 'es');
  await expect(weekly(page).getByRole('heading', { name: 'Vitaminas y minerales · últimos 7 días' })).toBeVisible();
  expect((await observed(request, browserRun)).mints).toBe(2);
});

test('a vitamin group opens inline and each nutrient links to its detail', async ({ page }) => {
  await signIn(page, 'today-pregnancy', newRun());
  await page.goto('/app/nutrition/hoy');
  const iron = weekly(page).getByRole('link', { name: /Hierro/ });
  await expect(iron).toBeHidden();
  await weekly(page).getByText('Corto: hierro, folato, vitamina D, colina').click();
  await expect(iron).toBeVisible();
  await expect(iron).toHaveAttribute('href', '/app/nutrition/nutriente/iron_mg?rango=7');
  await expect(iron).toContainText('media 9,8 mg');
  await expect(iron).toContainText('objetivo ≥ 27 mg');
  await expect(iron).toContainText('corto');
  await expect(iron).toContainText('con 4 días');
  expectTouchTarget(await iron.boundingBox());
  await weekly(page).getByText('Faltan datos: 3').click();
  await expect(weekly(page)).toContainText('pocos días (2)');
  await expect(weekly(page)).toContainText('pocos días (1)');
  await expect(weekly(page)).toContainText('media sin dato');
});

test('each panel degrades on its own', async ({ page }) => {
  await signIn(page, 'today-week-error', newRun());
  await page.goto('/app/nutrition/hoy');
  await expect(panel(page)).toContainText('Pan integral');
  await expect(weekly(page)).toContainText('El resumen de la semana no responde ahora.');
  await expect(weekly(page).getByRole('button', { name: 'Reintentar' })).toBeVisible();

  await signIn(page, 'today-error', newRun());
  await page.goto('/app/nutrition/hoy');
  await expect(panel(page)).toContainText('El diario no responde ahora. Inténtalo de nuevo.');
  await expect(weekly(page)).toContainText('Sin objetivo: 10');
});

test('a denied week reads its own copy, never the raw code', async ({ page }) => {
  await signIn(page, 'today-denied', newRun());
  await page.goto('/app/nutrition/hoy');
  await expect(weekly(page)).toContainText('No tienes acceso a este resumen.');
  await expect(panel(page)).toContainText('No tienes acceso a este diario.');
  expect(await page.locator('body').innerText()).not.toContain('ACCESS_DENIED');
});

test('the weekly panel at 390 px never scrolls sideways', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await signIn(page, 'today-pregnancy', newRun());
  await page.goto('/app/nutrition/hoy');
  await expect(weekly(page)).toContainText('Corto: hierro');
  for (const text of ['Corto: hierro, folato, vitamina D, colina', 'Bien: 3', 'Faltan datos: 3']) {
    await weekly(page).getByText(text).click();
  }
  await expect(weekly(page).getByRole('link', { name: /DHA/ })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  const box = await weekly(page).boundingBox();
  expect((box?.x ?? 0) + (box?.width ?? 0)).toBeLessThanOrEqual(390);
});
