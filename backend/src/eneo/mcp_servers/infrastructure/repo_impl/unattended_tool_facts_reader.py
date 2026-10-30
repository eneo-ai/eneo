from typing import TYPE_CHECKING, NamedTuple
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Load, aliased, joinedload
from sqlalchemy.sql.elements import SQLCoreOperations

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
from eneo.database.tables.tenant_table import Tenants
from eneo.main.exceptions import NotFoundException
from eneo.mcp_servers.application.unattended_tool_use import (
    ListedServer,
    ListedTool,
    ListedToolFacts,
    StoredToolFacts,
    ToolsOfSpace,
)
from eneo.mcp_servers.domain.entities.mcp_server import (
    GENERAL_PURPOSE,
    INTERNAL_AUTH_TYPE,
)
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


# The text each variable-length field of a listed option comes from, by the
# option's field name. The list's byte budget is the sum of these and of
# _DECISION_TEXT_FIELDS, so a field an option returns outside it would escape
# the bound; a test compares the names with the response model's. The tool's
# name counts because an MCP server bounds it only through the size of the
# whole definition.
LISTED_TEXT_FIELDS: dict[
    str, "SQLCoreOperations[str] | SQLCoreOperations[str | None]"
] = {
    "mcp_server_name": MCPServers.name,
    "tool_name": MCPServerTools.name,
    "tool_description": MCPServerTools.description,
    "input_schema": sa.cast(MCPServerTools.input_schema, sa.Text),
}

# The text counted for every tool that no option returns: the decision
# needs the server's address (server_credential_needs_https), and nothing
# bounds its length, so it counts against the same byte budget.
_DECISION_TEXT_FIELDS: tuple["SQLCoreOperations[str]", ...] = (MCPServers.http_url,)


class _ListedRow(NamedTuple):
    """One row of the list, read by the labels of the select: the server's
    columns and level, the tool's columns, the tenant's and the space's switch
    for the tool, the space's owner and level (each level with its tenant's
    classification switch), and the running sum of the bytes of the counted
    fields (the server name, the server address, the tool name, the approved
    description and the approved input schema). The outer joins' members are None when nothing is stored,
    which their types say.
    """

    server_id: UUID
    server_name: str
    server_is_enabled: bool
    server_purpose: str
    server_http_auth_type: str
    server_http_url: str
    server_forward_identity: bool
    server_level: SecurityClassificationTable | None
    server_security_enabled: bool | None
    tool_id: UUID
    tool_name: str
    tool_description: str | None
    tool_input_schema: dict[str, object] | None
    tool_is_enabled_by_default: bool
    tool_requires_approval: bool
    tool_removed_from_remote: bool
    tenant_setting: bool | None
    space_override: bool | None
    space_owner_id: UUID | None
    space_level: SecurityClassificationTable | None
    space_security_enabled: bool | None
    running_bytes: int


