"""Persistence for cached MCP App view HTML.

A view is written from a short transaction of its own, never from the
request's. A tool sync stores a server's views and then stages the tools that
pin them, and that staging locks the server row from its own transaction; a
view written by the request would hold the same row through its foreign key
until the request ends, and the staging would wait on it. A stored view is
inert until a tool pins it and an administrator approves it, so keeping one
whose sync later fails costs nothing.
"""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from eneo.database.database import sessionmanager
from eneo.database.tables.mcp_app_views_table import McpAppViews
from eneo.database.tables.mcp_server_table import MCPServers, MCPServerTools
from eneo.mcp_apps.domain.mcp_app_view import (
    MCP_APP_MIME,
    McpAppView,
    McpAppViewInfo,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


# A view is one row; the deadline only keeps a stuck write from holding a sync.
MCP_APP_VIEW_STORE_TIMEOUT_SECONDS = 5.0


class McpAppViewRepo:
    def __init__(self, session: "AsyncSession"):
        self.session = session

    @asynccontextmanager
    async def _tx(self) -> AsyncGenerator[None]:
        if self.session.in_transaction():
            yield
            return
        async with self.session.begin():
            yield

    async def upsert(
        self,
        *,
        tenant_id: UUID,
        mcp_server_id: UUID,
        uri: str,
        content_hash: str,
        html: str,
        ui_meta: Optional[dict[str, Any]],
    ) -> UUID:
        """Insert or refresh one content-addressed view row, returning its id.

        ``content_hash`` covers the HTML and its render policy
        (``view_content_hash``), so a stored row never changes what it serves.
        """
        stmt = (
            pg_insert(McpAppViews)
            .values(
                tenant_id=tenant_id,
                mcp_server_id=mcp_server_id,
                uri=uri,
                content_hash=content_hash,
                html=html,
                ui_meta=ui_meta,
                fetched_at=datetime.now(timezone.utc),
            )
            .on_conflict_do_update(
                constraint="uq_mcp_app_views_server_uri_hash",
                set_={
                    "fetched_at": datetime.now(timezone.utc),
                },
            )
            .returning(McpAppViews.id)
        )
        async with asyncio.timeout(MCP_APP_VIEW_STORE_TIMEOUT_SECONDS):
            async with sessionmanager.session() as session, session.begin():
                view_id = await session.scalar(stmt)
        assert view_id is not None
        return view_id

    async def find_view(
        self, *, tenant_id: UUID, mcp_server_id: UUID, uri: str, content_hash: str
    ) -> Optional[McpAppViewInfo]:
        """The stored view with exactly this content, if there is one."""
        stmt = sa.select(McpAppViews.id, McpAppViews.ui_meta).where(
            McpAppViews.tenant_id == tenant_id,
            McpAppViews.mcp_server_id == mcp_server_id,
            McpAppViews.uri == uri,
            McpAppViews.content_hash == content_hash,
        )
        async with self._tx():
            row = (await self.session.execute(stmt)).one_or_none()
        if row is None:
            return None
        return McpAppViewInfo(
            view_id=row.id,
            mcp_server_id=mcp_server_id,
            uri=uri,
            mime_type=MCP_APP_MIME,
            ui_meta=row.ui_meta,
        )

    async def describe_view(
        self, *, tenant_id: UUID, mcp_server_id: UUID, uri: str, content_hash: str
    ) -> Optional[tuple[int, Optional[dict[str, Any]]]]:
        """The size in bytes and render policy of a stored view, for review."""
        stmt = sa.select(
            sa.func.octet_length(McpAppViews.html), McpAppViews.ui_meta
        ).where(
            McpAppViews.tenant_id == tenant_id,
            McpAppViews.mcp_server_id == mcp_server_id,
            McpAppViews.uri == uri,
            McpAppViews.content_hash == content_hash,
        )
        async with self._tx():
            row = (await self.session.execute(stmt)).one_or_none()
        if row is None:
            return None
        return int(row[0]), row[1]

    async def get_for_tenant(
        self,
        view_id: UUID,
        tenant_id: UUID,
        *,
        approved_only: bool = False,
        tool_name: str | None = None,
    ) -> Optional[McpAppView]:
        """One stored view of the tenant.

        With ``approved_only`` the view must be the one approved for a tool of
        an enabled server: a view stored for review, or left behind by a tool
        that has since changed, is not found.
        """
        stmt = sa.select(McpAppViews).where(
            McpAppViews.id == view_id,
            McpAppViews.tenant_id == tenant_id,
        )
        if approved_only:
            stmt = stmt.where(
                sa.exists().where(
                    MCPServerTools.mcp_server_id == McpAppViews.mcp_server_id,
                    MCPServerTools.ui_resource_sha256 == McpAppViews.content_hash,
                    MCPServerTools.is_enabled_by_default.is_(True),
                    MCPServerTools.removed_from_remote.is_(False),
                    sa.func.coalesce(
                        MCPServerTools.meta["ui"]["resourceUri"].astext,
                        MCPServerTools.meta["ui/resourceUri"].astext,
                    )
                    == McpAppViews.uri,
                    *([MCPServerTools.name == tool_name] if tool_name else []),
                    MCPServers.id == MCPServerTools.mcp_server_id,
                    MCPServers.tenant_id == tenant_id,
                    MCPServers.is_enabled.is_(True),
                )
            )
        async with self._tx():
            row = await self.session.scalar(stmt)
            # Materialize inside the transaction: committing expires ORM
            # attributes, and this session cannot autobegin a refresh.
            if row is None:
                return None
            return McpAppView(
                id=row.id,
                tenant_id=row.tenant_id,
                mcp_server_id=row.mcp_server_id,
                uri=row.uri,
                content_hash=row.content_hash,
                html=row.html,
                ui_meta=row.ui_meta,
                fetched_at=row.fetched_at,
            )
