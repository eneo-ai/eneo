"""mcp_app_views rows are addressed by (server, uri, view hash), where the hash
covers the HTML and its render policy: storing the same view again keeps its
row, a changed HTML or policy gets a new row, a stored row never changes what
it serves, and reads are tenant-fenced in SQL. Storing a view leaves its
server's row free, so the tool staging that follows in a sync can lock it."""

import asyncio
from uuid import uuid4

import sqlalchemy as sa

from eneo.database.database import sessionmanager
from eneo.database.tables.mcp_server_table import MCPServers
from eneo.mcp_apps.domain.mcp_app_view import view_content_hash
from eneo.mcp_apps.infrastructure.repo_impl.mcp_app_view_repo_impl import (
    McpAppViewRepo,
)

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
