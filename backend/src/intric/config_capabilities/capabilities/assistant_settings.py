"""Assistant-scoped settings capabilities."""

from __future__ import annotations

from typing import TYPE_CHECKING, Awaitable, Callable, Optional, cast
from uuid import UUID

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from intric.actors.actors.space_actor import SpaceActor

from intric.ai_models.completion_models.completion_model import ModelKwargs
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.config_capabilities.capability import (
    CapabilityContext,
    CapabilityResult,
    ConfigCapability,
    Scope,
)
from intric.config_capabilities.registry import register
from intric.prompts.api.prompt_models import PromptCreate


class EmptyInput(BaseModel):
    pass


class SetNameInput(BaseModel):
    name: str = Field(description="The new display name for the assistant.")


class SetCompletionModelInput(BaseModel):
    completion_model_id: UUID = Field(
        description="The id of the completion model to use for this assistant."
    )


class SetPromptInput(BaseModel):
    text: str = Field(description="The new system prompt text for the assistant.")
    description: Optional[str] = Field(
        default=None, description="Optional label for this prompt version."
    )


class SetDescriptionInput(BaseModel):
    description: Optional[str] = Field(
        default=None, description="Public description of the assistant (or null)."
    )


class SetInsightEnabledInput(BaseModel):
    insight_enabled: bool = Field(
        description="Whether insights/analytics are enabled for this assistant."
    )


class SetDataRetentionInput(BaseModel):
    data_retention_days: Optional[int] = Field(
        default=None, description="Days to retain conversations; null for no limit."
    )


class SetAttachmentsInput(BaseModel):
    attachment_ids: list[UUID] = Field(
        description="Ids of already-uploaded files to attach as inline instructions "
        "(send [] to clear)."
    )


class McpToolSetting(BaseModel):
    tool_id: UUID
    is_enabled: bool


class SetMcpToolsInput(BaseModel):
    mcp_tools: list[McpToolSetting] = Field(
        description="Per-tool enable/disable overrides for the assistant's MCP tools."
    )


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


async def _set_completion_model(
    ctx: CapabilityContext, inp: BaseModel
) -> CapabilityResult:
    data = cast(SetCompletionModelInput, inp)
    assistant, _ = await ctx.container.assistant_service().update_assistant(
        assistant_id=ctx.assistant_id, completion_model_id=data.completion_model_id
    )
    model = assistant.completion_model
    label = model.name if model is not None else str(data.completion_model_id)
    return CapabilityResult(
        summary=f"Completion model set to '{label}'.", entity_id=ctx.assistant_id
    )


async def _set_prompt(ctx: CapabilityContext, inp: BaseModel) -> CapabilityResult:
    data = cast(SetPromptInput, inp)
    await ctx.container.assistant_service().update_assistant(
        assistant_id=ctx.assistant_id,
        prompt=PromptCreate(text=data.text, description=data.description),
    )
    return CapabilityResult(
        summary="System prompt updated.", entity_id=ctx.assistant_id
    )


async def _set_behavior(ctx: CapabilityContext, inp: BaseModel) -> CapabilityResult:
    data = cast(ModelKwargs, inp)
    await ctx.container.assistant_service().update_assistant(
        assistant_id=ctx.assistant_id, completion_model_kwargs=data
    )
    return CapabilityResult(
        summary="Model behavior updated.", entity_id=ctx.assistant_id
    )


async def _set_description(ctx: CapabilityContext, inp: BaseModel) -> CapabilityResult:
    data = cast(SetDescriptionInput, inp)
    await ctx.container.assistant_service().update_assistant(
        assistant_id=ctx.assistant_id, description=data.description
    )
    return CapabilityResult(summary="Description updated.", entity_id=ctx.assistant_id)


async def _set_insight_enabled(
    ctx: CapabilityContext, inp: BaseModel
) -> CapabilityResult:
    data = cast(SetInsightEnabledInput, inp)
    await ctx.container.assistant_service().update_assistant(
        assistant_id=ctx.assistant_id, insight_enabled=data.insight_enabled
    )
    state = "enabled" if data.insight_enabled else "disabled"
    return CapabilityResult(summary=f"Insights {state}.", entity_id=ctx.assistant_id)


async def _set_data_retention_days(
    ctx: CapabilityContext, inp: BaseModel
) -> CapabilityResult:
    data = cast(SetDataRetentionInput, inp)
    await ctx.container.assistant_service().update_assistant(
        assistant_id=ctx.assistant_id, data_retention_days=data.data_retention_days
    )
    return CapabilityResult(
        summary="Data retention updated.", entity_id=ctx.assistant_id
    )


