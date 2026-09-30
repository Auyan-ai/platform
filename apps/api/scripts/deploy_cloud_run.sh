#!/usr/bin/env bash
# Despliega el API en Google Cloud Run (staging por defecto).
#
# Uso (desde la raíz del repo, con la rama/commit que quieras desplegar):
#   apps/api/scripts/deploy_cloud_run.sh [ENV_FILE]
#
# ENV_FILE (default .env.staging) es un .env con las variables del API. Nunca se
# sube: las variables sensibles van a Secret Manager (una versión nueva por
# deploy, las anteriores se destruyen) y el resto como env vars de Cloud Run.
#
# Overrides por entorno: GCP_PROJECT, GCP_REGION, SERVICE_NAME.
#
# Dimensionado de Cloud Run (variables del shell o del ENV_FILE; no llegan al API):
#   CLOUD_RUN_MIN_INSTANCES  default 0 → se apaga sin tráfico (arranque en frío).
#                            1 → instancia siempre encendida: sin arranque en frío y
#                            el worker de la cola siempre vivo. ~63 USD/mes en
#                            europe-west3 (1 vCPU + 1 GiB, facturación por instancia).
#                            Activar en producción al firmar el primer cliente de pago.
#   CLOUD_RUN_MAX_INSTANCES  default 1.
#   CLOUD_RUN_CPU / CLOUD_RUN_MEMORY  default 1 / 1Gi. Con --no-cpu-throttling el
#                            mínimo es 1 vCPU (fracciones exigen facturación por request).
set -euo pipefail

ENV_FILE="${1:-.env.staging}"
PROJECT="${GCP_PROJECT:-auyan-510116}"
# Frankfurt: mismo sitio que el pooler de Supabase (eu-central-1).
REGION="${GCP_REGION:-europe-west3}"
SERVICE="${SERVICE_NAME:-auyan-api-staging}"
SA_NAME="${SERVICE}"
SA_EMAIL="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
SECRET_PREFIX="${SERVICE}"

# Claves de despliegue: se leen del ENV_FILE pero no se pasan al contenedor.
DEPLOY_KEYS=(CLOUD_RUN_MIN_INSTANCES CLOUD_RUN_MAX_INSTANCES CLOUD_RUN_CPU CLOUD_RUN_MEMORY)

SECRET_KEYS=(
  DATABASE_URL
  SUPABASE_SERVICE_ROLE_KEY
  SUPABASE_ANON_KEY
  SUPABASE_JWT_SECRET
  ANTHROPIC_API_KEY
  OPENAI_API_KEY
  WEBHOOK_SECRET
  INTEGRATIONS_SECRET_KEY
  LANGSMITH_API_KEY
  LANGFUSE_PUBLIC_KEY
  LANGFUSE_SECRET_KEY
  ZENDESK_OAUTH_CLIENT_SECRET
  GORGIAS_OAUTH_CLIENT_SECRET
  POSTMARK_API_TOKEN
)

[[ -f "$ENV_FILE" ]] || { echo "No existe $ENV_FILE" >&2; exit 1; }
[[ -f Dockerfile ]] || { echo "Córrelo desde la raíz del repo" >&2; exit 1; }

is_secret() {
  local k
  for k in "${SECRET_KEYS[@]}"; do [[ "$k" == "$1" ]] && return 0; done
  return 1
}

