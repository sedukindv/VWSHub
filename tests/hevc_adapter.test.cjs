/* Isolated adapter contract tests. No browser, worker, network or camera starts. */
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

class Events {
  constructor() { this.listeners = new Map(); }
  addEventListener(type, callback, options) {
    const list = this.listeners.get(type) || [];
    list.push({callback, once: !!options?.once}); this.listeners.set(type, list);
  }
  removeEventListener(type, callback) {
    this.listeners.set(type, (this.listeners.get(type) || []).filter(x => x.callback !== callback));
  }
  dispatchEvent(event) {
    for (const item of [...(this.listeners.get(event.type) || [])]) {
      if (item.once) this.removeEventListener(event.type, item.callback);
      item.callback.call(this, event);
    }
    this['on' + event.type]?.(event);
    return true;
  }
  listenerCount() { return [...this.listeners.values()].reduce((n, list) => n + list.length, 0); }
}

function browser(options = {}) {
  const log = {scripts: [], mediaSources: [], videos: [], created: [], revoked: [], status: [], installs: [], uninstalls: 0, computeAttached: [], computeDetached: [], workerStarts: 0, fetches: 0};
  const timers = new Map(); let timerId = 0, now = 0;
  const clock = {
    set(callback, delay = 0) { const id = ++timerId; timers.set(id, {callback, at: now + Number(delay)}); return id; },
    clear(id) { timers.delete(id); },
    advance(ms) {
      const target = now + ms; let steps = 0;
      while (true) {
        const entry = [...timers.entries()].filter(([, timer]) => timer.at <= target).sort((a, b) => a[1].at - b[1].at)[0];
        if (!entry) break;
        if (++steps > 1000) throw new Error('Unbounded adapter timer loop');
        now = entry[1].at; timers.delete(entry[0]); entry[1].callback();
      }
      now = target;
    },
    get pending() { return timers.size; },
  };
  class FakeMediaSource extends Events {
    constructor() { super(); this.readyState = 'closed'; this.sourceBuffers = []; log.mediaSources.push(this); }
    static isTypeSupported() { return options.mseSupported !== false; }
    addSourceBuffer(type) {
      if (options.sourceBufferFails) throw new Error('Unsupported exact codec');
      const buffer = new Events(); buffer.type = type; buffer.__wvwDestroy = () => { buffer.destroyed = (buffer.destroyed || 0) + 1; };
      this.sourceBuffers.push(buffer); return buffer;
    }
    removeSourceBuffer(buffer) { this.sourceBuffers.splice(this.sourceBuffers.indexOf(buffer), 1); }
    endOfStream() { this.readyState = 'ended'; }
  }
  const node = tag => {
    const element = new Events(); element.tagName = tag.toUpperCase(); element.style = {}; element.attributes = {};
    element.setAttribute = (key, value) => { element.attributes[key] = value; };
    element.removeAttribute = key => { delete element.attributes[key]; if (key === 'src') element.src = ''; };
    element.remove = () => { element.parentNode = null; element.removed = true; };
    element.pause = () => { element.paused = true; };
    element.load = () => {};
    element.canPlayType = () => options.canPlayType || '';
    element.appendChild = child => { child.parentNode = element; return child; };
    element.removeChild = child => { child.parentNode = null; return child; };
    if (tag === 'video') log.videos.push(element);
    return element;
  };
  let context;
  const originalAdd = FakeMediaSource.prototype.addSourceBuffer;
  const plugin = {
    version: '0.1.12', coreVersion: '1.7.0',
    attachHevcSupport(...args) {
      log.installs.push(args);
      FakeMediaSource.prototype.addSourceBuffer = function(type) { return originalAdd.call(this, type); };
      const cleanup = () => { log.uninstalls++; FakeMediaSource.prototype.addSourceBuffer = originalAdd; };
      cleanup.uninstall = cleanup;
      return cleanup;
    },
    attachHlsComputeAware(hls) {
      log.computeAttached.push(hls);
      return () => { log.computeDetached.push(hls); };
    },
  };
  const document = {
    baseURI: 'https://vms.example.test/', currentScript: {src: 'https://vms.example.test/static/vendor/hevc-adapter.js'},
    createElement: node,
  };
  document.body = node('body'); document.documentElement = node('html'); document.head = node('head');
  document.head.appendChild = script => {
    script.parentNode = document.head; log.scripts.push(script);
    if (options.script !== 'hang') queueMicrotask(() => {
      if (options.script === 'fail') script.dispatchEvent({type: 'error'});
      else { context.WVWHevcPlugin = options.plugin || plugin; script.dispatchEvent({type: 'load'}); }
    });
    return script;
  };
  class BrowserURL extends URL {
    static createObjectURL(source) {
      const id = 'blob:synthetic-' + log.created.length; log.created.push({id, source});
      if (!options.sourceOpenHangs) queueMicrotask(() => { source.readyState = 'open'; source.dispatchEvent({type: 'sourceopen'}); });
      return id;
    }
    static revokeObjectURL(id) { log.revoked.push(id); }
  }
  class FakeHls extends Events {
    static version = '1.7.0';
    static isSupported() { return true; }
    static Events = {MEDIA_ATTACHED: 'hlsMediaAttached', MEDIA_DETACHING: 'hlsMediaDetaching', DESTROYING: 'hlsDestroying', BUFFER_CREATED: 'hlsBufferCreated'};
    constructor() { super(); this.media = node('video'); }
    on(type, callback) { this.addEventListener(type, callback); }
    off(type, callback) { this.removeEventListener(type, callback); }
    emit(type, data) { for (const item of [...(this.listeners.get(type) || [])]) item.callback(type, data); }
  }
  const events = new Events();
  context = {
    console, document, location: new URL(options.protocol === 'http:' ? 'http://vms.example.test/' : 'https://vms.example.test/'),
    isSecureContext: options.secure !== false, WebAssembly,
    Worker: class { constructor() { log.workerStarts++; } }, MediaSource: FakeMediaSource,
    VideoFrame: class {}, EncodedVideoChunk: class {}, VideoEncoder: class { static async isConfigSupported() { return {supported: true}; } },
    Hls: FakeHls, URL: BrowserURL,
    navigator: {hardwareConcurrency: 8, deviceMemory: 8, mediaCapabilities: {async decodingInfo(config) { log.nativeConfig = config; return {supported: options.native === true, smooth: true, powerEfficient: true}; }}},
    CustomEvent: class { constructor(type, init = {}) { this.type = type; this.detail = init.detail; } },
    setTimeout: clock.set, clearTimeout: clock.clear, performance: {now: () => now},
    Date: class extends Date { static now() { return now + 1000000; } },
    fetch: async () => { log.fetches++; throw new Error('Unexpected adapter network request'); },
    addEventListener: events.addEventListener.bind(events), removeEventListener: events.removeEventListener.bind(events),
    dispatchEvent(event) { if (event.type === 'vwshub:hevc-status') log.status.push(event.detail); return events.dispatchEvent(event); },
  };
  Object.assign(context, options.globals || {}); context.window = context; context.self = context;
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/vendor/hevc-adapter.js'), 'utf8'), context, {filename: 'hevc-adapter.js'});
  async function settle() { for (let i = 0; i < 20; i++) await Promise.resolve(); }
  async function complete(promise, limit = 30000) {
    let state = 'pending', result;
    Promise.resolve(promise).then(value => { state = 'resolved'; result = value; }, error => { state = 'rejected'; result = error; });
    for (let elapsed = 0; elapsed <= limit && state === 'pending'; elapsed += 100) { await settle(); if (state === 'pending') clock.advance(100); }
    await settle(); assert.notEqual(state, 'pending', 'Adapter operation must settle within its bounded timeout');
    if (state === 'rejected') throw result;
    return result;
  }
  return {context, adapter: context.WVWHevc, log, clock, settle, complete, FakeHls, FakeMediaSource, events};
}

