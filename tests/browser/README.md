# WVW synthetic browser regression suite

This directory is test-only. `fixture_server.py` starts the real Flask application
against a fresh temporary store and replaces hardware operations with synthetic
implementations. It contains 82 sources, 7 physical devices, 27 spaces and a real
FFmpeg-generated MP4/HLS recording. No physical camera is contacted. Browser
requests outside the fixture origin are blocked and fail the test.

The suite has **201 functional tests**: 162 page/width/theme combinations,
18 dialog workflows, 3 authentication/playback flows, 2 branding persistence flows, and 16 archive state tests.
There are also **162 separately tagged visual comparisons**.

## Install and run on Linux CI

Requirements: Node >=20, Python with the repository's `requirements-dev.txt`, and
FFmpeg built with libx264. Run from the repository root:

```sh
python -m pip install -r requirements-dev.txt
cd tests/browser
npm ci --ignore-scripts --registry=https://registry.npmjs.org/
npx playwright install --with-deps chromium
npm test
```

`@playwright/test` is pinned to **1.64.1**, the official npm registry release
verified when this suite was authored. Playwright pins its matching browser
revision and its own runtime packages. A checked-in npm lockfile records the exact 1.64.1 dependency graph and registry integrity hashes. It was generated with `npm install --package-lock-only --ignore-scripts` against the official registry; no local browser was installed or launched. Use `npm ci` for repeatable installs.

The server listens only at `http://127.0.0.1:5191`. An existing listener causes a
failure: the suite never attaches to a production server. Override
`WVW_BROWSER_PORT` to choose another unoccupied port, `WVW_PYTHON` to select the
Python executable, and `FFMPEG_BINARY` if FFmpeg is not on PATH. Do not set
`WVW_BROWSER_SETUP=1`: this suite uses seeded test accounts.

The Playwright configuration creates a fresh OS temporary directory per run.
State is intentionally retained there for failure investigation; CI should use
an ephemeral runner. One worker avoids interference from server-wide fixture
modes, user themes and the audit journal. Every test uses a fresh browser context.

## What the tests check

- Pages: Live, Archive, Devices inventory, Spaces, Users, Hardware management,
  Logs, Customization and Settings.
- Widths: 320, 360, 390, 430, 768, 1024, 1280, 1440 and 1920 px; height 960 px;
  light and dark themes, device scale 1, Russian locale and Asia/Omsk timezone.
- Document horizontal overflow, broken images, visible buttons without a
  meaningful accessible label, and modal horizontal bounds. These are focused
  smoke checks, not a full accessibility or clipping audit.
- The narrow sidebar is opened through the real mobile-menu control before
  clicking navigation; navigation must close `menu-open`. Theme and profile
  controls are in the topbar and are used with that overlay closed. Theme save
  requests must succeed before proceeding.
- Normal Live pages wait for four positively negotiated synthetic H.264 streams
  to decode and enter playing state. Normal Archive pages wait for 12 intervals
  and the ready state. Intentional archive error/loading tests opt out of this
  normal-state wait and assert their specific state instead.
- User permissions expand/collapse/search across 27 spaces, local grant edits,
  inventory creation/editing, spaces and icon picker, logo/favicon icon pickers,
  profile editing; dialogs are cancelled and key state is checked unchanged.
- The actual login HTML form rejects a wrong password and authenticates valid
  admin/viewer credentials. The viewer receives server-side 403 from Users,
  Settings and Backup; admin navigation and archive download remain unavailable.
- Archive loads 12 intervals from the real route, decodes the fixture MP4 to
  320px video, advances playback, pauses, zooms/resets and releases video on
  navigation. Empty, lookup-error, playback-error and delayed-loading states use
  `/__qa/archive` fixture controls; normal mode is restored after every test.
  The delayed-playback case gates the genuine fixture HTTP response until the
  loading screenshot is captured, then releases it and verifies playback.

The seeded fixture automatically logs in an administrator for ordinary anonymous
requests. Consequently this suite **does not establish anonymous session security**
or first-setup behavior. Its real login-form and logged-in viewer authorization
checks remain meaningful. Live audio is deliberately unavailable in this fixture;
positive microphone lifecycle tests require the separate audio fixture. Hardware
calls are fake; these results cannot establish physical device compatibility.

## Screenshots and explicit baseline approval

Every functional matrix case attaches a PNG and JSON layout diagnostics to the
HTML report. These artifacts are evidence for human review; capturing them alone
is **not** a visual-regression pass.

No golden images are supplied from the restricted authoring machine. First create
candidate baselines on the chosen Linux/Chromium CI image, review every image,
then commit the approved `snapshots/` directory:

```sh
npm run visual:update
# Review snapshots/ and the Playwright HTML report before committing images.
npm run test:visual
```

