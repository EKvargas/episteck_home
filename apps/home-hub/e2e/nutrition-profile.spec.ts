import { randomUUID } from 'node:crypto';
import { expect, test, type APIRequestContext, type Page, type Request } from '@playwright/test';

const HUB = 'http://127.0.0.1:3322';
const BFF = 'http://127.0.0.1:3323';
const NUTRITION = 'http://127.0.0.1:9930';
const newRun = () => randomUUID().replace(/-/g, '');

/** Sets the scenario cookie and returns its value, so tests can assert the value never leaks. */
async function signIn(page: Page, scenario: string, run: string, variant = '') {
  const value = `authenticated${variant}-nutr-${scenario}-run${run}`;
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

async function bootstrapReads(request: APIRequestContext, run: string) {
  return (await (await request.get(`${BFF}/__test/bootstraps/${run}`)).json()).count as number;
}

/**
 * Every document and fetch body (RSC payloads, /api/context) the browser receives from the Hub.
 * Chromium keeps no RSC payload bodies (getResponseBody: "No data found"), so RSC fetches are
 * read through page.route and passed on unchanged; documents and other fetches still stream.
 * The scan never passes on nothing: it needs at least one non-empty body, and `rscContaining`
 * also needs the RSC payload of the retry or navigation the test exercises.
 */
async function captureHubBodies(page: Page) {
  const pending: Array<Promise<{ rsc: boolean; text: string }>> = [];
  const isRsc = (request: Request) => request.headers()['rsc'] === '1';
  page.on('response', (response) => {
    const request = response.request();
    const type = request.resourceType();
    if (response.url().startsWith(`${HUB}/`) && (type === 'document' || type === 'fetch') && !isRsc(request)) {
      pending.push(response.text().catch(() => '').then((text) => ({ rsc: false, text })));
    }
  });
  await page.route((url) => url.href.startsWith(`${HUB}/`), async (route) => {
    if (!isRsc(route.request())) return route.fallback();
    const response = await route.fetch({ maxRedirects: 0 });
    const body = await response.body();
    pending.push(Promise.resolve({ rsc: true, text: body.toString('utf8') }));
    await route.fulfill({ response, body });
  });
  return async ({ rscContaining }: { rscContaining?: string } = {}) => {
    // Let Next's speculative RSC requests settle before unregistering their intercepted routes.
    await page.waitForLoadState('networkidle');
    await page.unrouteAll({ behavior: 'wait' });
    const bodies = (await Promise.all(pending)).filter((body) => body.text.length > 0);
    expect(bodies.length, 'captured Hub response bodies').toBeGreaterThan(0);
    if (rscContaining) {
      expect(bodies.some((body) => body.rsc && body.text.includes(rscContaining)), `an RSC payload with "${rscContaining}"`).toBe(true);
    }
    return bodies.map((body) => body.text).join('\n');
  };
}

async function trackCspViolations(page: Page) {
  await page.addInitScript(() => {
    const w = window as typeof window & { __cspViolations?: string[] };
    w.__cspViolations = [];
    window.addEventListener('securitypolicyviolation', (event) => {
      w.__cspViolations?.push(`${event.violatedDirective}: ${event.blockedURI}`);
    });
  });
  return () => page.evaluate(() => (window as typeof window & { __cspViolations?: string[] }).__cspViolations ?? []);
}

const panel = (page: Page) => page.getByTestId('profile-panel');
const MOCK_STRINGS = /Protein|Carbs|Mealie|View Dashboard|Pregnancy Nutrition|Consent required/i;
const SECRETS = ['DELEGATION_SENTINEL', 'COOKIE_SENTINEL', 'episteck_home_session'];

function expectNoSecrets(text: string, cookieValue: string) {
  for (const secret of [...SECRETS, cookieValue]) expect(text, secret).not.toContain(secret);
}

test('PRESENT shows the full profile, nothing unknown, one mint, one call, no secrets', async ({ page, request }) => {
  const run = newRun();
  const cookieValue = await signIn(page, 'present', run, '-self-only');
  const cspViolations = await trackCspViolations(page);
  const hubBodies = await captureHubBodies(page);
  const response = await page.goto('/app/nutrition');
  await expect(panel(page)).toContainText('Embarazo · 2.º trimestre');
  await expect(panel(page)).toContainText('≈ 2.250 kcal');
  await expect(panel(page)).toContainText('vigentes desde 24 nov');
  await expect(panel(page)).toContainText('24 nov: perfil creado por chat');
  expect(await page.content()).not.toContain('UNKNOWN_FIELD_SENTINEL');
  // The legacy flat targets map is ignored: only target_set is shown.
  expect(await panel(page).innerText()).not.toContain('9.999');
  const food = panel(page).locator('section', { hasText: 'Comida' }).first();
  await expect(food).toContainText('PRIVATE_PREF_SENTINEL');
  await expect(food).toContainText('PRIVATE_DISLIKE_SENTINEL');
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
  const response = await page.request.get(`${HUB}/app/nutrition`);
  expect(response.status()).toBe(200);
  expect(await response.text()).toContain('Sin perfil de nutrición');
  expect(await bootstrapReads(request, run)).toBe(1);
  const { mints, calls } = await observed(request, run);
  expect(mints).toBe(1);
  expect(calls).toHaveLength(1);
});

test('hovering Home and Nutrition on a demo route never prefetches private diary or profile data', async ({ page, request }) => {
  const run = newRun();
  await signIn(page, 'present', run);
  await page.goto('/app/health');
  await expect(page.getByRole('tab', { name: /Synthetic Viewer/ })).toBeVisible();
  await page.getByRole('link', { name: 'Nutrition', exact: true }).first().hover();
  await page.getByRole('link', { name: 'Today', exact: true }).first().hover();
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(1_000);
  expect(await observed(request, run)).toEqual({ mints: 0, calls: [] });
});

test('the demo banner still shows on other routes in LIVE', async ({ page }) => {
  await signIn(page, 'absent', newRun());
  await page.goto('/app/health');
  await expect(page.getByRole('note', { name: 'Demo mock data' })).toBeVisible();
});

test('a trailing-slash /app/nutrition/ shows no demo banner after hydration', async ({ page }) => {
  await signIn(page, 'absent', newRun());
  await page.goto('/app/nutrition/');
  // The server HTML never had the banner; the panel appears only after hydration and /api/context.
  await expect(panel(page)).toContainText('Sin perfil de nutrición');
  await page.waitForLoadState('networkidle');
  await expect(page.getByRole('note', { name: 'Demo mock data' })).toHaveCount(0);
});

test('ABSENT renders an honest empty state, not zeros or mock', async ({ page, request }) => {
  const run = newRun();
  await signIn(page, 'absent', run);
  await page.goto('/app/nutrition');
  await expect(panel(page)).toContainText('Sin perfil de nutrición');
  expect(await page.locator('body').innerText()).not.toMatch(MOCK_STRINGS);
  expect((await observed(request, run)).mints).toBe(1);
});

test('DENIED shows Acceso restringido with no reason and keeps the subject', async ({ page }) => {
  await signIn(page, '403', newRun());
  await page.goto('/app/nutrition?person=PSN-00007');
  await expect(panel(page)).toContainText('Acceso restringido');
  await expect(panel(page)).toContainText('No tienes acceso al perfil de nutrición de Synthetic Care Context.');
  expect(await page.locator('body').innerText()).not.toContain('ACCESS_DENIED');
  await expect(page).toHaveURL(/person=PSN-00007$/);
});

test('a session that dies after the layout shows a sign-in panel', async ({ page }) => {
  await signIn(page, '401', newRun());
  await page.goto('/app/nutrition');
  await expect(panel(page)).toContainText('Tu sesión ha caducado');
  await expect(page.getByRole('link', { name: 'Iniciar sesión' })).toHaveAttribute('href', 'http://127.0.0.1:3322/login');
});

test('unavailable offers Reintentar; a retry mints a fresh delegation and leaks nothing', async ({ page, request }) => {
  const run = newRun();
  const cookieValue = await signIn(page, '503', run);
  const hubBodies = await captureHubBodies(page);
  await page.goto('/app/nutrition');
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
  await page.goto('/app/nutrition');
  await expect(panel(page)).toContainText('Nutrición no responde ahora');
  expect((await observed(request, run)).calls).toEqual([]);
});

test('a mint 401 shows a sign-in panel and never calls Nutrition', async ({ page, request }) => {
  const run = newRun();
  await signIn(page, 'present', run, '-mint-401');
  await page.goto('/app/nutrition');
  await expect(panel(page)).toContainText('Tu sesión ha caducado');
  await expect(page.getByRole('link', { name: 'Iniciar sesión' })).toHaveAttribute('href', 'http://127.0.0.1:3322/login');
  expect(await observed(request, run)).toEqual({ mints: 1, calls: [] });
});

test('a malformed Nutrition body is shown as could-not-be-shown-safely', async ({ page }) => {
  await signIn(page, 'badbody', newRun());
  await page.goto('/app/nutrition');
  await expect(panel(page)).toContainText('No se pudo mostrar el perfil con seguridad');
});

test('a hung Nutrition upstream streams a skeleton, then times out to unavailable', async ({ page }) => {
  test.setTimeout(30_000);
  await signIn(page, 'hang', newRun());
  await page.goto('/app/nutrition', { waitUntil: 'commit' });
  await expect(page.getByRole('heading', { name: 'Nutrición' })).toBeVisible();
  await expect(panel(page)).toContainText('Cargando el perfil…');
  await expect(panel(page)).toContainText('Nutrición no responde ahora', { timeout: 15_000 });
});

for (const person of ['PSN-00999', 'CIR-00001', 'broken', '']) {
  test(`stale selection "${person}" makes no read for it; the canonical self URL makes exactly one`, async ({ page, request }) => {
    const run = newRun();
    await signIn(page, 'absent', run);
    await page.goto(`/app/nutrition?person=${person}`);
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
  await page.goto('/app/nutrition?person=PSN-00001&actorPersonId=PSN-00999');
  await expect(panel(page)).toContainText('Sin perfil de nutrición');
  expect((await observed(request, run)).calls).toEqual([{ path: '/profile/PSN-00001', hasCookie: false }]);
});

test('switching subject re-reads for the new subject; Back restores the earlier panel without a new read', async ({ page, request }) => {
  const run = newRun();
  const cookieValue = await signIn(page, 'present', run);
  const hubBodies = await captureHubBodies(page);
  const other = 'Perfil de Synthetic Care Context';
  const viewer = 'Perfil de Synthetic Viewer';
  await page.goto('/app/nutrition?person=PSN-00007');
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
  await page.goto('/app/nutrition');
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
  await page.goto('/app/nutrition');
  await expect(panel(page)).toContainText('Tu bot te hace unas ocho preguntas y calcula tus objetivos.');
  await page.getByRole('button', { name: 'Copiar «Quiero crear mi perfil»' }).click();
  await expect(page.getByText('Mensaje copiado. Pégalo en tu chat de Nutrición.')).toBeVisible();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe('Quiero crear mi perfil');
});

test("another subject's Perfil shows no chat prompts", async ({ page }) => {
  await signIn(page, 'present', newRun());
  await page.goto('/app/nutrition');
  await expect(page.getByRole('button', { name: 'Cambiar en el chat' })).toHaveCount(2);
  await page.goto('/app/nutrition?person=PSN-00007');
  await expect(panel(page)).toContainText('Datos básicos');
  await expect(page.getByRole('button', { name: 'Cambiar en el chat' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Copiar «Quiero crear mi perfil»' })).toHaveCount(0);
});

test("another subject's Perfil omits the text addressed to the subject (ABSENT and mode-only)", async ({ page }) => {
  await signIn(page, 'absent', newRun());
  await page.goto('/app/nutrition');
  await expect(panel(page)).toContainText('Tu bot te hace unas ocho preguntas');
  await page.goto('/app/nutrition?person=PSN-00007');
  await expect(panel(page)).toContainText('Sin perfil de nutrición');
  await expect(panel(page)).not.toContainText('Tu bot te hace');
  await signIn(page, 'mode-only', newRun());
  await page.goto('/app/nutrition');
  await expect(panel(page)).toContainText('Tu bot te hace unas ocho preguntas');
  await page.goto('/app/nutrition?person=PSN-00007');
  await expect(panel(page)).toContainText('Todavía no hay perfil completo.');
  await expect(panel(page)).toContainText('Datos básicos');
  await expect(panel(page)).not.toContainText('Tu bot te hace');
});

test('Perfil at 390 px never scrolls sideways', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await signIn(page, 'long-text', newRun());
  await page.goto('/app/nutrition');
  await expect(panel(page)).toContainText('Comida');
  await expect(panel(page)).toContainText('P'.repeat(500));
  const widths = await page.evaluate(() => {
    const el = document.scrollingElement!;
    return { scroll: el.scrollWidth, client: el.clientWidth };
  });
  expect(widths.scroll).toBeLessThanOrEqual(widths.client);
});
