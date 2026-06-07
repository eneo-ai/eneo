"""Assistant knowledge-grant capability (native collections/websites + MCP servers)."""

from __future__ import annotations

from typing import Any, Optional, cast
from uuid import UUID

from pydantic import BaseModel, Field

from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.config_capabilities.capability import (
    CapabilityContext,
    CapabilityResult,
    ConfigCapability,
    Scope,
)
from intric.config_capabilities.registry import register


class EmptyInput(BaseModel):
    pass


class SetKnowledgeInput(BaseModel):
    collection_ids: Optional[list[UUID]] = Field(
        default=None,
        description="Collection ids to attach; omit to leave unchanged, [] to clear.",
    )
    website_ids: Optional[list[UUID]] = Field(
        default=None,
        description="Website ids to attach; omit to leave unchanged, [] to clear.",
    )
    mcp_server_ids: Optional[list[UUID]] = Field(
        default=None,
        description=(
            "MCP server ids to attach (e.g. a knowledge source); omit to leave "
            "unchanged, [] to clear. May coexist with collections/websites."
        ),
    )


async def _set_knowledge(ctx: CapabilityContext, inp: BaseModel) -> CapabilityResult:
    data = cast(SetKnowledgeInput, inp)
    if (
        data.collection_ids is None
        and data.website_ids is None
        and data.mcp_server_ids is None
    ):
        raise ValueError(
            "Provide at least one of collections, websites, or MCP servers."
        )

    update_kwargs: dict[str, Any] = {}
    parts: list[str] = []
    if data.collection_ids is not None:
        update_kwargs["groups"] = data.collection_ids
        parts.append(f"{len(data.collection_ids)} collection(s)")
    if data.website_ids is not None:
        update_kwargs["websites"] = data.website_ids
        parts.append(f"{len(data.website_ids)} website(s)")
    if data.mcp_server_ids is not None:
        update_kwargs["mcp_server_ids"] = data.mcp_server_ids
        parts.append(f"{len(data.mcp_server_ids)} MCP server(s)")

    await ctx.container.assistant_service().update_assistant(
        assistant_id=ctx.assistant_id, **update_kwargs
    )
    return CapabilityResult(
        summary=f"Knowledge updated: {', '.join(parts)}.", entity_id=ctx.assistant_id
    )


register(
    ConfigCapability(
        id="assistant.set_knowledge",
        scope=Scope.ASSISTANT,
        input_model=SetKnowledgeInput,
        permission=lambda actor: actor.can_edit_assistants(),
        handler=_set_knowledge,
        title_en="Set knowledge",
        title_sv="Ange kunskap",
        description=(
            "Attach knowledge to this assistant: native collections/websites and/or "
            "MCP servers (e.g. a knowledge source). Replace-all per field; to toggle "
            "a single MCP server safely use set_mcp_server instead."
        ),
        audit_action=ActionType.ASSISTANT_UPDATED,
        audit_entity=EntityType.ASSISTANT,
        confirm_summary_en="update the assistant's knowledge",
        confirm_summary_sv="uppdatera assistentens kunskap",
    )
)


async def _list_mcp_servers(
    ctx: CapabilityContext, _inp: BaseModel
) -> CapabilityResult:
    assistant, _ = await ctx.container.assistant_service().get_assistant(
        ctx.assistant_id
    )
    enabled_ids = {server.id for server in assistant.mcp_servers}
    return CapabilityResult(
        summary="",
        data={
            "mcp_servers": [
                {
                    "id": str(server.id),
                    "name": server.name,
                    "is_knowledge_source": server.is_knowledge_source,
                    "enabled_on_assistant": server.id in enabled_ids,
                }
                for server in ctx.space.mcp_servers
            ]
        },
    )


class SetMcpServerInput(BaseModel):
    mcp_server_id: UUID = Field(
        description="The MCP server (knowledge source) id to enable or disable."
    )
    enabled: bool = Field(
        description="True to enable the server on this assistant, false to disable it."
    )


async def _set_mcp_server(ctx: CapabilityContext, inp: BaseModel) -> CapabilityResult:
    data = cast(SetMcpServerInput, inp)
    assistant, _ = await ctx.container.assistant_service().get_assistant(
        ctx.assistant_id
    )
    # Toggle this one server without disturbing the rest of the assistant's set.
    current = [server.id for server in assistant.mcp_servers]
    if data.enabled and data.mcp_server_id not in current:
        current.append(data.mcp_server_id)
    elif not data.enabled:
        current = [sid for sid in current if sid != data.mcp_server_id]
    await ctx.container.assistant_service().update_assistant(
        assistant_id=ctx.assistant_id, mcp_server_ids=current
    )
    verb = "enabled on" if data.enabled else "disabled on"
    return CapabilityResult(
        summary=f"MCP server {verb} the assistant.", entity_id=ctx.assistant_id
    )


register(
    ConfigCapability(
        id="space.list_mcp_servers",
        scope=Scope.SPACE,
        input_model=EmptyInput,
        permission=lambda actor: actor.can_read_space(),
        handler=_list_mcp_servers,
        title_en="List MCP servers",
        title_sv="Lista MCP-servrar",
        description=(
            "List the MCP servers (incl. knowledge sources) available in this space, "
            "with whether each is currently enabled on this assistant."
        ),
        mutating=False,
        confirm=False,
    )
)

register(
    ConfigCapability(
        id="assistant.set_mcp_server",
        scope=Scope.ASSISTANT,
        input_model=SetMcpServerInput,
        permission=lambda actor: actor.can_edit_assistants(),
        handler=_set_mcp_server,
        title_en="Enable/disable MCP server",
        title_sv="Aktivera/inaktivera MCP-server",
        description=(
            "Enable or disable a single MCP server (e.g. a knowledge source) on this "
            "assistant, leaving its other knowledge untouched."
        ),
        audit_action=ActionType.ASSISTANT_UPDATED,
        audit_entity=EntityType.ASSISTANT,
        confirm_summary_en="change an MCP server on the assistant",
        confirm_summary_sv="ändra en MCP-server på assistenten",
        form_renderable=True,
    )
)
