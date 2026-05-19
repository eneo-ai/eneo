from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request, status

from intric.assistants.api.assistant_assembler import AssistantAssembler
from intric.assistants.api.assistant_models import (
    AssistantPublic,
    AssistantUpdatePublic,
)
from intric.audit.application.audit_metadata import AuditMetadata
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.flows.api import flow_router_common as common
from intric.flows.api.flow_api_common import error_response
from intric.flows.api.flow_models import FlowAssistantCreateRequest
from intric.flows.application.flow_service import FlowService
from intric.main.container.container import Container
from intric.main.exceptions import ErrorCodes, UnauthorizedException
from intric.server.dependencies.container import get_container

router = APIRouter()

_FLOW_ASSISTANT_PUBLIC_EXAMPLE: dict[str, object] = {
    "id": "00000000-0000-0000-0000-000000000201",
    "name": "Flow Step Assistant",
    "space_id": "00000000-0000-0000-0000-000000000020",
    "completion_model_kwargs": {},
    "logging_enabled": False,
    "attachments": [],
    "allowed_attachments": {
        "accepted_file_types": [],
        "limit": {"max_files": 0, "max_size": 0},
    },
    "groups": [],
    "websites": [],
    "integration_knowledge_list": [],
    "mcp_servers": [],
    "mcp_tools": [],
    "published": False,
    "user": {
        "id": "00000000-0000-0000-0000-000000000030",
        "email": "flow-builder@example.com",
        "username": "Flow Builder",
    },
    "tools": {"assistants": []},
    "type": "assistant",
    "description": "Summarizes extracted contract fields into a reviewer-ready note.",
    "insight_enabled": False,
    "metadata_json": {"origin": "flow_managed"},
}


def _get_flow_service(container: Container) -> FlowService:
    return container.flow_service()


def _get_assistant_assembler(container: Container) -> AssistantAssembler:
    return container.assistant_assembler()


async def _require_flow_assistant_access(
    request: Request,
    container: Container,
    *,
    flow_id: UUID,
) -> common.FlowAccessContext:
    access_context = await common.get_flow_access_context_for_request(
        request,
        container,
        flow_id=flow_id,
        required_access=common.FlowApiAction.EDIT,
    )
    if access_context.actor is None or not access_context.actor.can_edit_flows():
        raise UnauthorizedException(
            "You do not have permission to edit flows in this space.",
            code="insufficient_space_permission",
            context={"auth_layer": "space_membership"},
        )
    return access_context


