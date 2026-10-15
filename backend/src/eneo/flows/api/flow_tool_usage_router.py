"""The published flows that call an MCP server's tools, for the instance
administrator who switches the server or its tools off or changes them."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path
from pydantic import BaseModel, Field

from eneo.authentication.endpoint_access import Authentication, endpoint_access
from eneo.flows.infrastructure.published_tool_usage import (
    PUBLISHED_TOOL_USAGE_MAX_LISTED,
    PublishedFlowToolUse,
    PublishedToolUsage,
)
from eneo.main.container.container import Container
from eneo.roles.permissions import Permission
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses

router = APIRouter()


class PublishedFlowToolUsePublic(BaseModel):
    flow_id: UUID = Field(description="The flow.")
    flow_name: str = Field(description="The flow's name.")
    space_id: UUID = Field(description="The space the flow belongs to.")
    space_name: str = Field(description="The space's name.")
    published_version: int = Field(
        description="The flow's published version, the one its runs use."
    )
    tool_ids: list[UUID] = Field(
        description=(
            "Each tool of the server that a step of the published version "
            "calls, once, in id order."
        )
    )

    @classmethod
    def from_use(cls, use: PublishedFlowToolUse) -> PublishedFlowToolUsePublic:
        return cls(
            flow_id=use.flow_id,
            flow_name=use.flow_name,
            space_id=use.space_id,
            space_name=use.space_name,
            published_version=use.published_version,
            tool_ids=list(use.tool_ids),
        )


class PublishedToolUsagePublic(BaseModel):
    total_count: int = Field(
        description="How many published flows call a tool of the server."
    )
    items: list[PublishedFlowToolUsePublic] = Field(
        description=(
            f"The first {PUBLISHED_TOOL_USAGE_MAX_LISTED} of those flows, by "
            "space name, then flow name."
        )
    )

    @classmethod
    def from_usage(cls, usage: PublishedToolUsage) -> PublishedToolUsagePublic:
        return cls(
            total_count=usage.total_count,
            items=[PublishedFlowToolUsePublic.from_use(use) for use in usage.flows],
        )


@router.get(
    "/{mcp_server_id}/flow-usage",
    response_model=PublishedToolUsagePublic,
    operation_id="list_mcp_server_flow_usage",
    summary="List the published flows that use an MCP server",
    description=(
        "The flows whose published version has a step that calls a tool of the "
        "server, with the tools each one calls, so an administrator sees which "
        "flows a change to the server or a tool affects. A draft that is not "
        "published, an unpublished flow and a deleted flow are not listed. "
        "`total_count` counts every such flow; `items` lists the first "
        f"{PUBLISHED_TOOL_USAGE_MAX_LISTED}. The read does not look the server "
        "up: a flow published with a server keeps it in its published version "
        "when the server's purpose changes or the server is deleted, so its "
        "id still lists those flows. It needs the admin permission, as "
        "managing MCP servers does."
    ),
    responses=responses.get_responses([403]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Permission.ADMIN,
    reason="Organization administration requires the admin permission.",
)
async def list_mcp_server_flow_usage(
    mcp_server_id: Annotated[UUID, Path(description="The MCP server.")],
    container: Container = Depends(get_container(with_user=True)),
) -> PublishedToolUsagePublic:
    usage = await container.published_tool_usage_reader().read(
        tenant_id=container.user().tenant_id, mcp_server_id=mcp_server_id
    )
    return PublishedToolUsagePublic.from_usage(usage)


__all__ = ["router"]
