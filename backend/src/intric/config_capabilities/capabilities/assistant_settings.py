"""Assistant-scoped settings capabilities."""

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


class EmptyInput(BaseModel):
    pass


class SetNameInput(BaseModel):
    name: str = Field(description="The new display name for the assistant.")


async def _get_settings(ctx: CapabilityContext, _inp: BaseModel) -> CapabilityResult:
    assistant, _ = await ctx.container.assistant_service().get_assistant(
        ctx.assistant_id
    )
    model = assistant.completion_model
    return CapabilityResult(
        summary="",
        data={
            "name": assistant.name,
            "prompt": assistant.get_prompt_text(),
            "completion_model": (
                {"id": str(model.id), "name": model.name} if model is not None else None
            ),
            "description": assistant.description,
            "insight_enabled": assistant.insight_enabled,
            "published": assistant.published,
        },
    )


async def _set_name(ctx: CapabilityContext, inp: BaseModel) -> CapabilityResult:
    data = cast(SetNameInput, inp)
    assistant, _ = await ctx.container.assistant_service().update_assistant(
        assistant_id=ctx.assistant_id, name=data.name
    )
    return CapabilityResult(
        summary=f"Name set to '{assistant.name}'.", entity_id=ctx.assistant_id
    )


register(
    ConfigCapability(
        id="assistant.get_settings",
        scope=Scope.ASSISTANT,
        input_model=EmptyInput,
        permission=lambda actor: actor.can_read_assistants(),
        handler=_get_settings,
        title_en="Read assistant settings",
        title_sv="Läs assistentinställningar",
        description="Return the current configurable settings of this assistant.",
        mutating=False,
        confirm=False,
    )
)

register(
    ConfigCapability(
        id="assistant.set_name",
        scope=Scope.ASSISTANT,
        input_model=SetNameInput,
        permission=lambda actor: actor.can_edit_assistants(),
        handler=_set_name,
        title_en="Set name",
        title_sv="Sätt namn",
        description="Set the assistant's display name.",
        audit_action=ActionType.ASSISTANT_UPDATED,
        audit_entity=EntityType.ASSISTANT,
        confirm_summary_en="set the name to '{name}'",
        confirm_summary_sv="ändra namnet till '{name}'",
        form_renderable=True,
    )
)
