/* Reproducible integration of the existing hevc-cam01-fmp4 transport/plugin. */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const root = path.resolve(__dirname, '..');
const deps = path.join(__dirname, 'hevc', 'node_modules');
const out = path.join(root, 'static', 'vendor');
const core = path.join(deps, '@hevcjs', 'core');
function requireVersion(name, version) {
  const info = JSON.parse(fs.readFileSync(path.join(deps, name, 'package.json'), 'utf8'));
  if (info.version !== version) throw new Error(`${name}: expected ${version}, got ${info.version}`);
}
requireVersion('@hevcjs/core', '1.7.0');
requireVersion('@hevcjs/hlsjs-plugin', '0.1.12');
requireVersion('esbuild', '0.28.2');
requireVersion('mp4box', '2.4.1');
const coreFile = path.join(core, 'dist', 'index.js');
const original = fs.readFileSync(coreFile, 'utf8');
const sourceSha256 = crypto.createHash('sha256').update(original).digest('hex');
if (sourceSha256 !== 'ba30b253af38416403d18a90d01a569e3fd385a1a183595ef3fef0e7d884104e')
  throw new Error('Pinned @hevcjs/core source hash differs; review upstream before applying integration patches');
function replaceOnce(source, needle, replacement) {
  if (source.split(needle).length !== 2) throw new Error(`Pinned core integration anchor changed: ${needle}`);
  return source.replace(needle, replacement);
}
function replaceCount(source, needle, replacement, count) {
  if (source.split(needle).length !== count + 1) throw new Error(`Pinned Worker anchor changed: ${needle}`);
  return source.split(needle).join(replacement);
}
function patchWorkerLifecycle(source) {
  const begin = source.indexOf('var TranscodeWorkerClient = class {');
  const end = source.indexOf('async function loadWorker(', begin);
  if (begin < 0 || end < 0) throw new Error('Pinned Worker class changed');
  let client = source.slice(begin, end);
  client = replaceOnce(client, 'constructor(config) {', 'constructor(config) {\n    this._wvwDestroyed = false;\n    this._wvwStreaming = new Map();');
  client = replaceCount(client, 'this._readyPromise = new Promise((resolve) => {\n      this._readyResolve = resolve;\n    });',
    'this._readyPromise = new Promise((resolve, reject) => {\n      this._readyResolve = resolve;\n      this._readyReject = reject;\n    });\n    this._readyPromise.catch(() => {});', 2);
  client = replaceCount(client, 'this._initParsedReject = reject;\n    });',
    'this._initParsedReject = reject;\n    });\n    this._initParsedPromise.catch(() => {});', 3);
  client = replaceOnce(client, 'this._workerReady = loadWorker(config.workerUrl).then((worker) => {',
    'this._workerReady = loadWorker(config.workerUrl).then((worker) => {\n      if (this._wvwDestroyed) return worker;');
  client = replaceOnce(client, 'log.error("Worker error:", e.message);',
    'log.error("Worker error:", e.message);\n        this.destroy();');
  client = replaceCount(client, 'const worker = await this._workerReady;',
    'const worker = await this._workerReady;\n    if (this._wvwDestroyed) throw new Error("HEVC Worker is closed");', 4);
  client = replaceOnce(client, 'const handler = (e) => {',
    'const handler = (e) => {\n        if (this._wvwDestroyed) return;');
  client = replaceOnce(client, 'chainPromise = chainPromise.then(() => onChunk(h264, init, msg.codec ?? null));',
    'chainPromise = chainPromise.then(() => { if (!this._wvwDestroyed) return onChunk(h264, init, msg.codec ?? null); });');
  client = replaceCount(client, 'worker.removeEventListener("message", handler);',
    'worker.removeEventListener("message", handler);\n          this._wvwStreaming.delete(id);', 2);
  client = replaceOnce(client, 'worker.addEventListener("message", handler);',
    'this._wvwStreaming.set(id, { worker, handler, reject });\n      worker.addEventListener("message", handler);');
  const cancel = `    const closed = new Error("HEVC Worker is closed");
    this._readyReject?.(closed);
    this._initParsedReject?.(closed);
    for (const pending of this._wvwStreaming.values()) {
      pending.worker.removeEventListener("message", pending.handler);
      pending.reject(closed);
    }
    this._wvwStreaming.clear();`;
  client = replaceOnce(client, '  abort() {\n    for', `  abort() {
    if (this._wvwDestroyed) return;
${cancel}
    for`);
  client = replaceOnce(client, 'this._workerReady.then((worker) => worker.postMessage({ type: "abort" }));',
    'this._workerReady.then((worker) => { if (!this._wvwDestroyed) worker.postMessage({ type: "abort" }); }).catch(() => {});');
  client = replaceOnce(client, `  destroy() {
    this._pendingResolves.clear();
    this._pendingPrepareInit.clear();
    this._workerReady.then((worker) => {
      worker.postMessage({ type: "destroy" });
      worker.terminate();
    });
  }`, `  destroy() {
    if (this._wvwDestroyed) return;
    this._wvwDestroyed = true;
    this._ready = false;
${cancel}
    for (const pending of this._pendingResolves.values()) pending.reject(closed);
    for (const pending of this._pendingPrepareInit.values()) pending.reject(closed);
    this._pendingResolves.clear();
    this._pendingPrepareInit.clear();
    this._workerReady.then((worker) => {
      worker.onmessage = worker.onerror = null;
      try { worker.postMessage({ type: "destroy" }); } finally { worker.terminate(); }
    }).catch(() => {});
  }`);
  client = replaceOnce(client, '  _onMessage(msg) {',
    '  _onMessage(msg) {\n    if (this._wvwDestroyed) return;\n    if (msg.type === "error" && msg.id === -1 && !this._ready) { this.destroy(); return; }');
  return source.slice(0, begin) + client + source.slice(end);
}
// The upstream plugin patches MSE globally. Preserve native playback of codecs
// positively verified by this client while another camera uses the fallback.
let patched = replaceOnce(patchWorkerLifecycle(original), 'MediaSource.isTypeSupported = function(mimeType) {\n    if (HEVC_DETECT_RE.test(mimeType)) {',
  'MediaSource.isTypeSupported = function(mimeType) {\n    if (HEVC_DETECT_RE.test(mimeType) && interceptState.config.shouldTranscode?.(mimeType) !== false) {');
