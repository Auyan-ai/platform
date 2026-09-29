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
set -euo pipefail

ENV_FILE="${1:-.env.staging}"
PROJECT="${GCP_PROJECT:-auyan-510116}"
# Frankfurt: mismo sitio que el pooler de Supabase (eu-central-1).
REGION="${GCP_REGION:-europe-west3}"
SERVICE="${SERVICE_NAME:-auyan-api-staging}"
SA_NAME="${SERVICE}"
SA_EMAIL="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
SECRET_PREFIX="${SERVICE}"

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

# --no-cpu-throttling: el loop de cleanup, el listener NOTIFY de AOPs y las
# simulaciones corren fuera del request. min-instances=0 → se apaga sin tráfico.
gcloud run deploy "$SERVICE" \
  --project "$PROJECT" \
  --region "$REGION" \
  --source . \
  --service-account "$SA_EMAIL" \
  --allow-unauthenticated \
  --no-cpu-throttling \
  --min-instances 0 \
  --max-instances 1 \
  --cpu 1 \
  --memory 1Gi \
  --timeout 300 \
  --env-vars-file "$ENV_YAML" \
  --set-secrets "$secrets_arg" \
  --quiet

gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" \
  --format 'value(status.url)'
