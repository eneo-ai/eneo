import asyncio
from uuid import uuid4

import pytest
import sqlalchemy as sa

from eneo.database.database import sessionmanager
from eneo.database.tables.chat_session_mcp_state_table import ChatSessionMcpState
from eneo.database.tables.mcp_server_table import MCPServers
from eneo.database.tables.questions_table import Questions
from eneo.database.tables.sessions_table import Sessions
from eneo.mcp_servers.domain.entities.mcp_server import MCPServerTool
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
        await repo.upsert(chat_session_id, server_id, "protocol-committed")
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
        persisted = await asyncio.wait_for(
            repo.upsert(chat_session.id, server_id, "protocol-not-durable"),
            timeout=0.5,
        )

        assert persisted is False
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
        question_id = await service.create_question_placeholder(
            question="Use the stateful tool",
            session=chat_session,
            files=None,
            assistant_id=None,
            completion_model=None,
        )

        repo = ChatSessionMcpStateRepo(outer_session)
        persisted = await asyncio.wait_for(
            repo.upsert(chat_session.id, server_id, "protocol-first-turn"),
            timeout=0.5,
        )
        assert persisted is True
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

    async def stage(description: str) -> MCPServerTool | None:
        async with sessionmanager.session() as session, session.begin():
            repo = MCPServerToolRepoImpl(session, MCPServerToolMapper())
            return await repo.add_if_absent(
                MCPServerTool.pending_discovery(
                    mcp_server_id=server_id,
                    name="ordinary_only",
                    title="Ordinary only",
                    description=description,
                    input_schema={"type": "object", "properties": {}},
                )
            )

    try:
        staged = await asyncio.gather(stage("first"), stage("second"))
        assert sum(tool is not None for tool in staged) == 1

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
