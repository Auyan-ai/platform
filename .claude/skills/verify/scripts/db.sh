#!/usr/bin/env bash
# Usage: db.sh "<sql>"   READ-ONLY psql against the staging Supabase (session-level read-only).
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
load_staging_env
PGOPTIONS='-c default_transaction_read_only=on' psql "$DATABASE_URL" -X -P pager=off -v ON_ERROR_STOP=1 -c "$1"
