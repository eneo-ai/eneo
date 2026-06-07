"""Space-scoped external knowledge-source capability.

Creates a knowledge source backed by the configured external knowledge provider
and enables it in the space. Gated on space admin (``can_edit_space``): managing a
space's knowledge is an admin-level action, stricter than creating a plain
collection. Granting the source to an assistant is a separate step
(``assistant.set_knowledge``).
"""

from __future__ import annotations

from typing import cast

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


class CreateKnowledgeSourceInput(BaseModel):
    name: str = Field(description="Name for the new knowledge source.")


async def _create_knowledge_source(
    ctx: CapabilityContext, inp: BaseModel
) -> CapabilityResult:
    data = cast(CreateKnowledgeSourceInput, inp)
    server = await ctx.container.external_knowledge_service().create_knowledge_source(
        space=ctx.space, name=data.name
    )
    # Surface the id in the summary so the model can chain set_knowledge.
    return CapabilityResult(
        summary=(
            f"Created knowledge source '{server.name}' "
            f"(mcp_server_id={server.id}) and enabled it in the space. "
            "To use it on this assistant, enable it with set_mcp_server "
            "(enabled=true)."
        ),
        entity_id=server.id,
        data={"mcp_server_id": str(server.id), "name": server.name},
    )


register(
    ConfigCapability(
        id="knowledge_source.create",
        scope=Scope.SPACE,
        input_model=CreateKnowledgeSourceInput,
        permission=lambda actor: actor.can_edit_space(),
        handler=_create_knowledge_source,
        title_en="Create knowledge source",
        title_sv="Skapa kunskapskälla",
        description=(
            "Create an external knowledge source for this space, backed by the "
            "configured knowledge provider, and enable it in the space. Afterwards "
            "grant it to an assistant with set_knowledge."
        ),
        audit_action=ActionType.MCP_SERVER_CREATED,
        audit_entity=EntityType.MCP_SERVER,
        confirm_summary_en="create a knowledge source named '{name}'",
        confirm_summary_sv="skapa en kunskapskälla med namnet '{name}'",
        form_renderable=True,
    )
)
