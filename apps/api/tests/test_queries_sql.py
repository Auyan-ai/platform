"""Guards de SQL que los mocks no detectan (errores de tipos al preparar la query)."""

from __future__ import annotations

import inspect
import re

import pytest
from apps.api.db import queries


def test_upsert_tool_permission_casts_enabled_by_to_uuid() -> None:
    """$6 (enabled_by) se usa en VALUES y dentro de un CASE … ELSE NULL: sin cast
    explícito Postgres deduce `text` en uno y `uuid` en otro y rechaza la query
    SIEMPRE (AmbiguousParameterError). Rompía provision_tenant, el PUT de permisos
    y seed_canonical_aops."""
    sql = inspect.getsource(queries.upsert_tool_permission)
    assert "$6," not in sql.replace("$6::uuid,", "")
    assert "THEN $6::uuid ELSE NULL" in sql


def test_insert_tool_permission_if_missing_never_overwrites() -> None:
    """La siembra de permisos canónicos no pisa filas existentes (ni con --update)."""
    sql = inspect.getsource(queries.insert_tool_permission_if_missing)
    assert "ON CONFLICT (tenant_id, skill_slug) DO NOTHING" in sql
    assert "DO UPDATE" not in sql
    assert "$5::uuid)" in sql


_CONVERSATION_ROWS = re.compile(
    r"\bFROM (conversations|escalations|pending_approvals|messages|intent_classifier_runs)\b"
    r"(?! sim\b)",
    re.I,
)


@pytest.mark.parametrize(
    "reader",
    [
        queries.list_pending_approvals,
        queries.list_admin_review_queue,
        queries.list_escalations,
        queries.get_tenant_metrics,
        queries.get_tenant_resolution_series,
        queries.get_tenant_insights,
        queries.build_weekly_report_metrics,
    ],
)
def test_client_views_exclude_simulated_conversations(reader: object) -> None:
    """#348: la cola de aprobaciones, el inbox, las métricas y el informe del cliente no
    cuentan nada del simulador. Cada lectura de una tabla de conversación lleva su filtro."""
    sql = inspect.getsource(reader)
    reads = _CONVERSATION_ROWS.findall(sql)
    assert reads
    assert sql.count("is_simulation") == len(reads), reads


async def test_soft_deleting_a_simulated_conversation_takes_its_escalations_and_approvals() -> None:
    from unittest.mock import AsyncMock
    from uuid import uuid4

    conn = AsyncMock()
    await queries.soft_delete_conversation(conn, uuid4(), uuid4())
    sqls = [" ".join(call.args[0].split()) for call in conn.execute.await_args_list]
    assert [s.split()[1] for s in sqls] == ["escalations", "pending_approvals", "conversations"]
    assert all("is_simulation" in s for s in sqls), "nunca borra una conversación real"