const hevc = {codec: 'hevc', codec_string: 'hvc1.1.6.L93.B0', width: 1920, height: 1080, framerate: 25, bitrate: 2000000};

test('loading the adapter and reading status never downloads or starts decoding', () => {
  const b = browser();
  assert.ok(b.adapter);
  assert.equal(b.adapter.status(false).state, 'off');
  b.adapter.status(true);
  assert.equal(b.log.scripts.length, 0); assert.equal(b.log.workerStarts, 0); assert.equal(b.log.fetches, 0);
});

test('H.264 stays on the original TS path even without secure context and browser decoder APIs', async () => {
  const b = browser({secure: false, protocol: 'http:', globals: {WebAssembly: undefined, Worker: undefined, MediaSource: undefined, VideoEncoder: undefined}});
  const plan = await b.complete(b.adapter.prepare({codec: 'h264'}, true));
  assert.equal(plan.mode, 'h264'); assert.equal(plan.container, 'ts');
  plan.release(); assert.equal(b.log.scripts.length, 0); assert.equal(b.log.workerStarts, 0);
});

test('HTTP loopback is rejected for plugin use even when isSecureContext is true', async () => {
  const b = browser({protocol: 'http:', secure: true});
  assert.equal(b.adapter.status(true).state, 'httpsrequired');
  await assert.rejects(b.complete(b.adapter.prepare(hevc, true)));
  assert.equal(b.log.scripts.length, 0);
});

