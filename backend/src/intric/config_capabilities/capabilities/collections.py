"""Space-scoped collection capabilities."""

from __future__ import annotations

from typing import Optional, cast
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


class CreateCollectionInput(BaseModel):
    name: str = Field(description="Name of the new knowledge collection.")
    embedding_model_id: Optional[UUID] = Field(
        default=None,
        description="Embedding model id; omit to use the space default.",
    )


async def _list_collections(
    ctx: CapabilityContext, _inp: BaseModel
) -> CapabilityResult:
    return CapabilityResult(
        summary="",
        data={
            "collections": [
                {"id": str(c.id), "name": c.name} for c in ctx.space.collections
            ]
        },
    )


async def _create_collection(
    ctx: CapabilityContext, inp: BaseModel
) -> CapabilityResult:
    data = cast(CreateCollectionInput, inp)
    collection = await ctx.container.collection_crud_service().create_collection(
        space_id=cast(UUID, ctx.space.id),
        name=data.name,
        embedding_model_id=data.embedding_model_id,
    )
    return CapabilityResult(
        summary=f"Created collection '{collection.name}'.", entity_id=collection.id
    )


register(
    ConfigCapability(
        id="space.list_collections",
        scope=Scope.SPACE,
        input_model=EmptyInput,
        permission=lambda actor: actor.can_read_collections(),
        handler=_list_collections,
        title_en="List knowledge collections",
        title_sv="Lista kunskapssamlingar",
        description="List the knowledge collections in this assistant's space.",
        mutating=False,
        confirm=False,
    )
)

register(
    ConfigCapability(
        id="collection.create",
        scope=Scope.SPACE,
        input_model=CreateCollectionInput,
        permission=lambda actor: actor.can_create_collections(),
        handler=_create_collection,
        title_en="Create collection",
        title_sv="Skapa samling",
        description="Create a new (empty) knowledge collection in this space.",
        audit_action=ActionType.COLLECTION_CREATED,
        audit_entity=EntityType.COLLECTION,
        confirm_summary_en="create a collection named '{name}'",
        confirm_summary_sv="skapa en samling med namnet '{name}'",
        form_renderable=True,
    )
)
