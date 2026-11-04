const { test, expect, shell, navigate } = require('./helpers.cjs');

test('mobile navigation stays open during a background catalog refresh', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 960 });
  await shell(page, 'dark');
  await navigate(page, 'cameras');
  const original = await (await page.request.get('/api/branding')).json();
  const { csrf_token } = await (await page.request.get('/api/bootstrap')).json();
  let release, requested;
  const gate = new Promise(resolve => { release = resolve; });
  const pending = new Promise(resolve => { requested = resolve; });
  await page.route('**/api/workspace', async route => {
    const response = await route.fetch();
    expect(response.ok()).toBeTruthy();
    requested();
    await gate;
    await route.fulfill({ response });
  });
  try {
    const saved = await page.request.post('/api/branding', {
      data: { name: original.name }, headers: { 'X-CSRF-Token': csrf_token },
    });
    expect(saved.ok()).toBeTruthy();
    await pending;
    const oldSearch = await page.locator('[data-inventory-search]').elementHandle();
    await page.locator('#mobile-menu').click();
    await expect(page.locator('body')).toHaveClass(/menu-open/);
    release();
    // Require the refresh to finish, rather than asserting before it can close
    // the menu. The replacement inventory node is a visible completion signal.
    await expect.poll(() => oldSearch.evaluate(node => !node.isConnected)).toBe(true);
    await expect(page.locator('[data-inventory-search]')).toBeVisible();
    await expect(page.locator('body')).toHaveClass(/menu-open/);
    await page.locator('#navigation [data-view="groups"]').click();
    await expect(page.locator('body')).toHaveAttribute('data-view', 'groups');
    await expect(page.locator('body')).not.toHaveClass(/menu-open/);
  } finally {
    release();
    await page.unroute('**/api/workspace');
  }
});
