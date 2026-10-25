"""Entry point de la API.

Lifespan ordenado:
    startup:
        1. Cargar settings (falla en boot si falta cualquier var requerida).
        2. Inicializar pool de Postgres.
        3. Construir clientes LLM (Anthropic, OpenAI) y observabilidad.
        4. Compilar el grafo + crear AgentService.
        5. Exponer en app.state.
        6. Arrancar jobs de fondo (cleanup, AOP listener, worker de turnos inbound).
    shutdown:
        1. Flush de observabilidad (manda los traces pendientes).
        2. Cerrar pool de Postgres.

Para correr localmente:
    cd apps/api
    poetry run uvicorn apps.api.main:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

# Side-effect import: dispara `@SkillRegistry.register` de cada skill.
# Sin esto, el grafo arranca con el registry vacío y `execute_skill` siempre
# devuelve `unknown_skill`.
import apps.api.skills  # noqa: F401
from apps.api.agents.dependencies import AgentDependencies
from apps.api.agents.graph import build_graph
from apps.api.agents.nodes.handle_error import make_handle_error_node
from apps.api.agents.service import AgentService
from apps.api.core.config import get_models, get_settings
from apps.api.core.errors import UnhandledExceptionMiddleware, register_exception_handlers
from apps.api.core.log_config import configure_logging
from apps.api.db.client import close_pool, init_pool
from apps.api.integrations.anthropic_client import build_anthropic_client
from apps.api.integrations.langfuse_client import build_langfuse_client
from apps.api.integrations.langsmith_client import build_langsmith_client
from apps.api.integrations.observability import ObservabilityClient
from apps.api.integrations.openai_embeddings import build_openai_client
from apps.api.integrations.postmark import build_postmark_adapter
from apps.api.integrations.pricing import check_model_prices
from apps.api.routers.aops import router as aops_router
from apps.api.routers.approvals import router as approvals_router
from apps.api.routers.billing import router as billing_router
from apps.api.routers.conversations import router as conversations_router
from apps.api.routers.escalations import router as escalations_router
from apps.api.routers.oauth_gorgias import router as oauth_gorgias_router
from apps.api.routers.oauth_zendesk import router as oauth_zendesk_router
from apps.api.routers.proposals import router as proposals_router
from apps.api.routers.reasoning import router as reasoning_router
from apps.api.routers.returns_policy import router as returns_policy_router
from apps.api.routers.simulations import router as simulations_router
from apps.api.routers.tenants import router as tenants_router
from apps.api.routers.tool_permissions import router as tool_permissions_router
from apps.api.routers.users import router as users_router
from apps.api.routers.webhooks import router as webhooks_router
from apps.api.routers.webhooks_chatwoot import router as webhooks_chatwoot_router
from apps.api.routers.webhooks_gorgias import router as webhooks_gorgias_router
from apps.api.routers.webhooks_zendesk import router as webhooks_zendesk_router
from apps.api.routers.webhooks_zernio import router as webhooks_zernio_router
from apps.api.services.aop_listener import AopCacheListener
from apps.api.services.approval_execution import recover_stale_executions
from apps.api.services.audit import AuditLogger
from apps.api.services.cleanup import expire_demo_tenants, run_abandoned_cleanup
from apps.api.services.email_sender import EmailSender
from apps.api.services.inbound_worker import InboundWorker
from apps.api.services.llm_alert import LLMProviderAlerter, configure_alerter
from apps.api.services.reasoning import ReasoningTracker
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)


async def _cleanup_loop(interval_seconds: int) -> None:
    """Cada `interval_seconds` corre `run_abandoned_cleanup`, caduca las demos y reconcilia
    las aprobaciones L3 colgadas en `executing` (#376). Se cancela en shutdown."""
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            results = await run_abandoned_cleanup()
            if results:
                logger.info("cleanup_cycle_done results=%s", results)
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("cleanup_job_error")
        try:
            await expire_demo_tenants()
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("demo_expiry_job_error")
        try:
            recovered = await recover_stale_executions()
            if recovered:
                logger.warning("approval_executions_recovered count=%d", recovered)
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("approval_recovery_job_error")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    # JSON con `severity` en Cloud Run (alertas por severidad + campos `extra`).
    configure_logging(settings.log_level)

    logger.info("starting auyan-api env=%s", settings.app_env)
    check_model_prices(get_models().by_role())

    await init_pool()
    logger.info("db_pool_initialized")

    anthropic = build_anthropic_client(settings.anthropic_api_key.get_secret_value())
    openai = build_openai_client(settings.openai_api_key.get_secret_value())
    langsmith = build_langsmith_client(settings)
    langfuse = build_langfuse_client(settings)
    observability = ObservabilityClient(primary=langsmith, mirror=langfuse)

    reasoning_tracker = ReasoningTracker()
    audit_logger = AuditLogger()
    email_sender = EmailSender(build_postmark_adapter(settings))
    app.state.email_sender = email_sender
    configure_alerter(LLMProviderAlerter(email_sender, settings.alert_email_to))
    deps = AgentDependencies(
        anthropic=anthropic,
        openai=openai,
        settings=settings,
        reasoning_tracker=reasoning_tracker,
        audit_logger=audit_logger,
        observability=observability,
    )
    graph = build_graph(deps)
    service = AgentService(
        graph=graph,
        observability=observability,
        handle_error=make_handle_error_node(deps),
    )

    app.state.agent_service = service
    app.state.agent_deps = deps
    app.state.observability = observability
    app.state.langsmith = langsmith
    app.state.langfuse = langfuse

    logger.info(
        "agent_service_ready langsmith_enabled=%s langfuse_mirror_enabled=%s",
        observability.primary_enabled,
        observability.mirror_enabled,
    )

    cleanup_task = asyncio.create_task(
        _cleanup_loop(settings.cleanup_interval_seconds),
        name="abandoned-conversation-cleanup",
    )
    logger.info("cleanup_job_started interval_seconds=%d", settings.cleanup_interval_seconds)

    aop_listener = AopCacheListener()
    await aop_listener.start(str(settings.database_url))

    # Turnos inbound de helpdesk: los webhooks encolan, este worker corre el grafo.
    # Al arrancar también recoge jobs pendientes o huérfanos de una instancia anterior.
    inbound_worker = InboundWorker(
        agent_service=service,
        settings=settings,
        concurrency=settings.inbound_worker_concurrency,
        poll_interval_seconds=settings.inbound_worker_poll_seconds,
        lease_seconds=settings.inbound_worker_lease_seconds,
    )
    inbound_worker.start()
    app.state.inbound_worker = inbound_worker

    try:
        yield
    finally:
        logger.info("shutdown_initiated")
        # Primero el worker: libera el job en curso mientras el pool sigue vivo.
        await inbound_worker.stop()
        cleanup_task.cancel()
        await asyncio.gather(cleanup_task, return_exceptions=True)
        await aop_listener.stop()
        await observability.flush()
        await close_pool()
        logger.info("shutdown_complete")


app = FastAPI(title="Auyan API", version="0.1.0", lifespan=lifespan)
register_exception_handlers(app)

# Middleware order matters (Starlette aplica last-added como outermost):
#   1. UnhandledExceptionMiddleware (añadido PRIMERO → innermost): captura
#      cualquier Exception no controlada y devuelve JSONResponse 500.
#   2. CORSMiddleware (añadido SEGUNDO → outermost): envuelve TODO,
#      incluyendo las responses 500 del middleware anterior.
#
# Sin este orden, una excepción Python no controlada genera un 500 sin
# header Access-Control-Allow-Origin → browser lo bloquea como "CORS not
# allowed", enmascarando el bug real. Ver core/errors.py docstring de
# UnhandledExceptionMiddleware para el racional completo.
app.add_middleware(UnhandledExceptionMiddleware)

_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _settings.allowed_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Tenant-Id"],
)

