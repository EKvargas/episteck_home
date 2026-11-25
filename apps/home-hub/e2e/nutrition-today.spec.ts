import { expect, test, type Page } from '@playwright/test';
import { berlinDaysAgo, expectTouchTarget, HUB, newRun, observed, signIn } from './nutrition-support';

const panel = (page: Page) => page.getByTestId('today-panel');
const weekly = (page: Page) => page.getByTestId('weekly-panel');
const rows = (page: Page) => page.getByTestId('headline-row');
const verdict = (page: Page) => page.getByTestId('verdict');
const byPath = (calls: Array<{ path: string; hasCookie: boolean }>) => [...calls].sort((a, b) => a.path.localeCompare(b.path));
const paths = async (request: import('@playwright/test').APIRequestContext, run: string) =>
  byPath((await observed(request, run)).calls).map((call) => call.path);
const DAY = '/diary/PSN-00001/days/today';
const week = () => `/diary/PSN-00001/period?start=${berlinDaysAgo(6)}`;
const NO_ZERO = /(^|\D)0 (g|kcal)/;

/** The four headline rows keep one height, whether or not a bar or a word is drawn. */
async function expectEqualRowHeights(page: Page) {
  const heights = await rows(page).evaluateAll((els) => els.map((el) => el.getBoundingClientRect().height));
  expect(heights).toHaveLength(4);
  for (const height of heights) expect(Math.abs(height - heights[0]), `row heights ${heights.join(', ')}`).toBeLessThan(0.5);
}

/** Per row: how many parts its bar draws (fill + mark, or the mark alone) and the fill's share of the track. */
async function bars(page: Page) {
  return rows(page).evaluateAll((els) => els.map((row) => {
    const bar = row.querySelector('[data-mark]');
    if (!bar) return null;
    const width = bar.getBoundingClientRect().width;
    const fill = bar.children.length === 2 ? bar.children[0].getBoundingClientRect().width / width : null;
    return { mark: bar.getAttribute('data-mark'), tone: bar.getAttribute('data-tone'), parts: bar.children.length, fill };
  }));
}

// ------------------------------------------------------------------ the day

test('the first screen at 390×844 answers the day above the bottom nav', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await signIn(page, 'today-pregnancy', newRun());
  await page.goto('/app/nutrition/hoy');
  await expect(verdict(page)).toHaveText('Vas en camino. Te falta proteína. Faltan datos de 2 alimentos.');
  await expect(rows(page)).toContainText(['Energía', 'Proteína', 'Fibra', 'Azúcares libres']);
  await expect(rows(page).nth(0)).toContainText('1.640 de 2.250 kcal');
  await expect(rows(page).nth(0)).toContainText('en curso · faltan ~610 kcal');
  await expect(rows(page).nth(3)).toHaveAttribute('data-tone', 'unknown');
  const last = await rows(page).nth(3).boundingBox();
  expect(last!.y + last!.height).toBeLessThanOrEqual(844 - 60);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  await expectEqualRowHeights(page);
});

test('each bar fills the raw ratio over a 0–150 % track, with its target mark and tone', async ({ page }) => {
  await signIn(page, 'today-pregnancy', newRun());
  await page.goto('/app/nutrition/hoy');
  await expect(verdict(page)).toBeVisible();
  const drawn = await bars(page);
  expect(drawn.map((b) => [b?.mark, b?.tone, b?.parts])).toEqual([
    ['band', 'progress', 2], ['tick', 'progress', 2], ['tick', 'ok', 2], ['cap', 'unknown', 2],
  ]);
  // 1640.3 / 2241.6 and 12.0 / 50 of a track that ends at 150 %.
  expect(drawn[0]!.fill).toBeCloseTo(1640.3 / 2241.6 / 1.5, 2);
  expect(drawn[3]!.fill).toBeCloseTo(12 / 50 / 1.5, 2);
  await expect(rows(page).nth(3).locator('[data-mark]')).toHaveAttribute('style', /--bar-scale:\s*50;\s*--bar-value:\s*12\.0/);
  await expect(rows(page).nth(3).locator('[data-mark]')).toHaveAttribute('aria-hidden', 'true');
});

