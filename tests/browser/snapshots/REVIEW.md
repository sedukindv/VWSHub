# Reviewed screenshot baseline — WVW 0.9.0

Reviewed on 5 November 2026 by the primary Codex agent as part of the user's requested whole-site design audit. This records agent visual review; the user has not independently approved each image.

162 images cover nine views, two themes and nine widths (320–1920 px) at a 960 px viewport height. All 18 contact sheets were inspected. The table layouts for spaces, users and logs intentionally scroll horizontally inside their container. The shell scrolls content internally; these initial-position images do not cover every row or lower section. Scrolled sections, dialogs, authentication, focus and player states have separate evidence described in `../../../TEST_REPORT.md`.

158 images come from [Tests #51](https://github.com/sedukindv/WVW/actions/runs/41853160505), commit `5945337`, generated on Ubuntu 24.04 with the committed Playwright 1.64.1 lockfile and matching Chromium. The archive's 320/360 px light/dark images were replaced with four individually inspected originals from [Tests #52](https://github.com/sedukindv/WVW/actions/runs/41933526895), commit `21b1d4f`, after correcting the clipped download label. The 158 unchanged layouts were also regenerated there; twelve images differed by only 2–35 edge pixels, below the existing 0.001 ratio, so their already reviewed originals were retained.

This commit supplies baselines; generating or committing them is not a comparison pass. A separate CI run must execute `npm run test:visual` with snapshot updates disabled. Missing images must fail. Any future update requires inspection and an explicit commit; automatic verification cannot accept pixels.

Only changing media pixels, the wall clock and its stream counter are masked. Audit rows and machine metrics use declared fixed synthetic values after successful real endpoint/contract checks. Error toasts remain visible. See `../README.md` for the fixture and comparison boundaries. SHA-256 values of the shipped images are recorded in `BUILD_INFO.json`.
