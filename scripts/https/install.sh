#!/bin/sh
# Managed by VWSHub HTTPS Installer
set -eu
if [ "$(id -u)" -ne 0 ] || [ "$(uname -s)" != Linux ]; then
  echo 'Run this installer as root on the Debian/Ubuntu server.' >&2
  exit 1
fi
if [ ! -f /etc/debian_version ]; then
  echo 'This installer supports Debian/Ubuntu only.' >&2
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1 || ! command -v openssl >/dev/null 2>&1 || ! command -v ss >/dev/null 2>&1; then
  apt-get update
  apt-get install -y python3 openssl ca-certificates iproute2
fi
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$SCRIPT_DIR/vwshub-https.py" "$@"
