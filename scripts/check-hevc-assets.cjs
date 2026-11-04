/* Verify checked-in HEVC assets; never download or rebuild them in verification. */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const vendor = path.resolve(__dirname, '../static/vendor');
const manifest = JSON.parse(fs.readFileSync(path.join(vendor, 'hevc/manifest.json'), 'utf8'));
const required = ['hevc-plugin.js', 'hevc/transcode-worker.js', 'hevc/hevc-decode.js', 'hevc/hevc-decode.wasm', 'hevc/HEVC-CORE-LICENSE.txt', 'hevc/HEVC-PLUGIN-LICENSE.txt', 'hevc/MP4BOX-LICENSE.txt'];
for (const name of required) if (!Object.hasOwn(manifest.hashes || {}, name)) throw new Error(`Missing HEVC manifest entry: ${name}`);
if (manifest.sourceSha256 !== 'ba30b253af38416403d18a90d01a569e3fd385a1a183595ef3fef0e7d884104e') throw new Error('Pinned HEVC source identity changed; review the upstream integration before acceptance');
for (const [name, expected] of Object.entries(manifest.hashes)) {
  const file = path.resolve(vendor, name);
  if (!file.startsWith(vendor + path.sep) || !/^[a-f0-9]{64}$/.test(expected)) throw new Error(`Unsafe HEVC manifest entry: ${name}`);
  const actual = crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
  if (actual !== expected) throw new Error(`HEVC asset hash mismatch: ${name}`);
  process.stdout.write(`SHA256 OK ${name}\n`);
}
