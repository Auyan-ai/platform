#!/usr/bin/env bash
# Usage: up.sh api | web | all     Starts LOCAL code against the STAGING Supabase.
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
what="${1:-all}"

port_free() { ! ss -ltn "sport = :$1" | grep -q LISTEN; }

wait_for() { # url, pidfile, seconds
  for _ in $(seq 1 "$3"); do
    curl -fsS -m 3 "$1" >/dev/null 2>&1 && return 0
    kill -0 "$(cat "$2")" 2>/dev/null || { echo "el proceso murió; mira el log" >&2; return 1; }
    sleep 1
  done
  echo "timeout esperando $1" >&2; return 1
}

start_api() {
  port_free "$API_PORT" || { echo "puerto $API_PORT ocupado por algo que no arrancó este skill: no lo toco" >&2; exit 1; }
  load_staging_env
  cd "$REPO"
  setsid "$REPO/apps/api/.venv/bin/python" -m uvicorn apps.api.main:app --host 127.0.0.1 --port "$API_PORT" \
    >"$RUN_DIR/api.log" 2>&1 &
  echo $! >"$RUN_DIR/api.pid"
  wait_for "$API_LOCAL/health/ready" "$RUN_DIR/api.pid" 90
  echo "api ok  pid=$(cat "$RUN_DIR/api.pid")  $API_LOCAL  log=$RUN_DIR/api.log"
}

start_web() {
  port_free "$WEB_PORT" || { echo "puerto $WEB_PORT ocupado por algo que no arrancó este skill: no lo toco" >&2; exit 1; }
  load_staging_env
  # Process env beats apps/web/.env.local (which points at a local Supabase that does not exist here).
  export NEXT_PUBLIC_SUPABASE_URL="$SUPABASE_URL"
  export NEXT_PUBLIC_SUPABASE_ANON_KEY="$SUPABASE_ANON_KEY"
  export NEXT_PUBLIC_API_URL="$API_LOCAL"
  cd "$REPO/apps/web"
  setsid ./node_modules/.bin/next dev --turbopack -p "$WEB_PORT" >"$RUN_DIR/web.log" 2>&1 &
  echo $! >"$RUN_DIR/web.pid"
  wait_for "$WEB_LOCAL/login" "$RUN_DIR/web.pid" 120
  echo "web ok  pid=$(cat "$RUN_DIR/web.pid")  $WEB_LOCAL  log=$RUN_DIR/web.log"
}

case "$what" in
  api) start_api ;;
  web) start_web ;;
  all) start_api; start_web ;;
  *) echo "uso: up.sh api|web|all" >&2; exit 2 ;;
esac
