"""`upsert_integration` contra un Postgres real: solo una integración primaria por kind.

Solo corre con `AUYAN_TEST_DATABASE_URL` (ver `pg_support`).
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.db.client import tenant_scope
from apps.api.db.queries import upsert_integration
from apps.api.tests.pg_support import migrated_pool, requires_pg

pytestmark = requires_pg


async def test_connecting_woocommerce_after_shopify_makes_it_the_only_primary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant = uuid.uuid4()
    async with migrated_pool(monkeypatch) as pool:
        await pool.execute(
            "insert into tenants (id, slug, name) values ($1, 'tienda', 'Tienda')", tenant
        )
        async with tenant_scope(tenant) as conn:
            for provider in ("shopify", "woocommerce"):
                await upsert_integration(
                    conn,
                    tenant_id=tenant,
                    kind="commerce",
                    provider=provider,
                    credentials_encrypted=b"x",
                    config={},
                    is_primary_for_kind=True,
                )
            rows = await conn.fetch(
                "select provider, is_primary_for_kind from tenant_integrations "
                "where tenant_id = $1 order by provider",
                tenant,
            )

    assert [(r["provider"], r["is_primary_for_kind"]) for r in rows] == [
        ("shopify", False),
        ("woocommerce", True),
    ]