for (const missing of ['WebAssembly', 'Worker', 'MediaSource', 'VideoEncoder', 'VideoFrame', 'EncodedVideoChunk']) {
  test(`plugin refuses missing ${missing} before any download`, async () => {
    const b = browser({globals: {[missing]: undefined}});
    assert.equal(b.adapter.status(true).state, 'apiunsupported');
    await assert.rejects(b.complete(b.adapter.prepare(hevc, true)));
    assert.equal(b.log.scripts.length, 0);
  });
}

test('canPlayType alone never authorizes native HEVC playback', async () => {
  const b = browser({canPlayType: 'probably', native: false});
  const plan = await b.complete(b.adapter.prepare(hevc, true));
  assert.equal(plan.mode, 'plugin'); assert.equal(plan.container, 'fmp4');
  plan.release();
});

test('verified exact-codec native support has priority and never loads the plugin', async () => {
  const b = browser({native: true});
  const plan = await b.complete(b.adapter.prepare(hevc, true));
  assert.equal(plan.mode, 'native'); assert.equal(plan.container, 'fmp4');
  assert.match(b.log.nativeConfig.video.contentType, /hvc1\.1\.6\.L93\.B0/);
  assert.equal(b.log.scripts.length, 0); assert.equal(b.log.workerStarts, 0);
  assert.deepEqual(b.log.revoked, b.log.created.map(entry => entry.id));
  assert.ok(b.log.mediaSources.every(source => source.listenerCount() === 0));
  plan.release();
});

test('a real SourceBuffer rejection defeats a positive native capability report', async () => {
  const b = browser({native: true, sourceBufferFails: true});
  const plan = await b.complete(b.adapter.prepare(hevc, true));
  assert.equal(plan.mode, 'plugin'); plan.release();
  assert.deepEqual(b.log.revoked, b.log.created.map(entry => entry.id));
});

test('plugin script errors and missing load events settle with bounded failure', async () => {
  for (const script of ['fail', 'hang']) {
    const b = browser({script});
    await assert.rejects(b.complete(b.adapter.prepare(hevc, true)));
    assert.equal(b.log.scripts.length, 1); assert.equal(b.log.installs.length, 0);
    b.clock.advance(120000); await b.settle();
    assert.equal(b.log.scripts.length, 1, 'A failed script must not start an automatic retry loop');
  }
});

test('unknown codec and disabled fallback cannot download or start a decoder', async () => {
  const b = browser();
  await assert.rejects(b.complete(b.adapter.prepare({codec: 'unknown', reason: 'metadata not available'}, true)));
  await assert.rejects(b.complete(b.adapter.prepare(hevc, false)));
  assert.equal(b.log.scripts.length, 0); assert.equal(b.log.installs.length, 0);
});

