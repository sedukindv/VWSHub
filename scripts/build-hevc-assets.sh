#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATIC="${ROOT}/static/vendor"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  echo "Node.js 18+ и npm нужны только для сборки браузерного плагина." >&2
  exit 1
fi

NODE_MAJOR="$(node -p 'Number(process.versions.node.split(".")[0])')"
if [ "${NODE_MAJOR}" -lt 18 ]; then
  echo "Нужен Node.js 18 или новее; сейчас: $(node --version)" >&2
  exit 1
fi

npm install --prefix "${TMP}" --no-audit --no-fund --no-save \
  @hevcjs/hlsjs-plugin@0.1.12 @hevcjs/core@1.7.0 esbuild

mkdir -p "${STATIC}/hevc"
cp "${TMP}/node_modules/@hevcjs/core/dist/transcode-worker.js" "${STATIC}/hevc/"
cp "${TMP}/node_modules/@hevcjs/core/dist/wasm/hevc-decode.js" "${STATIC}/hevc/"
cp "${TMP}/node_modules/@hevcjs/core/dist/wasm/hevc-decode.wasm" "${STATIC}/hevc/"

cat > "${TMP}/hevc-entry.js" <<'EOF'
import { attachHevcSupport } from "@hevcjs/hlsjs-plugin";

window.VWSHevcReady = attachHevcSupport({
  workerUrl: "/static/vendor/hevc/transcode-worker.js",
  wasmUrl: "/static/vendor/hevc/hevc-decode.js",
  wasmBinaryUrl: "/static/vendor/hevc/hevc-decode.wasm",
  fps: 6,
  bitrate: 800000,
  logLevel: "warn",
}).catch((error) => {
  console.error("[VWSHub] HEVC plugin initialization failed:", error);
  return null;
});
EOF

"${TMP}/node_modules/.bin/esbuild" "${TMP}/hevc-entry.js" \
  --bundle --platform=browser --format=iife --target=es2020 \
  --outfile="${STATIC}/hevc-plugin.js"

echo "HEVC.js browser assets installed under ${STATIC}"
