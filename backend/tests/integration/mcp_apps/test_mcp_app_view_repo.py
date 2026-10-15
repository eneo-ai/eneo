"""mcp_app_views rows are addressed by (server, uri, view hash), where the hash
covers the HTML and its render policy: storing the same view again keeps its
row, a changed HTML or policy gets a new row, a stored row never changes what
it serves, and reads are tenant-fenced in SQL. Storing a view leaves its
server's row free, so the tool staging that follows in a sync can lock it. The
view a tool shows now is found by server and tool, and a conversation that is
read back shows it in place of the view its call was stored with."""

import asyncio
from uuid import uuid4

import sqlalchemy as sa

from eneo.database.database import sessionmanager
from eneo.database.tables.mcp_server_table import MCPServers, MCPServerTools
from eneo.main.config import get_settings
from eneo.mcp_apps.application import current_views
from eneo.mcp_apps.domain.mcp_app_view import view_content_hash
from eneo.mcp_apps.infrastructure.repo_impl.mcp_app_view_repo_impl import (
    McpAppViewRepo,
)
from eneo.questions.question import QuestionAdd, ToolCallInfo

VIEW_URI = "ui://weather/dashboard"


def _hash(html: str, ui_meta: dict | None = None) -> str:
    return view_content_hash(html, ui_meta)


async def _seed_server(tenant_id) -> object:
    async with sessionmanager.session() as session, session.begin():
        server = MCPServers(
            tenant_id=tenant_id,
            name=f"app-views-{uuid4()}",
            http_url="http://localhost:9000/mcp",
            http_auth_type="none",
            is_enabled=True,
        )
        session.add(server)
        await session.flush()
        return server.id


async def test_upsert_is_idempotent_per_content_hash(
    setup_database: None, admin_user
) -> None:
    server_id = await _seed_server(admin_user.tenant_id)
    html = "<html>v1</html>"

    async with sessionmanager.session() as session:
        repo = McpAppViewRepo(session)
        first = await repo.upsert(
            tenant_id=admin_user.tenant_id,
            mcp_server_id=server_id,
            uri=VIEW_URI,
            content_hash=_hash(html, {"prefersBorder": True}),
            html=html,
            ui_meta={"prefersBorder": True},
        )
        second = await repo.upsert(
            tenant_id=admin_user.tenant_id,
            mcp_server_id=server_id,
            uri=VIEW_URI,
            content_hash=_hash(html, {"prefersBorder": True}),
            html=html,
            ui_meta={"prefersBorder": True},
        )

        assert first == second
        row = await repo.get_for_tenant(first, admin_user.tenant_id)
        assert row is not None
        assert row.html == html
        assert row.ui_meta == {"prefersBorder": True}


async def test_same_html_with_another_policy_is_a_new_row_and_the_old_one_stays(
    setup_database: None, admin_user
) -> None:
    server_id = await _seed_server(admin_user.tenant_id)
    html = "<html>v1</html>"
    narrow = {"csp": {"connectDomains": []}}
    wide = {"csp": {"connectDomains": ["https://collect.example"]}}

    async with sessionmanager.session() as session:
        repo = McpAppViewRepo(session)
        approved = await repo.upsert(
            tenant_id=admin_user.tenant_id,
            mcp_server_id=server_id,
            uri=VIEW_URI,
            content_hash=_hash(html, narrow),
            html=html,
            ui_meta=narrow,
        )
        widened = await repo.upsert(
            tenant_id=admin_user.tenant_id,
            mcp_server_id=server_id,
            uri=VIEW_URI,
            content_hash=_hash(html, wide),
            html=html,
            ui_meta=wide,
        )

        assert approved != widened
        row = await repo.get_for_tenant(approved, admin_user.tenant_id)
        assert row is not None
        assert row.ui_meta == narrow


async def test_view_is_found_by_its_hash_only_within_its_tenant(
    setup_database: None, admin_user
) -> None:
    server_id = await _seed_server(admin_user.tenant_id)
    html = "<html>v1</html>"

    async with sessionmanager.session() as session:
        repo = McpAppViewRepo(session)
        view_id = await repo.upsert(
            tenant_id=admin_user.tenant_id,
            mcp_server_id=server_id,
            uri=VIEW_URI,
            content_hash=_hash(html),
            html=html,
            ui_meta=None,
        )

        found = await repo.find_view(
            tenant_id=admin_user.tenant_id,
            mcp_server_id=server_id,
            uri=VIEW_URI,
            content_hash=_hash(html),
        )
        assert found is not None
        assert found.view_id == view_id
        assert (
            await repo.find_view(
                tenant_id=uuid4(),
                mcp_server_id=server_id,
                uri=VIEW_URI,
                content_hash=_hash(html),
            )
            is None
        )
        assert (
            await repo.find_view(
                tenant_id=admin_user.tenant_id,
                mcp_server_id=server_id,
                uri=VIEW_URI,
                content_hash=_hash("<html>v2</html>"),
            )
            is None
        )


async def test_changed_content_creates_new_row(
    setup_database: None, admin_user
) -> None:
    server_id = await _seed_server(admin_user.tenant_id)

    async with sessionmanager.session() as session:
        repo = McpAppViewRepo(session)
        v1 = await repo.upsert(
            tenant_id=admin_user.tenant_id,
            mcp_server_id=server_id,
            uri=VIEW_URI,
            content_hash=_hash("<html>v1</html>"),
            html="<html>v1</html>",
            ui_meta=None,
        )
        v2 = await repo.upsert(
            tenant_id=admin_user.tenant_id,
            mcp_server_id=server_id,
            uri=VIEW_URI,
            content_hash=_hash("<html>v2</html>"),
            html="<html>v2</html>",
            ui_meta=None,
        )

        assert v1 != v2
        old_row = await repo.get_for_tenant(v1, admin_user.tenant_id)
        assert old_row is not None
        assert old_row.html == "<html>v1</html>"