# Parsea KEY=VALUE (ignora comentarios/vacías, quita comillas envolventes).
declare -A VARS=()
while IFS= read -r line || [[ -n "$line" ]]; do
  line="${line%$'\r'}"
  [[ "$line" =~ ^[[:space:]]*(#|$) ]] && continue
  [[ "$line" =~ ^[[:space:]]*(export[[:space:]]+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]] || continue
  key="${BASH_REMATCH[2]}"
  value="${BASH_REMATCH[3]}"
  if [[ "$value" =~ ^\"(.*)\"$ || "$value" =~ ^\'(.*)\'$ ]]; then value="${BASH_REMATCH[1]}"; fi
  [[ -z "$value" ]] && continue
  VARS["$key"]="$value"
done < "$ENV_FILE"

# Dimensionado: shell > ENV_FILE > default. Se sacan de VARS (no son config del API).
declare -A DEPLOY=()
for key in "${DEPLOY_KEYS[@]}"; do
  DEPLOY["$key"]="${!key:-${VARS[$key]:-}}"
  unset "VARS[$key]"
done
MIN_INSTANCES="${DEPLOY[CLOUD_RUN_MIN_INSTANCES]:-0}"
MAX_INSTANCES="${DEPLOY[CLOUD_RUN_MAX_INSTANCES]:-1}"
CPU="${DEPLOY[CLOUD_RUN_CPU]:-1}"
MEMORY="${DEPLOY[CLOUD_RUN_MEMORY]:-1Gi}"
for n in "$MIN_INSTANCES" "$MAX_INSTANCES"; do
  [[ "$n" =~ ^[0-9]+$ ]] || { echo "CLOUD_RUN_MIN/MAX_INSTANCES debe ser un entero: $n" >&2; exit 1; }
done
echo "Cloud Run: min=${MIN_INSTANCES} max=${MAX_INSTANCES} cpu=${CPU} memory=${MEMORY}"

# Service account dedicada (solo lee sus secretos).
if ! gcloud iam service-accounts describe "$SA_EMAIL" --project "$PROJECT" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$SA_NAME" --project "$PROJECT" \
    --display-name "Cloud Run ${SERVICE}" >/dev/null
  echo "service account creada: $SA_EMAIL"
fi

SET_SECRETS=()
ENV_YAML="$(mktemp)"
trap 'rm -f "$ENV_YAML"' EXIT

for key in "${!VARS[@]}"; do
  value="${VARS[$key]}"
  if is_secret "$key"; then
    secret="${SECRET_PREFIX}-$(tr '[:upper:]_' '[:lower:]-' <<<"$key")"
    if ! gcloud secrets describe "$secret" --project "$PROJECT" >/dev/null 2>&1; then
      gcloud secrets create "$secret" --project "$PROJECT" --replication-policy automatic >/dev/null
      gcloud secrets add-iam-policy-binding "$secret" --project "$PROJECT" \
        --member "serviceAccount:${SA_EMAIL}" --role roles/secretmanager.secretAccessor >/dev/null
    fi
    # Nueva versión solo si cambió el valor; se destruyen las anteriores (free tier).
    current="$(gcloud secrets versions access latest --secret "$secret" --project "$PROJECT" 2>/dev/null || true)"
    if [[ "$current" != "$value" ]]; then
      printf '%s' "$value" | gcloud secrets versions add "$secret" --project "$PROJECT" --data-file=- >/dev/null
      # Más reciente primero; se conserva la [0] y se destruye el resto. (No filtrar
      # por `name!=…`: gcloud no lo evalúa igual y acababa destruyendo la nueva.)
      mapfile -t versions < <(gcloud secrets versions list "$secret" --project "$PROJECT" \
        --filter 'state=ENABLED OR state=DISABLED' --sort-by '~createTime' \
        --format 'value(name.basename())')
      for old in "${versions[@]:1}"; do
        gcloud secrets versions destroy "$old" --secret "$secret" --project "$PROJECT" --quiet >/dev/null
      done
      echo "secreto actualizado: $key"
    fi
    SET_SECRETS+=("${key}=${secret}:latest")
  else
    # YAML: comillas simples, escapando las internas.
    printf "%s: '%s'\n" "$key" "${value//\'/\'\'}" >> "$ENV_YAML"
  fi
done

secrets_arg="$(IFS=,; echo "${SET_SECRETS[*]}")"

# --no-cpu-throttling: el worker de la cola inbound, el loop de cleanup, el listener
# NOTIFY de AOPs y las simulaciones corren fuera del request. --cpu-boost: CPU extra
# durante el arranque (acorta el arranque en frío).
gcloud run deploy "$SERVICE" \
  --project "$PROJECT" \
  --region "$REGION" \
  --source . \
  --service-account "$SA_EMAIL" \
  --allow-unauthenticated \
  --no-cpu-throttling \
  --cpu-boost \
  --min-instances "$MIN_INSTANCES" \
  --max-instances "$MAX_INSTANCES" \
  --cpu "$CPU" \
  --memory "$MEMORY" \
  --timeout 300 \
  --env-vars-file "$ENV_YAML" \
  --set-secrets "$secrets_arg" \
  --quiet

gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" \
  --format 'value(status.url)'
