import asyncio
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
import sqlalchemy as sa

from eneo.database.database import sessionmanager
from eneo.database.tables.chat_session_mcp_state_table import ChatSessionMcpState
from eneo.database.tables.mcp_server_table import MCPServers
from eneo.database.tables.questions_table import Questions
from eneo.database.tables.sessions_table import Sessions
from eneo.mcp_servers.application.mcp_server_service import MCPServerService
from eneo.mcp_servers.domain.entities.mcp_server import (
    MCPServer,
    MCPServerTool,
    MCPToolCatalogStagingTimeout,
)
from eneo.mcp_servers.infrastructure.mappers.mcp_server_mapper import (
    MCPServerToolMapper,
)
from eneo.mcp_servers.infrastructure.repo_impl.chat_session_mcp_state_repo_impl import (
    ChatSessionMcpStateRepo,
)
from eneo.mcp_servers.infrastructure.repo_impl.mcp_server_tool_repo_impl import (
    MCPServerToolRepoImpl,
)
from eneo.questions.questions_repo import QuestionRepository
from eneo.sessions.session_service import SessionService
from eneo.sessions.sessions_repo import SessionRepository


@pytest.mark.integration
@pytest.mark.asyncio
async def test_protocol_session_state_survives_outer_request_rollback(
    setup_database: None,
    admin_user,
) -> None:
    async with sessionmanager.session() as seed_session, seed_session.begin():
        server = MCPServers(
            tenant_id=admin_user.tenant_id,
            name=f"session-state-{uuid4()}",
            http_url="http://localhost:9000/mcp",
            http_auth_type="none",
            is_enabled=True,
            forward_identity=True,
        )
        chat_session = Sessions(
            user_id=admin_user.id,
            name="MCP session durability test",
        )
        seed_session.add_all([server, chat_session])
        await seed_session.flush()
        server_id = server.id
        chat_session_id = chat_session.id

    outer_session = sessionmanager.create_session()
    try:
        await outer_session.begin()
        await outer_session.scalar(
            sa.select(MCPServers.id).where(MCPServers.id == server_id)
        )
        repo = ChatSessionMcpStateRepo(outer_session)
        winner = await repo.claim(
            chat_session_id,
            server_id,
            candidate_mcp_session_id="protocol-committed",
            expected_mcp_session_id=None,
            identity_policy_generation=0,
        )
        assert winner == "protocol-committed"
        await outer_session.rollback()
    finally:
        await outer_session.close()

    try:
        async with sessionmanager.session() as verify_session, verify_session.begin():
            persisted = await verify_session.scalar(
                sa.select(ChatSessionMcpState.mcp_session_id).where(
                    ChatSessionMcpState.chat_session_id == chat_session_id,
                    ChatSessionMcpState.mcp_server_id == server_id,
                )
            )
        assert persisted == "protocol-committed"
    finally:
        async with sessionmanager.session() as cleanup_session, cleanup_session.begin():
            await cleanup_session.execute(
                sa.delete(Sessions).where(Sessions.id == chat_session_id)
            )
            await cleanup_session.execute(
                sa.delete(MCPServers).where(MCPServers.id == server_id)
            )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_protocol_session_state_rejects_uncommitted_chat_without_blocking(
    setup_database: None,
    admin_user,
) -> None:
    async with sessionmanager.session() as seed_session, seed_session.begin():
        server = MCPServers(
            tenant_id=admin_user.tenant_id,
            name=f"uncommitted-chat-{uuid4()}",
            http_url="http://localhost:9000/mcp",
            http_auth_type="none",
            is_enabled=True,
            forward_identity=True,
        )
        seed_session.add(server)
        await seed_session.flush()
        server_id = server.id

    outer_session = sessionmanager.create_session()
    try:
        await outer_session.begin()
        chat_session = Sessions(
            user_id=admin_user.id,
            name="Uncommitted MCP chat",
        )
        outer_session.add(chat_session)
        await outer_session.flush()

        repo = ChatSessionMcpStateRepo(outer_session)
        winner = await asyncio.wait_for(
            repo.claim(
                chat_session.id,
                server_id,
                candidate_mcp_session_id="protocol-not-durable",
                expected_mcp_session_id=None,
                identity_policy_generation=0,
            ),
            timeout=0.5,
        )

        assert winner is None
        await outer_session.rollback()
    finally:
        await outer_session.close()

    try:
        async with sessionmanager.session() as verify_session, verify_session.begin():
            state_count = await verify_session.scalar(
                sa.select(sa.func.count())
                .select_from(ChatSessionMcpState)
                .where(
                    ChatSessionMcpState.mcp_server_id == server_id,
                    ChatSessionMcpState.mcp_session_id == "protocol-not-durable",
                )
            )
        assert state_count == 0
    finally:
        async with sessionmanager.session() as cleanup_session, cleanup_session.begin():
            await cleanup_session.execute(
                sa.delete(MCPServers).where(MCPServers.id == server_id)
            )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_new_chat_and_protocol_state_survive_outer_request_rollback(
    setup_database: None,
    admin_user,
) -> None:
    async with sessionmanager.session() as seed_session, seed_session.begin():
        server = MCPServers(
            tenant_id=admin_user.tenant_id,
            name=f"first-turn-state-{uuid4()}",
            http_url="http://localhost:9000/mcp",
            http_auth_type="none",
            is_enabled=True,
            forward_identity=True,
        )
        seed_session.add(server)
        await seed_session.flush()
        server_id = server.id

    outer_session = sessionmanager.create_session()
    try:
        await outer_session.begin()
        service = SessionService(
            session_repo=SessionRepository(outer_session),
            question_repo=QuestionRepository(outer_session),
            user=admin_user,
        )
        chat_session = await service.create_session(
            name="First-turn MCP state",
            assistant_id=None,
            group_chat_id=None,
        )
        question_id, _question_created_at = await service.create_question_placeholder(
            question="Use the stateful tool",
            session=chat_session,
            files=None,
            assistant_id=None,
            completion_model=None,
        )

        repo = ChatSessionMcpStateRepo(outer_session)
        winner = await asyncio.wait_for(
            repo.claim(
                chat_session.id,
                server_id,
                candidate_mcp_session_id="protocol-first-turn",
                expected_mcp_session_id=None,
                identity_policy_generation=0,
            ),
            timeout=0.5,
        )
        assert winner == "protocol-first-turn"
        await outer_session.rollback()
    finally:
        await outer_session.close()

    try:
        async with sessionmanager.session() as verify_session, verify_session.begin():
            persisted_state = await verify_session.scalar(
                sa.select(ChatSessionMcpState.mcp_session_id).where(
                    ChatSessionMcpState.chat_session_id == chat_session.id,
                    ChatSessionMcpState.mcp_server_id == server_id,
                )
            )
            persisted_chat = await verify_session.scalar(
                sa.select(Sessions.id).where(Sessions.id == chat_session.id)
            )
            persisted_question = await verify_session.scalar(
                sa.select(Questions.question).where(Questions.id == question_id)
            )
        assert persisted_chat == chat_session.id
        assert persisted_question == "Use the stateful tool"
        assert persisted_state == "protocol-first-turn"
    finally:
        async with sessionmanager.session() as cleanup_session, cleanup_session.begin():
            await cleanup_session.execute(
                sa.delete(Sessions).where(Sessions.id == chat_session.id)
            )
            await cleanup_session.execute(
                sa.delete(MCPServers).where(MCPServers.id == server_id)
            )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_runtime_discovery_stages_one_pending_tool(
    setup_database: None,
    admin_user,
) -> None:
    async with sessionmanager.session() as seed_session, seed_session.begin():
        server = MCPServers(
            tenant_id=admin_user.tenant_id,
            name=f"tool-staging-{uuid4()}",
            http_url="http://localhost:9000/mcp",
            http_auth_type="none",
            is_enabled=True,
            forward_identity=True,
        )
        seed_session.add(server)
        await seed_session.flush()
        server_id = server.id

    async def stage(description: str) -> list[MCPServerTool]:
        async with sessionmanager.session() as session, session.begin():
            repo = MCPServerToolRepoImpl(session, MCPServerToolMapper())
            return await repo.stage_observed(
                [
                    MCPServerTool.pending_discovery(
                        mcp_server_id=server_id,
                        name="ordinary_only",
                        title="Ordinary only",
                        description=description,
                        input_schema={"type": "object", "properties": {}},
                    )
                ]
            )

    try:
        staged = await asyncio.gather(stage("first"), stage("second"))
        assert sum(bool(batch) for batch in staged) == 1

        async with sessionmanager.session() as verify_session, verify_session.begin():
            repo = MCPServerToolRepoImpl(verify_session, MCPServerToolMapper())
            tools = await repo.by_server(server_id)
        assert len(tools) == 1
        assert tools[0].description is None
        assert tools[0].pending_description in {"first", "second"}
        assert tools[0].requires_approval is True
    finally:
        async with sessionmanager.session() as cleanup_session, cleanup_session.begin():
            await cleanup_session.execute(
                sa.delete(MCPServers).where(MCPServers.id == server_id)
            )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_runtime_staging_completes_inside_read_only_request_transaction(
    setup_database: None,
    admin_user,
) -> None:
    async with sessionmanager.session() as seed_session, seed_session.begin():
        server = MCPServers(
            tenant_id=admin_user.tenant_id,
            name=f"tool-request-lifecycle-{uuid4()}",
            http_url="http://localhost:9000/mcp",
            http_auth_type="none",
            is_enabled=True,
            forward_identity=True,
        )
        seed_session.add(server)
        await seed_session.flush()
        server_id = server.id

    outer_session = sessionmanager.create_session()
    try:
        await outer_session.begin()
        await outer_session.scalar(
            sa.select(MCPServers.id).where(MCPServers.id == server_id)
        )
        repo = MCPServerToolRepoImpl(outer_session, MCPServerToolMapper())
        staged = await asyncio.wait_for(
            repo.stage_observed(
                [
                    MCPServerTool.pending_discovery(
                        mcp_server_id=server_id,
                        name="observed-in-request",
                        title=None,
                        description="Observed while the request transaction is open",
                        input_schema={"type": "object"},
                    )
                ]
            ),
            timeout=0.5,
        )
        assert [tool.name for tool in staged] == ["observed-in-request"]
        await outer_session.rollback()
    finally:
        await outer_session.close()

    try:
        async with sessionmanager.session() as verify_session, verify_session.begin():
            tools = await MCPServerToolRepoImpl(
                verify_session, MCPServerToolMapper()
            ).by_server(server_id)
        assert [tool.name for tool in tools] == ["observed-in-request"]
    finally:
        async with sessionmanager.session() as cleanup_session, cleanup_session.begin():
            await cleanup_session.execute(
                sa.delete(MCPServers).where(MCPServers.id == server_id)
            )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_runtime_staging_times_out_behind_conflicting_request_lock(
    setup_database: None,
    admin_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from eneo.mcp_servers.infrastructure.repo_impl import (
        mcp_server_tool_repo_impl as repo_module,
    )

    async with sessionmanager.session() as seed_session, seed_session.begin():
        server = MCPServers(
            tenant_id=admin_user.tenant_id,
            name=f"tool-request-lock-{uuid4()}",
            http_url="http://localhost:9000/mcp",
            http_auth_type="none",
            is_enabled=True,
            forward_identity=True,
        )
        seed_session.add(server)
        await seed_session.flush()
        server_id = server.id

    monkeypatch.setattr(repo_module, "MCP_TOOL_CATALOG_STAGE_TIMEOUT_SECONDS", 0.1)
    outer_session = sessionmanager.create_session()
    try:
        await outer_session.begin()
        await outer_session.scalar(
            sa.select(MCPServers.id).where(MCPServers.id == server_id).with_for_update()
        )
        repo = MCPServerToolRepoImpl(outer_session, MCPServerToolMapper())
        with pytest.raises(MCPToolCatalogStagingTimeout):
            await repo.stage_observed(
                [
                    MCPServerTool.pending_discovery(
                        mcp_server_id=server_id,
                        name="blocked-observation",
                        title=None,
                        description="Must not be partially written",
                        input_schema={"type": "object"},
                    )
                ]
            )
        await outer_session.rollback()
    finally:
        await outer_session.close()

    try:
        async with sessionmanager.session() as verify_session, verify_session.begin():
            tools = await MCPServerToolRepoImpl(
                verify_session, MCPServerToolMapper()
            ).by_server(server_id)
        assert tools == []
    finally:
        async with sessionmanager.session() as cleanup_session, cleanup_session.begin():
            await cleanup_session.execute(
                sa.delete(MCPServers).where(MCPServers.id == server_id)
            )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_runtime_discovery_rejects_disjoint_catalog_beyond_persisted_limit(
    setup_database: None,
    admin_user,
) -> None:
    async with sessionmanager.session() as seed_session, seed_session.begin():
        server = MCPServers(
            tenant_id=admin_user.tenant_id,
            name=f"tool-union-count-{uuid4()}",
            http_url="http://localhost:9000/mcp",
            http_auth_type="none",
            is_enabled=True,
            forward_identity=True,
            tool_catalog_max_count=2,
            tool_catalog_max_bytes=1024 * 1024,
        )
        seed_session.add(server)
        await seed_session.flush()
        server_id = server.id

    def observation(name: str) -> MCPServerTool:
        return MCPServerTool.pending_discovery(
            mcp_server_id=server_id,
            name=name,
            title=None,
            description=f"Contract for {name}",
            input_schema={"type": "object", "properties": {}},
        )

    try:
        async with sessionmanager.session() as first_session, first_session.begin():
            repo = MCPServerToolRepoImpl(first_session, MCPServerToolMapper())
            await repo.stage_observed([observation("first"), observation("second")])

        async with sessionmanager.session() as rejected_session:
            async with rejected_session.begin():
                repo = MCPServerToolRepoImpl(rejected_session, MCPServerToolMapper())
                with pytest.raises(ValueError, match="persisted tool catalog"):
                    await repo.stage_observed([observation("third")])

        async with sessionmanager.session() as verify_session, verify_session.begin():
            tools = await MCPServerToolRepoImpl(
                verify_session, MCPServerToolMapper()
            ).by_server(server_id)
        assert [tool.name for tool in tools] == ["first", "second"]
    finally:
        async with sessionmanager.session() as cleanup_session, cleanup_session.begin():
            await cleanup_session.execute(
                sa.delete(MCPServers).where(MCPServers.id == server_id)
            )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_identity_admin_refresh_cannot_grow_persisted_union_past_limit(
    setup_database: None,
    admin_user,
) -> None:
    async with sessionmanager.session() as seed_session, seed_session.begin():
        server_row = MCPServers(
            tenant_id=admin_user.tenant_id,
            name=f"admin-union-count-{uuid4()}",
            http_url="http://localhost:9000/mcp",
            http_auth_type="none",
            is_enabled=True,
            forward_identity=True,
            tool_catalog_max_count=2,
            tool_catalog_max_bytes=1024 * 1024,
        )
        seed_session.add(server_row)
        await seed_session.flush()
        server_id = server_row.id

    server = MCPServer(
        id=server_id,
        tenant_id=admin_user.tenant_id,
        name="admin-union-count",
        http_url="http://localhost:9000/mcp",
        forward_identity=True,
        tool_catalog_max_count=2,
        tool_catalog_max_bytes=1024 * 1024,
    )
    live_catalog = [
        {"name": "first", "description": "first", "input_schema": {}},
        {"name": "second", "description": "second", "input_schema": {}},
    ]

    class CatalogClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def list_tools(self):
            return list(live_catalog)

    try:
        async with sessionmanager.session() as service_session, service_session.begin():
            service = MCPServerService(
                mcp_server_repo=AsyncMock(),
                mcp_server_tool_repo=MCPServerToolRepoImpl(
                    service_session, MCPServerToolMapper()
                ),
                user=admin_user,
                mcp_state_repo=AsyncMock(),
            )
            with patch(
                "eneo.mcp_servers.application.mcp_server_service.MCPClient",
                CatalogClient,
            ):
                first = await service.discover_and_sync_tools(server)
                assert first.connection.success is True
                live_catalog[:] = [
                    {"name": "third", "description": "third", "input_schema": {}}
                ]
                rejected = await service.discover_and_sync_tools(server)
                assert rejected.connection.success is False

        async with sessionmanager.session() as verify_session, verify_session.begin():
            tools = await MCPServerToolRepoImpl(
                verify_session, MCPServerToolMapper()
            ).by_server(server_id)
        assert [tool.name for tool in tools] == ["first", "second"]
    finally:
        async with sessionmanager.session() as cleanup_session, cleanup_session.begin():
            await cleanup_session.execute(
                sa.delete(MCPServers).where(MCPServers.id == server_id)
            )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_runtime_and_admin_refresh_share_one_bounded_catalog_union(
    setup_database: None,
    admin_user,
) -> None:
    async with sessionmanager.session() as seed_session, seed_session.begin():
        server_row = MCPServers(
            tenant_id=admin_user.tenant_id,
            name=f"mixed-union-count-{uuid4()}",
            http_url="http://localhost:9000/mcp",
            http_auth_type="none",
            is_enabled=True,
            forward_identity=True,
            tool_catalog_max_count=1,
            tool_catalog_max_bytes=1024 * 1024,
        )
        seed_session.add(server_row)
        await seed_session.flush()
        server_id = server_row.id

    server = MCPServer(
        id=server_id,
        tenant_id=admin_user.tenant_id,
        name="mixed-union-count",
        http_url="http://localhost:9000/mcp",
        forward_identity=True,
        tool_catalog_max_count=1,
        tool_catalog_max_bytes=1024 * 1024,
    )

    class CatalogClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def list_tools(self):
            return [
                {
                    "name": "admin-observed",
                    "description": "admin",
                    "input_schema": {},
                }
            ]

    async def admin_refresh():
        async with sessionmanager.session() as service_session, service_session.begin():
            service = MCPServerService(
                mcp_server_repo=AsyncMock(),
                mcp_server_tool_repo=MCPServerToolRepoImpl(
                    service_session, MCPServerToolMapper()
                ),
                user=admin_user,
                mcp_state_repo=AsyncMock(),
            )
            return await service.discover_and_sync_tools(server)

    async def runtime_observation():
        async with sessionmanager.session() as runtime_session, runtime_session.begin():
            return await MCPServerToolRepoImpl(
                runtime_session, MCPServerToolMapper()
            ).stage_observed(
                [
                    MCPServerTool.pending_discovery(
                        mcp_server_id=server_id,
                        name="runtime-observed",
                        title=None,
                        description="runtime",
                        input_schema={},
                    )
                ]
            )

    try:
        with patch(
            "eneo.mcp_servers.application.mcp_server_service.MCPClient", CatalogClient
        ):
            refresh_result, runtime_result = await asyncio.gather(
                admin_refresh(), runtime_observation(), return_exceptions=True
            )

        successful_refresh = (
            not isinstance(refresh_result, BaseException)
            and refresh_result.connection.success
        )
        successful_runtime = isinstance(runtime_result, list)
        assert int(successful_refresh) + int(successful_runtime) == 1

        async with sessionmanager.session() as verify_session, verify_session.begin():
            tools = await MCPServerToolRepoImpl(
                verify_session, MCPServerToolMapper()
            ).by_server(server_id)
        assert len(tools) == 1
        assert tools[0].name in {"admin-observed", "runtime-observed"}
    finally:
        async with sessionmanager.session() as cleanup_session, cleanup_session.begin():
            await cleanup_session.execute(
                sa.delete(MCPServers).where(MCPServers.id == server_id)
            )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_disjoint_catalogs_cannot_exceed_persisted_byte_limit(
    setup_database: None,
    admin_user,
) -> None:
    async with sessionmanager.session() as seed_session, seed_session.begin():
        server = MCPServers(
            tenant_id=admin_user.tenant_id,
            name=f"tool-union-bytes-{uuid4()}",
            http_url="http://localhost:9000/mcp",
            http_auth_type="none",
            is_enabled=True,
            forward_identity=True,
            tool_catalog_max_count=10,
            tool_catalog_max_bytes=4096,
        )
        seed_session.add(server)
        await seed_session.flush()
        server_id = server.id

    async def stage(name: str) -> list[MCPServerTool]:
        async with sessionmanager.session() as session, session.begin():
            return await MCPServerToolRepoImpl(
                session, MCPServerToolMapper()
            ).stage_observed(
                [
                    MCPServerTool.pending_discovery(
                        mcp_server_id=server_id,
                        name=name,
                        title=None,
                        description="x" * 3000,
                        input_schema={"type": "object", "properties": {}},
                    )
                ]
            )

    try:
        results = await asyncio.gather(
            stage("catalog-a"), stage("catalog-b"), return_exceptions=True
        )
        assert sum(isinstance(result, list) for result in results) == 1
        assert (
            sum(
                isinstance(result, ValueError)
                and "persisted tool catalog" in str(result)
                for result in results
            )
            == 1
        )

        async with sessionmanager.session() as verify_session, verify_session.begin():
            tools = await MCPServerToolRepoImpl(
                verify_session, MCPServerToolMapper()
            ).by_server(server_id)
        assert len(tools) == 1
        assert tools[0].name in {"catalog-a", "catalog-b"}
        assert len(tools[0].pending_description or "") == 3000
    finally:
        async with sessionmanager.session() as cleanup_session, cleanup_session.begin():
            await cleanup_session.execute(
                sa.delete(MCPServers).where(MCPServers.id == server_id)
            )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_runtime_staging_queues_approved_drift_once(
    setup_database: None,
    admin_user,
) -> None:
    original_schema = {"type": "object", "properties": {}}
    changed_schema = {
        "type": "object",
        "properties": {"location": {"type": "string"}},
    }
    async with sessionmanager.session() as seed_session, seed_session.begin():
        server = MCPServers(
            tenant_id=admin_user.tenant_id,
            name=f"tool-drift-{uuid4()}",
            http_url="http://localhost:9000/mcp",
            http_auth_type="none",
            is_enabled=True,
            forward_identity=True,
        )
        seed_session.add(server)
        await seed_session.flush()
        server_id = server.id
        repo = MCPServerToolRepoImpl(seed_session, MCPServerToolMapper())
        await repo.upsert_by_server_and_name(
            MCPServerTool(
                mcp_server_id=server_id,
                name="ordinary_only",
                description="Approved contract",
                input_schema=original_schema,
            )
        )

    try:
        async with sessionmanager.session() as stage_session, stage_session.begin():
            repo = MCPServerToolRepoImpl(stage_session, MCPServerToolMapper())
            staged = await repo.stage_observed(
                [
                    MCPServerTool.pending_discovery(
                        mcp_server_id=server_id,
                        name="ordinary_only",
                        title=None,
                        description="Changed contract",
                        input_schema=changed_schema,
                    )
                ]
            )
            assert len(staged) == 1

        async with sessionmanager.session() as later_session, later_session.begin():
            repo = MCPServerToolRepoImpl(later_session, MCPServerToolMapper())
            await repo.stage_observed(
                [
                    MCPServerTool.pending_discovery(
                        mcp_server_id=server_id,
                        name="ordinary_only",
                        title=None,
                        description="Later unreviewed contract",
                        input_schema={"type": "object", "required": ["other"]},
                    )
                ]
            )

        async with sessionmanager.session() as verify_session, verify_session.begin():
            [tool] = await MCPServerToolRepoImpl(
                verify_session, MCPServerToolMapper()
            ).by_server(server_id)
        assert tool.description == "Approved contract"
        assert tool.input_schema == original_schema
        assert tool.pending_description == "Changed contract"
        assert tool.pending_input_schema == changed_schema
        assert tool.requires_approval is True
    finally:
        async with sessionmanager.session() as cleanup_session, cleanup_session.begin():
            await cleanup_session.execute(
                sa.delete(MCPServers).where(MCPServers.id == server_id)
            )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_protocol_session_claims_return_one_winner(
    setup_database: None,
    admin_user,
) -> None:
    async with sessionmanager.session() as seed_session, seed_session.begin():
        server = MCPServers(
            tenant_id=admin_user.tenant_id,
            name=f"session-claim-{uuid4()}",
            http_url="http://localhost:9000/mcp",
            http_auth_type="none",
            is_enabled=True,
            forward_identity=True,
        )
        chat_session = Sessions(
            user_id=admin_user.id,
            name="Concurrent MCP session claim",
        )
        seed_session.add_all([server, chat_session])
        await seed_session.flush()
        server_id = server.id
        chat_session_id = chat_session.id

    async def claim(candidate: str) -> str | None:
        async with sessionmanager.session() as session:
            return await ChatSessionMcpStateRepo(session).claim(
                chat_session_id,
                server_id,
                candidate_mcp_session_id=candidate,
                expected_mcp_session_id=None,
                identity_policy_generation=0,
            )

    try:
        winners = await asyncio.gather(claim("protocol-a"), claim("protocol-b"))
        assert len(set(winners)) == 1
        assert winners[0] in {"protocol-a", "protocol-b"}
    finally:
        async with sessionmanager.session() as cleanup_session, cleanup_session.begin():
            await cleanup_session.execute(
                sa.delete(Sessions).where(Sessions.id == chat_session_id)
            )
            await cleanup_session.execute(
                sa.delete(MCPServers).where(MCPServers.id == server_id)
            )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_expired_session_replacements_return_current_winner(
    setup_database: None,
    admin_user,
) -> None:
    async with sessionmanager.session() as seed_session, seed_session.begin():
        server = MCPServers(
            tenant_id=admin_user.tenant_id,
            name=f"session-replacement-{uuid4()}",
            http_url="http://localhost:9000/mcp",
            http_auth_type="none",
            is_enabled=True,
            forward_identity=True,
        )
        chat_session = Sessions(
            user_id=admin_user.id,
            name="Concurrent expired MCP session replacement",
        )
        seed_session.add_all([server, chat_session])
        await seed_session.flush()
        server_id = server.id
        chat_session_id = chat_session.id

    async def claim(candidate: str, expected: str | None) -> str | None:
        async with sessionmanager.session() as session:
            return await ChatSessionMcpStateRepo(session).claim(
                chat_session_id,
                server_id,
                candidate_mcp_session_id=candidate,
                expected_mcp_session_id=expected,
                identity_policy_generation=0,
            )

    try:
        assert await claim("expired", None) == "expired"
        winners = await asyncio.gather(
            claim("replacement-a", "expired"),
            claim("replacement-b", "expired"),
        )
        assert len(set(winners)) == 1
        assert winners[0] in {"replacement-a", "replacement-b"}
    finally:
        async with sessionmanager.session() as cleanup_session, cleanup_session.begin():
            await cleanup_session.execute(
                sa.delete(Sessions).where(Sessions.id == chat_session_id)
            )
            await cleanup_session.execute(
                sa.delete(MCPServers).where(MCPServers.id == server_id)
            )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_first_session_claim_crossing_identity_toggle_is_rejected(
    setup_database: None,
    admin_user,
) -> None:
    async with sessionmanager.session() as seed_session, seed_session.begin():
        server = MCPServers(
            tenant_id=admin_user.tenant_id,
            name=f"session-generation-{uuid4()}",
            http_url="http://localhost:9000/mcp",
            http_auth_type="none",
            is_enabled=True,
            forward_identity=False,
        )
        chat_session = Sessions(
            user_id=admin_user.id,
            name="MCP identity generation barrier",
        )
        seed_session.add_all([server, chat_session])
        await seed_session.flush()
        server_id = server.id
        chat_session_id = chat_session.id

    claim_ready = asyncio.Event()
    toggle_committed = asyncio.Event()

    async def old_generation_claim() -> str | None:
        claim_ready.set()
        await toggle_committed.wait()
        async with sessionmanager.session() as claim_session:
            return await ChatSessionMcpStateRepo(claim_session).claim(
                chat_session_id,
                server_id,
                candidate_mcp_session_id="old-policy-session",
                expected_mcp_session_id=None,
                identity_policy_generation=0,
            )

    claim_task = asyncio.create_task(old_generation_claim())
    await claim_ready.wait()
    try:
        async with sessionmanager.session() as toggle_session, toggle_session.begin():
            await toggle_session.execute(
                sa.update(MCPServers)
                .where(MCPServers.id == server_id)
                .values(identity_policy_generation=1, forward_identity=True)
            )
            await ChatSessionMcpStateRepo(toggle_session).delete_for_server(server_id)
        toggle_committed.set()

        assert await claim_task is None
        async with sessionmanager.session() as verify_session, verify_session.begin():
            state = await verify_session.scalar(
                sa.select(ChatSessionMcpState.mcp_session_id).where(
                    ChatSessionMcpState.chat_session_id == chat_session_id,
                    ChatSessionMcpState.mcp_server_id == server_id,
                )
            )
        assert state is None
    finally:
        toggle_committed.set()
        if not claim_task.done():
            claim_task.cancel()
        async with sessionmanager.session() as cleanup_session, cleanup_session.begin():
            await cleanup_session.execute(
                sa.delete(Sessions).where(Sessions.id == chat_session_id)
            )
            await cleanup_session.execute(
                sa.delete(MCPServers).where(MCPServers.id == server_id)
            )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_server_session_invalidation_joins_the_callers_transaction(
    setup_database: None,
    admin_user,
) -> None:
    async with sessionmanager.session() as seed_session, seed_session.begin():
        server = MCPServers(
            tenant_id=admin_user.tenant_id,
            name=f"session-invalidation-{uuid4()}",
            http_url="http://localhost:9000/mcp",
            http_auth_type="none",
            is_enabled=True,
            forward_identity=False,
        )
        chat_session = Sessions(
            user_id=admin_user.id,
            name="MCP identity-mode invalidation",
        )
        seed_session.add_all([server, chat_session])
        await seed_session.flush()
        server_id = server.id
        chat_session_id = chat_session.id

    async with sessionmanager.session() as claim_session:
        winner = await ChatSessionMcpStateRepo(claim_session).claim(
            chat_session_id,
            server_id,
            candidate_mcp_session_id="protocol-before-toggle",
            expected_mcp_session_id=None,
            identity_policy_generation=0,
        )
        assert winner == "protocol-before-toggle"

    async with sessionmanager.session() as rollback_session:
        async with rollback_session.begin():
            repo = ChatSessionMcpStateRepo(rollback_session)
            await repo.delete_for_server(server_id)
            assert await repo.get(chat_session_id, server_id, 0) is None
            await rollback_session.rollback()

    async with sessionmanager.session() as verify_session:
        assert (
            await ChatSessionMcpStateRepo(verify_session).get(
                chat_session_id, server_id, 0
            )
            == "protocol-before-toggle"
        )

    async with sessionmanager.session() as delete_session:
        async with delete_session.begin():
            await ChatSessionMcpStateRepo(delete_session).delete_for_server(server_id)

    async with sessionmanager.session() as stale_session:
        stale_winner = await ChatSessionMcpStateRepo(stale_session).claim(
            chat_session_id,
            server_id,
            candidate_mcp_session_id="protocol-stale-after-toggle",
            expected_mcp_session_id="protocol-before-toggle",
            identity_policy_generation=0,
        )
        assert stale_winner is None

    async with sessionmanager.session() as final_session:
        assert (
            await ChatSessionMcpStateRepo(final_session).get(
                chat_session_id, server_id, 0
            )
            is None
        )

    async with sessionmanager.session() as cleanup_session, cleanup_session.begin():
        await cleanup_session.execute(
            sa.delete(Sessions).where(Sessions.id == chat_session_id)
        )
        await cleanup_session.execute(
            sa.delete(MCPServers).where(MCPServers.id == server_id)
        )
