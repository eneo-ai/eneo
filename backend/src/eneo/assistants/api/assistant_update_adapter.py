from __future__ import annotations

from eneo.assistants.api.assistant_models import AssistantUpdatePublic
from eneo.assistants.assistant_update import AssistantUpdateCommand
from eneo.skills.presentation.skill_assembler import (
    assistant_skill_binding_intents_from_input,
)

# Nullable values that a standalone update may clear by sending null. Every
# other field treats null like omission and keeps what is stored, as on
# develop; a list is cleared only by an explicit []. One more exception is
# made before this mapper runs, as on develop: the request model turns a null
# completion_model_kwargs into the default settings, which are then stored.
_STANDALONE_NULL_CLEARS = frozenset(
    {"description", "metadata_json", "icon_id", "data_retention_days"}
)


def to_standalone_assistant_update_command(
    assistant: AssistantUpdatePublic,
) -> AssistantUpdateCommand:
    payload: dict[str, object] = {
        field: value
        for field, value in assistant.model_dump(exclude_unset=True).items()
        if value is not None or field in _STANDALONE_NULL_CLEARS
    }
    _, command_fields = _extract_common_update_fields(assistant, payload)
    # A null model keeps the current one; only Flow steps may clear their model.
    if assistant.completion_model is not None:
        command_fields["completion_model_id"] = assistant.completion_model.id
    return AssistantUpdateCommand.model_validate(command_fields)


def to_flow_assistant_update_command(
    assistant: AssistantUpdatePublic,
) -> AssistantUpdateCommand:
    payload, command_fields = _extract_common_update_fields(
        assistant, assistant.model_dump(exclude_unset=True)
    )
    command_fields["data_retention_days"] = assistant.data_retention_days
    if "completion_model" in payload:
        command_fields["completion_model_id"] = (
            assistant.completion_model.id
            if assistant.completion_model is not None
            else None
        )

    return AssistantUpdateCommand.model_validate(command_fields)


def _extract_common_update_fields(
    assistant: AssistantUpdatePublic,
    payload: dict[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    """Map the fields present in ``payload`` onto the update command."""
    command_fields: dict[str, object] = {}

    if "groups" in payload:
        command_fields["groups"] = [group.id for group in (assistant.groups or [])]
    if "websites" in payload:
        command_fields["websites"] = [
            website.id for website in (assistant.websites or [])
        ]
    if "integration_knowledge_list" in payload:
        command_fields["integration_knowledge_ids"] = [
            knowledge.id for knowledge in (assistant.integration_knowledge_list or [])
        ]
    if "attachments" in payload:
        command_fields["attachments"] = [
            (attachment.id, attachment.inline_text)
            for attachment in (assistant.attachments or [])
        ]
    if "mcp_servers" in payload:
        command_fields["mcp_server_ids"] = [
            server.id for server in (assistant.mcp_servers or [])
        ]
    if "enabled_capabilities" in payload:
        command_fields["enabled_capabilities"] = assistant.enabled_capabilities
    if "mcp_tools" in payload:
        command_fields["mcp_tools"] = [
            (tool.tool_id, tool.is_enabled) for tool in (assistant.mcp_tools or [])
        ]
    if "skill_bindings" in payload:
        command_fields["skill_binding_intents"] = (
            assistant_skill_binding_intents_from_input(assistant.skill_bindings or [])
        )

    if "completion_model_kwargs" in payload:
        command_fields["completion_model_kwargs"] = assistant.completion_model_kwargs
    if "description" in payload:
        command_fields["description"] = assistant.description
    if "metadata_json" in payload:
        command_fields["metadata_json"] = assistant.metadata_json
    if "icon_id" in payload:
        command_fields["icon_id"] = assistant.icon_id
    if "data_retention_days" in payload:
        command_fields["data_retention_days"] = assistant.data_retention_days

    if "name" in payload:
        command_fields["name"] = assistant.name
    if "prompt" in payload:
        command_fields["prompt"] = assistant.prompt
    if "logging_enabled" in payload:
        command_fields["logging_enabled"] = assistant.logging_enabled
    if "insight_enabled" in payload:
        command_fields["insight_enabled"] = assistant.insight_enabled
    if "inline_file_text" in payload:
        command_fields["inline_file_text"] = assistant.inline_file_text
    if "knowledge_mode" in payload:
        command_fields["knowledge_mode"] = assistant.knowledge_mode

    return payload, command_fields
