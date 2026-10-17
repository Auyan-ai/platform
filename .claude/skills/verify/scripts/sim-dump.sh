#!/usr/bin/env bash
# Usage: sim-dump.sh <simulation_run_id>...   Saves the DB side of simulator runs (read-only) to evidence/
# and, when the run has one, its LangSmith root trace via trace.sh.
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
[ $# -gt 0 ] || { echo "uso: sim-dump.sh <simulation_run_id>..." >&2; exit 2; }
for run in "$@"; do
  [[ "$run" =~ ^[0-9a-f-]{36}$ ]] || { echo "simulation_run_id no es un uuid: $run" >&2; exit 2; }
  out="$EVID_DIR/$(date +%Y%m%d-%H%M%S)-sim-$run.txt"
  conv="(select conversation_id from simulation_runs where id='$run')"
  {
    echo "## run"
    "$VERIFY_DIR/scripts/db.sh" "select row_to_json(t) from (select r.id, tn.slug tenant, s.name scenario, r.status, r.termination_reason, r.turns_count, (r.judge_eval->>'overall_score')::numeric judge, r.judge_eval->>'judge_goal_achieved' judge_goal, r.assertions_passed, r.assertions_total, r.cost_cents, r.langsmith_trace_id, r.conversation_id, (select count(*) from messages m where m.conversation_id=r.conversation_id and m.direction='inbound') inbound, (select count(*) from messages m where m.conversation_id=r.conversation_id and m.direction='outbound') outbound from simulation_runs r join simulation_scenarios s on s.id=r.scenario_id join tenants tn on tn.id=r.tenant_id where r.id='$run') t" -t -A
    echo "## messages"
    "$VERIFY_DIR/scripts/db.sh" "select role, direction, metadata->>'fixed_message' fixed, left(content,160) content, created_at from messages where conversation_id=$conv and deleted_at is null order by created_at"
    echo "## skills"
    "$VERIFY_DIR/scripts/db.sh" "select skill_slug, status, error_message, created_at from skill_audit_log where conversation_id=$conv order by created_at"
    echo "## escalations"
    "$VERIFY_DIR/scripts/db.sh" "select status, reason, created_at, deleted_at from escalations where conversation_id=$conv"
  } 2>&1 | tee "$out"
  tid="$(grep -o '"langsmith_trace_id":"[0-9a-f-]\{36\}"' "$out" | head -1 | cut -d'"' -f4 || true)"
  if [ -n "$tid" ]; then "$VERIFY_DIR/scripts/trace.sh" "$tid"; else echo "sin langsmith_trace_id para $run"; fi
  echo "evidencia: $out"
done
