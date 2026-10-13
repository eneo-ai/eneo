"""SpaceRepository: the SQL and loader options it uses, without a database."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from eneo.spaces.space_repo import SpaceRepository


@pytest.fixture
def session():
    return AsyncMock()


@pytest.fixture
def repo(session):
    return SpaceRepository(
        session=session,
        user=MagicMock(),
        factory=MagicMock(),
        file_content_loader=MagicMock(),
        app_repo=None,
        assistant_repo=AsyncMock(),
        completion_model_repo=AsyncMock(),
        transcription_model_repo=AsyncMock(),
        embedding_model_repo=AsyncMock(),
        http_auth_encryption=MagicMock(),
    )


def _repo(session: MagicMock) -> SpaceRepository:
    user = MagicMock()
    user.id = uuid4()
    user.tenant_id = uuid4()
    return SpaceRepository(
        session=session,
        user=user,
        factory=MagicMock(),
        file_content_loader=MagicMock(),
        app_repo=MagicMock(),
        assistant_repo=MagicMock(),
        completion_model_repo=MagicMock(),
        transcription_model_repo=MagicMock(),
        embedding_model_repo=MagicMock(),
        http_auth_encryption=MagicMock(),
    )


def _compiled(statement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


def _record():
    record = MagicMock()
    record.id = uuid4()
    return record


def _scalars(records):
    result = MagicMock()
    result.scalars.return_value.all.return_value = records
    return result


def _rows(pairs):
    result = MagicMock()
    result.all.return_value = pairs
    return result


class TestIntegrationKnowledgeUnion:
    async def test_attaches_the_active_document_count_in_one_query(self, repo, session):
        first, second = _record(), _record()
        session.execute.side_effect = [
            _scalars([first, second]),
            _rows([(first.id, 3)]),
        ]

        records = await repo._get_integration_knowledge_union([uuid4()])

        assert records == [first, second]
        assert first.document_count == 3
        assert second.document_count == 0
        assert session.execute.await_count == 2
        sql = _compiled(session.execute.await_args_list[1].args[0])
        assert "GROUP BY info_blobs.integration_knowledge_id" in sql
        assert "info_blobs.version_state = 'active'" in sql
        assert f"'{first.id}'" in sql and f"'{second.id}'" in sql

    async def test_no_knowledge_means_no_count_query(self, repo, session):
        session.execute.side_effect = [_scalars([])]

        assert await repo._get_integration_knowledge_union([uuid4()]) == []

        assert session.execute.await_count == 1


async def test_get_assistants_eager_loads_mcp_tool_settings():
    """Assistant factory reads assistant_mcp_server_tools synchronously.

    Keep the relationship eager-loaded in the space repository so loading a
    personal space cannot trigger async SQLAlchemy lazy IO during domain mapping.
    """
    session = MagicMock()
    assistants_result = MagicMock()
    assistants_result.scalars.return_value.all.return_value = []
    prompts_result = MagicMock()
    prompts_result.all.return_value = []
    session.execute = AsyncMock(side_effect=[assistants_result, prompts_result])

    repo = _repo(session)
    await repo._get_assistants(uuid4())

    assistants_stmt = session.execute.await_args_list[0].args[0]
    loader_paths = [str(option.path) for option in assistants_stmt._with_options]

    assert any("assistant_mcp_server_tools" in path for path in loader_paths)