async def _set_attachments(ctx: CapabilityContext, inp: BaseModel) -> CapabilityResult:
    data = cast(SetAttachmentsInput, inp)
    await ctx.container.assistant_service().update_assistant(
        assistant_id=ctx.assistant_id, attachment_ids=data.attachment_ids
    )
    return CapabilityResult(
        summary=f"Attachments set ({len(data.attachment_ids)}).",
        entity_id=ctx.assistant_id,
    )


async def _set_mcp_tools(ctx: CapabilityContext, inp: BaseModel) -> CapabilityResult:
    data = cast(SetMcpToolsInput, inp)
    await ctx.container.assistant_service().update_assistant(
        assistant_id=ctx.assistant_id,
        mcp_tools=[(tool.tool_id, tool.is_enabled) for tool in data.mcp_tools],
    )
    return CapabilityResult(
        summary="MCP tool settings updated.", entity_id=ctx.assistant_id
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


def _register_setter(
    *,
    id: str,
    input_model: type[BaseModel],
    handler: Callable[[CapabilityContext, BaseModel], Awaitable[CapabilityResult]],
    title_en: str,
    title_sv: str,
    description: str,
    confirm_en: str,
    confirm_sv: str,
    permission: Optional[Callable[["SpaceActor"], bool]] = None,
) -> None:
    register(
        ConfigCapability(
            id=id,
            scope=Scope.ASSISTANT,
            input_model=input_model,
            permission=permission or (lambda actor: actor.can_edit_assistants()),
            handler=handler,
            title_en=title_en,
            title_sv=title_sv,
            description=description,
            audit_action=ActionType.ASSISTANT_UPDATED,
            audit_entity=EntityType.ASSISTANT,
            confirm_summary_en=confirm_en,
            confirm_summary_sv=confirm_sv,
            form_renderable=True,
        )
    )


_register_setter(
    id="assistant.set_completion_model",
    input_model=SetCompletionModelInput,
    handler=_set_completion_model,
    title_en="Set completion model",
    title_sv="Välj språkmodell",
    description="Set the completion (language) model this assistant uses.",
    confirm_en="change the completion model",
    confirm_sv="byta språkmodell",
)

_register_setter(
    id="assistant.set_prompt",
    input_model=SetPromptInput,
    handler=_set_prompt,
    title_en="Set system prompt",
    title_sv="Ange systemprompt",
    description="Replace the assistant's system prompt (instructions) text.",
    confirm_en="update the system prompt",
    confirm_sv="uppdatera systemprompten",
)

_register_setter(
    id="assistant.set_behavior",
    input_model=ModelKwargs,
    handler=_set_behavior,
    title_en="Set model behavior",
    title_sv="Ange modellbeteende",
    description=(
        "Set model behavior parameters (e.g. temperature, top_p). Values unsupported "
        "by the selected model are ignored."
    ),
    confirm_en="adjust the model behavior",
    confirm_sv="justera modellbeteendet",
)

_register_setter(
    id="assistant.set_description",
    input_model=SetDescriptionInput,
    handler=_set_description,
    title_en="Set description",
    title_sv="Ange beskrivning",
    description="Set the assistant's public description.",
    confirm_en="update the description",
    confirm_sv="uppdatera beskrivningen",
)

_register_setter(
    id="assistant.set_insight_enabled",
    input_model=SetInsightEnabledInput,
    handler=_set_insight_enabled,
    title_en="Toggle insights",
    title_sv="Växla insikter",
    description="Enable or disable insights/analytics for this assistant.",
    confirm_en="toggle insights",
    confirm_sv="växla insikter",
    permission=lambda actor: actor.can_toggle_insight(),
)

_register_setter(
    id="assistant.set_data_retention_days",
    input_model=SetDataRetentionInput,
    handler=_set_data_retention_days,
    title_en="Set data retention",
    title_sv="Ange datalagring",
    description="Set how many days conversations are retained (null for no limit).",
    confirm_en="change data retention",
    confirm_sv="ändra datalagring",
)

_register_setter(
    id="assistant.set_attachments",
    input_model=SetAttachmentsInput,
    handler=_set_attachments,
    title_en="Set attachments",
    title_sv="Ange bifogade filer",
    description="Replace the assistant's inline-instruction file attachments.",
    confirm_en="update the attachments",
    confirm_sv="uppdatera bifogade filer",
)

_register_setter(
    id="assistant.set_mcp_tools",
    input_model=SetMcpToolsInput,
    handler=_set_mcp_tools,
    title_en="Set MCP tool overrides",
    title_sv="Ange MCP-verktygsval",
    description="Set per-tool enable/disable overrides for the assistant's MCP tools.",
    confirm_en="update MCP tool settings",
    confirm_sv="uppdatera MCP-verktygsinställningar",
)
