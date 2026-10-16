"""IntegrationKnowledgeRepoImpl: the SQL it issues, without a database."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from eneo.integration.infrastructure.repo_impl.integration_knowledge_repo_impl import (
    IntegrationKnowledgeRepoImpl,
)
from eneo.main.exceptions import NotFoundException


@pytest.fixture
def session():
    return AsyncMock()


@pytest.fixture
def repo(session):
    return IntegrationKnowledgeRepoImpl(
        session=session, mapper=MagicMock(), embedding_model_repo=AsyncMock()
    )


def _compiled(statement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


class TestAdjustSize:
    async def test_adds_delta_in_sql_and_returns_the_new_size(self, repo, session):
        knowledge_id = uuid4()
        session.scalar.return_value = 90

        new_size = await repo.adjust_size(knowledge_id, -40)

        assert new_size == 90
        sql = _compiled(session.scalar.await_args.args[0])
        assert "UPDATE integration_knowledge SET size=greatest(" in sql
        assert "coalesce(integration_knowledge.size, 0) + -40" in sql
        assert "RETURNING integration_knowledge.size" in sql
        assert f"'{knowledge_id}'" in sql

    async def test_missing_row_raises(self, repo, session):
        session.scalar.return_value = None

        with pytest.raises(NotFoundException):
            await repo.adjust_size(uuid4(), 10)


def _record(**attrs):
    record = MagicMock()
    record.id = uuid4()
    record.embedding_model_id = uuid4()
    for name, value in attrs.items():
        setattr(record, name, value)
    return record


def _rows(pairs):
    result = MagicMock()
    result.all.return_value = pairs
    return result


class TestDocumentCountProjection:
    async def test_get_by_ids_counts_all_records_in_one_query(self, repo, session):
        first, second = _record(), _record()
        session.scalars.return_value = MagicMock(all=lambda: [first, second])
        session.execute.return_value = _rows([(first.id, 3)])

        await repo.get_by_ids([first.id, second.id])

        assert session.execute.await_count == 1
        assert first.document_count == 3
        assert second.document_count == 0
        sql = _compiled(session.execute.await_args.args[0])
        assert "GROUP BY info_blobs.integration_knowledge_id" in sql
        assert "info_blobs.version_state = 'active'" in sql
        assert f"'{first.id}'" in sql and f"'{second.id}'" in sql
        repo.mapper.to_entities.assert_called_once()
        # Knowledge keeps its embedding model after the model is deprecated.
        repo.embedding_model_repo.all.assert_awaited_once_with(with_deprecated=True)

    async def test_one_or_none_attaches_the_count(self, repo, session):
        record = _record()
        session.scalar.return_value = record
        session.execute.return_value = _rows([(record.id, 7)])

        await repo.one_or_none(id=record.id)

        assert record.document_count == 7
        repo.mapper.to_entity.assert_called_once()

    async def test_no_records_means_no_count_query(self, repo, session):
        session.scalars.return_value = MagicMock(all=lambda: [])

        assert await repo.get_by_ids([uuid4()]) == []

        session.execute.assert_not_called()