test('explicit missing-FFprobe compatibility permits legacy TS on HTTP without decoder APIs or a guessed codec', async () => {
  const b = browser({secure: false, protocol: 'http:', globals: {WebAssembly: undefined, Worker: undefined, MediaSource: undefined, VideoEncoder: undefined}});
  const plan = await b.complete(b.adapter.prepare({codec: 'unknown', reason_code: 'ffprobe_unavailable', legacy_ts_allowed: true}, true));
  assert.equal(plan.mode, 'legacy'); assert.equal(plan.container, 'ts');
  const cleanup = plan.attach(new b.FakeHls()); cleanup(); plan.release(); plan.release();
  assert.equal(b.log.scripts.length, 0); assert.equal(b.log.installs.length, 0);
  assert.equal(b.log.workerStarts, 0); assert.equal(b.log.fetches, 0);
  assert.equal(b.log.mediaSources.length, 0); assert.equal(b.clock.pending, 0);
});

test('unknown profiles without both exact missing-FFprobe flags still fail closed', async () => {
  const b = browser({secure: false, protocol: 'http:'});
  const attempts = [
    {codec: 'unknown'},
    {codec: 'unknown', reason_code: 'ffprobe_unavailable'},
    {codec: 'unknown', legacy_ts_allowed: true},
    {codec: 'unknown', reason_code: 'ffprobe_timeout', legacy_ts_allowed: true},
    {codec: 'unknown', reason_code: 'ffprobe_error', legacy_ts_allowed: true},
    {codec: 'unknown', reason_code: 'ffprobe_unavailable', legacy_ts_allowed: 'true'},
    {codec: 'hevc', reason_code: 'ffprobe_unavailable', legacy_ts_allowed: true},
  ];
  for (const meta of attempts) await assert.rejects(b.complete(b.adapter.prepare(meta, true)));
  assert.equal(b.log.scripts.length, 0); assert.equal(b.log.installs.length, 0);
});

test('verified native HEVC remains available while fallback is disabled or the page is HTTP', async () => {
  const b = browser({native: true, protocol: 'http:', secure: false});
  const plan = await b.complete(b.adapter.prepare(hevc, false));
  assert.equal(plan.mode, 'native'); plan.release();
  assert.equal(b.log.scripts.length, 0);
});

test('unverified exact codec cannot be approved by a generic positive browser report', async () => {
  const b = browser({native: true});
  const plan = await b.complete(b.adapter.prepare({...hevc, codec_string: ''}, true));
  assert.equal(plan.mode, 'plugin'); assert.equal(b.log.mediaSources.length, 0); plan.release();
});

test('incompatible Hls and missing encoder query are rejected before loading the plugin', async () => {
  for (const version of ['1.6.13', '2.0.0', '']) {
    const b = browser(); b.context.Hls.version = version;
    assert.equal(b.adapter.status(true).state, 'apiunsupported');
    await assert.rejects(b.complete(b.adapter.prepare(hevc, true)));
    assert.equal(b.log.scripts.length, 0);
  }
  const b = browser({globals: {VideoEncoder: class {}}});
  await assert.rejects(b.complete(b.adapter.prepare(hevc, true)));
  assert.equal(b.log.scripts.length, 0);
});

test('unsupported and nonresponding H264 encoders fail without loading decoder resources', async () => {
  for (const encoder of [class { static async isConfigSupported() { return {supported: false}; } }, class { static isConfigSupported() { return new Promise(() => {}); } }]) {
    const b = browser({globals: {VideoEncoder: encoder}});
    await assert.rejects(b.complete(b.adapter.prepare(hevc, true)));
    assert.equal(b.log.scripts.length, 0); assert.equal(b.clock.pending, 0);
  }
});

