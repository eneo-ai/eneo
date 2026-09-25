"""Reference counting of the image model cleanup worker."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from eneo.image_models.infrastructure.image_model_cleanup_worker import (
    _find_candidates,
    _has_blocking_refs,
)


class TestHasBlockingRefs:
    async def test_a_builtin_provider_reference_blocks_cleanup(self):
        session = AsyncMock()
        session.scalar.return_value = 1

        assert await _has_blocking_refs(session, uuid4()) is True

    async def test_no_references_allows_cleanup(self):
        session = AsyncMock()
        session.scalar.return_value = 0

        assert await _has_blocking_refs(session, uuid4()) is False

    async def test_counts_mcp_servers_by_image_model_id(self):
        session = AsyncMock()
        session.scalar.return_value = 0
        model_id = uuid4()

        await _has_blocking_refs(session, model_id)

        statement = session.scalar.await_args.args[0]
        compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
        assert "FROM mcp_servers" in compiled
        assert "mcp_servers.image_model_id" in compiled


class TestFindCandidates:
    async def test_selects_only_tombstones(self):
        session = AsyncMock()
        row = MagicMock(id=uuid4(), nickname="Old image model")
        result = MagicMock()
        result.all.return_value = [row]
        session.execute.return_value = result

        candidates = await _find_candidates(session, limit=10)

        assert candidates == [(row.id, "Old image model")]
        statement = session.execute.await_args.args[0]
        compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
        assert "image_models.deleted_at IS NOT NULL" in compiled
        assert "LIMIT 10" in compiled
