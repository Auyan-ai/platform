"""Renombrado de la demo con el nombre oficial de la tienda (issue #423)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

import pytest
from apps.api.services.site_ingestion import demo_name
from apps.api.services.site_ingestion.demo_name import rename_demo_to_store_name


class FakeTenants:
    """Tabla `tenants` en memoria con las dos sentencias que usa el renombrado."""

    def __init__(self, rows: dict[UUID, dict[str, Any]]) -> None:
        self.rows = rows

    async def fetchrow(self, query: str, tenant_id: UUID) -> dict[str, Any] | None:
        row = self.rows.get(tenant_id)
        if row is None or row["origin"] != "demo" or row.get("deleted_at"):
            return None
        return {"name": row["name"], "demo_source_url": row["demo_source_url"]}

    async def fetchval(self, query: str, tenant_id: UUID, new: str, expected: str) -> UUID | None:
        row = self.rows[tenant_id]
        if row["name"] != expected:
            return None
        row["name"] = new
        return tenant_id


def _install(monkeypatch: pytest.MonkeyPatch, rows: dict[UUID, dict[str, Any]]) -> None:
    conn = FakeTenants(rows)

    @asynccontextmanager
    async def fake_connection() -> AsyncIterator[FakeTenants]:
        yield conn

    monkeypatch.setattr(demo_name, "bootstrap_connection", fake_connection)


def _tenant(
    name: str, origin: str = "demo", url: str | None = "https://thinkingmu.com"
) -> dict[str, Any]:
    return {"name": name, "origin": origin, "demo_source_url": url}


async def test_demo_with_domain_name_takes_the_official_store_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tid = uuid4()
    rows = {tid: _tenant("Thinkingmu")}
    _install(monkeypatch, rows)

    assert await rename_demo_to_store_name(tid, "Thinking MU") is True
    assert rows[tid]["name"] == "Thinking MU"
    assert await rename_demo_to_store_name(tid, "Thinking MU") is False


async def test_demo_with_a_hand_edited_name_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    tid = uuid4()
    rows = {tid: _tenant("Mi demo para Laura")}
    _install(monkeypatch, rows)

    assert await rename_demo_to_store_name(tid, "Thinking MU") is False
    assert rows[tid]["name"] == "Mi demo para Laura"


async def test_client_tenant_is_never_renamed(monkeypatch: pytest.MonkeyPatch) -> None:
    tid = uuid4()
    rows = {tid: _tenant("Thinkingmu", origin="client", url=None)}
    _install(monkeypatch, rows)

    assert await rename_demo_to_store_name(tid, "Thinking MU") is False
    assert rows[tid]["name"] == "Thinkingmu"


@pytest.mark.parametrize("store_name", [None, "", "   "])
async def test_missing_store_name_changes_nothing(
    monkeypatch: pytest.MonkeyPatch, store_name: str | None
) -> None:
    tid = uuid4()
    rows = {tid: _tenant("Thinkingmu")}
    _install(monkeypatch, rows)

    assert await rename_demo_to_store_name(tid, store_name) is False
    assert rows[tid]["name"] == "Thinkingmu"


async def test_whitespace_and_length_of_the_official_name_are_normalised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tid = uuid4()
    rows = {tid: _tenant("Thinkingmu")}
    _install(monkeypatch, rows)

    await rename_demo_to_store_name(tid, "  Thinking \n MU  " + "x" * 300)

    assert rows[tid]["name"].startswith("Thinking MU xxx")
    assert len(rows[tid]["name"]) == demo_name.MAX_STORE_NAME_LENGTH
