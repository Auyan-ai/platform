"""#420: mismo texto bajo otra clave se marca `duplicate_of`, no se descarta ni se deja pasar."""

from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

from apps.api.db import queries
from apps.api.db.queries import create_tenant_knowledge_submission, find_cross_key_duplicate
from apps.api.services.kb_source_key import content_sha256

TENANT = uuid.uuid4()
OTHER_ID = uuid.uuid4()


class FakeConn:
    """fetchrow resuelve el SELECT de duplicados (según `duplicate`) y el INSERT (eco)."""

    def __init__(self, duplicate: tuple[uuid.UUID, str] | None) -> None:
        self.duplicate = duplicate
        self.dup_args: tuple[Any, ...] | None = None
        self.execute = AsyncMock()

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        if "INSERT INTO tenant_knowledge_submissions" in query:
            now = datetime.now(UTC)
            return {
                "id": uuid.uuid4(),
                "tenant_id": TENANT,
                "title": args[1],
                "source_type": args[2],
                "source_url": args[3],
                "original_filename": None,
                "content": args[5],
                "notes": None,
                "status": "pending_review",
                "metadata": args[7],
                "submitted_by": None,
                "reviewed_by": None,
                "reviewed_at": None,
                "review_note": None,
                "processed_document_id": None,
                "source_key": args[9],
                "ingestion_id": None,
                "created_at": now,
                "updated_at": now,
            }
        self.dup_args = args
        if self.duplicate is None:
            return None
        return {"id": self.duplicate[0], "kind": self.duplicate[1]}


async def test_manual_submission_with_the_text_of_a_live_document_is_flagged() -> None:
    conn = FakeConn((OTHER_ID, "document"))

    sub = await create_tenant_knowledge_submission(
        conn,  # type: ignore[arg-type]
        TENANT,
        title="Política",
        source_type="text",
        content="  Devoluciones en 30 días.\n",
    )

    assert sub.metadata["duplicate_of"] == str(OTHER_ID)
    assert sub.metadata["duplicate_kind"] == "document"
    assert sub.status == "pending_review"
    # compara el hash del texto normalizado, con la clave de la nueva (None en manual)
    assert conn.dup_args == (TENANT, None, content_sha256("Devoluciones en 30 días."))


async def test_engine_page_with_text_pending_under_another_key_is_flagged() -> None:
    conn = FakeConn((OTHER_ID, "submission"))

    sub = await create_tenant_knowledge_submission(
        conn,  # type: ignore[arg-type]
        TENANT,
        title="Refund",
        source_type="url",
        source_url="https://tienda.com/policies/refund-policy",
        content="Texto",
        metadata={"priority": "normal"},
    )

    assert sub.metadata == {
        "priority": "normal",
        "duplicate_of": str(OTHER_ID),
        "duplicate_kind": "submission",
    }
    assert conn.dup_args is not None
    assert conn.dup_args[1] == "tienda.com/policies/refund-policy"


async def test_different_text_is_not_flagged() -> None:
    conn = FakeConn(None)

    sub = await create_tenant_knowledge_submission(
        conn,  # type: ignore[arg-type]
        TENANT,
        title="Envíos",
        source_type="url",
        source_url="https://tienda.com/envios",
        content="Envíos en 48 horas.",
    )

    assert "duplicate_of" not in sub.metadata


async def test_empty_content_skips_the_lookup() -> None:
    conn = FakeConn((OTHER_ID, "document"))

    sub = await create_tenant_knowledge_submission(
        conn,  # type: ignore[arg-type]
        TENANT,
        title="Solo URL",
        source_type="url",
        source_url="https://tienda.com/x",
        content="  ",
    )

    assert conn.dup_args is None
    assert "duplicate_of" not in sub.metadata


async def test_find_cross_key_duplicate_returns_none_without_a_match() -> None:
    conn = FakeConn(None)

    found = await find_cross_key_duplicate(conn, TENANT, sha256="x", source_key="a")  # type: ignore[arg-type]

    assert found is None


def test_query_excludes_the_same_key_and_covers_manual_without_key() -> None:
    src = inspect.getsource(queries.find_cross_key_duplicate)
    assert "$2::text IS NULL OR source_key IS DISTINCT FROM $2::text" in src
    assert "deleted_at IS NULL" in src
    assert "pending_review" in src
