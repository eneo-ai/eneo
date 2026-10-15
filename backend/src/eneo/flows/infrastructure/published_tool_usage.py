"""Which published flows call the tools of one MCP server.

The answer reads the pins publish writes into the current published version
(``flow_tool_publication.published_input_config``), so a draft that has not
been published again, an older version, an unpublished flow and a deleted flow
do not count: those are not what a run calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, aggregate_order_by
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.tables.flow_tables import Flows, FlowVersions
from eneo.database.tables.spaces_table import Spaces
from eneo.flows.domain.tool_input import TOOL_INPUT_CONFIG_KEY
from eneo.flows.enums import FlowInputSource

# How many flows one answer lists. The count covers every using flow, so an
# administrator sees the size of the effect even when the list is cut; a
# safety bound on the answer, not a policy an administrator tunes.
PUBLISHED_TOOL_USAGE_MAX_LISTED = 100


@dataclass(frozen=True, slots=True)
class PublishedFlowToolUse:
    flow_id: UUID
    flow_name: str
    space_id: UUID
    space_name: str
    published_version: int
    # Each tool of the server the published steps call, once, in id order.
    tool_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class PublishedToolUsage:
    total_count: int
    # The first PUBLISHED_TOOL_USAGE_MAX_LISTED flows by space name, then
    # flow name.
    flows: tuple[PublishedFlowToolUse, ...]


class PublishedToolUsageReader:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def read(self, *, tenant_id: UUID, mcp_server_id: UUID) -> PublishedToolUsage:
        """One statement over the published version of each live flow: the
        flows whose tool steps call ``mcp_server_id``, counted in full and
        listed up to the bound."""
        step = (
            sa.func.jsonb_array_elements(FlowVersions.definition_json["steps"])
            .table_valued(sa.column("value", JSONB))
            .lateral("step")
        )
        pin = step.c.value["input_config"][TOOL_INPUT_CONFIG_KEY]
        tool_id = pin["tool_id"].astext
        uses = (
            sa.select(
                Flows.id.label("flow_id"),
                Flows.name.label("flow_name"),
                Flows.space_id,
                Spaces.name.label("space_name"),
                Flows.published_version,
                sa.func.array_agg(
                    aggregate_order_by(sa.distinct(tool_id), tool_id)
                ).label("tool_ids"),
            )
            .select_from(Flows)
            .join(
                FlowVersions,
                sa.and_(
                    FlowVersions.flow_id == Flows.id,
                    FlowVersions.version == Flows.published_version,
                ),
            )
            .join(Spaces, Spaces.id == Flows.space_id)
            .join(step, sa.true())
            .where(Flows.tenant_id == tenant_id)
            .where(Flows.deleted_at.is_(None))
            .where(step.c.value["input_source"].astext == FlowInputSource.TOOL.value)
            .where(pin["mcp_server_id"].astext == str(mcp_server_id))
            .group_by(Flows.id, Spaces.name)
            .cte("uses")
        )
        rows = (
            await self.session.execute(
                sa.select(uses, sa.func.count().over().label("total_count"))
                .order_by(uses.c.space_name, uses.c.flow_name, uses.c.flow_id)
                .limit(PUBLISHED_TOOL_USAGE_MAX_LISTED)
            )
        ).all()
        return PublishedToolUsage(
            total_count=rows[0].total_count if rows else 0,
            flows=tuple(
                PublishedFlowToolUse(
                    flow_id=row.flow_id,
                    flow_name=row.flow_name,
                    space_id=row.space_id,
                    space_name=row.space_name,
                    published_version=row.published_version,
                    tool_ids=tuple(UUID(value) for value in row.tool_ids),
                )
                for row in rows
            ),
        )
