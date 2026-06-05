"""Configuración global de la API.

Cargada una sola vez por proceso vía `get_settings()` (lru_cache).
Todas las variables sensibles llegan por entorno; nada hardcodeado.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, HttpUrl, PostgresDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnv = Literal["development", "staging", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


class Settings(BaseSettings):
    """Settings cargadas desde .env o variables de entorno del SO.

    Falla en el arranque si falta cualquier campo `Field(...)` requerido —
    queremos enterarnos en boot, no en runtime cuando entra un ticket.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- App ---
    app_env: AppEnv = "development"
    log_level: LogLevel = "INFO"

    # --- Database (Postgres de Supabase, conexión directa para pgvector + GUC) ---
    database_url: PostgresDsn = Field(
        ...,
        description="DSN de Postgres de Supabase. Formato: postgresql://user:pass@host:port/dbname",
    )
    supabase_url: HttpUrl = Field(..., description="Base URL del proyecto Supabase")
    supabase_service_role_key: SecretStr = Field(..., description="Service-role key (server only)")
    supabase_anon_key: SecretStr = Field(..., description="Anon key (para clientes públicos)")

    # --- LLM providers ---
    anthropic_api_key: SecretStr = Field(..., description="API key de Anthropic")
    openai_api_key: SecretStr = Field(..., description="API key de OpenAI (embeddings)")

    # --- Observability ---
    langsmith_api_key: SecretStr | None = None
    langsmith_project: str = "auyan-staging"
    langsmith_endpoint: HttpUrl = Field(default=HttpUrl("https://api.smith.langchain.com"))
    langsmith_workspace_id: str | None = None
    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_host: HttpUrl = Field(default=HttpUrl("https://cloud.langfuse.com"))

    # --- Postmark (email outbound Auyan→cliente) ---
    # Obtener en https://account.postmarkapp.com/servers
    postmark_api_token: SecretStr | None = None
    # Dirección y nombre del remitente. El dominio debe estar verificado en Postmark.
    postmark_from_email: str = "noreply@auyan.ai"
    postmark_from_name: str = "Auyan"

    # Clave maestra AES-256-GCM para credentials de tenant_integrations.
    # Generar con: python -c "import secrets; print(secrets.token_hex(32))"
    integrations_secret_key: SecretStr | None = None

    # --- Zendesk OAuth (sub-PR 0.5) ---
    # Registrar en https://www.zendesk.com/partner/programs/technology/
    # Redirect URI: {api_base_url}/oauth/zendesk/callback
    zendesk_oauth_client_id: str | None = None
    zendesk_oauth_client_secret: SecretStr | None = None
    zendesk_oauth_redirect_uri: str | None = None

    # --- Gorgias OAuth (sub-PR 0.6) ---
    # Registrar en https://www.gorgias.com/integrations/developer
    # Redirect URI: {api_base_url}/oauth/gorgias/callback
    gorgias_oauth_client_id: str | None = None
    gorgias_oauth_client_secret: SecretStr | None = None
    gorgias_oauth_redirect_uri: str | None = None

    # --- Webhook security ---
    webhook_secret: SecretStr = Field(
        ..., description="HMAC shared secret para validar webhooks entrantes"
    )

    # URL pública de la API. Se usa para construir el target de webhooks salientes
    # que registramos en el helpdesk del cliente (ej. {api_base_url}/webhooks/chatwoot).
    # Sin esto, la conexión de Chatwoot no auto-registra el webhook entrante.
    api_base_url: str | None = None

    # --- Auth (Supabase JWT) ---
    # Supabase usa ES256 (ECDSA) en proyectos nuevos — se valida con JWKS público.
    # supabase_jwt_secret sólo se usa en proyectos legacy que aún tienen HS256.
    supabase_jwt_secret: SecretStr | None = None
    supabase_jwt_algorithm: str = "ES256"
    supabase_jwt_audience: str = "authenticated"
    # TTL del cache de claves JWKS (segundos). Las keys de Supabase rotan con poca frecuencia.
    supabase_jwks_cache_ttl_seconds: int = 3600

    # Cache del lookup de usuarios para auth. Se invalida por TTL — los cambios
    # de role/tenant_id tardan hasta `auth_user_cache_ttl_seconds` en propagarse.
    # `maxsize` acota la memoria: 1000 entries ≈ 1000 usuarios activos en paralelo;
    # subirlo si en producción se ven más usuarios concurrentes.
    auth_user_cache_ttl_seconds: int = 60
    auth_user_cache_maxsize: int = 1000

    # --- CORS ---
    # Orígenes permitidos, separados por comas.
    # Ejemplo Railway: ALLOWED_ORIGINS=https://platform-web-staging.up.railway.app
    allowed_origins: str = "http://localhost:3000,http://localhost:3001"

    # --- Defaults del agente (overridables por tenant_configurations) ---
    default_agent_model: str = "claude-sonnet-4-6"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    rag_top_k: int = 5
    rag_min_similarity: float = 0.6
    history_limit: int = 20
    llm_max_retries: int = 3
    llm_timeout_seconds: int = 30

    # --- Pool de conexiones a Postgres ---
    db_pool_min_size: int = 2
    db_pool_max_size: int = 10

    # --- Cleanup job ---
    # Intervalo entre ciclos de cierre de conversaciones abandonadas (segundos).
    # 900 = 15 minutos. Overrideable vía CLEANUP_INTERVAL_SECONDS en entorno.
    cleanup_interval_seconds: int = 900

    # --- Intent classifier (Sprint 7+) ---
    # Confidence mínima para usar el AOP seleccionado. Por debajo, se usa 'default'.
    intent_min_confidence: float = 0.60
    # Confidence mínima para CAMBIAR de AOP cuando ya hay uno activo del turno anterior.
    # Histéresis anti-flapping: por debajo de esto, la continuidad gana y se mantiene el
    # AOP previo (salvo que se venga de 'default', donde basta intent_min_confidence).
    intent_switch_threshold: float = 0.70
    # Modelo para el clasificador de intent. Haiku: rápido y barato para clasificación.
    intent_classifier_model: str = "claude-haiku-4-5-20251001"
    # Modelo para reescribir el mensaje al cliente tras aprobar/rechazar L3.
    # Haiku: barato/rápido para una frase de confirmación.
    reply_model: str = "claude-haiku-4-5-20251001"

    # --- Rate limiting (webhooks inbound) ---
    # Requests por minuto por tenant. Cubre ~50K tickets/día con headroom para bursts.
    # Override per-tenant: tenant_configurations.extra.rate_limits.tenant_per_minute
    rate_limit_tenant_per_minute: int = 300
    # Requests por minuto por end_customer. Frena spam sostenido sin bloquear reintentos.
    # Override per-tenant: tenant_configurations.extra.rate_limits.customer_per_minute
    rate_limit_customer_per_minute: int = 30

    # --- Budget diario por tenant ---
    # Presupuesto máximo de gasto LLM por día (USD). Bloquea el grafo si se supera.
    # Override per-tenant: tenant_configurations.extra.budget_usd_daily
    budget_usd_daily: float = 10.0

    # --- Message cap por conversación ---
    # Mensajes inbound máximos por conversación antes de escalar automáticamente.
    # Override per-tenant: tenant_configurations.extra.max_inbound_messages
    max_inbound_messages_per_conversation: int = 50

    @field_validator("rag_min_similarity")
    @classmethod
    def _validate_similarity(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("rag_min_similarity debe estar en [0, 1]")
        return v

    @field_validator("embedding_dimensions")
    @classmethod
    def _validate_embedding_dims(cls, v: int) -> int:
        # El schema de Supabase usa vector(1536). Cambiar ambos a la vez.
        if v != 1536:
            raise ValueError(
                "embedding_dimensions debe ser 1536 "
                "— el schema de Supabase está fijado a ese tamaño"
            )
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton de Settings. Usar siempre esta función, nunca instanciar Settings() directo."""
    return Settings()  # type: ignore[call-arg]
