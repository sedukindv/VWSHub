# Local HEVC assets

This adapts the existing `hevc-cam01-fmp4` implementation at commit
`d524f4c907702ce56e1c04af3a7d100e154dcfac`. LiveManager, authenticated Live
routes, leases, hls.js and `attachHevcSupport` remain the playback mechanism.
The camera-ID exception from that branch is replaced by factual profile metadata.

Pinned packages: `@hevcjs/hlsjs-plugin` 0.1.12, `@hevcjs/core` 1.7.0,
mp4box 2.4.1, esbuild 0.28.2. The existing application hls.js is 1.7.3.
`package-lock.json` records official npm tarball integrity values. Node >=20 and
npm are build tools; employees need neither tool nor an installed HEVC codec.

From the repository root on Linux/macOS:

```sh
bash scripts/build-hevc-assets.sh
```

On Windows with ordinary Node process permissions:

```powershell
npm ci --prefix scripts/hevc --ignore-scripts --no-audit --no-fund
node scripts/build-hevc-assets.cjs
```

The authoring sandbox blocks child processes launched by the Node esbuild API.
For that environment the same pinned compiler can be called directly, using the
explicit staging mode. This performs the same transformations and build options:

```powershell
node scripts/build-hevc-assets.cjs --stage
$taskCore = (Resolve-Path scripts/hevc/node_modules/@hevcjs/core/dist/wvw-patched-index.js).Path.Replace('\','/')
& scripts/hevc/node_modules/@esbuild/win32-x64/esbuild.exe scripts/hevc/entry.js --bundle --platform=browser --format=iife --target=es2020 --minify --legal-comments=linked "--alias:@hevcjs/core=$taskCore" --outfile=static/vendor/hevc-plugin.js
if ($LASTEXITCODE -ne 0) { throw 'HEVC compilation failed' }
node scripts/build-hevc-assets.cjs --finish
```

Ship the generated bundle, worker, glue, WASM, licenses, manifest, and the readable
`static/vendor/hevc-adapter.js`. The adapter loads the plugin only when a selected
HEVC stream needs it. All runtime URLs are same-origin under `/static/vendor/`;
no CDN is used. `manifest.json` records generated-file SHA256 values and the exact
upstream module hash. A normal deployment uses these committed assets and does
not require a build or Internet access on client computers.

## Reviewed integration patches

`build-hevc-assets.cjs` refuses a core module with a different SHA256 and checks
each original anchor/count before transforming it. The original npm module is
never overwritten: esbuild aliases a generated sibling module, then removes it.
Review these transformations before updating any package version.

- The upstream global MSE interception receives `shouldTranscode(mime)` so an
  exact codec positively verified as native is not forced through WASM while a
  different stream uses fallback. `hvc1` and `hev1` proofs remain separate.
- Each intercepted SourceBuffer exposes an idempotent `__wvwDestroy()` hook to
  destroy its worker pool/transcoder, cancel queued work and stop initialization
  polling. New appends after destruction fail immediately.
- The upstream Worker client rejects pending readiness/init/segment/streaming
  operations, removes per-stream handlers, clears message/error callbacks,
  terminates once, and ignores work/events arriving after close. The original
  implementation cleared pending maps without settling their promises.
- `attachHlsComputeAware(hls)` is attached independently per player. The upstream
  shared handle's `attachComputeAware()` retains only its most recent listener;
  using independent cleanup functions preserves simultaneous-player ownership.

The adapter reserves at most two software fallback plans per browser document,
with a single worker per SourceBuffer. Native streams do not consume this budget.
Different tabs own their own client resources and distinct authenticated server
leases. Existing server stream limits still apply. No global CPU or hardware
acceleration guarantee is implied.

## Verification and browser requirements

```sh
node --test --test-isolation=none tests/hevc_adapter.test.cjs tests/live_hevc_lifecycle.test.cjs
python -m pytest tests/test_media.py tests/test_mux_integration.py -q
```

The upstream lifecycle tests use the real pinned source with synthetic browser
APIs. Install the dependencies above so these tests run rather than skip.
Real-media tests require FFmpeg with libx264/libx265 and FFprobe. They generate
local video and replace RTSP acquisition with that file; no camera is contacted.

FFprobe is required for automatic HEVC/profile detection and positive Live audio
confirmation. An older ffmpeg-only installation can still try its ordinary TS
video player without claiming a codec: the API explicitly returns `codec:unknown`,
`reason_code:ffprobe_unavailable`, `legacy_ts_allowed:true`. This exception never
loads HEVC software support and makes one player attempt with no automatic
reconnect. Unknown codec after a failed/timed-out probe does not get this exception.

Fallback requires **both HTTPS and `window.isSecureContext`**, classic MediaSource,
WebAssembly, Worker, VideoEncoder with a working H.264 encoder, VideoFrame and
EncodedVideoChunk. HTTP localhost does not enable fallback. Native HEVC is checked
first against the actual profile's RFC 6381 codec, original MediaCapabilities API
and an actual SourceBuffer; `canPlayType()` alone is insufficient. Native playback
can remain available without enabling the fallback setting.

The plugin's published tested range is hls.js 1.7.x. Actual Chrome/Edge playback
and browser resource counters must be checked on trusted HTTPS before claiming a
browser compatibility pass. Firefox depends on its available WebCodecs H.264
encoder; unsupported configurations fail with a clear status. Safari/iOS may use
native HEVC; ManagedMediaSource-only browsers cannot use this classic-MSE fallback.
COOP/COEP are unnecessary for this single-thread WASM decoder. CSP permits
`wasm-unsafe-eval`, same-origin resources, and same-origin/blob workers; authentication,
CSRF and Origin controls remain in force.

Official references: [plugin documentation](https://www.hevcjs.dev/docs/hlsjs-plugin.html),
[versioned package README](https://www.npmjs.com/package/@hevcjs/hlsjs-plugin/v/0.1.12),
[upstream source](https://github.com/lid-labs/hevc.js).