@router.post(
    "/{id}/assistants/",
    response_model=AssistantPublic,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_flow_assistant",
    summary="Create Flow Assistant",
    description=(
        "Create a flow-managed assistant owned by the specified draft flow. Use this "
        "authoring endpoint when a flow editor needs a dedicated assistant for one or "
        "more steps instead of reusing an existing assistant. The created assistant is "
        "returned with the caller's effective permissions and can then be referenced by "
        "step `assistant_id` values in flow create/update payloads."
    ),
    responses={
        201: {
            "description": (
                "Flow-managed assistant created and returned with effective permissions."
            ),
            "content": {
                "application/json": {"example": _FLOW_ASSISTANT_PUBLIC_EXAMPLE}
            },
        },
        403: error_response(
            description="Caller lacks permission or API key scope to manage assistants for this flow.",
            message="API key space scope does not match requested flow.",
            intric_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
        404: error_response(
            description="Flow not found in tenant scope.",
            message="Flow not found.",
            intric_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
    },
)
async def create_flow_assistant(
    id: Annotated[
        UUID,
        Path(
            description="Identifier of the flow that will own the new flow-managed assistant."
        ),
    ],
    request: Request,
    assistant_in: FlowAssistantCreateRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    await _require_flow_assistant_access(request, container, flow_id=id)
    flow_service = _get_flow_service(container)
    assistant_assembler = _get_assistant_assembler(container)
    user = container.user()

    created_assistant, permissions = await flow_service.create_flow_assistant(
        flow_id=id,
        name=assistant_in.name,
    )
    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.ASSISTANT_CREATED,
        entity_type=EntityType.ASSISTANT,
        entity_id=created_assistant.id,
        description=f"Created flow-managed assistant '{created_assistant.name}' for flow {id}",
        metadata=AuditMetadata.standard(
            actor=user,
            target=created_assistant,
            extra={"flow_id": str(id), "origin": "flow_managed"},
        ),
    )
    return assistant_assembler.from_assistant_to_model(
        created_assistant, permissions=permissions
    )


@router.get(
    "/{id}/assistants/{assistant_id}/",
    response_model=AssistantPublic,
    status_code=status.HTTP_200_OK,
    operation_id="get_flow_assistant",
    summary="Get Flow Assistant",
    description=(
        "Return one flow-managed assistant that belongs to the specified flow, together "
        "with effective permissions for the caller. Use this endpoint before rendering "
        "an assistant-edit screen so the UI does not accidentally edit a global or "
        "unrelated assistant. The assistant id must be one owned by this flow."
    ),
    responses={
        200: {
            "description": (
                "Flow-managed assistant returned with effective caller permissions."
            ),
            "content": {
                "application/json": {"example": _FLOW_ASSISTANT_PUBLIC_EXAMPLE}
            },
        },
        403: error_response(
            description="Caller lacks permission or API key scope to access assistants for this flow.",
            message="API key space scope does not match requested flow.",
            intric_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
        404: error_response(
            description="Flow or flow-managed assistant not found in tenant scope.",
            message="Flow assistant not found.",
            intric_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
    },
)
async def get_flow_assistant(
    id: Annotated[
        UUID,
        Path(description="Identifier of the flow that owns the requested assistant."),
    ],
    assistant_id: Annotated[
        UUID, Path(description="Identifier of the flow-managed assistant to return.")
    ],
    request: Request,
    container: Container = Depends(get_container(with_user=True)),
):
    await _require_flow_assistant_access(request, container, flow_id=id)
    flow_service = _get_flow_service(container)
    assistant_assembler = _get_assistant_assembler(container)
    assistant, permissions = await flow_service.get_flow_assistant(
        flow_id=id,
        assistant_id=assistant_id,
    )
    return assistant_assembler.from_assistant_to_model(
        assistant, permissions=permissions
    )


@router.patch(
    "/{id}/assistants/{assistant_id}/",
    response_model=AssistantPublic,
    status_code=status.HTTP_200_OK,
    operation_id="update_flow_assistant",
    summary="Update Flow Assistant",
    description=(
        "Update a flow-managed assistant that belongs to the specified draft flow. "
        "Only fields accepted by `AssistantUpdatePublic` are applied; omitted fields "
        "are left unchanged. Use this endpoint for assistant details that should travel "
        "with the flow authoring experience, not for updating unrelated shared assistants."
    ),
    responses={
        200: {
            "description": (
                "Flow-managed assistant updated and returned with effective permissions."
            ),
            "content": {
                "application/json": {"example": _FLOW_ASSISTANT_PUBLIC_EXAMPLE}
            },
        },
        403: error_response(
            description="Caller lacks permission or API key scope to update assistants for this flow.",
            message="API key space scope does not match requested flow.",
            intric_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
        404: error_response(
            description="Flow or flow-managed assistant not found in tenant scope.",
            message="Flow assistant not found.",
            intric_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
    },
)
async def update_flow_assistant(
    id: Annotated[
        UUID,
        Path(description="Identifier of the flow that owns the assistant to update."),
    ],
    assistant_id: Annotated[
        UUID, Path(description="Identifier of the flow-managed assistant to update.")
    ],
    request: Request,
    assistant_in: AssistantUpdatePublic,
    container: Container = Depends(get_container(with_user=True)),
):
    await _require_flow_assistant_access(request, container, flow_id=id)
    flow_service = _get_flow_service(container)
    assistant_assembler = _get_assistant_assembler(container)
    user = container.user()
    update = common.extract_assistant_update_payload(assistant_in)

    updated_assistant, permissions = await flow_service.update_flow_assistant(
        flow_id=id,
        assistant_id=assistant_id,
        update=update,
    )
    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.ASSISTANT_UPDATED,
        entity_type=EntityType.ASSISTANT,
        entity_id=updated_assistant.id,
        description=f"Updated flow-managed assistant '{updated_assistant.name}' for flow {id}",
        metadata=AuditMetadata.standard(
            actor=user,
            target=updated_assistant,
            extra={"flow_id": str(id), "origin": "flow_managed"},
        ),
    )
    return assistant_assembler.from_assistant_to_model(
        updated_assistant, permissions=permissions
    )


@router.delete(
    "/{id}/assistants/{assistant_id}/",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="delete_flow_assistant",
    summary="Delete Flow Assistant",
    description=(
        "Delete a flow-managed assistant from the specified draft flow. The assistant id "
        "must belong to this flow; deleting it removes the flow-owned assistant resource "
        "and writes an audit event. Clients should remove or replace step references to "
        "the assistant before publishing a draft that no longer has this assistant."
    ),
    responses={
        403: error_response(
            description="Caller lacks permission or API key scope to delete assistants for this flow.",
            message="API key space scope does not match requested flow.",
            intric_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
        404: error_response(
            description="Flow or flow-managed assistant not found in tenant scope.",
            message="Flow assistant not found.",
            intric_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
    },
)
async def delete_flow_assistant(
    id: Annotated[
        UUID,
        Path(description="Identifier of the flow that owns the assistant to delete."),
    ],
    assistant_id: Annotated[
        UUID, Path(description="Identifier of the flow-managed assistant to delete.")
    ],
    request: Request,
    container: Container = Depends(get_container(with_user=True)),
):
    await _require_flow_assistant_access(request, container, flow_id=id)
    flow_service = _get_flow_service(container)
    user = container.user()
    assistant, _ = await flow_service.get_flow_assistant(
        flow_id=id, assistant_id=assistant_id
    )
    await flow_service.delete_flow_assistant(flow_id=id, assistant_id=assistant_id)

    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.ASSISTANT_DELETED,
        entity_type=EntityType.ASSISTANT,
        entity_id=assistant_id,
        description=f"Deleted flow-managed assistant '{assistant.name}' for flow {id}",
        metadata=AuditMetadata.standard(
            actor=user,
            target=assistant,
            extra={"flow_id": str(id), "origin": "flow_managed"},
        ),
    )
