"""Configuración global de la API.

Cargada una sola vez por proceso vía `get_settings()` (lru_cache).
Todas las variables sensibles llegan por entorno; nada hardcodeado.
"""

import logging
from functools import lru_cache
from typing import Literal, Self

from apps.api.integrations.model_capabilities import (
    MODEL_CAPABILITIES,
    Effort,
    ThinkingMode,
    ThinkingSettings,
    UnsupportedModelSetting,
    thinking_settings,
)
from pydantic import Field, HttpUrl, PostgresDsn, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

AppEnv = Literal["development", "staging", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]

# Tope de una llamada a Claude, reintentos y esperas incluidos. Por debajo del lease de
# `inbound_jobs`: un turno colgado en el LLM no debe dejar que otro worker retome el job.
LLM_CALL_BUDGET_SECONDS = 90.0


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

    # --- Transcripción de notas de voz de WhatsApp (Sprint 2, PR-7; ADR 0011) ---
    # Sin proveedor no se transcribe: el comprador recibe un mensaje fijo pidiéndole que
    # escriba. El proveedor definitivo sale del mini-benchmark de C0 (ADR 0011).
    transcription_provider: str | None = None  # "openai"
    transcription_model: str = "gpt-4o-transcribe"
    transcription_max_seconds: int = 300
    transcription_cost_per_minute_usd: float = 0.006

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
    # Destinatario de las alertas operativas (p. ej. caída del proveedor LLM). Sin valor,
    # la alerta solo queda en logs (error) y se avisa de que no hay a quién mandarla.
    alert_email_to: str | None = None

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
    # Los modelos de LLM viven en `ModelRegistry` / `get_models()`.
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    rag_top_k: int = 20
    # 0.0 = sin umbral: text-embedding-3-small da 0,5-0,65 al fragmento correcto (#410).
    rag_min_similarity: float = 0.0
    # Mensajes del cliente (los últimos) que forman la consulta del RAG.
    rag_query_messages: int = 3
    history_limit: int = 20
    # Intentos por llamada y tope de cada intento; el total lo acota LLM_CALL_BUDGET_SECONDS.
    llm_max_retries: int = 3
    llm_timeout_seconds: int = 30

    # Tope de gasto diario del simulador (USD, últimas 24 h, corridas terminadas). Vale
    # para el panel y para `run_simulator`: el saldo de Anthropic de staging se agotó dos
    # veces por corridas sin tope (s84, s85). Subirlo por variable de entorno a propósito.
    simulator_daily_cap_usd_tenant: float = 2.0
    simulator_daily_cap_usd_global: float = 5.0

    # --- Pool de conexiones a Postgres ---
    db_pool_min_size: int = 2
    db_pool_max_size: int = 10

    # --- Cleanup job ---
    # Intervalo entre ciclos de cierre de conversaciones abandonadas (segundos).
    # 900 = 15 minutos. Overrideable vía CLEANUP_INTERVAL_SECONDS en entorno.
    cleanup_interval_seconds: int = 900

    # --- Worker de turnos inbound (cola `inbound_jobs`, #260) ---
    # Turnos concurrentes por instancia (conversaciones distintas; la misma conversación
    # nunca corre en paralelo). Sondeo de respaldo y lease con heartbeat, en segundos.
    inbound_worker_concurrency: int = 2
    inbound_worker_poll_seconds: float = 5.0
    inbound_worker_lease_seconds: int = 120

    # --- Intent classifier (Sprint 7+) ---
    # Confidence mínima para usar el AOP seleccionado. Por debajo, se usa 'default'.
    intent_min_confidence: float = 0.60
    # Confidence mínima para CAMBIAR de AOP cuando ya hay uno activo del turno anterior.
    # Histéresis anti-flapping: por debajo de esto, la continuidad gana y se mantiene el
    # AOP previo (salvo que se venga de 'default', donde basta intent_min_confidence).
    intent_switch_threshold: float = 0.70
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

    @model_validator(mode="after")
    def _validate_lease_covers_llm_call(self) -> Self:
        if self.inbound_worker_lease_seconds <= LLM_CALL_BUDGET_SECONDS:
            raise ValueError(
                f"inbound_worker_lease_seconds ({self.inbound_worker_lease_seconds}) debe "
                f"superar el presupuesto de una llamada al LLM ({LLM_CALL_BUDGET_SECONDS:.0f} s)"
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton de Settings. Usar siempre esta función, nunca instanciar Settings() directo."""
    return Settings()  # type: ignore[call-arg]


class ModelRegistry(BaseSettings):
    """Único registro de modelos de LLM, uno por rol (#344).

    Cada campo se sobrescribe con la variable de entorno del mismo nombre en
    mayúsculas. No tiene campos obligatorios, así que se carga sin el resto de
    `Settings` (simulador, evals y tests). Todo ID que se añada aquí necesita su
    fila en `integrations/pricing.py` y en `integrations/model_capabilities.py`: los
    tests y el arranque de la API lo exigen.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Agente: modelo por defecto cuando el tenant no fija el suyo
    # (`tenant_configurations.agent_model`).
    default_agent_model: str = "claude-sonnet-4-6"
    # Turnos conversacionales puros (sin skills ni herramientas): Haiku basta y recorta
    # latencia/costo. Ver _select_reason_model en agents/nodes/reason.py.
    simple_turn_model: str = "claude-haiku-4-5-20251001"
    # Clasificador de intent: rápido y barato.
    intent_classifier_model: str = "claude-haiku-4-5-20251001"
    # Supervisor del loop ReAct: L1/L2 y L3 (acciones destructivas, con approval).
    supervisor_model_l1_l2: str = "claude-sonnet-4-6"
    supervisor_model_l3: str = "claude-opus-4-7"
    # Mensaje al cliente tras aprobar/rechazar una L3.
    reply_model: str = "claude-haiku-4-5-20251001"
    # Simulador: cliente sintético y jueces (Sonnet por defecto, Opus en calibraciones).
    simulator_model: str = "claude-haiku-4-5-20251001"
    judge_sonnet_model: str = "claude-sonnet-4-6"
    judge_opus_model: str = "claude-opus-4-7"
    # Slow agent: primer análisis. Si duda, escala al juez Opus (`judge_opus_model`).
    slow_agent_model: str = "claude-sonnet-4-6"

    # Thinking y esfuerzo por rol, en JSON por entorno, p. ej.
    # EFFORT_BY_ROLE='{"intent_classifier_model": "low"}'. Un rol sin entrada usa lo que
    # fija su modelo en `integrations/model_capabilities.py`: nada nuevo en los modelos
    # actuales; en los 5.5, thinking adaptive y esfuerzo `medium` explícitos.
    thinking_by_role: dict[str, ThinkingMode] = Field(default_factory=dict)
    effort_by_role: dict[str, Effort] = Field(default_factory=dict)

    def by_role(self) -> dict[str, str]:
        """Rol -> ID de modelo, para el test y el chequeo de precios del arranque."""
        return {
            name: getattr(self, name)
            for name, field in type(self).model_fields.items()
            if field.annotation is str
        }

    def thinking(self, role: str, *, model: str | None = None) -> ThinkingSettings:
        """Thinking y esfuerzo del rol para `model` (por defecto, el modelo del rol).

        `model` cubre el modelo que fija un tenant para el agente. El ajuste del rol se valida
        al cargar contra el modelo del rol, no contra el del tenant: si este lo rechazaría con
        un 400, la petición va con el ajuste por defecto de su modelo y queda un error, en vez
        de escalar todos los turnos del tenant."""
        mode = self.thinking_by_role.get(role)
        effort = self.effort_by_role.get(role)
        if model is None:
            return thinking_settings(getattr(self, role), mode=mode, effort=effort)
        try:
            return thinking_settings(model, mode=mode, effort=effort)
        except UnsupportedModelSetting as exc:
            logger.error(
                "model_setting_degraded role=%s model=%s thinking=%s effort=%s: %s; "
                "va con el ajuste por defecto del modelo",
                role,
                model,
                mode,
                effort,
                exc,
                extra={"role": role, "model": model},
            )
            return thinking_settings(model, mode=None, effort=None)

    def agent_model_for(self, tenant_model: str) -> str:
        """El modelo del agente para un tenant (`tenant_configurations.agent_model`, que se
        escribe por SQL). Un ID sin fila de capacidades no corre: cambiaría la petición y
        se cobraría a la tarifa máxima. Va el modelo por defecto y queda un error."""
        if tenant_model in MODEL_CAPABILITIES:
            return tenant_model
        logger.error(
            "tenant_agent_model_unsupported model=%s: sin fila en "
            "integrations/model_capabilities.py; corre %s",
            tenant_model,
            self.default_agent_model,
            extra={"model": tenant_model},
        )
        return self.default_agent_model

    @model_validator(mode="after")
    def _validate_role_settings(self) -> Self:
        """Falla al cargar si un rol usa un modelo sin fila en la tabla de capacidades (la
        petición cambiaría y se cobraría a la tarifa máxima) o pide algo que su modelo
        rechazaría con un 400. En Cloud Run, la revisión no arranca y no se promueve."""
        roles = self.by_role()
        unknown_models = {
            role: model for role, model in roles.items() if model not in MODEL_CAPABILITIES
        }
        if unknown_models:
            listed = ", ".join(f"{role}={model}" for role, model in sorted(unknown_models.items()))
            raise ValueError(
                f"modelos sin fila en integrations/model_capabilities.py: {listed}. "
                f"IDs válidos: {sorted(MODEL_CAPABILITIES)}"
            )
        unknown = (set(self.thinking_by_role) | set(self.effort_by_role)) - set(roles)
        if unknown:
            raise ValueError(f"roles desconocidos en thinking/effort_by_role: {sorted(unknown)}")
        for role in roles:
            self.thinking(role)
        return self


@lru_cache(maxsize=1)
def get_models() -> ModelRegistry:
    return ModelRegistry()
