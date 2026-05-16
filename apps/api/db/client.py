"""Pool de conexiones asyncpg + tenant scope.

Política de tenancy:
- Nos conectamos con el rol de Supabase (`postgres`) que bypasea RLS.
- La defensa multi-tenant es doble: (1) **toda** query filtra explícitamente por
  `tenant_id`; (2) antes de cualquier query del grafo seteamos el GUC
  `app.tenant_id` vía `tenant_scope(...)`. El helper SQL `public.current_tenant_id()`
  lo lee, y si en algún momento creamos funciones `SECURITY DEFINER` que respeten RLS
  ya tienen el contexto correcto.
- Las queries de bootstrap del webhook (identificar tenant, ver qué conversación es)
  usan `bootstrap_connection()` sin `tenant_scope` porque aún no conocemos el tenant.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING
from uuid import UUID

import asyncpg
from apps.api.core.config import get_settings
from pgvector.asyncpg import register_vector

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

_pool: asyncpg.Pool | None = None


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Hook ejecutado al crear cada conexión nueva del pool."""
    await register_vector(conn)
    # JSONB ↔ dict automático. Sin esto asyncpg devuelve str y hay que parsear a mano.
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )
    await conn.set_type_codec(
        "json",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )


async def init_pool() -> asyncpg.Pool:
    """Inicializa el pool global. Llamar una vez en startup de FastAPI."""
    global _pool
    if _pool is not None:
        return _pool
    settings = get_settings()
    _pool = await asyncpg.create_pool(
        dsn=str(settings.database_url),
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
        init=_init_connection,
    )
    assert _pool is not None  # mypy
    return _pool


async def close_pool() -> None:
    """Cierra el pool global. Llamar en shutdown de FastAPI."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    """Acceso al pool ya inicializado. Lanza si no fue inicializado en startup."""
    if _pool is None:
        raise RuntimeError(
            "DB pool no inicializado. Llamar `await init_pool()` en el startup de FastAPI."
        )
    return _pool


@asynccontextmanager
async def tenant_scope(tenant_id: UUID | str) -> AsyncIterator[asyncpg.Connection]:
    """Adquiere una conexión, abre transacción, setea `app.tenant_id` GUC local.

    Todas las queries del grafo y de cualquier código de negocio multi-tenant
    deben pasar por aquí.

    `set_config(..., is_local=true)` revierte el valor al final de la transacción,
    por eso es seguro reusar conexiones del pool entre requests sin contaminación.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT set_config('app.tenant_id', $1, true)",
                str(tenant_id),
            )
            yield conn


@asynccontextmanager
async def bootstrap_connection() -> AsyncIterator[asyncpg.Connection]:
    """Conexión SIN tenant scope. Sólo para operaciones de bootstrap del webhook.

    Casos válidos:
    - Resolver `tenant_id` desde un dominio/inbox/slug externo.
    - Healthchecks.

    No usar para nada de lectura/escritura de datos de negocio: para eso, `tenant_scope`.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        yield conn
