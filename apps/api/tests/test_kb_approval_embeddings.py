from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

from apps.api.integrations.openai_embeddings import get_embeddings
from apps.api.services.kb_approval import FailureCode, embed_submissions


async def test_chunks_of_many_submissions_share_requests_of_at_most_256_texts() -> None:
    calls: list[int] = []

    async def embedder(texts: list[str]) -> list[list[float]]:
        calls.append(len(texts))
        return [[float(len(t))] for t in texts]

    ids = [uuid.uuid4() for _ in range(3)]
    chunks = {ids[0]: ["a"] * 200, ids[1]: ["bb"] * 100, ids[2]: ["ccc"] * 300}

    embedded, failures = await embed_submissions(embedder, chunks)

    assert failures == []
    assert calls == [200, 100, 256, 44]
    assert embedded[ids[1]][0] == ("bb", [2.0])
    assert len(embedded[ids[2]]) == 300


async def test_a_failed_request_is_retried_per_submission() -> None:
    async def embedder(texts: list[str]) -> list[list[float]]:
        if "BOOM" in texts:
            raise RuntimeError("no")
        return [[1.0] for _ in texts]

    good, bad = uuid.uuid4(), uuid.uuid4()

    embedded, failures = await embed_submissions(embedder, {good: ["ok"], bad: ["BOOM"]})

    assert list(embedded) == [good]
    assert [(f.submission_id, f.code) for f in failures] == [(bad, FailureCode.EMBEDDING_FAILED)]


async def test_get_embeddings_sends_one_request_and_keeps_the_input_order() -> None:
    items = [SimpleNamespace(index=1, embedding=[2.0]), SimpleNamespace(index=0, embedding=[1.0])]
    create = AsyncMock(return_value=SimpleNamespace(data=items))
    client = SimpleNamespace(embeddings=SimpleNamespace(create=create))

    vectors = await get_embeddings(client, ["uno", "dos"], model="m")  # type: ignore[arg-type]

    assert vectors == [[1.0], [2.0]]
    create.assert_awaited_once_with(model="m", input=["uno", "dos"])