async def test_get_refuses_other_tenant(setup_database: None, admin_user) -> None:
    server_id = await _seed_server(admin_user.tenant_id)

    async with sessionmanager.session() as session:
        repo = McpAppViewRepo(session)
        view_id = await repo.upsert(
            tenant_id=admin_user.tenant_id,
            mcp_server_id=server_id,
            uri=VIEW_URI,
            content_hash=_hash("<html></html>"),
            html="<html></html>",
            ui_meta=None,
        )

        assert await repo.get_for_tenant(view_id, uuid4()) is None


async def test_storing_a_view_leaves_the_server_row_lockable(
    setup_database: None, admin_user
) -> None:
    server_id = await _seed_server(admin_user.tenant_id)
    html = "<html>v1</html>"

    # A sync stores the view while its request's transaction is open, then
    # stages the tools from another transaction that locks the server row.
    async with sessionmanager.session() as session, session.begin():
        await McpAppViewRepo(session).upsert(
            tenant_id=admin_user.tenant_id,
            mcp_server_id=server_id,
            uri=VIEW_URI,
            content_hash=_hash(html),
            html=html,
            ui_meta=None,
        )

        async with asyncio.timeout(2):
            async with sessionmanager.session() as staging, staging.begin():
                locked = await staging.scalar(
                    sa.select(MCPServers.id)
                    .where(MCPServers.id == server_id)
                    .with_for_update()
                )

    assert locked == server_id


async def _release_view(tenant_id, server_id, name: str, html: str) -> object:
    """Store ``html`` as a new view of ``server_id`` and approve it for its tool.

    The address changes with the content, as the built-in runtime's does.
    """
    uri = f"ui://charts/{name}.html"
    async with sessionmanager.session() as session:
        view_id = await McpAppViewRepo(session).upsert(
            tenant_id=tenant_id,
            mcp_server_id=server_id,
            uri=uri,
            content_hash=_hash(html),
            html=html,
            ui_meta=None,
        )
    async with sessionmanager.session() as session, session.begin():
        updated = await session.execute(
            sa.update(MCPServerTools)
            .where(
                MCPServerTools.mcp_server_id == server_id,
                MCPServerTools.name == "create_chart",
            )
            .values(meta={"ui": {"resourceUri": uri}}, ui_resource_sha256=_hash(html))
        )
        if updated.rowcount == 0:
            session.add(
                MCPServerTools(
                    mcp_server_id=server_id,
                    name="create_chart",
                    description="Draw a chart",
                    meta={"ui": {"resourceUri": uri}},
                    ui_resource_sha256=_hash(html),
                )
            )
    return view_id


async def test_the_view_a_tool_shows_now_follows_its_releases(
    setup_database: None, admin_user
) -> None:
    server_id = await _seed_server(admin_user.tenant_id)
    tool = (server_id, "create_chart")
    first = await _release_view(admin_user.tenant_id, server_id, "chart-1", "<p>1</p>")
    async with sessionmanager.session() as session:
        repo = McpAppViewRepo(session)
        assert (await repo.approved_for_tools([tool]))[tool].view_id == first

    second = await _release_view(admin_user.tenant_id, server_id, "chart-2", "<p>2</p>")
    async with sessionmanager.session() as session:
        repo = McpAppViewRepo(session)
        shown = await repo.approved_for_tools([tool, (server_id, "other_tool")])
        assert set(shown) == {tool}
        assert shown[tool].view_id == second
        # The earlier release is kept but is no longer what a link is given for.
        assert (
            await repo.get_for_tenant(first, admin_user.tenant_id, approved_only=True)
            is None
        )

    async with sessionmanager.session() as session, session.begin():
        await session.execute(
            sa.update(MCPServerTools)
            .where(MCPServerTools.mcp_server_id == server_id)
            .values(is_enabled_by_default=False)
        )
    async with sessionmanager.session() as session:
        assert await McpAppViewRepo(session).approved_for_tools([tool]) == {}


async def test_a_conversation_read_back_shows_the_view_approved_now(
    db_container, admin_user, monkeypatch
) -> None:
    settings = get_settings().model_copy(update={"mcp_apps_enabled": True})
    monkeypatch.setattr(current_views, "get_settings", lambda: settings)
    server_id = await _seed_server(admin_user.tenant_id)
    first = await _release_view(admin_user.tenant_id, server_id, "chart-1", "<p>1</p>")

    async with db_container() as container:
        session_service = container.session_service()
        conversation = await session_service.create_session(name="charts")
        await container.question_repo().add(
            QuestionAdd(
                question="draw",
                answer="here",
                num_tokens_question=0,
                num_tokens_answer=0,
                tenant_id=admin_user.tenant_id,
                session_id=conversation.id,
                tool_calls=[
                    ToolCallInfo(
                        server_name="charts",
                        tool_name="create_chart",
                        tool_call_id="call_1",
                        app_view={
                            "view_id": str(first),
                            "mcp_server_id": str(server_id),
                            "ui": {},
                        },
                    )
                ],
            )
        )

    second = await _release_view(admin_user.tenant_id, server_id, "chart-2", "<p>2</p>")

    async with db_container() as container:
        read = await container.session_service().get_session_by_uuid(conversation.id)
        call = read.questions[0].tool_calls[0]
        assert call.app_view is not None
        assert call.app_view["view_id"] == str(second)
