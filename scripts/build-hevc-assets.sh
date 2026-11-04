#!/usr/bin/env bash
# Adapted from hevc-cam01-fmp4 d524f4c; assets are shipped, never fetched by clients.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
command -v node >/dev/null && command -v npm >/dev/null || { echo 'Node.js 20+ and npm are required only to build assets.' >&2; exit 1; }
npm ci --prefix "${ROOT}/scripts/hevc" --ignore-scripts --no-audit --no-fund
node "${ROOT}/scripts/build-hevc-assets.cjs"
