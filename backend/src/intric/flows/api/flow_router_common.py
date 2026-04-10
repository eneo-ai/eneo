from __future__ import annotations

from typing import Any, cast
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
from intric.flows.flow_file_upload_service import FlowFileUploadService
from intric.main.container.container import Container

dispatch_flow_run_after_commit = flow_dispatch.dispatch_flow_run_after_commit


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
) -> dict[str, Any]:
    payload = assistant.model_dump(exclude_unset=True)
    groups = (
        [group.id for group in (assistant.groups or [])]
        if "groups" in payload
        else None
    )
    websites = (
        [website.id for website in (assistant.websites or [])]
        if "websites" in payload
        else None
    )
    integration_knowledge_ids = (
        [knowledge.id for knowledge in (assistant.integration_knowledge_list or [])]
        if "integration_knowledge_list" in payload
        else None
    )
    attachment_ids = None
    if "attachments" in payload:
        attachments = assistant.attachments or []
        attachment_ids = [attachment.id for attachment in attachments]
    mcp_server_ids = (
        [server.id for server in (assistant.mcp_servers or [])]
        if "mcp_servers" in payload
        else None
    )
    mcp_tools = None
    if "mcp_tools" in payload:
        tools = assistant.mcp_tools or []
        mcp_tools = [(tool.tool_id, tool.is_enabled) for tool in tools]
    completion_model_id = (
        assistant.completion_model.id
        if "completion_model" in payload and assistant.completion_model is not None
        else None
    )
    completion_model_kwargs = (
        assistant.completion_model_kwargs
        if "completion_model_kwargs" in payload
        else None
    )

    description: str | Any = (
        cast(str, payload["description"]) if "description" in payload else None
    )
    metadata_json: dict[str, Any] | None | Any = (
        cast(dict[str, Any] | None, payload["metadata_json"])
        if "metadata_json" in payload
        else None
    )

    icon_id: UUID | None | Any = None
    if "icon_id" in payload:
        icon_id = cast(UUID | None, payload["icon_id"])

    from intric.main.models import NOT_PROVIDED

    if "description" not in payload:
        description = NOT_PROVIDED
    if "metadata_json" not in payload:
        metadata_json = NOT_PROVIDED
    if "icon_id" not in payload:
        icon_id = NOT_PROVIDED

    return {
        "name": assistant.name,
        "prompt": assistant.prompt,
        "completion_model_id": completion_model_id,
        "completion_model_kwargs": completion_model_kwargs,
        "logging_enabled": assistant.logging_enabled,
        "groups": groups,
        "websites": websites,
        "integration_knowledge_ids": integration_knowledge_ids,
        "mcp_server_ids": mcp_server_ids,
        "mcp_tools": mcp_tools,
        "attachment_ids": attachment_ids,
        "description": description,
        "insight_enabled": assistant.insight_enabled,
        "data_retention_days": assistant.data_retention_days,
        "metadata_json": metadata_json,
        "icon_id": icon_id,
    }


def required_uuid(value: UUID | None, *, field: str) -> UUID:
    if value is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Expected non-null UUID for {field}.",
        )
    return value


def flow_upload_service(container: Container) -> FlowFileUploadService:
    return FlowFileUploadService(
        flow_service=cast(Any, container.flow_service()),  # pyright: ignore[reportUnknownMemberType]
        file_service=container.file_service(),
        settings_service=cast(Any, container.settings_service()),  # pyright: ignore[reportUnknownMemberType]
        flow_version_repo=cast(Any, container.flow_version_repo()),  # pyright: ignore[reportUnknownMemberType]
        template_asset_repo=cast(Any, container.flow_template_asset_repo()),  # pyright: ignore[reportUnknownMemberType]
    )


async def enforce_flow_scope_for_request(
    request: Request,
    container: Container,
    *,
    flow_id: UUID,
    required_access: str = "view",
    require_flow_lookup_without_scope: bool = False,
) -> None:
    await enforce_flow_scope(
        request,
        container,
        flow_id=flow_id,
        required_access=required_access,
        require_flow_lookup_without_scope=require_flow_lookup_without_scope,
        scope_filter_getter=get_scope_filter,
    )


async def get_flow_access_context_for_request(
    request: Request,
    container: Container,
    *,
    flow_id: UUID,
    required_access: str = "view",
    load_actor_context: bool = True,
) -> FlowAccessContext:
    return await resolve_flow_access_context(
        request,
        container,
        flow_id=flow_id,
        required_access=required_access,
        scope_filter_getter=get_scope_filter,
        load_actor_context=load_actor_context,
    )


async def get_space_access_context_for_request(
    request: Request,
    container: Container,
    *,
    space_id: UUID,
    required_access: str = "view",
    scope_mismatch_message: str = "API key space scope does not match requested flow.",
) -> FlowSpaceAccessContext:
    return await resolve_space_access_context(
        request,
        container,
        space_id=space_id,
        required_access=required_access,
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
