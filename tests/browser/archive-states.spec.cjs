const { test, expect, shell, navigate, audit, capture } = require('./helpers.cjs');

async function mode(page, value) {
  await page.goto('/__qa/archive');
  await page.getByLabel('Archive fixture mode').selectOption(value);
  await Promise.all([
    page.waitForResponse(r => new URL(r.url()).pathname === '/__qa/archive' && r.request().method() === 'POST'),
    page.getByRole('button', { name: 'Apply archive fixture' }).click(),
  ]);
}

for (const theme of ['light', 'dark']) for (const width of [320, 1440]) {
  for (const state of ['empty', 'error', 'failed', 'slow']) {
    test(`archive-${state}-${theme}-${width}: usable synthetic failure/loading state`, async ({ page, baseURL }, testInfo) => {
      await page.setViewportSize({ width, height: 960 });
      let releasePlayback;
      if (state === 'slow') {
        const gate = new Promise(resolve => { releasePlayback = resolve; });
        // Keep the genuine fixture response pending until its loading UI is captured.
        // This avoids a slow CI screenshot racing the server's four-second delay.
        await page.route(/\/api\/playback(?:\?|$)/, async route => {
          if (new URL(route.request().url()).origin !== new URL(baseURL).origin) return route.fallback();
          const response = await route.fetch();
          await gate;
          await route.fulfill({ response });
        });
      }
      await mode(page, state);
      try {
        await shell(page, theme);
        await navigate(page, 'archive', { settle: false });
        const viewer = page.locator('#arc-viewer');
        if (state === 'empty') {
          await expect(viewer).toHaveAttribute('data-player-state', 'empty');
          await expect(page.locator('.arc-recording')).toHaveCount(0);
          await expect(page.locator('#arc-play')).toBeDisabled();
        } else if (state === 'error') {
          await expect(viewer).toHaveAttribute('data-player-state', 'error');
          await expect(page.locator('#arc-state [data-action="retry"]')).toBeVisible();
          await expect(page.locator('#arc-search')).toBeEnabled();
        } else {
          await expect(viewer).toHaveAttribute('data-player-state', 'ready');
          await page.locator('#arc-play').click();
          await expect(viewer).toHaveAttribute('data-player-state', state === 'slow' ? 'loading' : 'error');
          await expect(page.locator('#arc-state')).toBeVisible();
          if (state === 'slow') await expect(viewer).toHaveAttribute('aria-busy', 'true');
        }
        await audit(page, testInfo, state);
        await capture(page, testInfo, `archive-${state}`);
        if (state === 'slow') {
          releasePlayback();
          await expect(viewer).toHaveAttribute('data-player-state', 'playing');
          await expect.poll(() => page.locator('#arc-video').evaluate(v => v.currentTime)).toBeGreaterThan(0);
        }
      } finally {
        releasePlayback?.();
        // Fixture mode is process-wide; always restore it for the next independent test.
        await mode(page, 'normal');
      }
    });
  }
}