patched = replaceOnce(patched, 'if (cfg.video?.contentType && HEVC_DETECT_RE.test(cfg.video.contentType)) {',
  'if (cfg.video?.contentType && HEVC_DETECT_RE.test(cfg.video.contentType) && interceptState.config.shouldTranscode?.(cfg.video.contentType) !== false) {');
patched = replaceOnce(patched, 'if (!HEVC_DETECT_RE.test(mimeType)) {',
  'if (!HEVC_DETECT_RE.test(mimeType) || interceptState.config.shouldTranscode?.(mimeType) === false) {');
patched = replaceOnce(patched, 'function createTranscodingProxy(realSB, config, muxed = false) {',
  'function createTranscodingProxy(realSB, config, muxed = false) {\n  let wvwDestroyed = false;');
patched = replaceOnce(patched, 'Object.defineProperty(realSB, "appendBuffer", {\n    value: function(data) {',
  'Object.defineProperty(realSB, "appendBuffer", {\n    value: function(data) {\n      if (wvwDestroyed) throw new Error("HEVC SourceBuffer is closed");');
patched = replaceOnce(patched, 'while (!transcoder.isInitialized) await new Promise((r) => setTimeout(r, 10));',
  'while (!transcoder.isInitialized) {\n        if (wvwDestroyed) throw new Error("HEVC SourceBuffer is closed");\n        await new Promise((r) => setTimeout(r, 10));\n      }\n      if (wvwDestroyed) throw new Error("HEVC SourceBuffer is closed");');
