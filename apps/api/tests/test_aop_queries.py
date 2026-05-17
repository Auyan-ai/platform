"""Tests para queries de AOPs (Sprint 7.1)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from apps.api.db.models import AopVersion, AopWithContent, IntentClassifierRun
from apps.api.db.queries import (
    create_aop,
    get_active_aops,
    get_aop_by_slug,
    insert_intent_classifier_run,
    save_aop_version,
)
from apps.api.tests.conftest import CONVERSATION_ID, TENANT_ID

AOP_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
AOP_VERSION_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
USER_ID = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
NOW = datetime(2026, 5, 17, 12, 0, 0, tzinfo=UTC)

SAMPLE_FRONTMATTER = {
    "name": "Consulta de envío",
    "slug": "consulta_envio",
    "workspace": "production",
    "allowed_skills": ["shopify.get_order_by_email", "shopify.get_order_status"],
    "triggers": {"description": "El cliente pregunta por el estado de su envío o pedido"},
}
SAMPLE_BODY = "## Cómo te comportas\n\nSiempre pide el email antes de buscar el pedido."
SAMPLE_RAW = f"---\n{json.dumps(SAMPLE_FRONTMATTER)}\n---\n\n{SAMPLE_BODY}"


def _aop_with_content_row(**overrides: object) -> MagicMock:
    """Simula un asyncpg.Record para el join aops+aop_versions."""
    base = {
        "id": AOP_ID,
        "tenant_id": TENANT_ID,
        "slug": "consulta_envio",
        "workspace": "production",
        "current_version": 1,
        "yaml_frontmatter": SAMPLE_FRONTMATTER,
        "body_markdown": SAMPLE_BODY,
        "raw_source": SAMPLE_RAW,
    }
    base.update(overrides)
    row = MagicMock()
    row.__iter__ = lambda self: iter(base.items())
    row.keys = lambda: base.keys()
    row.__getitem__ = lambda self, k: base[k]
    return row


def _aop_version_row(**overrides: object) -> MagicMock:
    """Simula un asyncpg.Record para aop_versions."""
    base = {
        "id": AOP_VERSION_ID,
        "aop_id": AOP_ID,
        "tenant_id": TENANT_ID,
        "version": 2,
        "yaml_frontmatter": SAMPLE_FRONTMATTER,
        "body_markdown": SAMPLE_BODY,
        "raw_source": SAMPLE_RAW,
        "created_by": None,
        "created_at": NOW,
    }
    base.update(overrides)
    row = MagicMock()
    row.__iter__ = lambda self: iter(base.items())
    row.keys = lambda: base.keys()
    row.__getitem__ = lambda self, k: base[k]
    return row


def _classifier_run_row(**overrides: object) -> MagicMock:
    base = {
        "id": uuid4(),
        "tenant_id": TENANT_ID,
        "conversation_id": CONVERSATION_ID,
        "turn_number": 1,
        "primary_slug": "consulta_envio",
        "primary_confidence": 0.92,
        "alternative_slug": None,
        "alternative_confidence": None,
        "ambiguity_detected": False,
        "was_reclassification": False,
        "human_correction": None,
        "created_at": NOW,
    }
    base.update(overrides)
    row = MagicMock()
    row.__iter__ = lambda self: iter(base.items())
    row.keys = lambda: base.keys()
    row.__getitem__ = lambda self, k: base[k]
    return row


# ============================================================
# get_active_aops
# ============================================================


@pytest.mark.asyncio
async def test_get_active_aops_returns_list() -> None:
    conn = AsyncMock()
    conn.fetch.return_value = [_aop_with_content_row()]

    result = await get_active_aops(conn, TENANT_ID)

    assert len(result) == 1
    assert isinstance(result[0], AopWithContent)
    assert result[0].slug == "consulta_envio"
    assert result[0].workspace == "production"
    assert result[0].current_version == 1


@pytest.mark.asyncio
async def test_get_active_aops_passes_workspace() -> None:
    conn = AsyncMock()
    conn.fetch.return_value = []

    await get_active_aops(conn, TENANT_ID, workspace="staging")

    args = conn.fetch.call_args
    assert "staging" in args[0]


@pytest.mark.asyncio
async def test_get_active_aops_defaults_to_production() -> None:
    conn = AsyncMock()
    conn.fetch.return_value = []

    await get_active_aops(conn, TENANT_ID)

    args = conn.fetch.call_args
    assert "production" in args[0]


@pytest.mark.asyncio
async def test_get_active_aops_empty_tenant() -> None:
    conn = AsyncMock()
    conn.fetch.return_value = []

    result = await get_active_aops(conn, TENANT_ID)

    assert result == []


@pytest.mark.asyncio
async def test_get_active_aops_yaml_frontmatter_is_dict() -> None:
    conn = AsyncMock()
    conn.fetch.return_value = [_aop_with_content_row()]

    result = await get_active_aops(conn, TENANT_ID)

    assert isinstance(result[0].yaml_frontmatter, dict)
    assert result[0].yaml_frontmatter["slug"] == "consulta_envio"


# ============================================================
# get_aop_by_slug
# ============================================================


@pytest.mark.asyncio
async def test_get_aop_by_slug_found() -> None:
    conn = AsyncMock()
    conn.fetchrow.return_value = _aop_with_content_row()

    result = await get_aop_by_slug(conn, TENANT_ID, "consulta_envio")

    assert result is not None
    assert result.slug == "consulta_envio"
    assert result.body_markdown == SAMPLE_BODY


@pytest.mark.asyncio
async def test_get_aop_by_slug_not_found() -> None:
    conn = AsyncMock()
    conn.fetchrow.return_value = None

    result = await get_aop_by_slug(conn, TENANT_ID, "nonexistent")

    assert result is None


@pytest.mark.asyncio
async def test_get_aop_by_slug_default_workspace_is_production() -> None:
    conn = AsyncMock()
    conn.fetchrow.return_value = None

    await get_aop_by_slug(conn, TENANT_ID, "consulta_envio")

    args = conn.fetchrow.call_args
    assert "production" in args[0]


@pytest.mark.asyncio
async def test_get_aop_by_slug_staging() -> None:
    conn = AsyncMock()
    conn.fetchrow.return_value = _aop_with_content_row(workspace="staging")

    result = await get_aop_by_slug(conn, TENANT_ID, "consulta_envio", workspace="staging")

    assert result is not None
    assert result.workspace == "staging"


# ============================================================
# create_aop
# ============================================================


@pytest.mark.asyncio
async def test_create_aop_inserts_aop_and_version() -> None:
    conn = AsyncMock()
    aop_insert_row = MagicMock()
    aop_insert_row.__getitem__ = lambda self, k: {
        "id": AOP_ID,
        "tenant_id": TENANT_ID,
        "slug": "consulta_envio",
        "workspace": "production",
        "current_version": 1,
    }[k]

    conn.fetchrow.side_effect = [
        aop_insert_row,    # INSERT INTO aops RETURNING
        _aop_with_content_row(),  # get_aop_by_slug internamente
    ]
    conn.execute.return_value = None

    result = await create_aop(
        conn,
        tenant_id=TENANT_ID,
        slug="consulta_envio",
        workspace="production",
        yaml_frontmatter=SAMPLE_FRONTMATTER,
        body_markdown=SAMPLE_BODY,
        raw_source=SAMPLE_RAW,
    )

    assert isinstance(result, AopWithContent)
    assert result.slug == "consulta_envio"
    assert conn.execute.call_count == 1  # INSERT INTO aop_versions


@pytest.mark.asyncio
async def test_create_aop_passes_created_by() -> None:
    conn = AsyncMock()
    aop_insert_row = MagicMock()
    aop_insert_row.__getitem__ = lambda self, k: {
        "id": AOP_ID,
        "tenant_id": TENANT_ID,
        "slug": "consulta_envio",
        "workspace": "production",
        "current_version": 1,
    }[k]

    conn.fetchrow.side_effect = [aop_insert_row, _aop_with_content_row()]
    conn.execute.return_value = None

    await create_aop(
        conn,
        tenant_id=TENANT_ID,
        slug="consulta_envio",
        workspace="production",
        yaml_frontmatter=SAMPLE_FRONTMATTER,
        body_markdown=SAMPLE_BODY,
        raw_source=SAMPLE_RAW,
        created_by=USER_ID,
    )

    execute_call_args = conn.execute.call_args[0]
    assert USER_ID in execute_call_args


# ============================================================
# save_aop_version
# ============================================================


@pytest.mark.asyncio
async def test_save_aop_version_returns_aop_version() -> None:
    conn = AsyncMock()
    conn.fetchrow.return_value = _aop_version_row(version=2)
    conn.execute.return_value = "UPDATE 1"

    result = await save_aop_version(
        conn,
        tenant_id=TENANT_ID,
        aop_id=AOP_ID,
        yaml_frontmatter=SAMPLE_FRONTMATTER,
        body_markdown=SAMPLE_BODY,
        raw_source=SAMPLE_RAW,
    )

    assert isinstance(result, AopVersion)
    assert result.version == 2
    assert result.aop_id == AOP_ID


@pytest.mark.asyncio
async def test_save_aop_version_bumps_current_version() -> None:
    conn = AsyncMock()
    conn.fetchrow.return_value = _aop_version_row(version=2)
    conn.execute.return_value = "UPDATE 1"

    await save_aop_version(
        conn,
        tenant_id=TENANT_ID,
        aop_id=AOP_ID,
        yaml_frontmatter=SAMPLE_FRONTMATTER,
        body_markdown=SAMPLE_BODY,
        raw_source=SAMPLE_RAW,
    )

    # Debe haber un UPDATE aops SET current_version = current_version + 1
    update_sql = conn.execute.call_args[0][0]
    assert "current_version" in update_sql
    assert "UPDATE" in update_sql


@pytest.mark.asyncio
async def test_save_aop_version_raises_if_aop_not_found() -> None:
    conn = AsyncMock()
    conn.fetchrow.return_value = None

    with pytest.raises(ValueError, match="no encontrado"):
        await save_aop_version(
            conn,
            tenant_id=TENANT_ID,
            aop_id=AOP_ID,
            yaml_frontmatter=SAMPLE_FRONTMATTER,
            body_markdown=SAMPLE_BODY,
            raw_source=SAMPLE_RAW,
        )


@pytest.mark.asyncio
async def test_save_aop_version_yaml_frontmatter_is_dict() -> None:
    conn = AsyncMock()
    conn.fetchrow.return_value = _aop_version_row()
    conn.execute.return_value = "UPDATE 1"

    result = await save_aop_version(
        conn,
        tenant_id=TENANT_ID,
        aop_id=AOP_ID,
        yaml_frontmatter=SAMPLE_FRONTMATTER,
        body_markdown=SAMPLE_BODY,
        raw_source=SAMPLE_RAW,
    )

    assert isinstance(result.yaml_frontmatter, dict)


# ============================================================
# insert_intent_classifier_run
# ============================================================


@pytest.mark.asyncio
async def test_insert_classifier_run_basic() -> None:
    conn = AsyncMock()
    conn.fetchrow.return_value = _classifier_run_row()

    result = await insert_intent_classifier_run(
        conn,
        tenant_id=TENANT_ID,
        conversation_id=CONVERSATION_ID,
        turn_number=1,
        primary_slug="consulta_envio",
        primary_confidence=0.92,
        ambiguity_detected=False,
        was_reclassification=False,
    )

    assert isinstance(result, IntentClassifierRun)
    assert result.primary_slug == "consulta_envio"
    assert result.primary_confidence == 0.92
    assert result.ambiguity_detected is False


@pytest.mark.asyncio
async def test_insert_classifier_run_with_alternative() -> None:
    conn = AsyncMock()
    conn.fetchrow.return_value = _classifier_run_row(
        alternative_slug="cancelacion",
        alternative_confidence=0.45,
        ambiguity_detected=True,
    )

    result = await insert_intent_classifier_run(
        conn,
        tenant_id=TENANT_ID,
        conversation_id=CONVERSATION_ID,
        turn_number=1,
        primary_slug="consulta_envio",
        primary_confidence=0.88,
        alternative_slug="cancelacion",
        alternative_confidence=0.45,
        ambiguity_detected=True,
        was_reclassification=False,
    )

    assert result.alternative_slug == "cancelacion"
    assert result.ambiguity_detected is True


@pytest.mark.asyncio
async def test_insert_classifier_run_reclassification() -> None:
    conn = AsyncMock()
    conn.fetchrow.return_value = _classifier_run_row(
        turn_number=3, was_reclassification=True
    )

    result = await insert_intent_classifier_run(
        conn,
        tenant_id=TENANT_ID,
        conversation_id=CONVERSATION_ID,
        turn_number=3,
        primary_slug="consulta_envio",
        primary_confidence=0.91,
        ambiguity_detected=False,
        was_reclassification=True,
    )

    assert result.was_reclassification is True
    assert result.turn_number == 3


@pytest.mark.asyncio
async def test_insert_classifier_run_passes_all_params_to_db() -> None:
    conn = AsyncMock()
    conn.fetchrow.return_value = _classifier_run_row()

    await insert_intent_classifier_run(
        conn,
        tenant_id=TENANT_ID,
        conversation_id=CONVERSATION_ID,
        turn_number=2,
        primary_slug="cancelacion",
        primary_confidence=0.85,
        alternative_slug="consulta_envio",
        alternative_confidence=0.30,
        ambiguity_detected=False,
        was_reclassification=True,
    )

    call_args = conn.fetchrow.call_args[0]
    assert TENANT_ID in call_args
    assert CONVERSATION_ID in call_args
    assert 2 in call_args
    assert "cancelacion" in call_args