`npm run test:visual` compares against committed images with updates disabled.
Missing baselines fail. `npm run visual:update` is the explicit update operation;
do not use it as the CI verification command. Updating pixels never repairs or
approves a functional assertion. `npm run test:all` runs both functional checks
and approved visual comparisons. Use the same OS image, fonts, browser revision
and dependency versions for baseline creation and verification.

The screenshot clock is fixed to 2026-11-03 12:00 Asia/Omsk; timers still run.
Visual comparisons mask only video/canvas and the wall clock/stream counter.
For deterministic audit and machine-metric pixels, visual cases first fetch the
real `/api/logs` or `/api/settings` endpoint and require a successful response
and expected JSON shape. They then replace only audit rows and metric values
with declared fixed fixture data before rendering. Rows, counters, metric text
and all surrounding layout are therefore pixel-compared; this does not establish
the correctness of actual audit delivery or machine measurements. Functional
cases use the real returned data and attach evidence, with volatile timestamps
and metric values masked in their evidence images only. Error toasts are never
masked and are rejected on normal fixture pages. Do not expand masks to hide
regressions. The fixed application shell scrolls its content internally, so a
full-page screenshot shows the current scroll position rather than stitching
every row of a long inventory table.

Artifacts: `test-results/` includes failed-case traces/screenshots and attached
matrix screenshots/diagnostics; `playwright-report/` is the HTML report.
Run `npm run report` to inspect it. CI should upload both directories even on
failure. All generated artifacts and node_modules are ignored by git.

## Verification status of this contribution

The JavaScript files were checked with `node --check`. The installed pinned
Playwright runner successfully discovered all 363 tests using `test --list`
(201 functional and 162 visual), which starts neither a browser nor the fixture
server. No CLI browser was launched
in the restricted Windows environment (known browser spawn EPERM / absent browser
binary). These newly authored tests and goldens must be executed/reviewed on Linux
before claiming a browser-suite pass. Existing native CUA checks are separate
evidence and are not execution of this suite.

References: [Playwright visual comparisons](https://playwright.dev/docs/test-snapshots),
[web server configuration](https://playwright.dev/docs/test-webserver),
[official package metadata](https://registry.npmjs.org/@playwright/test/latest).


## GitHub Actions

`.github/workflows/tests.yml` runs the Python suite, every `*.test.cjs` Node unit test, recursive JavaScript syntax, HTTPS shell syntax and checked-in HEVC SHA-256 validation. Its separate Ubuntu 24.04 browser job uses the committed lockfile, installs matching Chromium plus system dependencies and runs the functional suite only. Failure traces/screenshots and the HTML report are uploaded for review. These workflow definitions are not a claim that the jobs have already executed successfully.

`.github/workflows/visual-review.yml` is manual (`workflow_dispatch`) with two explicit modes:

- `compare` (default): compare against committed, reviewed goldens; missing images fail.
- `candidates`: first run the functional assertions, then create candidate images and upload them with the report. This produces review material only.

Neither mode has repository write permission or commits/accepts snapshots. Download candidate artifacts, review the full images and diagnostics, then commit approved `snapshots/` files through a separate reviewed change. Run `compare` against that commit to inspect differences. Automatic push/PR CI never updates baselines.


## Separate real Chrome/Edge HEVC over HTTPS

`hevc-https.config.cjs` defines two additional tests, one in official Chrome and one in official Edge. They are excluded from the ordinary HTTP matrix. `.github/workflows/hevc-browser.yml` runs them in a disposable Ubuntu runner with certificate validation enabled (`ignoreHTTPSErrors:false`).

The workflow creates a short-lived loopback certificate using `create_test_tls.py` and trusts its public CA only in that disposable runner's OS/NSS stores. No user computer's trust store is changed and TLS private keys are never uploaded. The server and Node health check use the same explicit test identity. Do not run these trust-store commands on a working user's machine.

The fixture generates and FFprobe-verifies an actual HEVC source, remuxes it to fMP4 HLS with `copy`, and supplies factual HEVC metadata with the optional RFC6381 detail absent. That supported metadata case selects software decoding without replacing browser APIs or disabling security. The test requires Worker/WASM requests, actual decoded/advancing video frames, and successful playback after navigation teardown. Native HEVC support for a specific camera/OS is a separate check. Passing test discovery alone is not a positive HEVC browser result.


Before the new manual workflow reaches the default branch, the existing **Tests** workflow can also be dispatched explicitly on a `release-*` branch. After its functional checks pass, its `browser-visual-review` job generates unapproved candidates if `snapshots/` is absent; when committed images exist it compares with updates disabled. The job has read-only repository permissions and never commits images. Review every candidate and commit the approved images separately before calling the result a visual-regression pass. Ordinary push/PR runs never generate or update goldens.