def _facts_select() -> "sa.Select[_FactRow]":
    """What one row of facts for one tool is made of, read as it is stored
    now. A classification's tenant carries whether classification is in use
    at all, which the comparison asks.
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
    ) -> StoredToolFacts:
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
        self,
        *,
        tenant_id: UUID,
        space_id: UUID,
        max_count: int,
        max_text_bytes: int,
    ) -> ToolsOfSpace:
        """The facts for the tools of the general servers ``space_id`` has
        activated, cut where the list crosses a bound, in one statement.

        For a caller that shows an author what can be chosen: each tool with
        what the decision would say about it now, the refused ones included.
        Ordered by server name, then tool name. A server that is not general
        has nothing a flow can choose, so its tools are neither returned nor
        counted. The bytes are those of the server name, the tool name, the
        approved description and the approved input schema, which an option
        returns (``LISTED_TEXT_FIELDS``), and the server's address, which the
        decision reads (``_DECISION_TEXT_FIELDS``); the classification names
        and descriptions the statement also reads are not counted. A pending
        definition is not selected. The rows end after ``max_count`` + 1 tools,
        or after the first tool that brings the bytes over
        ``max_text_bytes``, whichever comes first: a list over a bound
        is returned only as far as it takes to see that. Empty for a space that
        has activated no general server, and for one that does not exist.

        One statement, so the cut and the rows are one moment of the catalog:
        tools a catalog refresh stores meanwhile are in both or in neither.
        """
        text_bytes = sa.literal(0)
        for text in (*LISTED_TEXT_FIELDS.values(), *_DECISION_TEXT_FIELDS):
            text_bytes = text_bytes + sa.func.coalesce(sa.func.octet_length(text), 0)
        # Unique: a server's tool names are (uq_mcp_server_tools_server_name).
        order = (MCPServers.name, MCPServers.id, MCPServerTools.name)
        listed = (
            sa.select(
                MCPServerTools.id.label("tool_id"),
                sa.func.row_number().over(order_by=order).label("position"),
                sa.func.sum(text_bytes)
                .over(order_by=order, rows=(None, 0))
                .label("running_bytes"),
                text_bytes.label("text_bytes"),
            )
            .select_from(Spaces)
            .join(SpacesMCPServers, SpacesMCPServers.space_id == Spaces.id)
            .join(
                MCPServers,
                sa.and_(
                    MCPServers.id == SpacesMCPServers.mcp_server_id,
                    MCPServers.tenant_id == tenant_id,
                    general_server_sql(
                        purpose=MCPServers.purpose,
                        http_auth_type=MCPServers.http_auth_type,
                    ),
                ),
            )
            .join(MCPServerTools, MCPServerTools.mcp_server_id == MCPServers.id)
            .where(Spaces.id == space_id, Spaces.tenant_id == tenant_id)
            .subquery("listed")
        )
        # Named, so the row is read by label and not by position.
        server_level = aliased(SecurityClassificationTable, name="server_level")
        space_level = aliased(SecurityClassificationTable, name="space_level")
        # A level compares only while its tenant has classification switched
        # on; that switch is the one column the list needs of a tenant row.
        server_level_tenant = aliased(Tenants)
        space_level_tenant = aliased(Tenants)
        rows = await self._session.execute(
            sa.select(
                MCPServers.id.label("server_id"),
                MCPServers.name.label("server_name"),
                MCPServers.is_enabled.label("server_is_enabled"),
                MCPServers.purpose.label("server_purpose"),
                MCPServers.http_auth_type.label("server_http_auth_type"),
                MCPServers.http_url.label("server_http_url"),
                MCPServers.forward_identity.label("server_forward_identity"),
                server_level,
                server_level_tenant.security_enabled.label("server_security_enabled"),
                MCPServerTools.id.label("tool_id"),
                MCPServerTools.name.label("tool_name"),
                MCPServerTools.description.label("tool_description"),
                MCPServerTools.input_schema.label("tool_input_schema"),
                MCPServerTools.is_enabled_by_default.label(
                    "tool_is_enabled_by_default"
                ),
                MCPServerTools.requires_approval.label("tool_requires_approval"),
                MCPServerTools.removed_from_remote.label("tool_removed_from_remote"),
                MCPServerToolSettings.is_enabled.label("tenant_setting"),
                SpacesMCPServerTools.is_enabled.label("space_override"),
                Spaces.user_id.label("space_owner_id"),
                space_level,
                space_level_tenant.security_enabled.label("space_security_enabled"),
                listed.c.running_bytes,
            )
            .select_from(listed)
            .join(MCPServerTools, MCPServerTools.id == listed.c.tool_id)
            .join(MCPServers, MCPServers.id == MCPServerTools.mcp_server_id)
            .join(Spaces, Spaces.id == space_id)
            .outerjoin(
                server_level, server_level.id == MCPServers.security_classification_id
            )
            .outerjoin(space_level, space_level.id == Spaces.security_classification_id)
            .outerjoin(
                server_level_tenant, server_level_tenant.id == server_level.tenant_id
            )
            .outerjoin(
                space_level_tenant, space_level_tenant.id == space_level.tenant_id
            )
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
                    SpacesMCPServerTools.space_id == space_id,
                    SpacesMCPServerTools.mcp_server_tool_id == MCPServerTools.id,
                ),
            )
            .where(
                listed.c.position <= max_count + 1,
                listed.c.running_bytes - listed.c.text_bytes <= max_text_bytes,
            )
            .order_by(listed.c.position)
            .execution_options(populate_existing=True)
        )
        listed_rows = [_ListedRow(**row) for row in rows.mappings()]
        return ToolsOfSpace(
            facts=[_listed_facts(row) for row in listed_rows],
            # The running sum of the last row read is the sum of all read.
            text_bytes=int(listed_rows[-1].running_bytes) if listed_rows else 0,
        )


def general_server_sql(
    *, purpose: "SQLCoreOperations[str]", http_auth_type: "SQLCoreOperations[str]"
) -> "sa.ColumnElement[bool]":
    """``is_general_server`` in SQL, for a statement that leaves the other
    servers' tools unread. Like ``is_capability_purpose``, an empty purpose
    is no capability."""
    return sa.and_(
        purpose.in_((GENERAL_PURPOSE, "")),
        http_auth_type != INTERNAL_AUTH_TYPE,
    )


def _listed_facts(row: _ListedRow) -> ListedToolFacts:
    return ListedToolFacts(
        server=ListedServer(
            id=row.server_id,
            name=row.server_name,
            is_enabled=row.server_is_enabled,
            purpose=row.server_purpose,
            http_auth_type=row.server_http_auth_type,
            http_url=row.server_http_url,
            forward_identity=row.server_forward_identity,
            effective_security_classification=SecurityClassification.to_domain(
                row.server_level, tenant_security_enabled=row.server_security_enabled
            ),
        ),
        tool=ListedTool(
            id=row.tool_id,
            mcp_server_id=row.server_id,
            name=row.tool_name,
            description=row.tool_description,
            input_schema=row.tool_input_schema,
            is_enabled_by_default=row.tool_is_enabled_by_default,
            requires_approval=row.tool_requires_approval,
            removed_from_remote=row.tool_removed_from_remote,
        ),
        tenant_setting=row.tenant_setting,
        space_is_personal=row.space_owner_id is not None,
        # Every row came in through the space's activation of its server.
        server_in_space=True,
        space_override=row.space_override,
        space_security_classification=SecurityClassification.to_domain(
            row.space_level, tenant_security_enabled=row.space_security_enabled
        ),
    )


def _facts(row: "sa.Row[_FactRow]") -> StoredToolFacts:
    space, server, tool, tenant_setting, activated_server_id, space_override = row
    return StoredToolFacts(
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
