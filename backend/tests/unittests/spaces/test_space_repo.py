"""SpaceRepository: the SQL and loader options it uses, without a database."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from eneo.database.tables.mcp_server_table import MCPServerTools, SpacesMCPServerTools
from eneo.mcp_servers.domain.entities.mcp_server import MCPServer
from eneo.spaces.space_repo import SpaceRepository


@pytest.mark.parametrize(
    "default,tenant,space,assistant,expected",
    [
        (False, True, None, True, True),
        (True, False, True, True, None),
        (True, None, False, True, None),
        (False, None, True, True, True),
        (True, None, None, False, False),
        (True, None, None, None, False),
    ],
)
def test_assistant_tool_policy_preserves_catalog_default(
    default, tenant, space, assistant, expected
):
    server = MCPServer(
        id=uuid4(),
        tenant_id=uuid4(),
        name="source",
        http_url="https://example.test/mcp",
    )
    row = MCPServerTools(
        id=uuid4(), mcp_server_id=server.id, name="tool", is_enabled_by_default=default
    )

    SpaceRepository._project_assistant_mcp_server_tools(
        mcp_servers=[server],
        tools_db=[row],
        tenant_tool_settings={} if tenant is None else {row.id: tenant},
        space_tool_overrides={} if space is None else {row.id: space},
        assistant_tool_overrides={} if assistant is None else {row.id: assistant},
    )

    if expected is None:
        assert server.tools == []
    else:
        (tool,) = server.tools
        assert tool.is_enabled is expected
        assert tool.is_enabled_by_default is default


@pytest.mark.parametrize("enabled", [False, True])
async def test_space_tool_policy_preserves_catalog_default(repo, session, enabled):
    server = MCPServer(
        id=uuid4(),
        tenant_id=uuid4(),
        name="source",
        http_url="https://example.test/mcp",
    )
    row = MCPServerTools(
        id=uuid4(),
        mcp_server_id=server.id,
        name="tool",
        is_enabled_by_default=not enabled,
    )
    space_id = uuid4()
    override = SpacesMCPServerTools(
        space_id=space_id, mcp_server_tool_id=row.id, is_enabled=enabled
    )
    session.execute.side_effect = [_scalars([row]), _scalars([]), _scalars([override])]

    await repo._load_mcp_server_tools_with_overrides(space_id, [server])

    (tool,) = server.tools
    assert tool.is_enabled is enabled
    assert tool.is_enabled_by_default is not enabled


@pytest.fixture
def session():
    return AsyncMock()


@pytest.fixture
def repo(session):
    user = MagicMock()
    user.tenant_id = uuid4()
    return SpaceRepository(
        session=session,
        tenant=SimpleNamespace(id=user.tenant_id),
        user=user,
        factory=MagicMock(),
        file_content_loader=MagicMock(),
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
        tenant=SimpleNamespace(id=user.tenant_id),
        user=user,
        factory=MagicMock(),
        file_content_loader=MagicMock(),
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

        records = await repo._get_integration_knowledge_union(
            [uuid4()], with_document_counts=True
        )

        assert records == [first, second]
        assert first.document_count == 3
        assert second.document_count == 0
        assert session.execute.await_count == 2
        sql = _compiled(session.execute.await_args_list[1].args[0])
        assert "GROUP BY info_blobs.integration_knowledge_id" in sql
        assert "info_blobs.version_state = 'active'" in sql
        assert f"'{first.id}'" in sql and f"'{second.id}'" in sql

    async def test_the_count_query_matches_its_partial_index(self, repo, session):
        from eneo.database.tables.info_blobs_table import InfoBlobs

        record = _record()
        session.execute.side_effect = [_scalars([record]), _rows([])]

        await repo._get_integration_knowledge_union(
            [uuid4()], with_document_counts=True
        )

        index = next(
            index
            for index in InfoBlobs.__table__.indexes
            if index.name == "ix_info_blobs_active_integration_knowledge"
        )
        assert [column.name for column in index.columns] == ["integration_knowledge_id"]
        predicate = str(index.dialect_options["postgresql"]["where"])
        assert predicate == "version_state = 'active'"
        sql = _compiled(session.execute.await_args_list[1].args[0])
        assert (
            f"WHERE info_blobs.integration_knowledge_id IN ('{record.id}') AND info_blobs.{predicate}"
            in sql
        )

    async def test_hydration_without_counts_issues_no_count_query(self, repo, session):
        first, second = _record(), _record()
        session.execute.side_effect = [_scalars([first, second])]

        records = await repo._get_integration_knowledge_union([uuid4()])

        assert records == [first, second]
        assert session.execute.await_count == 1
        assert "info_blobs" not in _compiled(session.execute.await_args.args[0])

    async def test_no_knowledge_means_no_count_query(self, repo, session):
        session.execute.side_effect = [_scalars([])]

        assert (
            await repo._get_integration_knowledge_union(
                [uuid4()], with_document_counts=True
            )
            == []
        )

        assert session.execute.await_count == 1

    @pytest.mark.parametrize(
        ("lookup", "arguments", "counted"),
        [
            # Served to the UI as SpacePublic: the knowledge list needs counts.
            ("one_or_none", (uuid4(),), True),
            ("get_personal_space", (uuid4(),), True),
            # The organization space is served through this lookup.
            ("get_space_by_name_and_tenant", ("Organization", uuid4()), True),
            # Resource lookups on the chat and job paths never show the list.
            ("get_space_by_assistant", (uuid4(),), False),
            ("get_space_by_app", (uuid4(),), False),
            ("get_space_by_service", (uuid4(),), False),
            ("get_space_by_group_chat", (uuid4(),), False),
            ("get_space_by_collection", (uuid4(),), False),
            ("get_space_by_website", (uuid4(),), False),
            ("get_space_by_integration_knowledge", (uuid4(),), False),
        ],
    )
    async def test_only_space_lookups_served_to_the_ui_count_documents(
        self, repo, lookup: str, arguments: tuple, counted: bool
    ):
        repo._get_from_query = AsyncMock(return_value=MagicMock())

        await getattr(repo, lookup)(*arguments)

        kwargs = repo._get_from_query.await_args.kwargs
        assert kwargs.get("with_document_counts", False) is counted


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