test('a partial GENERAL day: words, no 0 anywhere', async ({ page }) => {
  await signIn(page, 'today-partial', newRun());
  await page.goto('/app/nutrition/hoy');
  await expect(verdict(page)).toHaveText('Vas en camino. Te faltan proteína y fibra. Faltan datos de 1 alimento.');
  await expect(rows(page).nth(0)).toContainText('436 de 2.250 kcal');
  await expect(rows(page).nth(1)).toContainText('12 de 60 g');
  await expect(rows(page).nth(1)).toContainText('en curso · faltan 48 g');
  await expect(rows(page).nth(2)).toContainText('3 de 30 g');
  await expect(rows(page).nth(3)).toContainText('17 de 50 g');
  await expect(rows(page).nth(3)).toContainText('faltan datos');
  await expect(rows(page).nth(3).locator('[data-mark]')).toHaveAttribute('style', /--bar-scale:\s*50;\s*--bar-value:\s*17\.0/);
  await expect(panel(page)).toContainText('Grasa sin dato · Carbohidratos sin dato');
  await expect(panel(page)).toContainText('Zumo, 1 vaso (~200 g)');
  await expect(panel(page)).toContainText('Pan integral, 2 rebanadas (~60 g)');
  await expect(panel(page)).toContainText('Azúcares libres: sin dato');
  await expect(panel(page)).toContainText('sin datos de azúcares libres');
  const text = await panel(page).innerText();
  expect(text).not.toMatch(NO_ZERO);
  expect(text).not.toContain('Crea tu perfil');
  await expectEqualRowHeights(page);
});

test('an empty day: four rows say Sin registros and never 0; two mints, no cookie, no store', async ({ page, request }) => {
  const run = newRun();
  await signIn(page, 'today-empty', run);
  const response = await page.goto('/app/nutrition/hoy');
  await expect(verdict(page)).toHaveText('Aún no has anotado nada hoy.');
  await expect(rows(page)).toHaveCount(4);
  for (const row of await rows(page).all()) {
    await expect(row).toContainText('Sin registros');
    await expect(row).toHaveAttribute('data-tone', 'empty');
  }
  // Empty tracks: each bar draws its mark and no fill.
  expect((await bars(page)).map((b) => b?.parts)).toEqual([1, 1, 1, 1]);
  await expect(panel(page).getByRole('heading', { name: 'Comidas de hoy' })).toHaveCount(0);
  expect(await panel(page).innerText()).not.toMatch(NO_ZERO);
  await expect(panel(page)).toHaveAttribute('lang', 'es');
  await expect(panel(page)).toHaveAttribute('aria-label', 'Hoy');
  expect(response?.headers()['cache-control']).toContain('no-store');
  await expectEqualRowHeights(page);
  const { mints, calls } = await observed(request, run);
  expect(mints).toBe(2);
  expect(byPath(calls)).toEqual([
    { path: DAY, hasCookie: false },
    { path: week(), hasCookie: false },
  ]);
});

test('without a profile Hoy reads values only and offers the person the prompt', async ({ page }) => {
  await signIn(page, 'today-no-profile', newRun());
  await page.goto('/app/nutrition/hoy');
  await expect(verdict(page)).toHaveText('Día abierto. Faltan datos de 1 alimento.');
  await expect(panel(page)).toContainText('Crea tu perfil en el chat para ver energía, proteína y fibra frente a tus objetivos.');
  await expect(panel(page).getByRole('button', { name: 'Copiar «Quiero crear mi perfil»' })).toBeVisible();
  await expect(rows(page).nth(0)).toContainText('436 kcal');
  await expect(rows(page).nth(0)).not.toContainText(' de ');
  expect((await bars(page)).map((b) => b === null)).toEqual([true, true, true, false]);
  // A row without a target says why in its word slot; the one with a limit keeps its state word.
  for (const i of [0, 1, 2]) await expect(rows(page).nth(i)).toContainText('sin objetivo');
  await expect(rows(page).nth(3)).not.toContainText('sin objetivo');
  await expect(rows(page).nth(3)).toContainText('faltan datos');
  await expectEqualRowHeights(page);
});

test('a consent viewer sees neutral copy and no prompt', async ({ page }) => {
  await signIn(page, 'today-no-profile', newRun());
  await page.goto('/app/nutrition/hoy?person=PSN-00007');
  await expect(panel(page)).toContainText('Todavía no hay perfil completo.');
  await expect(page.getByRole('button', { name: 'Copiar «Quiero crear mi perfil»' })).toHaveCount(0);
  await expect(panel(page)).not.toContainText('Crea tu perfil');

  await signIn(page, 'today-pregnancy', newRun());
  await page.goto('/app/nutrition/hoy?person=PSN-00007');
  await expect(verdict(page)).toHaveText('Va en camino. Le falta proteína. Faltan datos de 2 alimentos.');
  await expect(panel(page)).toContainText('El prenatal aún no se cuenta: folato, yodo, vitamina D y DHA pueden estar cubiertos.');
  await expect(panel(page)).not.toContainText('Tu prenatal');
  await expect(page.getByRole('button', { name: /^Copiar/ })).toHaveCount(0);
});

