"""Aprobación de submissions de conocimiento hacia la KB, una a una o por lote (ADR 0015 §3)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from apps.api.db.client import tenant_scope
from apps.api.db.models import KbConfirmation, TenantKnowledgeSubmission
from apps.api.db.queries import (
    approve_tenant_knowledge_submission_with_document,
    get_tenant_knowledge_submission,
)
from apps.api.services.knowledge_ingestion import Embedder, chunk_text_for_kb

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

MAX_EMBED_INPUTS = 256


class FailureCode(StrEnum):
    NOT_FOUND = "not_found"
    NO_CONTENT = "no_content"
    EMBEDDING_FAILED = "embedding_failed"
    ERROR = "error"


@dataclass(frozen=True)
class SubmissionFailure:
    submission_id: UUID
    code: FailureCode
    detail: str


@dataclass
class BatchApproval:
    approved: list[TenantKnowledgeSubmission] = field(default_factory=list)
    skipped: list[UUID] = field(default_factory=list)
    failures: list[SubmissionFailure] = field(default_factory=list)


Chunks = list[tuple[str, list[float]]]


def indexable_chunks(submission: TenantKnowledgeSubmission) -> list[str]:
    """Trozos a indexar. Vacío si el contenido es nada o solo la URL de la fuente."""
    content = submission.content.strip()
    if not content or (submission.source_url and content == submission.source_url.strip()):
        return []
    return chunk_text_for_kb(content)


async def _embed_all(embedder: Embedder, texts: list[str]) -> list[list[float]]:
    vectors: list[list[float]] = []
    for start in range(0, len(texts), MAX_EMBED_INPUTS):
        part = texts[start : start + MAX_EMBED_INPUTS]
        embedded = await embedder(part)
        if len(embedded) != len(part):
            raise ValueError(f"el embedder devolvió {len(embedded)} vectores para {len(part)}")
        vectors.extend(embedded)
    return vectors


def _group_by_input_budget(chunks_by_id: dict[UUID, list[str]]) -> list[list[UUID]]:
    groups: list[list[UUID]] = []
    current: list[UUID] = []
    size = 0
    for submission_id, chunks in chunks_by_id.items():
        if current and size + len(chunks) > MAX_EMBED_INPUTS:
            groups.append(current)
            current, size = [], 0
        current.append(submission_id)
        size += len(chunks)
    if current:
        groups.append(current)
    return groups


async def embed_submissions(
    embedder: Embedder, chunks_by_id: dict[UUID, list[str]]
) -> tuple[dict[UUID, Chunks], list[SubmissionFailure]]:
    """Embebe los trozos de varias submissions juntos, en peticiones de hasta 256 textos.

    Si una petición falla se reintenta submission a submission, para que una sola mala no
    pierda las demás."""
    embedded: dict[UUID, Chunks] = {}
    failures: list[SubmissionFailure] = []

    async def run(ids: list[UUID]) -> None:
        texts = [text for sid in ids for text in chunks_by_id[sid]]
        try:
            vectors = await _embed_all(embedder, texts)
        except Exception as exc:
            if len(ids) > 1:
                for sid in ids:
                    await run([sid])
                return
            logger.warning(
                "kb_embedding_failed", extra={"submission_id": str(ids[0])}, exc_info=True
            )
            detail = f"{type(exc).__name__}: {exc}"
            failures.append(SubmissionFailure(ids[0], FailureCode.EMBEDDING_FAILED, detail))
            return
        offset = 0
        for sid in ids:
            n = len(chunks_by_id[sid])
            embedded[sid] = list(zip(chunks_by_id[sid], vectors[offset : offset + n], strict=True))
            offset += n

    for group in _group_by_input_budget(chunks_by_id):
        await run(group)
    return embedded, failures


async def approve_submissions_batch(
    *,
    tenant_id: UUID,
    submission_ids: list[UUID],
    reviewed_by: UUID | None,
    review_note: str | None,
    confirmation: KbConfirmation,
    embedder: Embedder,
) -> BatchApproval:
    """Aprueba e indexa las submissions pendientes de `submission_ids`.

    Los embeddings se piden por lotes y cada submission se aprueba en su propia transacción:
    una que falle se reporta y no arrastra a las demás. Las que ya no están pendientes se
    cuentan como `skipped`, así que repetir la llamada solo toca lo que sigue pendiente.
    """
    result = BatchApproval()
    chunks_by_id: dict[UUID, list[str]] = {}
    for submission_id in dict.fromkeys(submission_ids):
        async with tenant_scope(tenant_id) as conn:
            submission = await get_tenant_knowledge_submission(conn, tenant_id, submission_id)
        if submission is None:
            result.failures.append(
                SubmissionFailure(submission_id, FailureCode.NOT_FOUND, "Submission no encontrado")
            )
        elif submission.status != "pending_review":
            result.skipped.append(submission_id)
        elif not (chunks := indexable_chunks(submission)):
            result.failures.append(
                SubmissionFailure(
                    submission_id, FailureCode.NO_CONTENT, "Submission sin contenido indexable"
                )
            )
        else:
            chunks_by_id[submission_id] = chunks

    embedded, embedding_failures = await embed_submissions(embedder, chunks_by_id)
    result.failures.extend(embedding_failures)

    for submission_id, chunks in embedded.items():
        try:
            async with tenant_scope(tenant_id) as conn:
                approved = await approve_tenant_knowledge_submission_with_document(
                    conn,
                    tenant_id,
                    submission_id,
                    reviewed_by=reviewed_by,
                    review_note=review_note,
                    chunks=chunks,
                    confirmation=confirmation,
                )
        except Exception as exc:
            logger.exception("kb_approval_failed", extra={"submission_id": str(submission_id)})
            result.failures.append(
                SubmissionFailure(submission_id, FailureCode.ERROR, f"{type(exc).__name__}: {exc}")
            )
            continue
        if approved is None:
            result.skipped.append(submission_id)
        else:
            result.approved.append(approved)
    return result
