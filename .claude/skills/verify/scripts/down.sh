#!/usr/bin/env bash
# Stops ONLY the process groups this skill started (pidfiles in run/). Leaves evidence/ alone.
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
for name in api web; do
  pf="$RUN_DIR/$name.pid"
  [ -f "$pf" ] || continue
  pid="$(cat "$pf")"
  if kill -0 "$pid" 2>/dev/null; then
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null
    for _ in $(seq 1 15); do kill -0 "$pid" 2>/dev/null || break; sleep 1; done
    kill -0 "$pid" 2>/dev/null && { kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null; }
    echo "$name detenido (pid $pid)"
  else
    echo "$name: pid $pid ya no existía"
  fi
  rm -f "$pf"
done
