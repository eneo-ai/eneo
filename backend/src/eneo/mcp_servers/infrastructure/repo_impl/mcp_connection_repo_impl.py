"""SQLAlchemy implementation of the MCP connection-state lookups."""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa

from eneo.database.tables.idp_user_tokens_table import IdpUserTokens
from eneo.database.tables.mcp_exchanged_tokens_table import MCPExchangedTokens

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class MCPConnectionRepositoryImpl:
    def __init__(self, session: "AsyncSession"):
        self.session = session

    async def get_user_idp_issuers(self, user_id: UUID) -> set[str]:
        rows = (
            (
                await self.session.execute(
                    sa.select(IdpUserTokens.idp_issuer).where(
                        IdpUserTokens.user_id == user_id,
                        IdpUserTokens.revoked_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        return {row.rstrip("/") for row in rows}

    async def get_exchanged_tokens_by_server(
        self, *, tenant_id: UUID, user_id: UUID
    ) -> dict[UUID, datetime]:
        rows = (
            await self.session.execute(
                sa.select(
                    MCPExchangedTokens.mcp_server_id,
                    MCPExchangedTokens.expires_at,
                ).where(
                    MCPExchangedTokens.tenant_id == tenant_id,
                    sa.or_(
                        sa.and_(
                            MCPExchangedTokens.subject_type == "user",
                            MCPExchangedTokens.subject_id == user_id,
                        ),
                        sa.and_(
                            MCPExchangedTokens.subject_type == "tenant",
                            MCPExchangedTokens.subject_id == tenant_id,
                        ),
                    ),
                )
            )
        ).all()
        return {row.mcp_server_id: row.expires_at for row in rows}
