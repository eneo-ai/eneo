"""Candidate selection of the rerank model cleanup worker."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from eneo.rerank_models.infrastructure.rerank_model_cleanup_worker import (
    _find_candidates,
    _has_blocking_refs,
)


class TestFindCandidates:
    async def test_selects_only_tombstones(self):
        session = AsyncMock()
        row = MagicMock(id=uuid4(), nickname="Old reranker")
        result = MagicMock()
        result.all.return_value = [row]
        session.execute.return_value = result

        candidates = await _find_candidates(session, limit=10)

        assert candidates == [(row.id, "Old reranker")]
        statement = session.execute.await_args.args[0]
        compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
        assert "rerank_models.deleted_at IS NOT NULL" in compiled
        assert "LIMIT 10" in compiled


class TestHasBlockingRefs:
    async def test_assistant_references_never_block(self):
        # assistants.rerank_model_id is SET NULL; the worker never skips.
        assert await _has_blocking_refs(AsyncMock(), uuid4()) is False
