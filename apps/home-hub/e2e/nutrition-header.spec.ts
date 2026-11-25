import { expect, test } from '@playwright/test';
import { newRun, observed, signIn } from './nutrition-support';

const chip = (page: import('@playwright/test').Page) => page.getByTestId('profile-chip');
const tabs = (page: import('@playwright/test').Page) => page.getByRole('navigation', { name: 'Nutrición', exact: true });

test('the chip reads the mode from the page\'s own payload with no extra read', async ({ page, request }) => {
  const run = newRun();
  await signIn(page, 'days-pregnancy', run);
  await page.goto('/app/nutrition/dias');
  await expect(chip(page)).toHaveText('Embarazo · 2.º trimestre');
  await expect(chip(page)).toHaveAttribute('href', '/app/nutrition/perfil');
  const { mints, calls } = await observed(request, run);
  expect(mints).toBe(1);
  expect(calls).toHaveLength(1);
});

test('the chip on Hoy reads the day\'s mode; a plain profile reads Perfil', async ({ page }) => {
  await signIn(page, 'today-pregnancy', newRun());
  await page.goto('/app/nutrition/hoy');
  await expect(chip(page)).toHaveText('Embarazo · 2.º trimestre');

  await signIn(page, 'days-three', newRun());
  await page.goto('/app/nutrition/dias?person=PSN-00001');
  await expect(chip(page)).toHaveText('Perfil');
  await expect(chip(page)).toHaveAttribute('href', '/app/nutrition/perfil?person=PSN-00001');
});

test('without a profile: "Crear perfil" for the person, "Sin perfil" without a link for a viewer', async ({ page }) => {
  await signIn(page, 'days-no-profile', newRun());
  await page.goto('/app/nutrition/dias');
  await expect(chip(page)).toHaveText('Crear perfil');
  await expect(page.getByRole('link', { name: 'Crear perfil' })).toHaveAttribute('href', '/app/nutrition/perfil');

  await page.goto('/app/nutrition/dias?person=PSN-00007');
  await expect(chip(page)).toHaveText('Sin perfil');
  await expect(page.getByRole('link', { name: 'Sin perfil' })).toHaveCount(0);
});

test('Perfil marks the chip as current; the Hoy · Días tabs keep ?person= and mark the current one', async ({ page }) => {
  await signIn(page, 'present', newRun());
  await page.goto('/app/nutrition/perfil?person=PSN-00001');
  await expect(chip(page)).toHaveAttribute('aria-current', 'page');
  await expect(tabs(page).getByRole('link')).toHaveCount(2);
  await expect(tabs(page).getByRole('link', { name: 'Perfil' })).toHaveCount(0);
  await expect(tabs(page).getByRole('link', { name: 'Hoy', exact: true })).toHaveAttribute('href', /\/nutrition\/hoy\?person=PSN-00001$/);
  await expect(tabs(page).getByRole('link', { name: 'Días', exact: true })).toHaveAttribute('href', /\/nutrition\/dias\?person=PSN-00001$/);

  await signIn(page, 'days-three', newRun());
  await page.goto('/app/nutrition/dias?person=PSN-00001');
  await expect(tabs(page).getByRole('link', { name: 'Días', exact: true })).toHaveAttribute('aria-current', 'page');
  await expect(tabs(page).getByRole('link', { name: 'Hoy', exact: true })).not.toHaveAttribute('aria-current', 'page');
  await expect(chip(page)).not.toHaveAttribute('aria-current', 'page');
});

test('one person sees no switcher; two see it with chips at least 44 px tall', async ({ page }) => {
  await signIn(page, 'days-three', newRun(), '-self-only');
  await page.goto('/app/nutrition/dias');
  await expect(chip(page)).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'Context switcher' })).toHaveCount(0);

  await signIn(page, 'days-three', newRun());
  await page.goto('/app/nutrition/dias');
  await expect(chip(page)).toBeVisible();
  const options = page.getByRole('navigation', { name: 'Context switcher' }).getByRole('tab');
  await expect(options).toHaveCount(2);
  for (const option of await options.all()) {
    const box = await option.boundingBox();
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
  }
});

test('Actualizado HH:MM and Actualizar on Hoy and Días, not on Perfil', async ({ page }) => {
  await signIn(page, 'today-partial', newRun());
  for (const path of ['/app/nutrition/hoy', '/app/nutrition/dias']) {
    await page.goto(path);
    await expect(page.getByText(/Actualizado \d{2}:\d{2}/)).toBeVisible();
    await expect(page.getByRole('button', { name: 'Actualizar', exact: true })).toBeVisible();
  }
  await signIn(page, 'present', newRun());
  await page.goto('/app/nutrition/perfil');
  await expect(chip(page)).toBeVisible();
  await expect(page.getByText(/Actualizado \d{2}:\d{2}/)).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Actualizar', exact: true })).toHaveCount(0);
});

test('the header at 390 px never scrolls sideways', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await signIn(page, 'days-pregnancy', newRun());
  for (const path of ['/app/nutrition/dias?person=PSN-00001', '/app/nutrition/hoy', '/app/nutrition/ayuda']) {
    await page.goto(path);
    await expect(chip(page)).toBeVisible();
    const scrolls = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
    expect(scrolls, path).toBe(false);
  }
});

test('the help page shows the header with the plain Perfil chip and no extra read', async ({ page, request }) => {
  const run = newRun();
  await signIn(page, 'days-three', run);
  await page.goto('/app/nutrition/ayuda');
  await expect(chip(page)).toHaveText('Perfil');
  const { mints, calls } = await observed(request, run);
  expect(mints).toBe(0);
  expect(calls).toHaveLength(0);
});
