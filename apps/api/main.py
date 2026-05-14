"""Entry point de la API.

Lifespan ordenado:
    startup:
        1. Cargar settings (falla en boot si falta cualquier var requerida).
        2. Inicializar pool de Postgres.
        3. Construir clientes LLM (Anthropic, OpenAI) y Langfuse.
        4. Compilar el grafo + crear AgentService.
        5. Exponer en app.state.
    shutdown:
        1. Flush de Langfuse (manda los traces pendientes).
        2. Cerrar pool de Postgres.

Para correr localmente:
    cd apps/api
    poetry run uvicorn apps.api.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.agents.dependencies import AgentDependencies
from apps.api.agents.graph import build_graph
from apps.api.agents.service import AgentService
from apps.api.core.config import get_settings
from apps.api.core.errors import register_exception_handlers
from apps.api.db.client import close_pool, init_pool
from apps.api.integrations.anthropic_client import build_anthropic_client
from apps.api.integrations.langfuse_client import build_langfuse_client
from apps.api.integrations.openai_embeddings import build_openai_client
from apps.api.routers.conversations import router as conversations_router
from apps.api.routers.escalations import router as escalations_router
from apps.api.routers.tenants import router as tenants_router
from apps.api.routers.webhooks import router as webhooks_router

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    logger.info("starting auyan-api env=%s", settings.app_env)

    await init_pool()
    logger.info("db_pool_initialized")

    anthropic = build_anthropic_client(settings.anthropic_api_key.get_secret_value())
    openai = build_openai_client(settings.openai_api_key.get_secret_value())
    langfuse = build_langfuse_client(settings)

    deps = AgentDependencies(anthropic=anthropic, openai=openai, settings=settings)
    graph = build_graph(deps)
    service = AgentService(graph=graph, langfuse=langfuse)

    app.state.agent_service = service
    app.state.langfuse = langfuse

    logger.info("agent_service_ready langfuse_enabled=%s", langfuse.is_enabled)

    try:
        yield
    finally:
        logger.info("shutdown_initiated")
        await langfuse.flush()
        await close_pool()
        logger.info("shutdown_complete")


app = FastAPI(title="Auyan API", version="0.1.0", lifespan=lifespan)
register_exception_handlers(app)

_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _settings.allowed_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Tenant-Id"],
)

app.include_router(webhooks_router)
app.include_router(tenants_router)
app.include_router(conversations_router)
app.include_router(escalations_router)


@app.get("/health", tags=["health"])
async def health() -> dict[str, str | bool]:
    settings = get_settings()
    return {"ok": True, "env": settings.app_env}
