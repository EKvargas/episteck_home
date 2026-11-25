import { expect, test, type Page } from '@playwright/test';
import { HUB, captureHubBodies, expectNoSecrets, expectTouchTarget, newRun, observed, signIn, trackCspViolations } from './nutrition-support';

const panel = (page: Page) => page.getByTestId('profile-panel');
const MOCK_STRINGS = /Protein|Carbs|Mealie|View Dashboard|Pregnancy Nutrition|Consent required/i;

test('PRESENT shows the full profile, nothing unknown, one mint, one call, no secrets', async ({ page, request }) => {
  const run = newRun();
  const cookieValue = await signIn(page, 'present', run, '-self-only');
  const cspViolations = await trackCspViolations(page);
  const hubBodies = await captureHubBodies(page);
  const response = await page.goto('/app/nutrition/perfil');
  await expect(panel(page)).toContainText('Embarazo · 2.º trimestre');
  await expect(panel(page)).toContainText('≈ 2.250 kcal');
  await expect(panel(page)).toContainText('vigentes desde 24 nov');
  // The due date sits at the top, before the targets.
  const text = await panel(page).innerText();
  expect(text.indexOf('Fecha prevista de parto')).toBeGreaterThan(-1);
  expect(text.indexOf('Fecha prevista de parto')).toBeLessThan(text.indexOf('Objetivos diarios'));
  expect(text.indexOf('1 mar 2027')).toBeLessThan(text.indexOf('Objetivos diarios'));
  // Explanation and source stay behind the ⓘ disclosure until it is opened.
  const sourceText = 'Mifflin-St Jeor';
  await expect(panel(page).getByText(sourceText).first()).toBeHidden();
  const info = page.locator('summary[aria-label="De dónde sale: Energía"]');
  expectTouchTarget(await info.boundingBox());
  await info.click();
  await expect(panel(page).getByText(sourceText).first()).toBeVisible();
  // History is collapsed until Historial is opened.
  await expect(panel(page).getByText('24 nov: perfil creado por chat')).toBeHidden();
  await panel(page).getByText('Historial', { exact: true }).click();
  await expect(panel(page).getByText('24 nov: perfil creado por chat')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Cambiar en el chat' })).toHaveCount(1);
  expect(await page.content()).not.toContain('UNKNOWN_FIELD_SENTINEL');
  // The legacy flat targets map is ignored: only target_set is shown.
  expect(await panel(page).innerText()).not.toContain('9.999');
  const food = panel(page).locator('section', { hasText: 'Comida' }).first();
  await expect(food).toContainText('PRIVATE_PREF_SENTINEL');
  await expect(food).toContainText('PRIVATE_DISLIKE_SENTINEL');
  await expect(food.getByText('lactosa', { exact: true })).toBeVisible();
  await expect(food.getByText('frutos secos', { exact: true })).toBeVisible();
  const { mints, calls } = await observed(request, run);
  expect(mints).toBe(1);
  expect(calls).toEqual([{ path: '/profile/PSN-00001', hasCookie: false }]);

  expect(response?.headers()['cache-control']).toContain('no-store');
  const html = (await response?.text()) ?? '';
  expect(new Set(html.match(/PSN-\d{5,}/g) ?? [])).toEqual(new Set(html.includes('PSN-00001') ? ['PSN-00001'] : []));
  expectNoSecrets(await hubBodies(), cookieValue);
  expect(await page.locator('body').innerText()).not.toMatch(MOCK_STRINGS);
  await expect(page.getByRole('note', { name: 'Demo mock data' })).toHaveCount(0);
  await expect.poll(cspViolations).toEqual([]);
});

test('one document render: layout and panel share one bootstrap, one mint, one Nutrition call', async ({ page, request }) => {
  const run = newRun();
  await signIn(page, 'absent', run);
  // Document only: no hydration and no /api/context, so the counters see the server render alone.
  const response = await page.request.get(`${HUB}/app/nutrition/perfil`);
  expect(response.status()).toBe(200);
  expect(await response.text()).toContain('Sin perfil de nutrición');
  expect((await observed(request, run)).bootstraps).toBe(1);
  const { mints, calls } = await observed(request, run);
  expect(mints).toBe(1);
  expect(calls).toHaveLength(1);
});

test('hovering Home and Nutrition on a demo route never prefetches private diary or profile data', async ({ page, request }) => {
  const run = newRun();
  await signIn(page, 'present', run);
  await page.goto('/app/health');
  await expect(page.getByRole('tab', { name: /Synthetic Viewer/ })).toBeVisible();
  await page.getByRole('link', { name: 'Nutrición', exact: true }).first().hover();
  await page.getByRole('link', { name: 'Inicio', exact: true }).first().hover();
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(1_000);
  expect(await observed(request, run)).toMatchObject({ mints: 0, calls: [] });
});

test('the demo banner still shows on other routes in LIVE', async ({ page }) => {
  await signIn(page, 'absent', newRun());
  await page.goto('/app/health');
  await expect(page.getByRole('note', { name: 'Demo mock data' })).toBeVisible();
});

test('a trailing-slash /app/nutrition/ shows no demo banner after hydration', async ({ page }) => {
  await signIn(page, 'absent', newRun());
  await page.goto('/app/nutrition/perfil/');
  // The server HTML never had the banner; the panel appears only after hydration and /api/context.
  await expect(panel(page)).toContainText('Sin perfil de nutrición');
  await page.waitForLoadState('networkidle');
  await expect(page.getByRole('note', { name: 'Demo mock data' })).toHaveCount(0);
});

test('ABSENT renders an honest empty state, not zeros or mock', async ({ page, request }) => {
  const run = newRun();
  await signIn(page, 'absent', run);
  await page.goto('/app/nutrition/perfil');
  await expect(panel(page)).toContainText('Sin perfil de nutrición');
  expect(await page.locator('body').innerText()).not.toMatch(MOCK_STRINGS);
  expect((await observed(request, run)).mints).toBe(1);
});

test('DENIED shows Acceso restringido with no reason and keeps the subject', async ({ page }) => {
  await signIn(page, '403', newRun());
  await page.goto('/app/nutrition/perfil?person=PSN-00007');
  await expect(panel(page)).toContainText('Acceso restringido');
  await expect(panel(page)).toContainText('No tienes acceso al perfil de nutrición de Synthetic Care Context.');
  expect(await page.locator('body').innerText()).not.toContain('ACCESS_DENIED');
  await expect(page).toHaveURL(/person=PSN-00007$/);
});

test('a session that dies after the layout shows a sign-in panel', async ({ page }) => {
  await signIn(page, '401', newRun());
  await page.goto('/app/nutrition/perfil');
  await expect(panel(page)).toContainText('Tu sesión ha caducado');
  await expect(page.getByRole('link', { name: 'Iniciar sesión' })).toHaveAttribute('href', 'http://127.0.0.1:3322/login');
});

test('unavailable offers Reintentar; a retry mints a fresh delegation and leaks nothing', async ({ page, request }) => {
  const run = newRun();
  const cookieValue = await signIn(page, '503', run);
  const hubBodies = await captureHubBodies(page);
  await page.goto('/app/nutrition/perfil');
  await expect(panel(page)).toContainText('Nutrición no responde ahora');
  await page.getByRole('button', { name: 'Reintentar' }).click();
  await expect.poll(async () => (await observed(request, run)).mints).toBe(2);
  expect((await observed(request, run)).calls).toHaveLength(2);
  await expect(page.getByRole('button', { name: 'Reintentar' })).toBeEnabled();
  expectNoSecrets(await hubBodies({ rscContaining: 'Nutrición no responde ahora' }), cookieValue);
});

test('a failed mint shows unavailable and never calls Nutrition', async ({ page, request }) => {
  const run = newRun();
  await signIn(page, 'present', run, '-mint-503');
  await page.goto('/app/nutrition/perfil');
  await expect(panel(page)).toContainText('Nutrición no responde ahora');
  expect((await observed(request, run)).calls).toEqual([]);
});

test('a mint 401 shows a sign-in panel and never calls Nutrition', async ({ page, request }) => {
  const run = newRun();
  await signIn(page, 'present', run, '-mint-401');
  await page.goto('/app/nutrition/perfil');
  await expect(panel(page)).toContainText('Tu sesión ha caducado');
  await expect(page.getByRole('link', { name: 'Iniciar sesión' })).toHaveAttribute('href', 'http://127.0.0.1:3322/login');
  expect(await observed(request, run)).toMatchObject({ mints: 1, calls: [] });
});

test('a malformed Nutrition body is shown as could-not-be-shown-safely', async ({ page }) => {
  await signIn(page, 'badbody', newRun());
  await page.goto('/app/nutrition/perfil');
  await expect(panel(page)).toContainText('No se pudo mostrar el perfil con seguridad');
});

test('a hung Nutrition upstream streams a skeleton, then times out to unavailable', async ({ page }) => {
  test.setTimeout(30_000);
  await signIn(page, 'hang', newRun());
  await page.goto('/app/nutrition/perfil', { waitUntil: 'commit' });
  await expect(page.getByRole('heading', { name: 'Nutrición' })).toBeVisible();
  await expect(panel(page)).toContainText('Cargando el perfil…');
  await expect(panel(page)).toContainText('Nutrición no responde ahora', { timeout: 15_000 });
});

for (const person of ['PSN-00999', 'CIR-00001', 'broken', '']) {
  test(`stale selection "${person}" makes no read for it; the canonical self URL makes exactly one`, async ({ page, request }) => {
    const run = newRun();
    await signIn(page, 'absent', run);
    await page.goto(`/app/nutrition/perfil?person=${person}`);
    await expect(page).toHaveURL(/person=PSN-00001$/);
    await expect(panel(page)).toContainText('Sin perfil de nutrición');
    const { mints, calls } = await observed(request, run);
    expect(mints).toBe(1);
    expect(calls).toEqual([{ path: '/profile/PSN-00001', hasCookie: false }]);
  });
}

test('actor-shaped query noise cannot change the subject', async ({ page, request }) => {
  const run = newRun();
  await signIn(page, 'absent', run);
  await page.goto('/app/nutrition/perfil?person=PSN-00001&actorPersonId=PSN-00999');
  await expect(panel(page)).toContainText('Sin perfil de nutrición');
  expect((await observed(request, run)).calls).toEqual([{ path: '/profile/PSN-00001', hasCookie: false }]);
});

test('switching subject re-reads for the new subject; Back restores the earlier panel without a new read', async ({ page, request }) => {
  const run = newRun();
  const cookieValue = await signIn(page, 'present', run);
  const hubBodies = await captureHubBodies(page);
  const other = 'Perfil de Synthetic Care Context';
  const viewer = 'Perfil de Synthetic Viewer';
  await page.goto('/app/nutrition/perfil?person=PSN-00007');
  await expect(panel(page)).toContainText(other);
  await expect(panel(page)).not.toContainText(viewer);
  await page.getByRole('tab', { name: /Synthetic Viewer/ }).click();
  await expect(page).toHaveURL(/person=PSN-00001$/);
  await expect(panel(page)).toContainText(viewer);
  await expect(panel(page)).not.toContainText(other);
  await page.goBack();
  await expect(page).toHaveURL(/person=PSN-00007$/);
  await expect(panel(page)).toContainText(other);
  await expect(panel(page)).not.toContainText(viewer);
  await page.waitForLoadState('networkidle');
  // Pinned (spec Invariants (b)): Next restores the history entry from its client router cache, so Back makes no new read.
  const paths = (await observed(request, run)).calls.map((call) => call.path);
  expect(paths).toEqual(['/profile/PSN-00007', '/profile/PSN-00001']);
  expectNoSecrets(await hubBodies({ rscContaining: 'Perfil de Synthetic' }), cookieValue);
});

test('a mode-only profile offers onboarding and still shows the due date', async ({ page }) => {
  await signIn(page, 'mode-only', newRun());
  await page.goto('/app/nutrition/perfil');
  await expect(panel(page)).toContainText('Todavía no hay perfil completo.');
  await expect(panel(page)).toContainText('Tu bot te hace unas ocho preguntas y calcula tus objetivos.');
  await expect(panel(page)).toContainText('Embarazo · 2.º trimestre');
  await expect(panel(page)).toContainText('1 mar 2027');
  await expect(panel(page)).not.toContainText('Sin perfil de nutrición');
  await expect(page.getByRole('button', { name: 'Copiar «Quiero crear mi perfil»' })).toBeVisible();
});

test('ABSENT offers the copy-ready "Quiero crear mi perfil"', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await signIn(page, 'absent', newRun());
  await page.goto('/app/nutrition/perfil');
  await expect(panel(page)).toContainText('Tu bot te hace unas ocho preguntas y calcula tus objetivos.');
  await page.getByRole('button', { name: 'Copiar «Quiero crear mi perfil»' }).click();
  await expect(page.getByText('Mensaje copiado. Pégalo en tu chat de Nutrición.')).toBeVisible();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe('Quiero crear mi perfil');
});

