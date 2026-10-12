#!/usr/bin/env bash
# Read-only. "Is this instance worth driving?"  Exit 0 = ok, 1 = something to fix (see FAIL lines).
set -uo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/env.sh"
load_staging_env
bad=0
ok()   { echo "ok    $*"; }
fail() { echo "FAIL  $*"; bad=1; }
warn() { echo "warn  $*"; }

echo "repo: $(git -C "$REPO" rev-parse --abbrev-ref HEAD) @ $(git -C "$REPO" rev-parse --short HEAD), $(git -C "$REPO" status --porcelain | wc -l) archivos sin commitear (el API/web locales corren ESTE working tree)"

# Staging DB (Supabase free tier pauses after 7 idle days)
if PGCONNECT_TIMEOUT=10 psql "$DATABASE_URL" -X -A -t -c "select 1" >/dev/null 2>&1; then ok "Supabase staging responde"
else fail "Supabase staging no responde (¿pausado? reanudar en el dashboard de Supabase)"; fi

# Cloud Run staging (informativo: el flujo local no depende de él)
if curl -fsS -m 60 "$API_BASE_URL/health" >/dev/null 2>&1; then ok "Cloud Run staging /health"; else warn "Cloud Run staging no responde (cold start >60s o caído); no bloquea la verificación local"; fi

# Local API
if [ -f "$RUN_DIR/api.pid" ] && kill -0 "$(cat "$RUN_DIR/api.pid")" 2>/dev/null; then
  pid="$(cat "$RUN_DIR/api.pid")"
  owner="$(ss -ltnp "sport = :$API_PORT" 2>/dev/null | grep -o "pid=$pid" | head -1)"
  [ -n "$owner" ] && ok "api local: pid $pid dueño del puerto $API_PORT" || fail "api local: el puerto $API_PORT no es de nuestro pid $pid"
  h="$(curl -fsS -m 5 "$API_LOCAL/health" 2>/dev/null)" && echo "$h" | grep -q '"env":"staging"' && ok "api local /health env=staging" || fail "api local /health no responde o env != staging"
  curl -fsS -m 10 "$API_LOCAL/health/ready" 2>/dev/null | grep -q '"db":true' && ok "api local /health/ready db=true" || fail "api local sin DB"
  grep -q "inbound_worker_started concurrency=0" "$RUN_DIR/api.log" && ok "worker de cola apagado (concurrency=0): no roba jobs de Cloud Run" || fail "el worker local NO está apagado: pararlo con down.sh y relanzar con up.sh"
else
  warn "api local no está corriendo (up.sh api)"
fi

# Local web
if [ -f "$RUN_DIR/web.pid" ] && kill -0 "$(cat "$RUN_DIR/web.pid")" 2>/dev/null; then
  code="$(curl -s -o /dev/null -m 20 -w '%{http_code}' "$WEB_LOCAL/login")"
  [ "$code" = "200" ] && ok "web local /login 200" || fail "web local /login devolvió $code"
  # The dashboard asks the local API who the user is (/users/me); without it every page loops / <-> /login.
  { [ -f "$RUN_DIR/api.pid" ] && kill -0 "$(cat "$RUN_DIR/api.pid")" 2>/dev/null; } || fail "web local arriba pero la API local NO: las páginas dan ERR_TOO_MANY_REDIRECTS (up.sh api)"
else
  warn "web local no está corriendo (up.sh web)"
fi

# Browser sessions of the dashboard (a human logs in once per profile; see SKILL.md)
for prof in profile profile-tenant; do
  who="super_admin"; [ "$prof" = "profile-tenant" ] && who="tenant_admin (VERIFY_PROFILE=tenant)"
  if [ -f "$VERIFY_DIR/$prof/.logged-in" ]; then ok "sesión de dashboard $who guardada ($prof/)"; else warn "sin sesión de dashboard $who: corre web-session.sh${prof/profile-tenant/ con VERIFY_PROFILE=tenant} (los drivers lo hacen solos)"; fi
done

exit $bad
