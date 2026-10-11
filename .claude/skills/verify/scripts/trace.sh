#!/usr/bin/env bash
# Usage: trace.sh <trace_id>   Confirms the run exists in LangSmith (project auyan-staging) and saves a summary.
# The API key stays in the environment; it is never printed.
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
tid="${1:?trace_id (viene en la respuesta de inbound.sh)}"
[[ "$tid" =~ ^[0-9a-f-]{36}$ ]] || { echo "trace_id no es un uuid" >&2; exit 2; }
load_staging_env
tmp="$(mktemp)"; trap 'rm -f "$tmp"' EXIT
code="$(curl -s -m 20 -o "$tmp" -w '%{http_code}' -H "x-api-key: $LANGSMITH_API_KEY" \
  ${LANGSMITH_WORKSPACE_ID:+-H "X-Tenant-Id: $LANGSMITH_WORKSPACE_ID"} \
  "${LANGSMITH_ENDPOINT:-https://api.smith.langchain.com}/api/v1/runs/$tid")"
out="$EVID_DIR/$(date +%Y%m%d-%H%M%S)-trace-$tid.txt"
python3 - "$tmp" "$code" "$tid" <<'PY' | tee "$out"
import json, sys
path, code, tid = sys.argv[1:]
print(f"http={code} trace_id={tid}")
if code == "200":
    d = json.load(open(path))
    print({k: d.get(k) for k in ("name", "run_type", "status", "error", "total_tokens", "total_cost")})
else:
    sys.exit(1)
PY
echo "evidencia: $out"