test('pregnancy shows the prenatal note under the week; a GENERAL day does not', async ({ page }) => {
  await signIn(page, 'today-pregnancy', newRun());
  await page.goto('/app/nutrition/hoy');
  const note = panel(page).getByText('Tu prenatal aún no se cuenta: folato, yodo, vitamina D y DHA pueden estar cubiertos.');
  await expect(note).toBeVisible();
  await expect(weekly(page)).toContainText('Corto: hierro');
  const [noteBox, weekBox] = [await note.boundingBox(), await weekly(page).boundingBox()];
  expect(noteBox!.y).toBeGreaterThanOrEqual(weekBox!.y + weekBox!.height);

  await signIn(page, 'today-partial', newRun());
  await page.goto('/app/nutrition/hoy');
  await expect(verdict(page)).toBeVisible();
  await expect(panel(page)).not.toContainText('prenatal');
});

test('a meal opens inline to its items and notes', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await signIn(page, 'today-pregnancy', newRun());
  await page.goto('/app/nutrition/hoy');
  await expect(panel(page).getByRole('heading', { name: 'Comidas de hoy' })).toBeVisible();
  const lunch = panel(page).locator('summary', { hasText: '13:30 · Lentejas con arroz, Tarta casera' });
  const unmatched = panel(page).getByText('sin coincidencia en la base de alimentos');
  await expect(unmatched).toBeHidden();
  // One line at 390 px, even when the names do not fit, and a full touch target.
  const box = await lunch.boundingBox();
  expectTouchTarget(box);
  expect(box!.height).toBeLessThan(50);
  await panel(page).getByText('13:30 · Lentejas con arroz, Tarta casera').click();
  await expect(unmatched).toBeVisible();
  await expect(panel(page).getByText('Tarta casera, 1 rebanada (~90 g)')).toBeVisible();
  await expect(panel(page).getByText('Azúcares libres: sin dato')).toBeVisible();
  await expect(panel(page).getByText('sin datos de fibra')).toBeHidden();
  await panel(page).getByText('08:10 · Avena con leche, Plátano').click();
  await expect(panel(page).getByText('sin datos de fibra')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
});

test('Fuentes is collapsed and holds the reference and the BLS attribution', async ({ page }) => {
  await signIn(page, 'today-partial', newRun());
  await page.goto('/app/nutrition/hoy');
  const reference = panel(page).getByText('Referencia general: 50 g de azúcares libres al día (OMS, DGE). No es una indicación médica.');
  const attribution = panel(page).getByText('Bundeslebensmittelschlüssel (BLS) 4.0, Max Rubner-Institut');
  await expect(reference).toBeHidden();
  await expect(attribution).toBeHidden();
  const fuentes = panel(page).getByText('Fuentes', { exact: true });
  expectTouchTarget(await fuentes.boundingBox());
  await fuentes.click();
  await expect(reference).toBeVisible();
  await expect(attribution).toBeVisible();
});

test('¿Cómo anoto? links to /ayuda keeping ?person=', async ({ page, request }) => {
  const run = newRun();
  await signIn(page, 'today-partial', run);
  await page.goto('/app/nutrition/hoy?person=PSN-00001');
  const howTo = panel(page).getByRole('link', { name: '¿Cómo anoto?' });
  await expect(howTo).toHaveAttribute('href', '/app/nutrition/ayuda?person=PSN-00001');
  expectTouchTarget(await howTo.boundingBox());

  await page.goto('/app/nutrition/hoy');
  await expect(howTo).toHaveAttribute('href', '/app/nutrition/ayuda');
  await howTo.click();
  await expect(page).toHaveURL(/\/app\/nutrition\/ayuda$/);
  await expect(page.getByRole('heading', { name: '¿Cómo anoto?' })).toBeVisible();
  await page.waitForLoadState('networkidle');
  // Two Hoy renders of two panels each; the help page reads nothing.
  expect((await observed(request, run)).mints).toBe(4);
});

// ------------------------------------------------------- states and refresh

