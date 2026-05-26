from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, Request, status

from intric.assistants.api.assistant_models import AssistantUpdatePublic
from intric.authentication.auth_dependencies import get_scope_filter
from intric.flows.api.flow_api_common import (
    FlowAccessContext,
    FlowSpaceAccessContext,
    enforce_flow_scope,
    resolve_flow_access_context,
    resolve_space_access_context,
)
from intric.flows.api.flow_models import (
    FlowCreateRequest,
    FlowInputSource,
    FlowInputType,
    FlowUpdateRequest,
)
from intric.flows.application import flow_dispatch
from intric.flows.application.flow_assistant_update import FlowAssistantUpdateCommand
from intric.flows.flow_access_policy import FlowApiAction
from intric.main.container.container import Container

dispatch_flow_run_after_commit = flow_dispatch.dispatch_flow_run_after_commit
dispatch_flow_run_recoverably_after_commit = (
    flow_dispatch.dispatch_flow_run_recoverably_after_commit
)


def find_classification_overrides(
    flow_data: FlowCreateRequest | FlowUpdateRequest,
) -> list[int]:
    steps = flow_data.steps
    if not steps:
        return []
    return [
        step.step_order
        for step in steps
        if step.output_classification_override is not None
    ]


def extract_assistant_update_payload(
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


def required_uuid(value: UUID | None, *, field: str) -> UUID:
    if value is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Expected non-null UUID for {field}.",
        )
    return value


async def enforce_flow_scope_for_request(
    request: Request,
    container: Container,
    *,
    flow_id: UUID,
    required_access: FlowApiAction = FlowApiAction.VIEW,
    require_flow_lookup_without_scope: bool = False,
    allow_service_key_principals: bool = False,
    require_published_for_service_key: bool = False,
) -> None:
    await enforce_flow_scope(
        request,
        container,
        flow_id=flow_id,
        required_access=required_access,
        require_flow_lookup_without_scope=require_flow_lookup_without_scope,
        allow_service_key_principals=allow_service_key_principals,
        require_published_for_service_key=require_published_for_service_key,
        scope_filter_getter=get_scope_filter,
    )


async def get_flow_access_context_for_request(
    request: Request,
    container: Container,
    *,
    flow_id: UUID,
    required_access: FlowApiAction = FlowApiAction.VIEW,
    load_actor_context: bool = True,
    allow_service_key_principals: bool = False,
    require_published_for_service_key: bool = False,
) -> FlowAccessContext:
    return await resolve_flow_access_context(
        request,
        container,
        flow_id=flow_id,
        required_access=required_access,
        allow_service_key_principals=allow_service_key_principals,
        require_published_for_service_key=require_published_for_service_key,
        scope_filter_getter=get_scope_filter,
        load_actor_context=load_actor_context,
    )


async def get_space_access_context_for_request(
    request: Request,
    container: Container,
    *,
    space_id: UUID,
    required_access: FlowApiAction = FlowApiAction.VIEW,
    scope_mismatch_message: str = "API key space scope does not match requested flow.",
    allow_service_key_principals: bool = False,
) -> FlowSpaceAccessContext:
    return await resolve_space_access_context(
        request,
        container,
        space_id=space_id,
        required_access=required_access,
        allow_service_key_principals=allow_service_key_principals,
        scope_filter_getter=get_scope_filter,
        scope_mismatch_message=scope_mismatch_message,
    )


def coerce_input_type(value: str | None) -> FlowInputType | str | None:
    if value is None:
        return None
    try:
        return FlowInputType(value)
    except ValueError:
        return value


def coerce_input_source(value: str | None) -> FlowInputSource | str | None:
    if value is None:
        return None
    try:
        return FlowInputSource(value)
    except ValueError:
        return value