test("another subject's Perfil shows no chat prompts", async ({ page }) => {
  await signIn(page, 'present', newRun());
  await page.goto('/app/nutrition/perfil');
  await expect(page.getByRole('button', { name: 'Cambiar en el chat' })).toHaveCount(1);
  await page.goto('/app/nutrition/perfil?person=PSN-00007');
  await expect(panel(page).getByRole('heading', { name: 'Datos' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Cambiar en el chat' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Copiar «Quiero crear mi perfil»' })).toHaveCount(0);
});

test("another subject's Perfil omits the text addressed to the subject (ABSENT and mode-only)", async ({ page }) => {
  await signIn(page, 'absent', newRun());
  await page.goto('/app/nutrition/perfil');
  await expect(panel(page)).toContainText('Tu bot te hace unas ocho preguntas');
  await page.goto('/app/nutrition/perfil?person=PSN-00007');
  await expect(panel(page)).toContainText('Sin perfil de nutrición');
  await expect(panel(page)).not.toContainText('Tu bot te hace');
  await signIn(page, 'mode-only', newRun());
  await page.goto('/app/nutrition/perfil');
  await expect(panel(page)).toContainText('Tu bot te hace unas ocho preguntas');
  await page.goto('/app/nutrition/perfil?person=PSN-00007');
  await expect(panel(page)).toContainText('Todavía no hay perfil completo.');
  await expect(panel(page).getByRole('heading', { name: 'Datos' })).toBeVisible();
  await expect(panel(page)).not.toContainText('Tu bot te hace');
});

test('Perfil at 390 px never scrolls sideways', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await signIn(page, 'long-text', newRun());
  await page.goto('/app/nutrition/perfil');
  await expect(panel(page)).toContainText('Comida');
  await expect(panel(page)).toContainText('P'.repeat(500));
  const widths = await page.evaluate(() => {
    const el = document.scrollingElement!;
    return { scroll: el.scrollWidth, client: el.clientWidth };
  });
  expect(widths.scroll).toBeLessThanOrEqual(widths.client);
});
