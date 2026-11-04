const path = require('node:path');
const { test, expect, shell, navigate } = require('./helpers.cjs');

test('unsaved logo survives a catalog revision from another settings save', async ({ page }) => {
  await shell(page);
  await navigate(page, 'customize');
  const bootstrap = await page.request.get('/api/bootstrap');
  const { csrf_token } = await bootstrap.json();
  await page.locator('#branding-file').setInputFiles(path.join(__dirname, '../../static/brand/favicon.png'));
  const preview = page.locator('#logo-preview img');
  await expect(preview).toHaveAttribute('src', /^data:image\/png;base64,/);
  const draft = await preview.getAttribute('src');
  const revision = page.waitForResponse(r => new URL(r.url()).pathname === '/api/workspace/revision');
  const saved = await page.request.post('/api/settings', { data: {}, headers: { 'X-CSRF-Token': csrf_token } });
  expect(saved.ok()).toBeTruthy();
  await revision;
  await expect(page.locator('#brand-form')).toHaveAttribute('data-dirty', 'true');
  await expect(preview).toHaveAttribute('src', draft);
});

test('editing while branding save is pending retains the newer unsaved draft', async ({ page }) => {
  await shell(page);
  await navigate(page, 'customize');
  const originalResponse = await page.request.get('/api/branding');
  const original = await originalResponse.json();
  const bootstrap = await page.request.get('/api/bootstrap');
  const { csrf_token } = await bootstrap.json();
  let release, requested;
  const pending = new Promise(resolve => { requested = resolve; });
  const gate = new Promise(resolve => { release = resolve; });
  await page.route('**/api/branding', async route => {
    if (route.request().method() !== 'POST') return route.fallback();
    const response = await route.fetch();
    expect(response.ok()).toBeTruthy();
    requested();
    await gate;
    await route.fulfill({ response });
  });
  try {
    await page.locator('#brand-name').fill('Saved synthetic draft');
    await page.locator('button[form="brand-form"]').click();
    await pending;
    await expect(page.locator('button[form="brand-form"]')).toBeDisabled();
    await page.locator('#brand-name').fill('Newer unsaved synthetic draft');
    release();
    await expect(page.locator('button[form="brand-form"]')).toBeEnabled();
    await expect(page.locator('#brand-form')).toHaveAttribute('data-dirty', 'true');
    await expect(page.locator('#brand-name')).toHaveValue('Newer unsaved synthetic draft');
  } finally {
    release();
    await page.unroute('**/api/branding');
    const restored = await page.request.post('/api/branding', { data: original, headers: { 'X-CSRF-Token': csrf_token } });
    expect(restored.ok()).toBeTruthy();
  }
});
