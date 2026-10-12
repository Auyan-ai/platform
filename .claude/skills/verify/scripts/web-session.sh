#!/usr/bin/env bash
# Usage: [VERIFY_PROFILE=tenant] web-session.sh   Crea la sesión del dashboard de staging sin contraseña (ver web-session.cjs).
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
node_bin="$(command -v node || ls -d "$HOME"/.local/share/mise/installs/node/*/bin/node 2>/dev/null | sort -V | tail -1)"
[ -x "$node_bin" ] || { echo "no encuentro node" >&2; exit 1; }
exec "$node_bin" "$here/web-session.cjs"
