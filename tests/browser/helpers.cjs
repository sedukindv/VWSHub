const { test: base, expect } = require('@playwright/test');

const WIDTHS = [320, 360, 390, 430, 768, 1024, 1280, 1440, 1920];
const THEMES = ['light', 'dark'];
const VIEWS = ['live', 'archive', 'cameras', 'groups', 'users', 'devices', 'logs', 'customize', 'settings'];
const READY = {
  live: '#wall-grid', archive: '#arc-camera', cameras: '[data-inventory-search]',
  groups: '[data-space-search]', users: '[data-user-row]', devices: '[data-device-grid]',
  logs: '#logs-refresh', customize: '#brand-form', settings: '#settings-form',
};

const test = base.extend({
  page: async ({ page, baseURL }, use, testInfo) => {
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const origin = new URL(baseURL).origin;
    await page.route('**/*', route => {
      const url = new URL(route.request().url());
      if (['data:', 'blob:', 'about:'].includes(url.protocol) || url.origin === origin) return route.continue();
      errors.push(`Unexpected external request: ${url.origin}${url.pathname}`);
      return route.abort('blockedbyclient');
    });
    await page.clock.setFixedTime(new Date('2026-11-03T06:00:00Z'));
    await use(page);
    await testInfo.attach('browser-errors', { body: JSON.stringify(errors, null, 2), contentType: 'application/json' });
    expect(errors, 'Uncaught JS errors or attempted non-loopback requests').toEqual([]);
  },
});

async function shell(page, theme = 'light') {
  await page.goto('/__qa/admin');
  await expect(page.locator('#navigation [data-view="live"]')).toBeAttached();
  // Theme controls are in the topbar; the mobile sidebar overlay would cover them.
  await expect(page.locator('body')).not.toHaveClass(/menu-open/);
  const [saved] = await Promise.all([
    page.waitForResponse(response => new URL(response.url()).pathname === '/api/profile/theme' && response.request().method() === 'POST'),
    page.locator(`#theme-switch [data-theme="${theme}"]`).click(),
  ]);
  expect(saved.ok(), 'Theme persistence request').toBeTruthy();
  await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
}

async function navigate(page, view, options = {}) {
  if (await page.locator('#mobile-menu').isVisible() && !(await page.locator('body').evaluate(el => el.classList.contains('menu-open')))) {
    await page.locator('#mobile-menu').click();
    await expect(page.locator('body')).toHaveClass(/menu-open/);
  }
  await page.locator(`#navigation [data-view="${view}"]`).click();
  await expect(page.locator('body')).toHaveAttribute('data-view', view);
  await expect(page.locator(READY[view]).first()).toBeAttached();
  await page.evaluate(() => document.fonts.ready);
  await expect(page.locator('body')).not.toHaveClass(/menu-open/);
  if (options.settle !== false) await settleView(page, view);
}

async function settleView(page, view) {
  if (view === 'live') {
    // New Live first performs asynchronous per-profile codec checks. Attached
    // tiles alone do not establish a working synthetic H.264 video wall.
    const videos = page.locator('#wall-grid video');
    await expect(videos).toHaveCount(4);
    await expect.poll(() => page.evaluate(() => ({
      playing: [...document.querySelectorAll('#wall-grid .wall-stream-status')].filter(node => node.dataset.state === 'playing').length,
      decoded: [...document.querySelectorAll('#wall-grid video')].filter(video => video.readyState >= 2 && video.videoWidth > 0).length,
    })), { timeout: 20000, message: 'All four synthetic Live streams must decode after codec negotiation' }).toEqual({ playing: 4, decoded: 4 });
  } else if (view === 'archive') {
    await expect(page.locator('#arc-viewer')).toHaveAttribute('data-player-state', 'ready');
    await expect(page.locator('.arc-recording')).toHaveCount(12);
    await expect(page.locator('#arc-search')).toBeEnabled();
  }
  await expect(page.locator('.toast.error'), 'Unexpected error toast on a normal fixture page').toHaveCount(0);
}

