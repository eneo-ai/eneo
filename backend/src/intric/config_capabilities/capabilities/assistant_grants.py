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
            "MCP servers (e.g. a knowledge source). They may be combined."
        ),
        audit_action=ActionType.ASSISTANT_UPDATED,
        audit_entity=EntityType.ASSISTANT,
        confirm_summary_en="update the assistant's knowledge",
        confirm_summary_sv="uppdatera assistentens kunskap",
    )
)
