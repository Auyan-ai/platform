#!/usr/bin/env bash
# Operación del API en Cloud Run: alerta de errores por email + keep-alive diario.
#
# Uso (idempotente; se puede re-ejecutar):
#   ALERT_EMAIL=tu@correo.com apps/api/scripts/setup_cloud_run_ops.sh
#
# Crea o actualiza:
#   1. Canal de notificación por email (Cloud Monitoring).
#   2. Alerta basada en logs: cualquier línea del servicio con severity>=ERROR →
#      email. Como mucho 1 cada 5 min; se cierra sola a los 30 min sin repetirse.
#      Requiere logs JSON con `severity` (apps/api/core/log_config.py).
#   3. Keep-alive: Cloud Scheduler hace GET /health/ready (consulta real a la base)
#      una vez al día. Evita que Supabase free tier pause el proyecto (7 días sin
#      actividad) y de paso despierta el worker.
#
# Overrides: GCP_PROJECT, GCP_REGION, SERVICE_NAME, KEEPALIVE_SCHEDULE (cron),
# KEEPALIVE_TZ.
set -euo pipefail

: "${ALERT_EMAIL:?Define ALERT_EMAIL (destino de las alertas)}"
PROJECT="${GCP_PROJECT:-auyan-510116}"
REGION="${GCP_REGION:-europe-west3}"
SERVICE="${SERVICE_NAME:-auyan-api-staging}"
SCHEDULE="${KEEPALIVE_SCHEDULE:-0 6 * * *}"
TZ_NAME="${KEEPALIVE_TZ:-Europe/Madrid}"

API="https://monitoring.googleapis.com/v3/projects/${PROJECT}"
TOKEN="$(gcloud auth print-access-token)"
auth=(-H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json")

gcloud services enable monitoring.googleapis.com cloudscheduler.googleapis.com \
  --project "$PROJECT" >/dev/null

# ─── 1. Canal de email ───────────────────────────────────────────────────────
channel="$(curl -sf "${auth[@]}" "${API}/notificationChannels?filter=type%3D%22email%22" |
  python3 -c "
import json, sys
email = sys.argv[1]
for c in json.load(sys.stdin).get('notificationChannels', []):
    if c.get('labels', {}).get('email_address') == email:
        print(c['name']); break
" "$ALERT_EMAIL")"
if [[ -z "$channel" ]]; then
  channel="$(curl -sf "${auth[@]}" -X POST "${API}/notificationChannels" -d "$(python3 -c "
import json, sys
print(json.dumps({'type': 'email', 'displayName': f'Auyan alertas ({sys.argv[1]})',
                  'labels': {'email_address': sys.argv[1]}}))" "$ALERT_EMAIL")" |
    python3 -c "import json,sys; print(json.load(sys.stdin)['name'])")"
  echo "canal creado: $channel"
else
  echo "canal existente: $channel"
fi

# ─── 2. Alerta de errores ────────────────────────────────────────────────────
display="${SERVICE} · errores (severity>=ERROR)"
# Heredoc entre comillas simples: el texto lleva comillas invertidas (markdown).
policy_json="$(SERVICE="$SERVICE" CHANNEL="$channel" DISPLAY="$display" python3 - <<'PY'
import json, os
service, channel, display = os.environ["SERVICE"], os.environ["CHANNEL"], os.environ["DISPLAY"]
flt = (f'resource.type="cloud_run_revision" AND '
       f'resource.labels.service_name="{service}" AND severity>=ERROR')
print(json.dumps({
  "displayName": display,
  "combiner": "OR",
  "severity": "ERROR",
  "conditions": [{"displayName": "Log con severity>=ERROR",
                  "conditionMatchedLog": {"filter": flt}}],
  "alertStrategy": {"notificationRateLimit": {"period": "300s"}, "autoClose": "1800s"},
  "notificationChannels": [channel],
  "documentation": {"mimeType": "text/markdown", "content": (
    f"La API **{service}** registró un error. Revisa el log enlazado.\n\n"
    "Eventos clave: `inbound_job_failed` (mensaje sin respuesta tras reintentos), "
    "`agent_reply_delivery_failed` / `agent_reply_no_helpdesk` (respuesta no entregada), "
    "`inbound_turn_graph_error` (el grafo falló: LLM, crédito…), "
    "`approved_skill_execution_failed` (acción L3 aprobada que Shopify rechazó).")},
}))
PY
)"
existing="$(curl -sf "${auth[@]}" "${API}/alertPolicies" | python3 -c "
import json, sys
for p in json.load(sys.stdin).get('alertPolicies', []):
    if p.get('displayName') == sys.argv[1]:
        print(p['name']); break
" "$display")"
if [[ -z "$existing" ]]; then
  curl -sf "${auth[@]}" -X POST "${API}/alertPolicies" -d "$policy_json" >/dev/null
  echo "alerta creada: $display"
else
  curl -sf "${auth[@]}" -X PATCH "https://monitoring.googleapis.com/v3/${existing}" \
    -d "$policy_json" >/dev/null
  echo "alerta actualizada: $display"
fi

# ─── 3. Keep-alive ───────────────────────────────────────────────────────────
url="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" \
  --format 'value(status.url)')/health/ready"
job="${SERVICE}-keepalive"
verb=create
if gcloud scheduler jobs describe "$job" --location "$REGION" --project "$PROJECT" \
  >/dev/null 2>&1; then
  verb=update
fi
gcloud scheduler jobs "$verb" http "$job" \
  --project "$PROJECT" --location "$REGION" \
  --schedule "$SCHEDULE" --time-zone "$TZ_NAME" \
  --uri "$url" --http-method GET \
  --attempt-deadline 60s --max-retry-attempts 3 >/dev/null
echo "keep-alive (${verb}): ${job} → GET ${url} [${SCHEDULE} ${TZ_NAME}]"
