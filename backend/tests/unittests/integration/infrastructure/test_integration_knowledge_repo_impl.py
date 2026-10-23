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


def _entity():
    entity = MagicMock()
    entity.id = uuid4()
    entity.document_count = 0
    return entity


class TestOneOrNone:
    """The filters the interface accepts reach the query; none at all is refused."""

    async def test_filters_reach_the_query(self, repo, session):
        space_id = uuid4()
        session.scalar.return_value = None

        assert await repo.one_or_none(space_id=space_id, name="Docs") is None

        sql = _compiled(session.scalar.await_args.args[0])
        assert f"integration_knowledge.space_id = '{space_id}'" in sql
        assert "integration_knowledge.name = 'Docs'" in sql

    async def test_without_any_filter_is_refused(self, repo, session):
        with pytest.raises(ValueError, match="No filter"):
            await repo.one_or_none()

        session.scalar.assert_not_called()


class TestDocumentCountProjection:
    """Fetches never count; the count is attached where an item is served."""

    async def test_fetches_issue_no_count_query(self, repo, session):
        record = _record()
        session.scalar.return_value = record
        session.scalars.return_value = MagicMock(all=lambda: [record])

        await repo.one_or_none(id=record.id)
        await repo.get_by_ids([record.id])

        session.execute.assert_not_called()
        repo.mapper.to_entity.assert_called_once()
        repo.mapper.to_entities.assert_called_once()
        # Knowledge keeps its embedding model after the model is deprecated.
        repo.embedding_model_repo.all.assert_awaited_with(with_deprecated=True)

    async def test_attach_document_counts_counts_all_items_in_one_query(
        self, repo, session
    ):
        first, second = _entity(), _entity()
        session.execute.return_value = _rows([(first.id, 3)])

        await repo.attach_document_counts([first, second])

        assert session.execute.await_count == 1
        assert (first.document_count, second.document_count) == (3, 0)
        sql = _compiled(session.execute.await_args.args[0])
        assert "GROUP BY info_blobs.integration_knowledge_id" in sql
        assert "info_blobs.version_state = 'active'" in sql
        assert f"'{first.id}'" in sql and f"'{second.id}'" in sql

    async def test_attach_document_counts_without_items_issues_no_query(
        self, repo, session
    ):
        await repo.attach_document_counts([])

        session.execute.assert_not_called()


class TestUpdateSyncState:
    """A sync writes its own columns only; a rename committed meanwhile survives."""

    async def test_writes_only_the_given_sync_columns(self, repo, session):
        knowledge_id = uuid4()
        session.execute.return_value = MagicMock(rowcount=1)

        await repo.update_sync_state(
            knowledge_id, last_sync_status="success", delta_token="token-2"
        )

        sql = _compiled(session.execute.await_args.args[0])
        assert sql.startswith(
            "UPDATE integration_knowledge SET last_sync_status='success', "
            "delta_token='token-2', updated_at=now() WHERE"
        )
        assert f"'{knowledge_id}'" in sql

    async def test_without_fields_issues_no_query(self, repo, session):
        await repo.update_sync_state(uuid4())

        session.execute.assert_not_called()

    async def test_missing_row_raises(self, repo, session):
        session.execute.return_value = MagicMock(rowcount=0)

        with pytest.raises(NotFoundException):
            await repo.update_sync_state(uuid4(), last_sync_status="error")
