from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status

from intric.assistants.api.assistant_models import AssistantPublic, AssistantUpdatePublic
from intric.audit.application.audit_metadata import AuditMetadata
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.flows.api import flow_router_common as common
from intric.flows.api.flow_models import FlowAssistantCreateRequest
from intric.main.container.container import Container
from intric.server.dependencies.container import get_container

router = APIRouter()


@router.post(
    "/{id}/assistants/",
    response_model=AssistantPublic,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_flow_assistant",
)
async def create_flow_assistant(
    id: UUID,
    assistant_in: FlowAssistantCreateRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    flow_service = container.flow_service()
    assistant_assembler = container.assistant_assembler()
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
    return assistant_assembler.from_assistant_to_model(created_assistant, permissions=permissions)


@router.get(
    "/{id}/assistants/{assistant_id}/",
    response_model=AssistantPublic,
    status_code=status.HTTP_200_OK,
    operation_id="get_flow_assistant",
)
async def get_flow_assistant(
    id: UUID,
    assistant_id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    flow_service = container.flow_service()
    assistant_assembler = container.assistant_assembler()
    assistant, permissions = await flow_service.get_flow_assistant(
        flow_id=id,
        assistant_id=assistant_id,
    )
    return assistant_assembler.from_assistant_to_model(assistant, permissions=permissions)


@router.patch(
    "/{id}/assistants/{assistant_id}/",
    response_model=AssistantPublic,
    status_code=status.HTTP_200_OK,
    operation_id="update_flow_assistant",
)
async def update_flow_assistant(
    id: UUID,
    assistant_id: UUID,
    assistant_in: AssistantUpdatePublic,
    container: Container = Depends(get_container(with_user=True)),
):
    flow_service = container.flow_service()
    assistant_assembler = container.assistant_assembler()
    user = container.user()
    update_payload = common.extract_assistant_update_payload(assistant_in)

    updated_assistant, permissions = await flow_service.update_flow_assistant(
        flow_id=id,
        assistant_id=assistant_id,
        **update_payload,
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
    return assistant_assembler.from_assistant_to_model(updated_assistant, permissions=permissions)


@router.delete(
    "/{id}/assistants/{assistant_id}/",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="delete_flow_assistant",
)
async def delete_flow_assistant(
    id: UUID,
    assistant_id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    flow_service = container.flow_service()
    user = container.user()
    assistant, _ = await flow_service.get_flow_assistant(flow_id=id, assistant_id=assistant_id)
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
