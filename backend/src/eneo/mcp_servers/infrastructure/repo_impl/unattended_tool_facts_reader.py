from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Load, joinedload

from eneo.database.tables.mcp_server_table import (
    MCPServers,
    MCPServerTools,
    MCPServerToolSettings,
    SpacesMCPServers,
    SpacesMCPServerTools,
)
from eneo.database.tables.security_classifications_table import (
    SecurityClassification as SecurityClassificationTable,
)
from eneo.database.tables.spaces_table import Spaces
from eneo.main.exceptions import NotFoundException
from eneo.mcp_servers.application.unattended_tool_use import UnattendedToolFacts
from eneo.mcp_servers.infrastructure.mappers.mcp_server_mapper import (
    MCPServerMapper,
    MCPServerToolMapper,
)
from eneo.security_classifications.domain.entities.security_classification import (
    SecurityClassification,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


# The type SQLAlchemy gives the row. Every member after the space is None when
# an outer join found nothing stored, which this type cannot say.
_FactRow = tuple[Spaces, MCPServers, MCPServerTools, bool, UUID, bool]


def _facts_select() -> "sa.Select[_FactRow]":
    """What one row of facts is made of, read as it is stored now.

    Both statements below start from this, so a tool's facts are the same
    whether it was asked for or listed. A classification's tenant carries
    whether classification is in use at all, which the comparison asks.
    """
    return (
        sa.select(
            Spaces,
            MCPServers,
            MCPServerTools,
            MCPServerToolSettings.is_enabled,
            SpacesMCPServers.mcp_server_id,
            SpacesMCPServerTools.is_enabled,
        )
        .select_from(Spaces)
        .options(
            Load(Spaces).raiseload("*"),
            Load(MCPServers).raiseload("*"),
            joinedload(Spaces.security_classification).joinedload(
                SecurityClassificationTable.tenant
            ),
            joinedload(MCPServers.security_classification).joinedload(
                SecurityClassificationTable.tenant
            ),
        )
        .execution_options(populate_existing=True)
    )


class UnattendedToolFactsReader:
    """Reads what every level has stored about a tool for one space.

    One statement reads every fact, so the decision is taken on rows as they
    were stored together at one moment. Read one after another, a server that
    was switched off and a tool that was approved just after could be combined
    into facts no level ever allowed.

    The statement runs in the caller's transaction and reads what is stored
    now: the session's own copy of a row it already holds is not reused but
    overwritten, and the relationships that copy had loaded are unloaded with
    it. A caller that keeps such a copy (of the space, the server, the tool,
    or a classification or tenant these point to) loads its relationships
    again before it reads them.

    None of the rows is read through a projection made for a space or an
    assistant: those have already applied the switches, so they cannot say
    which level switched a tool off, and the space's has no review state.
    """

    def __init__(self, session: "AsyncSession") -> None:
        self._session = session

    async def read(
        self, *, tenant_id: UUID, space_id: UUID, mcp_server_id: UUID, tool_id: UUID
    ) -> UnattendedToolFacts:
        """The facts for ``tool_id`` of ``mcp_server_id`` in ``space_id``.

        A server or tool that is not stored, and a tool that is not the asked
        server's, is an absent fact, which the decision refuses. An unknown
        space raises NotFoundException instead: the caller asks for the space
        of a flow, which exists as long as the flow does, so there is no
        refusal an author could be told.
        """
        # Every join names at most one row, by its primary key.
        row = (
            await self._session.execute(
                _facts_select()
                .outerjoin(
                    MCPServers,
                    sa.and_(
                        MCPServers.id == mcp_server_id,
                        MCPServers.tenant_id == tenant_id,
                    ),
                )
                .outerjoin(
                    MCPServerTools,
                    sa.and_(
                        MCPServerTools.id == tool_id,
                        MCPServerTools.mcp_server_id == MCPServers.id,
                    ),
                )
                .outerjoin(
                    MCPServerToolSettings,
                    sa.and_(
                        MCPServerToolSettings.tenant_id == tenant_id,
                        MCPServerToolSettings.mcp_server_tool_id == tool_id,
                    ),
                )
                .outerjoin(
                    SpacesMCPServers,
                    sa.and_(
                        SpacesMCPServers.space_id == Spaces.id,
                        SpacesMCPServers.mcp_server_id == mcp_server_id,
                    ),
                )
                .outerjoin(
                    SpacesMCPServerTools,
                    sa.and_(
                        SpacesMCPServerTools.space_id == Spaces.id,
                        SpacesMCPServerTools.mcp_server_tool_id == tool_id,
                    ),
                )
                .where(Spaces.id == space_id, Spaces.tenant_id == tenant_id)
            )
        ).one_or_none()
        if row is None:
            raise NotFoundException()
        return _facts(row)

    async def read_tools_of_space(
        self, *, tenant_id: UUID, space_id: UUID
    ) -> list[UnattendedToolFacts]:
        """The facts for every tool of every server ``space_id`` has activated.

        For a caller that shows an author what can be chosen: each tool with
        what the decision would say about it now, the refused ones included.
        Ordered by server name, then tool name. Empty for a space that has
        activated no server, and for one that does not exist.
        """
        rows = await self._session.execute(
            _facts_select()
            .join(SpacesMCPServers, SpacesMCPServers.space_id == Spaces.id)
            .join(
                MCPServers,
                sa.and_(
                    MCPServers.id == SpacesMCPServers.mcp_server_id,
                    MCPServers.tenant_id == tenant_id,
                ),
            )
            .join(MCPServerTools, MCPServerTools.mcp_server_id == MCPServers.id)
            .outerjoin(
                MCPServerToolSettings,
                sa.and_(
                    MCPServerToolSettings.tenant_id == tenant_id,
                    MCPServerToolSettings.mcp_server_tool_id == MCPServerTools.id,
                ),
            )
            .outerjoin(
                SpacesMCPServerTools,
                sa.and_(
                    SpacesMCPServerTools.space_id == Spaces.id,
                    SpacesMCPServerTools.mcp_server_tool_id == MCPServerTools.id,
                ),
            )
            .where(Spaces.id == space_id, Spaces.tenant_id == tenant_id)
            .order_by(MCPServers.name, MCPServers.id, MCPServerTools.name)
        )
        return [_facts(row) for row in rows]


def _facts(row: "sa.Row[_FactRow]") -> UnattendedToolFacts:
    space, server, tool, tenant_setting, activated_server_id, space_override = row
    return UnattendedToolFacts(
        server=MCPServerMapper.to_entity(server) if server is not None else None,
        tool=MCPServerToolMapper.to_entity(tool) if tool is not None else None,
        tenant_setting=tenant_setting,
        space_is_personal=space.user_id is not None,
        server_in_space=activated_server_id is not None,
        space_override=space_override,
        space_security_classification=SecurityClassification.to_domain(
            space.security_classification
        ),
    )
