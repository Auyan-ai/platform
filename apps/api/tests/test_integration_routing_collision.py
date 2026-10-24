"""H5: el routing cross-tenant de webhooks de helpdesk falla cerrado ante colisión.

Si un identificador externo (account_id / subdomain / domain) apunta a más de una
integración activa, las funciones get_integration_by_* NO deben adivinar el tenant:
lanzan ConflictError. Defensa en profundidad junto al índice único parcial en DB.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from apps.api.core.errors import ConflictError
from apps.api.db.models import TenantIntegration
from apps.api.db.queries import (
    get_integration_by_chatwoot_account,
    get_integration_by_gorgias_domain,
    get_integration_by_zendesk_subdomain,
)

TENANT_A = UUID("11111111-1111-1111-1111-111111111111")
TENANT_B = UUID("22222222-2222-2222-2222-222222222222")
INTEGRATION_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
NOW = datetime(2026, 6, 3, 12, 0, 0, tzinfo=UTC)


def _integration_row(*, tenant_id: UUID, provider: str, **config: str) -> MagicMock:
    """Simula un asyncpg.Record de tenant_integrations."""
    base = {
        "id": INTEGRATION_ID,
        "tenant_id": tenant_id,
        "kind": "helpdesk",
        "provider": provider,
        "config": dict(config),
        "is_active": True,
        "is_primary_for_kind": True,
        "enabled_at": NOW,
        "enabled_by": None,
        "created_at": NOW,
        "updated_at": NOW,
    }
    row = MagicMock()
    row.__getitem__ = lambda _self, k: base[k]
    row.keys = lambda: base.keys()
    return row


def _conn_returning(rows: list[MagicMock]) -> MagicMock:
    conn = MagicMock()
    conn.fetch = AsyncMock(return_value=rows)
    return conn


# Cada caso: (función, kwargs, provider, config_key, valor)
_CASES = [
    (
        get_integration_by_chatwoot_account,
        {"account_id": "167723"},
        "chatwoot",
        "account_id",
        "167723",
    ),
    (get_integration_by_zendesk_subdomain, {"subdomain": "acme"}, "zendesk", "subdomain", "acme"),
    (
        get_integration_by_gorgias_domain,
        {"domain": "acme.gorgias.com"},
        "gorgias",
        "domain",
        "acme.gorgias.com",
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("fn", "kwargs", "provider", "key", "value"), _CASES)
async def test_collision_fails_closed(fn, kwargs, provider, key, value) -> None:
    """Dos tenants con el mismo identificador → ConflictError, no adivina."""
    rows = [
        _integration_row(tenant_id=TENANT_A, provider=provider, **{key: value}),
        _integration_row(tenant_id=TENANT_B, provider=provider, **{key: value}),
    ]
    conn = _conn_returning(rows)

    with pytest.raises(ConflictError) as exc:
        await fn(conn, **kwargs)

    assert exc.value.code == "integration_routing_collision"


@pytest.mark.asyncio
@pytest.mark.parametrize(("fn", "kwargs", "provider", "key", "value"), _CASES)
async def test_single_match_resolves(fn, kwargs, provider, key, value) -> None:
    """Un solo match → devuelve la integración de ese tenant."""
    rows = [_integration_row(tenant_id=TENANT_A, provider=provider, **{key: value})]
    conn = _conn_returning(rows)

    result = await fn(conn, **kwargs)

    assert isinstance(result, TenantIntegration)
    assert result.tenant_id == TENANT_A


@pytest.mark.asyncio
@pytest.mark.parametrize(("fn", "kwargs", "provider", "key", "value"), _CASES)
async def test_no_match_returns_none(fn, kwargs, provider, key, value) -> None:
    """Ningún match → None (el caller traduce a 404)."""
    conn = _conn_returning([])

    result = await fn(conn, **kwargs)

    assert result is None
