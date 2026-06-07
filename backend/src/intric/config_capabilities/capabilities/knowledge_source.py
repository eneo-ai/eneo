"""Space-scoped external knowledge-source capability.

Creates a knowledge source backed by the configured external knowledge provider
and enables it in the space. Gated on space admin (``can_edit_space``): managing a
space's knowledge is an admin-level action, stricter than creating a plain
collection. Granting the source to an assistant is a separate step
(``assistant.set_knowledge``).
"""

from __future__ import annotations

from typing import cast
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


class IngestFilesInput(BaseModel):
    knowledge_source_id: UUID = Field(
        description="Id of the existing knowledge source to add the files to."
    )
    file_ids: list[UUID] = Field(
        description=(
            "Ids of already-uploaded files to add. Use the 'id' from the attached "
            "file references in the conversation."
        )
    )


async def _ingest_files(ctx: CapabilityContext, inp: BaseModel) -> CapabilityResult:
    data = cast(IngestFilesInput, inp)
    count = await ctx.container.external_knowledge_service().ingest_files(
        space=ctx.space,
        knowledge_source_id=data.knowledge_source_id,
        file_ids=data.file_ids,
    )
    return CapabilityResult(
        summary=f"Added {count} file(s) to the knowledge source.",
        entity_id=data.knowledge_source_id,
        data={"ingested": count},
    )


register(
    ConfigCapability(
        id="knowledge_source.ingest_files",
        scope=Scope.SPACE,
        input_model=IngestFilesInput,
        permission=lambda actor: actor.can_edit_space(),
        handler=_ingest_files,
        title_en="Add files to knowledge source",
        title_sv="Lägg till filer i kunskapskälla",
        description=(
            "Add already-uploaded files to an EXISTING knowledge source. Eneo hands "
            "the provider signed download URLs and the provider fetches them. Do not "
            "create a new knowledge source to hold attached files; use this instead."
        ),
        audit_action=ActionType.MCP_SERVER_UPDATED,
        audit_entity=EntityType.MCP_SERVER,
        confirm_summary_en="add the selected files to the knowledge source",
        confirm_summary_sv="lägg till de valda filerna i kunskapskällan",
        form_renderable=True,
    )
)