async function visualData(page, baseURL) {
  // Read the real endpoint first and fail if its response contract is broken.
  // Only pixels generated from cumulative/host-specific data are controlled here.
  await page.route(/\/api\/(?:logs|settings)(?:\?|$)/, async route => {
    if (new URL(route.request().url()).origin !== new URL(baseURL).origin) return route.fallback();
    if (route.request().method() !== 'GET') return route.fallback();
    const response = await route.fetch();
    expect(response.ok(), 'Visual fixture endpoint must succeed').toBeTruthy();
    const data = await response.json();
    if (new URL(route.request().url()).pathname === '/api/logs') {
      expect(Array.isArray(data.logs), 'Audit endpoint contract').toBeTruthy();
      data.logs = [
        { time: '2026-11-03T05:59:00+00:00', actor: 'demo_admin', action: 'auth.login', detail: {} },
        { time: '2026-11-03T06:00:00+00:00', actor: 'demo_admin', action: 'profile.updated', detail: { theme: 'light' } },
      ];
    } else {
      expect(data).toHaveProperty('settings');
      expect(data).toHaveProperty('metrics');
      expect(data.metrics).not.toBeNull();
      data.metrics = { cpu_percent: 12.5, memory_percent: 35, disk: { free: 68719476736, total: 137438953472 },
        uptime_seconds: 3660, process_memory_mb: 192 };
    }
    await route.fulfill({ response, json: data });
  });
}

async function audit(page, testInfo, name) {
  await page.evaluate(async () => {
    await Promise.all(Array.from(document.images).filter(img => img.getAttribute('src')).map(img =>
      img.decode().catch(() => {})));
  });
  const issues = await page.evaluate(() => {
    const visible = el => !!(el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden');
    const label = el => {
      const refs = (el.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean)
        .map(id => document.getElementById(id)?.textContent || '').join(' ');
      return (el.getAttribute('aria-label') || refs || el.getAttribute('title') || el.innerText ||
        Array.from(el.querySelectorAll('img[alt],svg title')).map(n => n.getAttribute('alt') || n.textContent).join(' ')).trim();
    };
    return {
      overflow: { actual: document.documentElement.scrollWidth, viewport: window.innerWidth },
      brokenImages: Array.from(document.images).filter(img => img.getAttribute('src') && (!img.complete || !img.naturalWidth))
        .map(img => ({ src: img.getAttribute('src'), id: img.id })),
      unlabelledButtons: Array.from(document.querySelectorAll('button,[role="button"]')).filter(visible).filter(el => !label(el))
        .map(el => el.outerHTML.slice(0, 500)),
      dialogs: Array.from(document.querySelectorAll('[role="dialog"]')).filter(visible).map(el => {
        const r = el.getBoundingClientRect();
        return { left: r.left, right: r.right, width: r.width };
      }),
    };
  });
  await testInfo.attach(`${name}-layout`, { body: JSON.stringify(issues, null, 2), contentType: 'application/json' });
  expect(issues.overflow.actual, 'Document horizontal overflow').toBeLessThanOrEqual(issues.overflow.viewport + 1);
  expect(issues.brokenImages, 'Broken images').toEqual([]);
  expect(issues.unlabelledButtons, 'Visible buttons without a meaningful accessible label').toEqual([]);
  for (const dialog of issues.dialogs) {
    expect(dialog.left, 'Dialog left edge').toBeGreaterThanOrEqual(-1);
    expect(dialog.right, 'Dialog right edge').toBeLessThanOrEqual(issues.overflow.viewport + 1);
  }
}

function screenshotOptions(page, visual = false) {
  return {
    fullPage: true, animations: 'disabled', caret: 'hide',
    mask: [page.locator('video,canvas,#wall-clock,#wall-streams'),
      ...(visual ? [] : [page.locator('.log-time,.metric strong,.metric .meter,.metric > span:last-child')])],
    maskColor: '#808080',
  };
}
async function capture(page, testInfo, name) {
  await testInfo.attach(name, { body: await page.screenshot(screenshotOptions(page)), contentType: 'image/png' });
}
async function cancel(page) {
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  await dialog.locator('[data-close]').first().click();
  await expect(dialog).toHaveCount(0);
}

module.exports = { test, expect, WIDTHS, THEMES, VIEWS, shell, navigate, audit, capture, cancel, screenshotOptions, visualData };
