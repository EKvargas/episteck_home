import { randomUUID } from 'node:crypto';
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

const HUB = 'http://127.0.0.1:3322';
const BFF = 'http://127.0.0.1:3323';
const NUTRITION = 'http://127.0.0.1:9930';
const newRun = () => randomUUID().replace(/-/g, '');

async function signIn(page: Page, scenario: string, run: string) {
  const value = `authenticated-nutr-${scenario}-run${run}`;
  await page.context().addCookies([{
    name: 'episteck_home_session', value, url: HUB, httpOnly: true, sameSite: 'Lax',
  }]);
  return value;
}

async function observed(request: APIRequestContext, run: string) {
  const mints = (await (await request.get(`${BFF}/__test/mints/${run}`)).json()).count as number;
  const calls = (await (await request.get(`${NUTRITION}/__test/calls/${run}`)).json()).calls as Array<{ path: string; hasCookie: boolean }>;
  return { mints, calls };
}

const panel = (page: Page) => page.getByTestId('today-panel');

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
  expect(mints).toBe(1);
  expect(calls).toEqual([{ path: '/diary/PSN-00001/days/today', hasCookie: false }]);
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
  await expect(panel(page).locator('meter')).toHaveAttribute('max', '50');
  await expect(panel(page).locator('meter')).toHaveAttribute('value', '17');
  expect(await text()).not.toMatch(/(^|\D)0 g/);
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
  await page.getByRole('button', { name: 'Try again' }).click();
  await expect.poll(async () => (await observed(request, run)).mints).toBe(2);
});

test('no demo banner on /app/nutrition/hoy in LIVE', async ({ page }) => {
  await signIn(page, 'today-empty', newRun());
  await page.goto('/app/nutrition/hoy');
  await expect(panel(page)).toBeVisible();
  await expect(page.getByRole('note', { name: 'Demo mock data' })).toHaveCount(0);
});

test('the Nutrition page links to Hoy and keeps ?person=', async ({ page }) => {
  await signIn(page, 'today-empty', newRun());
  await page.goto('/app/nutrition');
  await expect(page.getByRole('link', { name: 'Hoy', exact: true })).toHaveAttribute('href', /\/nutrition\/hoy$/);
  await page.goto('/app/nutrition?person=PSN-00007');
  await expect(page.getByRole('link', { name: 'Hoy', exact: true })).toHaveAttribute('href', /\/nutrition\/hoy\?person=PSN-00007$/);
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

  const nutritionLink = page.getByRole('link', { name: 'Nutrition', exact: true });
  await nutritionLink.click();
  await expect(page).toHaveURL(/\/app\/nutrition\/hoy\?person=PSN-00001$/);
  await expect(nutritionLink).toHaveAttribute('aria-current', 'page');
  await expect(panel(page)).toContainText('Zumo');
  await page.getByRole('link', { name: 'Acciones en Telegram' }).click();
  await expect(page.getByRole('region', { name: 'Acciones en Telegram' })).toBeFocused();
  await expect(page.getByRole('heading', { name: 'Acciones en Telegram' })).toBeInViewport();
  await page.getByRole('link', { name: 'Perfil y objetivos' }).click();
  await expect(page).toHaveURL(/\/app\/nutrition\?person=PSN-00001$/);
  await expect(nutritionLink).toHaveAttribute('aria-current', 'location');
  await expect(page.getByTestId('profile-panel')).toContainText('Sin perfil de nutrición');
});

test('a Telegram action copies a generic prompt without personal diary data', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await signIn(page, 'today-partial', newRun());
  await page.goto('/app/nutrition/hoy');
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
  expect((await observed(request, run)).mints).toBe(2);
});
