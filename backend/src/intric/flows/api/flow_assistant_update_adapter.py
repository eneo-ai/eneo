from __future__ import annotations

from intric.assistants.api.assistant_models import AssistantUpdatePublic
from intric.flows.application.flow_assistant_update import FlowAssistantUpdateCommand


def to_flow_assistant_update_command(
    assistant: AssistantUpdatePublic,
) -> FlowAssistantUpdateCommand:
    payload = assistant.model_dump(exclude_unset=True)
    command_fields: dict[str, object] = {
        "data_retention_days": assistant.data_retention_days,
    }
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
        attachments = assistant.attachments or []
        command_fields["attachment_ids"] = [attachment.id for attachment in attachments]
    if "mcp_servers" in payload:
        command_fields["mcp_server_ids"] = [
            server.id for server in (assistant.mcp_servers or [])
        ]
    if "mcp_tools" in payload:
        tools = assistant.mcp_tools or []
        command_fields["mcp_tools"] = [
            (tool.tool_id, tool.is_enabled) for tool in tools
        ]
    if "completion_model" in payload:
        command_fields["completion_model_id"] = (
            assistant.completion_model.id
            if assistant.completion_model is not None
            else None
        )
    if "completion_model_kwargs" in payload:
        command_fields["completion_model_kwargs"] = assistant.completion_model_kwargs

    if "description" in payload:
        command_fields["description"] = assistant.description
    if "metadata_json" in payload:
        command_fields["metadata_json"] = assistant.metadata_json
    if "icon_id" in payload:
        command_fields["icon_id"] = assistant.icon_id

    if "name" in payload:
        command_fields["name"] = assistant.name
    if "prompt" in payload:
        command_fields["prompt"] = assistant.prompt
    if "logging_enabled" in payload:
        command_fields["logging_enabled"] = assistant.logging_enabled
    if "insight_enabled" in payload:
        command_fields["insight_enabled"] = assistant.insight_enabled

    return FlowAssistantUpdateCommand.model_validate(command_fields)
