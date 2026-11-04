const { test, expect, shell, navigate, audit } = require('./helpers.cjs');

async function loginForm(page, username, password) {
  await page.goto('/login');
  await expect(page.locator('form[action="/login"]')).toBeVisible();
  await page.locator('#login').fill(username);
  await page.locator('#password').fill(password);
  const [response] = await Promise.all([
    page.waitForResponse(r => new URL(r.url()).pathname === '/login' && r.request().method() === 'POST'),
    page.waitForEvent('framenavigated', frame => frame === page.mainFrame()),
    page.locator('form[action="/login"] button[type="submit"]').click(),
  ]);
  return response;
}

test('actual login form rejects a bad password, then authenticates admin', async ({ page }, testInfo) => {
  const denied = await loginForm(page, 'demo_admin', 'incorrect-synthetic-password');
  expect(denied.status()).toBe(401);
  await expect(page.locator('form[action="/login"]')).toBeVisible();
  await audit(page, testInfo, 'login-rejected');
  const accepted = await loginForm(page, 'demo_admin', 'synthetic-demo-password');
  expect(accepted.status()).toBe(302);
  await expect(page.locator('#navigation')).toBeVisible();
  const bootstrap = await page.request.get('/api/bootstrap');
  expect((await bootstrap.json()).user.username).toBe('demo_admin');
});

test('viewer authenticates through form and receives server-side 403 for admin APIs', async ({ page }) => {
  const accepted = await loginForm(page, 'demo_viewer', 'synthetic-viewer-password');
  expect(accepted.status()).toBe(302);
  await expect(page.locator('#navigation')).toBeVisible();
  const bootstrap = await page.request.get('/api/bootstrap');
  expect((await bootstrap.json()).user.username).toBe('demo_viewer');
  for (const route of ['/api/users', '/api/settings', '/api/backup']) {
    const response = await page.request.get(route);
    expect(response.status(), route).toBe(403);
    expect(await response.json()).toHaveProperty('error');
  }
  await expect(page.locator('#navigation [data-view="users"]')).toHaveCount(0);
  await expect(page.locator('#navigation [data-view="devices"]')).toHaveCount(0);
  await navigate(page, 'archive');
  await expect(page.locator('#arc-export')).toBeDisabled();
});

test('synthetic archive decodes real MP4, plays, pauses, zooms and stops on navigation', async ({ page }, testInfo) => {
  await shell(page);
  await navigate(page, 'archive');
  await page.locator('#arc-camera').selectOption('demo_0');
  await expect(page.locator('#arc-search')).toBeEnabled();
  const [recordings] = await Promise.all([
    page.waitForResponse(r => new URL(r.url()).pathname === '/api/recordings' && r.ok()),
    page.locator('#arc-search').click(),
  ]);
  expect(await recordings.json()).toHaveLength(12);
  await expect(page.locator('.arc-recording')).toHaveCount(12);
  await expect(page.locator('#arc-play')).toBeEnabled();
  const video = page.locator('#arc-video');
  const [playback] = await Promise.all([
    page.waitForResponse(r => new URL(r.url()).pathname === '/api/playback' && [200, 206].includes(r.status())),
    page.locator('#arc-play').click(),
  ]);
  expect(playback.headers()['content-type']).toContain('video/mp4');
  await expect.poll(() => video.evaluate(v => v.readyState)).toBeGreaterThanOrEqual(2);
  await expect.poll(() => video.evaluate(v => v.videoWidth)).toBe(320);
  await expect.poll(() => video.evaluate(v => v.currentTime)).toBeGreaterThan(0.3);
  expect(await video.evaluate(v => v.paused)).toBe(false);
  await page.locator('#arc-viewer').hover();
  await page.locator('#arc-play').click();
  await expect.poll(() => video.evaluate(v => v.paused)).toBe(true);
  const paused = await video.evaluate(v => v.currentTime);
  // Positive polling verifies the frozen pause state across a bounded real interval.
  await page.waitForTimeout(300);
  expect(Math.abs((await video.evaluate(v => v.currentTime)) - paused)).toBeLessThan(0.1);
  await page.locator('#arc-zoom-in').click();
  await expect(page.locator('#arc-zoom-value')).not.toHaveText('1×');
  await page.locator('#arc-zoom-reset').click();
  await expect(page.locator('#arc-zoom-value')).toHaveText('1×');
  await expect(page.locator('#arc-audio-toggle')).toBeDisabled();
  await audit(page, testInfo, 'archive-playback');
  const oldVideo = await video.elementHandle();
  await navigate(page, 'groups');
  expect(await oldVideo.evaluate(v => v.paused && !v.getAttribute('src'))).toBe(true);
});
