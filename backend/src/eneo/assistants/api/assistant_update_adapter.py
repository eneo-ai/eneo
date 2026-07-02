from __future__ import annotations

from eneo.assistants.api.assistant_models import AssistantUpdatePublic
from eneo.assistants.assistant_update import AssistantUpdateCommand


def to_standalone_assistant_update_command(
    assistant: AssistantUpdatePublic,
) -> AssistantUpdateCommand:
    _, command_fields = _extract_common_update_fields(assistant)
    return AssistantUpdateCommand.model_validate(command_fields)


def to_flow_assistant_update_command(
    assistant: AssistantUpdatePublic,
) -> AssistantUpdateCommand:
    payload, command_fields = _extract_common_update_fields(assistant)
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
) -> tuple[dict[str, object], dict[str, object]]:
    payload: dict[str, object] = assistant.model_dump(exclude_unset=True)
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
        command_fields["attachment_ids"] = [
            attachment.id for attachment in (assistant.attachments or [])
        ]
    if "mcp_servers" in payload:
        command_fields["mcp_server_ids"] = [
            server.id for server in (assistant.mcp_servers or [])
        ]
    if "mcp_tools" in payload:
        command_fields["mcp_tools"] = [
            (tool.tool_id, tool.is_enabled) for tool in (assistant.mcp_tools or [])
        ]

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

    return payload, command_fields
