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


def test_merge_tenant_playbook_never_blanks_existing_columns() -> None:
    """El wizard manda "" en lo que no pregunta: cada columna solo cambia si el valor
    nuevo no está vacío (NULLIF + COALESCE); si no, conserva la existente."""
    sql = inspect.getsource(queries.merge_tenant_playbook)
    for column in (
        "brand_voice",
        "product_overview",
        "policies",
        "escalation_notes",
        "agent_instructions",
    ):
        assert re.search(
            rf"{column}\s*=\s*COALESCE\(NULLIF\(EXCLUDED\.{column}, ''\),\s*"
            rf"tenant_playbook\.{column}\)",
            sql,
        ), column


def test_merge_tenant_facts_merges_jsonb_instead_of_replacing() -> None:
    sql = inspect.getsource(queries.merge_tenant_facts)
    assert "tenant_facts.data || EXCLUDED.data" in sql
    assert "data           = EXCLUDED.data" not in sql


@pytest.mark.asyncio
async def test_merge_tenant_facts_drops_blank_incoming_values() -> None:
    from unittest.mock import AsyncMock
    from uuid import uuid4

    tenant_id = uuid4()
    conn = AsyncMock()
    conn.fetchrow.return_value = {
        "tenant_id": tenant_id,
        "data": {"company_name": "Marea", "shipping": "48h"},
    }
    facts = await queries.merge_tenant_facts(
        conn,
        tenant_id,
        {"company_name": "Marea", "support_email": "", "business_hours": None, "x": "  "},
    )
    sent = conn.fetchrow.await_args.args[2]
    assert sent == {"company_name": "Marea"}
    assert facts.data == {"company_name": "Marea", "shipping": "48h"}