test('two concurrent streams share one installation, enforce capacity, and tear down independently', async () => {
  const b = browser();
  const plans = await b.complete(Promise.all([b.adapter.prepare(hevc, true), b.adapter.prepare({...hevc, width: 1280, height: 720}, true)]));
  assert.equal(b.log.scripts.length, 1); assert.equal(b.log.installs.length, 1);
  await assert.rejects(b.complete(b.adapter.prepare(hevc, true)), reason => reason.code === 'capacity');
  const first = new b.FakeHls(), second = new b.FakeHls();
  const cleanup1 = plans[0].attach(first); plans[1].attach(second);
  const buffer1 = {destroyed: 0, __wvwDestroy() { this.destroyed++; }};
  const buffer2 = {destroyed: 0, __wvwDestroy() { this.destroyed++; }};
  first.emit(b.FakeHls.Events.BUFFER_CREATED, {tracks: {video: {buffer: buffer1}}});
  first.emit(b.FakeHls.Events.BUFFER_CREATED, {tracks: {video: {buffer: buffer1}}});
  second.emit(b.FakeHls.Events.BUFFER_CREATED, {tracks: {video: {buffer: buffer2}}});
  cleanup1(); cleanup1(); plans[0].release();
  assert.equal(buffer1.destroyed, 1); assert.equal(buffer2.destroyed, 0);
  assert.equal(first.listenerCount(), 0); assert.ok(second.listenerCount() > 0);
  assert.equal(b.log.computeDetached.length, 1); assert.equal(b.log.uninstalls, 0);
  second.emit(b.FakeHls.Events.DESTROYING); plans[1].release();
  assert.equal(buffer2.destroyed, 1); assert.equal(second.listenerCount(), 0);
  assert.equal(b.log.computeDetached.length, 2); assert.equal(b.log.uninstalls, 1);
  assert.equal(b.clock.pending, 0);
  const replacement = await b.complete(b.adapter.prepare(hevc, true)); replacement.release();
  assert.equal(b.log.scripts.length, 1); assert.equal(b.log.installs.length, 2); assert.equal(b.log.uninstalls, 2);
});

test('a lease cannot attach twice or after release; release before attach frees its capacity', async () => {
  const b = browser();
  const plan = await b.complete(b.adapter.prepare(hevc, true));
  const hls = new b.FakeHls(); plan.attach(hls);
  assert.throws(() => plan.attach(hls));
  plan.release(); assert.throws(() => plan.attach(hls));
  const next = await b.complete(b.adapter.prepare(hevc, true)); next.release(); next.release();
  assert.equal(b.log.uninstalls, 2); assert.equal(hls.listenerCount(), 0);
});

test('disabling fallback refuses new plugin plans without interrupting an existing plan', async () => {
  const b = browser(); const plan = await b.complete(b.adapter.prepare(hevc, true));
  assert.equal(b.adapter.status(false).state, 'off');
  await assert.rejects(b.complete(b.adapter.prepare(hevc, false)), reason => reason.code === 'off');
  assert.equal(b.log.uninstalls, 0);
  const hls = new b.FakeHls(); plan.attach(hls); plan.release();
  assert.equal(b.log.uninstalls, 1); assert.equal(hls.listenerCount(), 0);
});

test('separate tabs own separate decoder leases and never release each other', async () => {
  const a = browser(), b = browser();
  const one = await a.complete(a.adapter.prepare(hevc, true));
  const two = await b.complete(b.adapter.prepare(hevc, true));
  one.release(); assert.equal(a.log.uninstalls, 1); assert.equal(b.log.uninstalls, 0);
  assert.equal(b.adapter.status(true).state, 'ready'); two.release();
  assert.equal(b.log.uninstalls, 1);
});

