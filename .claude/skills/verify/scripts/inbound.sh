#!/usr/bin/env bash
# Usage: [VERIFY_EMAIL=<email del pedido>] inbound.sh <tenant_slug> "<mensaje>" [conversation_id]
# Sends a signed customer message to the LOCAL api (/webhooks/inbound, channel=chat). That endpoint runs the
# whole graph inside the request and returns the reply in the HTTP body, so nothing is delivered to a real
# helpdesk and the shared inbound_jobs queue is not involved. Writes the raw response to evidence/.
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
tenant="${1:?tenant slug (p. ej. marea-studio)}"; content="${2:?mensaje}"; conv="${3:-}"
load_staging_env
stamp="$(date +%Y%m%d-%H%M%S)"
out="$EVID_DIR/$stamp-inbound-$tenant.txt"
args=(--tenant "$tenant" --channel chat --url "$API_LOCAL" --name "VERIFY bot" \
      --email "${VERIFY_EMAIL:-verify-$stamp@example.com}" --content "$content")
[ -n "$conv" ] && args+=(--conversation-id "$conv")
cd "$REPO/apps/api"
./.venv/bin/python -m scripts.send_test_webhook "${args[@]}" | tee "$out"
echo "evidencia: $out"
