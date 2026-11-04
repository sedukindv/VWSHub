const { test, expect, WIDTHS, THEMES, VIEWS, shell, navigate, audit, capture, screenshotOptions, visualData } = require('./helpers.cjs');

for (const theme of THEMES) for (const width of WIDTHS) for (const view of VIEWS) {
  const name = `${view}-${theme}-${width}`;
  test(`${name}: responsive structure`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 960 });
    await shell(page, theme);
    await navigate(page, view);
    await audit(page, testInfo, name);
    await capture(page, testInfo, name);
  });
  test(`${name}: reviewed baseline @visual`, async ({ page, baseURL }) => {
    await page.setViewportSize({ width, height: 960 });
    await visualData(page, baseURL);
    await shell(page, theme);
    await navigate(page, view);
    // This reads committed, independently reviewed goldens. Missing baseline is a failure.
    await expect(page).toHaveScreenshot(`${name}.png`, screenshotOptions(page, true));
  });
}