test('all plugin assets are requested from the application origin', async () => {
  const b = browser(); const plan = await b.complete(b.adapter.prepare(hevc, true));
  const src = new URL(b.log.scripts[0].src, b.context.location);
  assert.equal(src.origin, b.context.location.origin);
  const config = b.log.installs[0][0];
  for (const key of ['workerUrl', 'wasmUrl', 'wasmBinaryUrl']) {
    assert.equal(new URL(config[key], b.context.location).origin, b.context.location.origin);
    assert.match(new URL(config[key], b.context.location).pathname, /^\/static\/vendor\//);
  }
  plan.release();
});

test('wrong plugin version fails closed before installing the MSE interceptor', async () => {
  let installs = 0;
  const b = browser({plugin: {version: '0.1.11', coreVersion: '1.7.0', attachHevcSupport() { installs++; }}});
  await assert.rejects(b.complete(b.adapter.prepare(hevc, true)));
  assert.equal(installs, 0); assert.equal(b.adapter.status(true).state, 'initerror');
});

test('script failures are cached briefly and permit no more than two explicit loads', async () => {
  const b = browser({script: 'fail'});
  await assert.rejects(b.complete(b.adapter.prepare(hevc, true)));
  await assert.rejects(b.complete(b.adapter.prepare(hevc, true)));
  assert.equal(b.log.scripts.length, 1);
  b.clock.advance(16000);
  await assert.rejects(b.complete(b.adapter.prepare(hevc, true)));
  assert.equal(b.log.scripts.length, 2);
  b.clock.advance(16000);
  await assert.rejects(b.complete(b.adapter.prepare(hevc, true)));
  assert.equal(b.log.scripts.length, 2); assert.equal(b.clock.pending, 0);
});

test('timed-out initialization cleans up a handle that resolves later', async () => {
  let resolve, removed = 0;
  const pending = new Promise(done => { resolve = done; });
  const plugin = {version: '0.1.12', coreVersion: '1.7.0', attachHevcSupport() { return pending; }};
  const b = browser({plugin});
  await assert.rejects(b.complete(b.adapter.prepare(hevc, true)));
  const handle = () => { removed++; }; handle.uninstall = handle;
  resolve(handle); await b.settle();
  assert.equal(removed, 1); assert.equal(b.clock.pending, 0);
  assert.equal(b.adapter.status(true).state, 'initerror');
});

test('native verification uses original APIs after another stream installs the plugin', async () => {
  const options = {native: false}; const b = browser(options);
  const pluginPlan = await b.complete(b.adapter.prepare(hevc, true));
  options.native = true;
  b.context.navigator.mediaCapabilities.decodingInfo = async () => ({supported: false});
  b.context.MediaSource.isTypeSupported = () => false;
  b.context.MediaSource.prototype.addSourceBuffer = () => { throw new Error('Plugin interceptor is not native evidence'); };
  const nativePlan = await b.complete(b.adapter.prepare({...hevc, codec_string: 'hvc1.2.4.L120.B0'}, true));
  assert.equal(nativePlan.mode, 'native'); assert.equal(b.log.installs.length, 1);
  nativePlan.release(); pluginPlan.release();
});

test('a native probe with no sourceopen event releases URL, timer and event listener', async () => {
  const b = browser({native: true, sourceOpenHangs: true});
  const plan = await b.complete(b.adapter.prepare(hevc, true));
  assert.equal(plan.mode, 'plugin');
  assert.deepEqual(b.log.revoked, b.log.created.map(entry => entry.id));
  assert.ok(b.log.mediaSources.every(source => source.listenerCount() === 0), 'Timed-out probes must explicitly remove sourceopen listeners');
  assert.equal(b.clock.pending, 0); plan.release();
});

test('a late timed-out global installation cannot uninstall a newer active decoder', async () => {
  let firstResolve, b, calls = 0;
  const first = new Promise(resolve => { firstResolve = resolve; });
  let original;
  const install = () => {
    b.context.MediaSource.prototype.addSourceBuffer = function(...args) { return original.apply(this, args); };
    const cleanup = () => { b.context.MediaSource.prototype.addSourceBuffer = original; };
    cleanup.uninstall = cleanup; return cleanup;
  };
  const plugin = {version: '0.1.12', coreVersion: '1.7.0', attachHevcSupport() { return ++calls === 1 ? first : install(); }};
  b = browser({plugin}); original = b.context.MediaSource.prototype.addSourceBuffer;
  await assert.rejects(b.complete(b.adapter.prepare(hevc, true)));
  b.clock.advance(16000);
  let newer;
  try { newer = await b.complete(b.adapter.prepare(hevc, true)); }
  catch (_) { /* Refusing overlap while a prior global initialization is pending is also safe. */ }
  firstResolve(install()); await b.settle();
  if (newer) {
    try {
      assert.notEqual(b.context.MediaSource.prototype.addSourceBuffer, original, 'A stale handle must not remove the active newer global interceptor');
    } finally { newer.release(); }
  } else {
    assert.equal(b.context.MediaSource.prototype.addSourceBuffer, original, 'A cancelled late initializer must be cleaned up');
  }
});

test('native hvc1 support cannot exempt an unverified hev1 sample entry from transcoding', async () => {
  const options = {native: true}; const b = browser(options);
  const native = await b.complete(b.adapter.prepare(hevc, true));
  assert.equal(native.mode, 'native'); options.native = false;
  const fallback = await b.complete(b.adapter.prepare({...hevc, codec_string: 'hev1.1.6.L93.B0'}, true));
  assert.equal(fallback.mode, 'plugin');
  const config = b.log.installs[0][0];
  try {
    assert.equal(config.shouldTranscode('video/mp4; codecs="hev1.1.6.L93.B0"'), true, 'Only the exact verified sample entry may bypass fallback');
    assert.equal(config.shouldTranscode('video/mp4; codecs="hvc1.1.6.L93.B0"'), false);
  } finally { native.release(); fallback.release(); }
});

// Exercise the pinned upstream SourceBuffer wrapper with the exact integration
// replacement from the build script, without importing WASM or starting workers.
function patchedCore() {
  const candidates = [
    path.join(__dirname, '../scripts/hevc/node_modules/@hevcjs/core/dist/index.js'),
    path.join(__dirname, '../../hevc-deps/node_modules/@hevcjs/core/dist/index.js'),
  ];
  const file = candidates.find(candidate => fs.existsSync(candidate));
  if (!file) return null;
  const source = fs.readFileSync(file, 'utf8');
  const build = fs.readFileSync(path.join(__dirname, '../scripts/build-hevc-assets.cjs'), 'utf8');
  const transformBegin = build.indexOf('function replaceOnce('), transformEnd = build.indexOf('fs.mkdirSync(');
  assert.ok(transformBegin >= 0 && transformEnd > transformBegin, 'Only pure pinned source transformations are evaluated');
  return vm.runInNewContext(build.slice(transformBegin, transformEnd) + '\npatched;', {original: source});
}

function upstreamProxy() {
  const patched = patchedCore();
  if (!patched) return null;
  const begin = patched.indexOf('function createTranscodingProxy('), end = patched.indexOf('function isInitSegment', begin);
  assert.ok(begin >= 0 && end > begin);
  const proxy = patched.slice(begin, end);
  assert.match(proxy, /__wvwDestroy/);
  const b = browser(), stats = {destroyed: 0, appends: 0};
  class Buffer extends Events {
    constructor() { super(); this.buffered = {length: 0}; this.offset = 0; }
    get updating() { return false; }
    get timestampOffset() { return this.offset; }
    set timestampOffset(value) { this.offset = value; }
    appendBuffer() { stats.appends++; }
    abort() {}
    remove() {}
  }
  const context = {
    SourceBuffer: Buffer, Map, Set, Uint8Array, DataView,
    log: {debug() {}, info() {}, error() {}},
    SegmentTranscoder: class {
      get isInitialized() { return false; }
      init() { return new Promise(() => {}); }
      destroy() { stats.destroyed++; }
    },
    recommendedPoolSize: () => 1, isInitSegment: () => true,
    toUint8Array: data => data, isSelfContainedSegment: () => true,
    Event: class { constructor(type) { this.type = type; } },
    setTimeout: b.clock.set, clearTimeout: b.clock.clear,
  };
  vm.createContext(context); vm.runInContext(proxy + '\nthis.makeProxy=createTranscodingProxy;', context);
  const buffer = context.makeProxy(new Buffer(), {poolSize: 1}, true);
  return {buffer, stats, clock: b.clock, settle: b.settle};
}

test('the upstream SourceBuffer destructor is idempotent and stops pending initialization polling', async t => {
  const upstream = upstreamProxy();
  if (!upstream) { t.skip('Install pinned scripts/hevc dependencies to test upstream destructor integration'); return; }
  const {buffer, stats, clock, settle} = upstream;
  buffer.appendBuffer(new Uint8Array([0, 0, 0, 8, 102, 116, 121, 112]));
  await settle(); assert.ok(clock.pending > 0, 'The synthetic upstream initializer must actually be pending');
  buffer.__wvwDestroy(); buffer.__wvwDestroy();
  assert.throws(() => buffer.appendBuffer(new Uint8Array([0, 0, 0, 8, 102, 116, 121, 112])));
  for (let i = 0; i < 5; i++) { clock.advance(20); await settle(); }
  assert.equal(stats.destroyed, 1); assert.equal(stats.appends, 0);
  assert.equal(clock.pending, 0, 'Closed SourceBuffers must not retain the main-thread WASM initialization poll');
});

function upstreamWorker() {
  const patched = patchedCore();
  if (!patched) return null;
  const begin = patched.indexOf('var TranscodeWorkerClient = class'), end = patched.indexOf('async function loadWorker', begin);
  assert.ok(begin >= 0 && end > begin);
  const worker = new Events(); worker.messages = []; worker.terminated = 0;
  worker.postMessage = message => worker.messages.push(message.type);
  worker.terminate = () => { worker.terminated++; };
  const context = {log: {error() {}, info() {}, debug() {}}, loadWorker: async () => worker, Uint8Array};
  vm.createContext(context); vm.runInContext(patched.slice(begin, end) + '\nthis.Client=TranscodeWorkerClient;', context);
  const client = new context.Client({workerUrl: '/static/vendor/hevc/transcode-worker.js'});
  const settle = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };
  return {worker, client, settle};
}

