const { defineConfig } = require('@playwright/test');
const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');

const port = Number(process.env.WVW_BROWSER_PORT || 5191);
if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error('Invalid WVW_BROWSER_PORT');
const baseURL = `http://127.0.0.1:${port}`;
const python = process.env.WVW_PYTHON || 'python';
// A fresh isolated store for every invocation; never attach to a real WVW server.
const data = fs.mkdtempSync(path.join(os.tmpdir(), 'wvw-browser-'));
module.exports = defineConfig({
  testDir: __dirname,
  testMatch: '**/*.spec.cjs',
  testIgnore: '**/hevc-https.spec.cjs',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60000,
  expect: { timeout: 10000, toHaveScreenshot: { animations: 'disabled', caret: 'hide', maxDiffPixelRatio: 0.001 } },
  // Missing images must fail comparison, never silently become accepted baselines.
  updateSnapshots: 'none',
  snapshotPathTemplate: '{testDir}/snapshots/{projectName}/{testFilePath}/{arg}{ext}',
  reporter: [['list'], ['html', { open: 'never' }]],
  outputDir: path.join(__dirname, 'test-results'),
  use: {
    baseURL, browserName: 'chromium', headless: true,
    viewport: { width: 1440, height: 960 }, deviceScaleFactor: 1,
    locale: 'ru-RU', timezoneId: 'Asia/Omsk', reducedMotion: 'reduce',
    trace: 'retain-on-failure', screenshot: 'only-on-failure',
    serviceWorkers: 'block',
  },
  projects: [{ name: 'chromium' }],
  webServer: {
    command: `"${python}" "${path.join(__dirname, 'fixture_server.py')}"`,
    cwd: __dirname,
    url: `${baseURL}/health`,
    timeout: 120000,
    reuseExistingServer: false,
    env: { WVW_BROWSER_PORT: String(port), WVW_BROWSER_DATA: data, WVW_BROWSER_SETUP: '0', PYTHONIOENCODING: 'utf-8' },
    stdout: 'ignore', stderr: 'pipe',
  },
});
