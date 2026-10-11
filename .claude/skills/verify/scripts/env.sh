#!/usr/bin/env bash
# Sourced by the other scripts. Defines paths and loads the STAGING env for the local processes.
# Never print values from .env.staging: it holds live keys.
set -euo pipefail

VERIFY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="$(cd "$VERIFY_DIR/../../.." && pwd)"
RUN_DIR="$VERIFY_DIR/run"          # pidfiles + logs of instances this skill started
EVID_DIR="$VERIFY_DIR/evidence"    # proofs; cleanup NEVER touches this
API_PORT=8000                      # fixed: .env.staging ALLOWED_ORIGINS only allows localhost:3000
WEB_PORT=3000
API_LOCAL="http://localhost:$API_PORT"
WEB_LOCAL="http://localhost:$WEB_PORT"
mkdir -p "$RUN_DIR" "$EVID_DIR"

load_staging_env() {
  [ -f "$REPO/.env.staging" ] || { echo "falta $REPO/.env.staging" >&2; return 1; }
  set -a; . "$REPO/.env.staging"; set +a
  # The local API shares the staging DB with Cloud Run. Without these two lines the local
  # process would also claim real helpdesk jobs from `inbound_jobs` and run the abandoned-
  # conversation cleanup against live tenants.
  export INBOUND_WORKER_CONCURRENCY=0
  export CLEANUP_INTERVAL_SECONDS=86400
}
