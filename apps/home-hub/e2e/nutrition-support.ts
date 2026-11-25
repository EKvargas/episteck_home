import { randomUUID } from 'node:crypto';
import { expect, type APIRequestContext, type Page, type Request } from '@playwright/test';

export const HUB = 'http://127.0.0.1:3322';
export const BFF = 'http://127.0.0.1:3323';
export const NUTRITION = 'http://127.0.0.1:9930';
export const newRun = () => randomUUID().replace(/-/g, '');

/** Sets the scenario cookie and returns its value, so tests can assert the value never leaks. */
export async function signIn(page: Page, scenario: string, run: string, variant = '') {
  const value = `authenticated${variant}-nutr-${scenario}-run${run}`;
  await page.context().addCookies([{
    name: 'episteck_home_session', value, url: HUB, httpOnly: true, sameSite: 'Lax',
  }]);
  return value;
}

/** What the fake BFF and the fake Nutrition service saw for one run. */
export async function observed(request: APIRequestContext, run: string) {
  const mints = (await (await request.get(`${BFF}/__test/mints/${run}`)).json()).count as number;
  const calls = (await (await request.get(`${NUTRITION}/__test/calls/${run}`)).json()).calls as Array<{ path: string; hasCookie: boolean }>;
  const bootstraps = (await (await request.get(`${BFF}/__test/bootstraps/${run}`)).json()).count as number;
  return { mints, calls, bootstraps };
}

/** The Berlin date `back` days before today, computed independently of the Hub. */
export function berlinDaysAgo(back: number): string {
  const now = new Date();
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Europe/Berlin', year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(now).map((p) => [p.type, p.value]));
  return new Date(Date.UTC(Number(parts.year), Number(parts.month) - 1, Number(parts.day) - back)).toISOString().slice(0, 10);
}

/**
 * Every document and fetch body (RSC payloads, /api/context) the browser receives from the Hub.
 * Chromium keeps no RSC payload bodies (getResponseBody: "No data found"), so RSC fetches are
 * read through page.route and passed on unchanged; documents and other fetches still stream.
 * The scan never passes on nothing: it needs at least one non-empty body, and `rscContaining`
 * also needs the RSC payload of the retry or navigation the test exercises.
 */
export async function captureHubBodies(page: Page) {
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

export async function trackCspViolations(page: Page) {
  await page.addInitScript(() => {
    const w = window as typeof window & { __cspViolations?: string[] };
    w.__cspViolations = [];
    window.addEventListener('securitypolicyviolation', (event) => {
      w.__cspViolations?.push(`${event.violatedDirective}: ${event.blockedURI}`);
    });
  });
  return () => page.evaluate(() => (window as typeof window & { __cspViolations?: string[] }).__cspViolations ?? []);
}

const SECRETS = ['DELEGATION_SENTINEL', 'COOKIE_SENTINEL', 'episteck_home_session'];

export function expectNoSecrets(text: string, cookieValue: string) {
  for (const secret of [...SECRETS, cookieValue]) expect(text, secret).not.toContain(secret);
}

/** A touch target is at least 44 px tall; getBoundingClientRect can read 43.99999 for a 44 px box. */
export function expectTouchTarget(box: { height: number } | null) {
  expect(box?.height ?? 0, 'touch target height in px').toBeGreaterThanOrEqual(43.99);
}