patched = replaceOnce(patched, 'await pool.waitReady();\n      await pool.processInitSegment(segment);',
  'await pool.waitReady();\n      if (wvwDestroyed) throw new Error("HEVC SourceBuffer is closed");\n      await pool.processInitSegment(segment);');
// Upstream abort flushes work but keeps its Worker pool alive. Expose an explicit
// idempotent per-SourceBuffer destructor; hls.js alone cannot dispose that pool.
patched = replaceOnce(patched, '  return realSB;\n}\nfunction isInitSegment', `
  Object.defineProperty(realSB, '__wvwDestroy', { value() {
    if (wvwDestroyed) return;
    wvwDestroyed = true;
    abortGeneration++;
    queue.length = 0;
    for (const rec of inFlight) { rec.done = true; rec.wake?.(); }
    inFlight.length = 0;
    fakeUpdating = false;
    processing = false;
    pool?.destroy();
    transcoder?.destroy();
  }});
  return realSB;
}
function isInitSegment`);
fs.mkdirSync(path.join(out, 'hevc'), { recursive: true });
// Alias a generated sibling module, never edit the installed upstream package.
const patchedFile = path.join(core, 'dist', 'wvw-patched-index.js');
fs.writeFileSync(patchedFile, patched);
if (process.argv.includes('--stage')) {
  console.log(`Staged pinned core integration: ${patchedFile}`);
  return;
}
try {
  if (!process.argv.includes('--finish')) require(path.join(deps, 'esbuild')).buildSync({
    entryPoints: [path.join(__dirname, 'hevc', 'entry.js')], bundle: true,
    platform: 'browser', format: 'iife', target: 'es2020', minify: true,
    legalComments: 'linked', outfile: path.join(out, 'hevc-plugin.js'),
    alias: { '@hevcjs/core': patchedFile },
  });
} finally { fs.rmSync(patchedFile, { force: true }); }
for (const [source, name] of [
  ['dist/transcode-worker.js', 'transcode-worker.js'],
  ['dist/wasm/hevc-decode.js', 'hevc-decode.js'],
  ['dist/wasm/hevc-decode.wasm', 'hevc-decode.wasm'],
]) fs.copyFileSync(path.join(core, source), path.join(out, 'hevc', name));
for (const [name, label] of [['@hevcjs/core','HEVC-CORE'], ['@hevcjs/hlsjs-plugin','HEVC-PLUGIN'], ['mp4box','MP4BOX']]) {
  const packageDir = path.join(deps, name);
  const license = fs.readdirSync(packageDir).find(file => /^licen[cs]e(?:\.|$)/i.test(file));
  if (!license) throw new Error(`Missing license: ${name}`);
  fs.copyFileSync(path.join(packageDir, license), path.join(out, 'hevc', `${label}-LICENSE.txt`));
}
const files = ['hevc-plugin.js', 'hevc/transcode-worker.js', 'hevc/hevc-decode.js', 'hevc/hevc-decode.wasm',
  'hevc/HEVC-CORE-LICENSE.txt', 'hevc/HEVC-PLUGIN-LICENSE.txt', 'hevc/MP4BOX-LICENSE.txt'];
if (fs.existsSync(path.join(out, 'hevc-plugin.js.LEGAL.txt'))) files.push('hevc-plugin.js.LEGAL.txt');
const hashes = Object.fromEntries(files.map(file => [file, crypto.createHash('sha256').update(fs.readFileSync(path.join(out, file))).digest('hex')]));
fs.writeFileSync(path.join(out, 'hevc', 'manifest.json'), JSON.stringify({
  sourceBranchCommit: 'd524f4c907702ce56e1c04af3a7d100e154dcfac',
  sourceSha256,
  packages: { '@hevcjs/core': '1.7.0', '@hevcjs/hlsjs-plugin': '0.1.12', mp4box: '2.4.1', esbuild: '0.28.2', 'hls.js': '1.7.3' },
  integration: ['per-codec native bypass', 'explicit per-source Worker cleanup'], hashes,
}, null, 2) + '\n');
console.log('HEVC assets built locally with pinned dependencies; client downloads are same-origin only.');
