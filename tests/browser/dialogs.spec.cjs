const { test, expect, WIDTHS, THEMES, shell, navigate, audit, capture, cancel } = require('./helpers.cjs');

for (const theme of THEMES) for (const width of WIDTHS) {
  test(`dialogs-${theme}-${width}: open, edit locally, cancel without saving`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 960 });
    await shell(page, theme);

    await navigate(page, 'users');
    await page.locator('[data-do="add-user"]').click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.locator('#user-form')).toBeVisible();
    const policy = dialog.locator('.infra-policy-section').first();
    await expect(policy.locator('.infra-grant-branch')).toHaveCount(27);
    await policy.locator('[data-policy-expand="true"]').click();
    await expect(policy.locator('.infra-grant-branch[open]')).toHaveCount(27);
    await policy.locator('[data-policy-expand="false"]').click();
    await expect(policy.locator('.infra-grant-branch[open]')).toHaveCount(0);
    await policy.locator('[data-policy-search]').fill('Вкусная кулинария 1');
    await expect(policy.locator('.infra-grant-branch:not([hidden])').first()).toBeVisible();
    await dialog.locator('[data-grant="spaces"][data-id="group_0"]').selectOption('read');
    await expect(dialog.locator('[data-grant="spaces"][data-id="group_0"]')).toHaveValue('read');
    await audit(page, testInfo, 'user-rights');
    await capture(page, testInfo, 'user-rights');
    await cancel(page);
    await expect(page.locator('[data-user-row]')).toHaveCount(3);

    await navigate(page, 'cameras');
    await page.locator('[data-do="add"]').click();
    await expect(dialog.locator('#device-form')).toBeVisible();
    await dialog.locator('input[name="name"]').fill('Несохранённое тестовое устройство');
    await audit(page, testInfo, 'inventory-create');
    await capture(page, testInfo, 'inventory-create');
    await cancel(page);
    await expect(page.locator('.inventory-device')).toHaveCount(7);
    await page.locator('.inventory-device [data-do="device"]').first().click();
    await expect(dialog.locator('#device-form')).toBeVisible();
    await audit(page, testInfo, 'inventory-edit');
    await cancel(page);

    await navigate(page, 'groups');
    await page.locator('[data-do="add-space"]').click();
    await expect(dialog.locator('#space-form')).toBeVisible();
    await dialog.locator('input[name="name"]').fill('Несохранённое пространство');
    await dialog.locator('.infra-icon-picker summary').click();
    await expect(dialog.locator('.infra-icon-grid button').first()).toBeVisible();
    await audit(page, testInfo, 'space-create');
    await capture(page, testInfo, 'space-create');
    await cancel(page);
    await expect(page.locator('.infra-space-row')).toHaveCount(27);

    await navigate(page, 'customize');
    for (const asset of ['logo', 'favicon']) {
      await page.locator(`#${asset}-icon`).click();
      await expect(dialog.locator('[data-brand-icon-picker]')).toBeVisible();
      await expect(dialog.locator('.infra-icon-grid button').first()).toBeVisible();
      await audit(page, testInfo, `${asset}-picker`);
      await capture(page, testInfo, `${asset}-picker`);
      await cancel(page);
    }

    // The account control is in the topbar, outside the mobile sidebar overlay.
    await expect(page.locator('body')).not.toHaveClass(/menu-open/);
    await page.locator('#user-button').click();
    await expect(dialog.locator('#profile-form')).toBeVisible();
    await dialog.locator('input[name="alias"]').fill('Несохранённый псевдоним');
    await audit(page, testInfo, 'profile');
    await capture(page, testInfo, 'profile');
    await cancel(page);
    const profile = await page.request.get('/api/profile');
    expect(profile.ok()).toBeTruthy();
    expect(JSON.stringify(await profile.json())).not.toContain('Несохранённый псевдоним');
  });
}
