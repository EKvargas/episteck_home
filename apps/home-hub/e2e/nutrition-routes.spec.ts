import { expect, test } from '@playwright/test';
import { HUB, newRun, observed, signIn } from './nutrition-support';

test('/app/nutrition redirects to Hoy keeping ?person=, before any Nutrition read', async ({ page, request }) => {
  const run = newRun();
  await signIn(page, 'today-partial', run);
  const response = await page.request.get(`${HUB}/app/nutrition?person=PSN-00007&dias=3`, { maxRedirects: 0 });
  expect(response.status()).toBe(307);
  expect(response.headers().location).toMatch(/\/app\/nutrition\/hoy\?person=PSN-00007$/);
  expect((await observed(request, run)).mints).toBe(0);
});

test('/app/nutrition without a selection redirects to plain Hoy', async ({ page }) => {
  await signIn(page, 'today-partial', newRun());
  const response = await page.request.get(`${HUB}/app/nutrition`, { maxRedirects: 0 });
  expect(response.status()).toBe(307);
  expect(response.headers().location).toMatch(/\/app\/nutrition\/hoy$/);
});

test('Perfil lives at /app/nutrition/perfil with no demo banner', async ({ page, request }) => {
  const run = newRun();
  await signIn(page, 'absent', run);
  await page.goto('/app/nutrition/perfil');
  await expect(page.getByTestId('profile-panel')).toContainText('Sin perfil de nutrición');
  await expect(page.getByRole('note', { name: 'Demo mock data' })).toHaveCount(0);
  const tabs = page.getByRole('navigation', { name: 'Nutrición' });
  await expect(tabs.getByRole('link', { name: 'Perfil', exact: true })).toHaveAttribute('aria-current', 'page');
  expect((await observed(request, run)).mints).toBe(1);
});

test('¿Cómo anoto? holds the Telegram actions and reads nothing from Nutrition', async ({ page, request }) => {
  const run = newRun();
  await signIn(page, 'today-partial', run);
  await page.goto('/app/nutrition/ayuda');
  await expect(page.getByRole('heading', { name: '¿Cómo anoto?' })).toBeVisible();
  await expect(page.getByText('Registrar una comida', { exact: true })).toBeVisible();
  await expect(page.getByRole('note', { name: 'Demo mock data' })).toHaveCount(0);
  const tabs = page.getByRole('navigation', { name: 'Nutrición' });
  await expect(tabs.locator('[aria-current]')).toHaveCount(0);
  await page.waitForLoadState('networkidle');
  const { mints, calls } = await observed(request, run);
  expect(mints).toBe(0);
  expect(calls).toEqual([]);
});

test('the bottom nav reads Inicio, Memoria, Nutrición, Salud, Ajustes; Nutrición opens Hoy', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await signIn(page, 'today-partial', newRun());
  await page.goto('/app/nutrition/ayuda');
  const nav = page.locator('nav').filter({ has: page.getByRole('link', { name: 'Inicio', exact: true }) }).last();
  await expect(nav.getByRole('link')).toHaveText(['Inicio', 'Memoria', 'Nutrición', 'Salud', 'Ajustes']);
  await expect(nav.getByRole('link', { name: 'Nutrición', exact: true })).toHaveAttribute('href', '/app/nutrition/hoy?person=PSN-00001');
});

test('Ajustes lists Perfil de nutrición, never prefetched; it opens Perfil', async ({ page, request }) => {
  const run = newRun();
  await signIn(page, 'absent', run);
  await page.goto('/app/settings/appearance');
  const link = page.getByRole('link', { name: 'Perfil de nutrición' });
  await expect(link).toHaveAttribute('href', '/app/nutrition/perfil?person=PSN-00001');
  await link.hover();
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(1_000);
  expect((await observed(request, run)).mints).toBe(0);
  await link.click();
  await expect(page.getByTestId('profile-panel')).toBeVisible();
});
