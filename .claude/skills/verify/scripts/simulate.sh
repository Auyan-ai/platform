#!/usr/bin/env bash
# Usage: simulate.sh <tenant_uuid> <run_simulator args...>   e.g. simulate.sh 683246c2-10ce-4f6c-a299-5053f32f8c01 --ids CE-06
# Runs the simulator from the working tree against STAGING (spends Anthropic credit), saves its output
# to evidence/ and calls sim-dump.sh for every run it printed.
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
tenant="${1:?tenant uuid (marea-studio = 683246c2-10ce-4f6c-a299-5053f32f8c01)}"; shift
[[ "$tenant" =~ ^[0-9a-f-]{36}$ ]] || { echo "tenant no es un uuid" >&2; exit 2; }
out="$EVID_DIR/$(date +%Y%m%d-%H%M%S)-simulator.txt"
status=0
( load_staging_env; cd "$REPO" && PYTHONUNBUFFERED=1 "$REPO/apps/api/.venv/bin/python" apps/api/scripts/run_simulator.py --tenant "$tenant" "$@" ) \
  2>&1 | tee "$out" || status=$?
mapfile -t runs < <(grep -o '^  Run: [0-9a-f-]\{36\}' "$out" | awk '{print $2}')
[ ${#runs[@]} -eq 0 ] || "$VERIFY_DIR/scripts/sim-dump.sh" "${runs[@]}" >/dev/null
echo "evidencia: $out"
echo "runs: ${runs[*]:-ninguno}"
exit "$status"
