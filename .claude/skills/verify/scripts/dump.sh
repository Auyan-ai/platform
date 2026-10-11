#!/usr/bin/env bash
# Usage: dump.sh <conversation_id>   Saves the DB side of a conversation (read-only) to evidence/.
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
conv="${1:?conversation_id}"
[[ "$conv" =~ ^[0-9a-f-]{36}$ ]] || { echo "conversation_id no es un uuid" >&2; exit 2; }
out="$EVID_DIR/$(date +%Y%m%d-%H%M%S)-db-$conv.txt"
{
  echo "## conversation";   "$VERIFY_DIR/scripts/db.sh" "select id, channel, status, subject, created_at, resolved_at from conversations where id='$conv'"
  echo "## messages";       "$VERIFY_DIR/scripts/db.sh" "select role, direction, left(content,160) content, created_at from messages where conversation_id='$conv' and deleted_at is null order by created_at"
  echo "## reasoning";      "$VERIFY_DIR/scripts/db.sh" "select seq, phase, event_type, label, status from agent_reasoning_events where conversation_id='$conv' and deleted_at is null order by seq"
  echo "## escalations";    "$VERIFY_DIR/scripts/db.sh" "select id, status, reason, created_at from escalations where conversation_id='$conv' and deleted_at is null"
  echo "## inbound_jobs";   "$VERIFY_DIR/scripts/db.sh" "select status, attempts, decision, last_error from inbound_jobs where conversation_id='$conv'"
} 2>&1 | tee "$out"
echo "evidencia: $out"
