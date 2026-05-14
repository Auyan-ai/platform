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
    langfuse_public_key: SecretStr = Field(...)
    langfuse_secret_key: SecretStr = Field(...)
    langfuse_host: HttpUrl = Field(default=HttpUrl("https://cloud.langfuse.com"))

    # --- Integrations (opcionales según etapa del proyecto) ---
    postmark_api_token: SecretStr | None = None

    # --- Webhook security ---
    webhook_secret: SecretStr = Field(
        ..., description="HMAC shared secret para validar webhooks entrantes"
    )

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
                "embedding_dimensions debe ser 1536 — el schema de Supabase está fijado a ese tamaño"
            )
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton de Settings. Usar siempre esta función, nunca instanciar Settings() directo."""
    return Settings()  # type: ignore[call-arg]
