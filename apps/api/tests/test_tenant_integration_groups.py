"""Tarjeta de integraciones del cliente (#288): se deriva de `tenant_integrations`.

Cubre el SQL (filtros y columnas en lista blanca), el agrupado por kind y el contrato
de `GET /tenants/me/config` (sin credenciales, sin `active_channels`).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from apps.api.db import queries
from apps.api.db.models import IntegrationGroup, IntegrationSummary
from apps.api.services.tenants import list_tenant_integration_groups
from apps.api.tests.conftest import TENANT_ID, make_tenant_configuration
from apps.api.tests.test_tenants import _make_app, _make_jwt
from fastapi.testclient import TestClient

OTHER_TENANT_ID = UUID("99999999-9999-9999-9999-999999999999")


class _FakeConn:
    """Conexión falsa que devuelve filas por tenant y registra el SQL ejecutado."""

    def __init__(self, rows_by_tenant: dict[UUID, list[dict[str, Any]]]) -> None:
        self.rows_by_tenant = rows_by_tenant
        self.queries: list[str] = []

    async def fetch(self, sql: str, tenant_id: UUID) -> list[dict[str, Any]]:
        self.queries.append(sql)
        return self.rows_by_tenant.get(tenant_id, [])


def _row(kind: str, provider: str, primary: bool = False) -> dict[str, Any]:
    return {"kind": kind, "provider": provider, "is_primary_for_kind": primary}


class TestListActiveIntegrationSummaries:
    async def test_query_filters_active_not_deleted_and_scopes_tenant(self) -> None:
        conn = _FakeConn({TENANT_ID: [_row("channel", "whatsapp", True)]})

        result = await queries.list_active_integration_summaries(conn, tenant_id=TENANT_ID)  # type: ignore[arg-type]

        assert result == [IntegrationSummary(kind="channel", provider="whatsapp", is_primary=True)]
        sql = " ".join(conn.queries[0].lower().split())
        assert "tenant_id = $1" in sql
        assert "deleted_at is null" in sql
        assert "is_active = true" in sql

    async def test_query_never_selects_secrets(self) -> None:
        conn = _FakeConn({})

        await queries.list_active_integration_summaries(conn, tenant_id=TENANT_ID)  # type: ignore[arg-type]

        select_clause = conn.queries[0].lower().split("from")[0]
        assert "credentials" not in select_clause
        assert "config" not in select_clause
        assert "select *" not in select_clause

    async def test_other_tenant_rows_do_not_leak(self) -> None:
        conn = _FakeConn(
            {
                TENANT_ID: [_row("channel", "whatsapp")],
                OTHER_TENANT_ID: [_row("helpdesk", "gorgias")],
            }
        )

        result = await queries.list_active_integration_summaries(conn, tenant_id=TENANT_ID)  # type: ignore[arg-type]

        assert [s.provider for s in result] == ["whatsapp"]


class TestListTenantIntegrationGroups:
    async def test_groups_channel_helpdesk_and_commerce(self, monkeypatch: pytest.MonkeyPatch) -> None:
        summaries = [
            IntegrationSummary(kind="commerce", provider="shopify", is_primary=True),
            IntegrationSummary(kind="helpdesk", provider="zendesk", is_primary=True),
            IntegrationSummary(kind="channel", provider="whatsapp", is_primary=True),
        ]
        monkeypatch.setattr(
            "apps.api.services.tenants.list_active_integration_summaries",
            AsyncMock(return_value=summaries),
        )

        groups = await list_tenant_integration_groups(AsyncMock(), TENANT_ID)

        assert [g.kind for g in groups] == ["channel", "helpdesk", "commerce"]
        assert groups[0].integrations[0].provider == "whatsapp"
        assert groups[1].integrations[0].provider == "zendesk"
        assert groups[2].integrations[0].is_primary is True

    async def test_no_integrations_gives_empty_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "apps.api.services.tenants.list_active_integration_summaries",
            AsyncMock(return_value=[]),
        )

        assert await list_tenant_integration_groups(AsyncMock(), TENANT_ID) == []

    async def test_several_providers_in_one_kind_stay_together(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        summaries = [
            IntegrationSummary(kind="channel", provider="whatsapp", is_primary=True),
            IntegrationSummary(kind="channel", provider="chat", is_primary=False),
        ]
        monkeypatch.setattr(
            "apps.api.services.tenants.list_active_integration_summaries",
            AsyncMock(return_value=summaries),
        )

        groups = await list_tenant_integration_groups(AsyncMock(), TENANT_ID)

        assert len(groups) == 1
        assert [i.provider for i in groups[0].integrations] == ["whatsapp", "chat"]

    async def test_llm_kind_is_internal_and_hidden(self, monkeypatch: pytest.MonkeyPatch) -> None:
        summaries = [IntegrationSummary(kind="llm", provider="anthropic", is_primary=True)]
        monkeypatch.setattr(
            "apps.api.services.tenants.list_active_integration_summaries",
            AsyncMock(return_value=summaries),
        )

        assert await list_tenant_integration_groups(AsyncMock(), TENANT_ID) == []


class TestConfigEndpointIntegrations:
    def test_response_has_groups_and_no_active_channels_nor_secrets(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _fake_config(conn: Any, tenant_id: UUID) -> Any:
            return make_tenant_configuration()

        groups = [
            IntegrationGroup(
                kind="channel",
                integrations=[IntegrationSummary(kind="channel", provider="whatsapp", is_primary=True)],
            )
        ]
        monkeypatch.setattr("apps.api.routers.tenants.get_tenant_config", _fake_config)
        monkeypatch.setattr(
            "apps.api.routers.tenants.list_tenant_integration_groups",
            AsyncMock(return_value=groups),
        )
        client = TestClient(_make_app(monkeypatch))

        resp = client.get("/tenants/me/config", headers={"Authorization": f"Bearer {_make_jwt()}"})

        assert resp.status_code == 200
        body = resp.json()
        assert "active_channels" not in body
        assert body["integrations"] == [
            {"kind": "channel", "integrations": [{"kind": "channel", "provider": "whatsapp", "is_primary": True}]}
        ]
        raw = resp.text.lower()
        assert "credentials" not in raw
        assert "token" not in raw

    def test_empty_integrations_is_empty_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _fake_config(conn: Any, tenant_id: UUID) -> Any:
            return make_tenant_configuration()

        monkeypatch.setattr("apps.api.routers.tenants.get_tenant_config", _fake_config)
        monkeypatch.setattr(
            "apps.api.routers.tenants.list_tenant_integration_groups", AsyncMock(return_value=[])
        )
        client = TestClient(_make_app(monkeypatch))

        resp = client.get("/tenants/me/config", headers={"Authorization": f"Bearer {_make_jwt()}"})

        assert resp.json()["integrations"] == []
