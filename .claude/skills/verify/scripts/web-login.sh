#!/usr/bin/env bash
# Usage: web-login.sh   (humano, una sola vez) Abre Chromium visible en el dashboard local para iniciar sesión.
# Envuelve web-login.cjs y encuentra `node` aunque mise no esté activado en esta terminal.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
node_bin="$(command -v node || ls -d "$HOME"/.local/share/mise/installs/node/*/bin/node 2>/dev/null | sort -V | tail -1)"
[ -x "$node_bin" ] || { echo "no encuentro node" >&2; exit 1; }
exec "$node_bin" "$here/web-login.cjs"