app.include_router(webhooks_router)
app.include_router(webhooks_chatwoot_router)
app.include_router(webhooks_zendesk_router)
app.include_router(webhooks_gorgias_router)
app.include_router(webhooks_zernio_router)
app.include_router(oauth_zendesk_router)
app.include_router(oauth_gorgias_router)
app.include_router(users_router)
app.include_router(tenants_router)
app.include_router(conversations_router)
app.include_router(escalations_router)
app.include_router(aops_router)
app.include_router(proposals_router)
app.include_router(reasoning_router)
app.include_router(approvals_router)
app.include_router(tool_permissions_router)
app.include_router(returns_policy_router)
app.include_router(simulations_router)
app.include_router(billing_router)


@app.get("/health", tags=["health"])
async def health() -> dict[str, str | bool]:
    settings = get_settings()
    data: dict[str, str | bool] = {"ok": True, "env": settings.app_env}
    observability = getattr(app.state, "observability", None)
    if observability is not None:
        data.update(
            {
                "langsmith_enabled": bool(observability.primary_enabled),
                "langsmith_project": str(observability.primary_project),
                "langfuse_mirror_enabled": bool(observability.mirror_enabled),
            }
        )
    return data


@app.get("/health/ready", tags=["health"])
async def readiness() -> dict[str, str | bool]:
    """Readiness probe — verifies DB pool is reachable.

    Returns 200 if the database responds to a simple query.
    Returns 503 if the pool is not initialized or the query fails.
    """
    from apps.api.db.client import get_pool

    settings = get_settings()
    checks: dict[str, str | bool] = {"env": settings.app_env}

    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            result = await conn.fetchval("SELECT 1")
            checks["db"] = result == 1
    except Exception as exc:
        logger.warning("readiness_check_failed component=db error=%s", exc)
        checks["db"] = False

    checks["ok"] = all(v is True for k, v in checks.items() if k != "env")
    if not checks["ok"]:
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=503, content=checks)  # type: ignore[return-value]
    return checks