test('denied shows the Spanish denied copy; a 500 offers retry', async ({ page, request }) => {
  await signIn(page, 'today-denied', newRun());
  await page.goto('/app/nutrition/hoy');
  await expect(panel(page)).toContainText('No tienes acceso a este diario.');
  expect(await page.locator('body').innerText()).not.toContain('ACCESS_DENIED');
  await expect(page.getByText(/Actualizado \d{2}:\d{2}/)).toHaveCount(0);

  const run = newRun();
  await signIn(page, 'today-error', run);
  await page.goto('/app/nutrition/hoy');
  await expect(panel(page)).toContainText('El diario no responde ahora. Inténtalo de nuevo.');
  await expect(weekly(page)).toContainText('Sin objetivo: 10');
  // One refresh control over a failed day: its own Reintentar, no header Actualizar.
  await expect(page.getByText(/Actualizado \d{2}:\d{2}/)).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Actualizar', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Reintentar' }).click();
  await expect.poll(async () => (await observed(request, run)).mints).toBe(4);
  await expect.poll(() => paths(request, run)).toEqual([DAY, DAY, week(), week()]);
  await expect(panel(page)).toContainText('El diario no responde ahora. Inténtalo de nuevo.');
  await expect(weekly(page)).toContainText('Sin objetivo: 10');
});

test('no demo banner on /app/nutrition/hoy in LIVE', async ({ page }) => {
  await signIn(page, 'today-empty', newRun());
  await page.goto('/app/nutrition/hoy');
  await expect(panel(page)).toBeVisible();
  await expect(page.getByRole('note', { name: 'Demo mock data' })).toHaveCount(0);
});

test('refreshing Hoy fetches the latest diary after a meal changes in Telegram', async ({ page, request }) => {
  const run = newRun();
  await signIn(page, 'today-updated', run);
  await page.goto('/app/nutrition/hoy');
  await expect(verdict(page)).toHaveText('Aún no has anotado nada hoy.');
  await expect(weekly(page)).toContainText('Sin objetivo: 10');
  // One refresh control: the header's. The day no longer carries its own.
  const refresh = page.getByRole('button', { name: /^Actualiza/ });
  await expect(refresh).toHaveCount(1);
  await expect(refresh).toHaveText('Actualizar');
  await refresh.click();
  await expect(verdict(page)).toHaveText('Vas en camino. Te faltan proteína y fibra. Faltan datos de 1 alimento.');
  await expect(panel(page)).toContainText('Pan integral');
  await expect.poll(async () => (await observed(request, run)).mints).toBe(4);
  await expect.poll(() => paths(request, run)).toEqual([DAY, DAY, week(), week()]);
  await expect(weekly(page)).toContainText('Sin objetivo: 10');
});

// ------------------------------------------------------------- home card

test('mobile Home shows the verdict and four rows, and reads only the day', async ({ page, request }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const run = newRun();
  await signIn(page, 'today-partial', run);
  await page.goto('/app');
  await expect(verdict(page)).toHaveText('Vas en camino. Te faltan proteína y fibra. Faltan datos de 1 alimento.');
  await expect(rows(page)).toHaveCount(4);
  await expect(rows(page).nth(3)).toContainText('17 de 50 g');
  await expect(panel(page).getByRole('button', { name: 'Actualizar', exact: true })).toBeVisible();
  // The compact card is the answer only: no meals, no Fuentes, no week.
  await expect(panel(page).getByText('Zumo', { exact: false })).toHaveCount(0);
  await expect(panel(page).getByText('Referencia general')).toHaveCount(0);
  await expect(panel(page).getByText('Bundeslebensmittelschlüssel (BLS)', { exact: false })).toHaveCount(0);
  await expect(weekly(page)).toHaveCount(0);
  await expect(page.getByRole('note', { name: 'Demo mock data' })).toHaveCount(0);
  await expect(page.getByRole('heading', { name: /Attention & Tasks/ })).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Acciones en Telegram' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  await page.waitForLoadState('networkidle');
  // As before the redesign: one mint and one day GET, nothing more.
  const { mints, calls } = await observed(request, run);
  expect(mints).toBe(1);
  expect(calls).toEqual([{ path: DAY, hasCookie: false }]);

  await panel(page).getByRole('button', { name: 'Actualizar', exact: true }).click();
  await expect.poll(async () => (await observed(request, run)).mints).toBe(2);
  await expect.poll(() => paths(request, run)).toEqual([DAY, DAY]);

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

// ------------------------------------------------------ the weekly status

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
    { path: DAY, hasCookie: false },
    { path: week(), hasCookie: false },
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
  // The no-break space keeps "·" from starting the title's second line at this width.
  const title = weekly(page).getByRole('heading', { name: 'Vitaminas y minerales · últimos 7 días' });
  expect(await title.textContent()).toBe('Vitaminas y minerales\u00a0· últimos 7 días');
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  const box = await weekly(page).boundingBox();
  expect((box?.x ?? 0) + (box?.width ?? 0)).toBeLessThanOrEqual(390);
});