test('destroying the upstream worker client before WASM readiness settles waiting work', async t => {
  const fixture = upstreamWorker();
  if (!fixture) { t.skip('Install pinned scripts/hevc dependencies to test upstream worker cancellation'); return; }
  const {worker, client, settle} = fixture;
  let state = 'pending';
  client.waitReady().then(() => { state = 'resolved'; }, () => { state = 'rejected'; });
  await settle();
  assert.equal(state, 'pending'); assert.deepEqual(worker.messages, ['init']);
  client.destroy();
  await settle();
  assert.equal(worker.terminated, 1);
  assert.notEqual(state, 'pending', 'Closing a not-yet-ready worker must settle its ready waiters');
  assert.equal(worker.listenerCount(), 0);
  assert.ok(!worker.onmessage && !worker.onerror, 'Destroyed workers must not retain dispatch handlers');
});

test('closing an active upstream worker rejects pending segments and removes per-stream listeners', async t => {
  const fixture = upstreamWorker();
  if (!fixture) { t.skip('Install pinned scripts/hevc dependencies to test upstream worker cancellation'); return; }
  const {worker, client, settle} = fixture;
  await settle(); worker.dispatchEvent({type: 'message', data: {type: 'ready'}});
  await client.waitReady();
  let chunks = 0;
  const work = [
    client.processInitSegment(new Uint8Array([1, 2, 3])),
    client.prepareInit(new Uint8Array([1, 2, 3])),
    client.processMediaSegment(new Uint8Array([1, 2, 3])),
    client.processMediaSegmentStreaming(new Uint8Array([1, 2, 3]), () => { chunks++; }),
  ];
  const states = work.map(() => 'pending');
  work.forEach((promise, index) => promise.then(() => { states[index] = 'resolved'; }, () => { states[index] = 'rejected'; }));
  await settle(); assert.ok(worker.listenerCount() > 0, 'The streaming callback must actually be registered');
  client.destroy(); await settle();
  assert.ok(states.every(state => state !== 'pending'), 'All pending init and media operations must settle on close');
  assert.equal(worker.listenerCount(), 0); assert.equal(worker.terminated, 1);
  worker.dispatchEvent({type: 'message', data: {type: 'partialTranscoded', id: 2, h264: new Uint8Array([4]).buffer}});
  await settle(); assert.equal(chunks, 0, 'Closed streams must not dispatch late decoded chunks');
});

test('worker operations awaiting the transport cannot enqueue new work after an immediate close', async t => {
  const fixture = upstreamWorker();
  if (!fixture) { t.skip('Install pinned scripts/hevc dependencies to test upstream worker cancellation'); return; }
  const {worker, client, settle} = fixture;
  await settle(); worker.dispatchEvent({type: 'message', data: {type: 'ready'}});
  await client.waitReady();
  const work = [client.processInitSegment(new Uint8Array([1])), client.prepareInit(new Uint8Array([1])), client.processMediaSegment(new Uint8Array([1])), client.processMediaSegmentStreaming(new Uint8Array([1]), () => {})];
  const states = work.map(() => 'pending');
  work.forEach((promise, index) => promise.then(() => { states[index] = 'resolved'; }, () => { states[index] = 'rejected'; }));
  client.destroy(); // Deliberately before any async method resumes after _workerReady.
  await settle();
  assert.ok(states.every(state => state !== 'pending'));
  assert.deepEqual(worker.messages.filter(type => type !== 'init' && type !== 'destroy'), [], 'A closed transport must never receive new init or media work');
  assert.equal(worker.listenerCount(), 0);
});
