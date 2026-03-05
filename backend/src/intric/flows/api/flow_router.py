from __future__ import annotations

import logging
from typing import Any, cast
from uuid import UUID

from dependency_injector import providers
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)

from intric.assistants.api.assistant_models import (
    AssistantPublic,
    AssistantUpdatePublic,
)
from intric.audit.application.audit_metadata import AuditMetadata
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.authentication.auth_dependencies import get_scope_filter
from intric.database.database import sessionmanager
from intric.files.file_models import FilePublic
from intric.flows.flow import FlowRunStatus
from intric.flows.api.flow_assembler import FlowAssembler
from intric.flows.api.flow_api_common import enforce_flow_scope, error_response
from intric.flows.api.flow_graph import build_graph_from_steps, enrich_nodes_with_run_results
from intric.flows.api.flow_models import (
    FlowAssistantCreateRequest,
    FlowCreateRequest,
    FlowInputSource,
    FlowInputPolicyPublic,
    FlowInputType,
    FlowPublic,
    FlowRunCreateRequest,
    FlowRunEvidenceResponse,
    FlowRunPublic,
    FlowRunRedispatchResponse,
    FlowRunStepPublic,
    FlowSparsePublic,
    FlowUpdateRequest,
    GraphResponse,
)
from intric.flows.flow_file_upload_service import FlowFileUploadService
from intric.main.container.container import Container
from intric.main.exceptions import ErrorCodes
from intric.main.models import NOT_PROVIDED, NotProvided, PaginatedResponse
from intric.server.dependencies.container import get_container

router = APIRouter()
logger = logging.getLogger(__name__)


async def _dispatch_flow_run_after_commit(
    *,
    run_id: UUID,
    flow_id: UUID,
    tenant_id: UUID,
    user_id: UUID | None,
) -> None:
    async with sessionmanager.session() as session:
        container = Container(session=providers.Object(session))
        backend = container.flow_execution_backend()
        run_repo = container.flow_run_repo()
        try:
            await backend.dispatch(
                run_id=run_id,
                flow_id=flow_id,
                tenant_id=tenant_id,
                user_id=user_id,
            )
        except Exception:
            logger.exception(
                "flow_dispatch_after_commit_failed run_id=%s flow_id=%s tenant_id=%s",
                run_id,
                flow_id,
                tenant_id,
            )
            async with session.begin():
                await run_repo.update_status(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    status=FlowRunStatus.FAILED,
                    # Keep consumer-facing run errors stable and non-sensitive.
                    error_message=(
                        "flow_dispatch_failed: "
                        "Flow dispatch failed before execution started. "
                        "Retry creating a new run."
                    ),
                )


def _find_classification_overrides(flow_data: FlowCreateRequest | FlowUpdateRequest) -> list[int]:
    steps = flow_data.steps
    if not steps:
        return []
    return [
        step.step_order
        for step in steps
        if step.output_classification_override is not None
    ]


def _extract_assistant_update_payload(assistant: AssistantUpdatePublic) -> dict[str, Any]:
    payload = assistant.model_dump(exclude_unset=True)
    groups = [group.id for group in assistant.groups] if "groups" in payload else None
    websites = [website.id for website in assistant.websites] if "websites" in payload else None
    integration_knowledge_ids = (
        [knowledge.id for knowledge in assistant.integration_knowledge_list]
        if "integration_knowledge_list" in payload
        else None
    )
    attachment_ids = None
    if "attachments" in payload:
        attachments = assistant.attachments or []
        attachment_ids = [attachment.id for attachment in attachments]
    mcp_server_ids = (
        [server.id for server in assistant.mcp_servers]
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
        assistant.completion_model_kwargs if "completion_model_kwargs" in payload else None
    )

    description: str | NotProvided = (
        cast(str, payload["description"]) if "description" in payload else NOT_PROVIDED
    )
    metadata_json: dict[str, Any] | None | NotProvided = (
        cast(dict[str, Any] | None, payload["metadata_json"])
        if "metadata_json" in payload
        else NOT_PROVIDED
    )

    icon_id = NOT_PROVIDED
    if "icon_id" in payload:
        icon_id = cast(UUID | None, payload["icon_id"])

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


def _required_uuid(value: UUID | None, *, field: str) -> UUID:
    if value is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Expected non-null UUID for {field}.",
        )
    return value


def _flow_upload_service(container: Container) -> FlowFileUploadService:
    return FlowFileUploadService(
        flow_service=container.flow_service(),
        file_service=container.file_service(),
        settings_service=container.settings_service(),
    )


async def _enforce_flow_scope(
    request: Request,
    container: Container,
    *,
    flow_id: UUID,
    require_flow_lookup_without_scope: bool = False,
) -> None:
    await enforce_flow_scope(
        request,
        container,
        flow_id=flow_id,
        require_flow_lookup_without_scope=require_flow_lookup_without_scope,
        scope_filter_getter=get_scope_filter,
    )


def _coerce_input_type(value: str | None) -> FlowInputType | str | None:
    if value is None:
        return None
    try:
        return FlowInputType(value)
    except ValueError:
        return value


def _coerce_input_source(value: str | None) -> FlowInputSource | str | None:
    if value is None:
        return None
    try:
        return FlowInputSource(value)
    except ValueError:
        return value


@router.post("/", response_model=FlowPublic, status_code=status.HTTP_201_CREATED)
async def create_flow(
    request: Request,
    flow_in: FlowCreateRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    scope_filter = get_scope_filter(request)
    if scope_filter.space_id is not None and scope_filter.space_id != flow_in.space_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "insufficient_scope",
                "message": (
                    f"API key is scoped to space '{scope_filter.space_id}'. "
                    f"Cannot create flow in space '{flow_in.space_id}'."
                ),
                "context": {"auth_layer": "api_key_scope"},
            },
        )

    assembler = FlowAssembler()
    flow_service = container.flow_service()
    user = container.user()

    created = await flow_service.create_flow(
        space_id=flow_in.space_id,
        name=flow_in.name,
        description=flow_in.description,
        steps=[assembler.to_domain_step(step) for step in flow_in.steps],
        metadata_json=flow_in.metadata_json,
        data_retention_days=flow_in.data_retention_days,
    )

    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.FLOW_CREATED,
        entity_type=EntityType.FLOW,
        entity_id=_required_uuid(created.id, field="flow.id"),
        description=f"Created flow '{created.name}'",
        metadata=AuditMetadata.standard(actor=user, target=created),
    )
    overrides = _find_classification_overrides(flow_in)
    if overrides:
        await audit_service.log_async(
            tenant_id=user.tenant_id,
            actor_id=user.id,
            action=ActionType.FLOW_CLASSIFICATION_OVERRIDE,
            entity_type=EntityType.FLOW,
            entity_id=_required_uuid(created.id, field="flow.id"),
            description="Configured output classification overrides for flow steps.",
            metadata=AuditMetadata.standard(
                actor=user,
                target=created,
                changes={"step_orders": overrides},
            ),
        )

    return assembler.to_public(created)


@router.get("/", response_model=PaginatedResponse[FlowSparsePublic], status_code=status.HTTP_200_OK)
async def list_flows(
    request: Request,
    space_id: UUID = Query(...),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    container: Container = Depends(get_container(with_user=True)),
):
    scope_filter = get_scope_filter(request)
    if scope_filter.space_id is not None and scope_filter.space_id != space_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "insufficient_scope",
                "message": "API key space scope does not match requested space.",
                "context": {"auth_layer": "api_key_scope"},
            },
        )

    assembler = FlowAssembler()
    flow_service = container.flow_service()
    flows = await flow_service.list_flows(
        space_id=space_id,
        sparse=True,
        limit=limit,
        offset=offset,
    )
    return {"count": len(flows), "items": [assembler.to_sparse_public(flow) for flow in flows]}


@router.get("/{id}/", response_model=FlowPublic, status_code=status.HTTP_200_OK)
async def get_flow(
    id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    assembler = FlowAssembler()
    flow = await container.flow_service().get_flow(id)
    return assembler.to_public(flow)


@router.patch("/{id}/", response_model=FlowPublic, status_code=status.HTTP_200_OK)
async def update_flow(
    id: UUID,
    flow_in: FlowUpdateRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    assembler = FlowAssembler()
    flow_service = container.flow_service()
    user = container.user()

    payload = flow_in.model_dump(exclude_unset=True)
    steps = None
    if "steps" in payload:
        steps = [assembler.to_domain_step(step) for step in flow_in.steps]

    updated = await flow_service.update_flow(
        flow_id=id,
        name=payload.get("name", NOT_PROVIDED),
        description=payload.get("description", NOT_PROVIDED),
        steps=steps,
        metadata_json=payload.get("metadata_json", NOT_PROVIDED),
        data_retention_days=payload.get("data_retention_days", NOT_PROVIDED),
    )

    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.FLOW_UPDATED,
        entity_type=EntityType.FLOW,
        entity_id=_required_uuid(updated.id, field="flow.id"),
        description=f"Updated flow '{updated.name}'",
        metadata=AuditMetadata.standard(actor=user, target=updated),
    )
    overrides = _find_classification_overrides(flow_in)
    if overrides:
        await audit_service.log_async(
            tenant_id=user.tenant_id,
            actor_id=user.id,
            action=ActionType.FLOW_CLASSIFICATION_OVERRIDE,
            entity_type=EntityType.FLOW,
            entity_id=_required_uuid(updated.id, field="flow.id"),
            description="Updated output classification overrides for flow steps.",
            metadata=AuditMetadata.standard(
                actor=user,
                target=updated,
                changes={"step_orders": overrides},
            ),
        )

    return assembler.to_public(updated)


@router.delete("/{id}/", status_code=status.HTTP_204_NO_CONTENT)
async def delete_flow(
    id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    flow_service = container.flow_service()
    user = container.user()
    flow = await flow_service.get_flow(id)
    await flow_service.delete_flow(id)

    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.FLOW_DELETED,
        entity_type=EntityType.FLOW,
        entity_id=id,
        description=f"Deleted flow '{flow.name}'",
        metadata=AuditMetadata.standard(actor=user, target=flow),
    )


@router.post("/{id}/publish/", response_model=FlowPublic, status_code=status.HTTP_200_OK)
async def publish_flow(
    id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    assembler = FlowAssembler()
    flow_service = container.flow_service()
    user = container.user()
    published = await flow_service.publish_flow(flow_id=id)

    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.FLOW_PUBLISHED,
        entity_type=EntityType.FLOW,
        entity_id=id,
        description=f"Published flow '{published.name}' as version {published.published_version}",
        metadata=AuditMetadata.standard(actor=user, target=published),
    )
    return assembler.to_public(published)


@router.post("/{id}/unpublish/", response_model=FlowPublic, status_code=status.HTTP_200_OK)
async def unpublish_flow(
    id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    assembler = FlowAssembler()
    flow_service = container.flow_service()
    user = container.user()
    unpublished = await flow_service.unpublish_flow(flow_id=id)

    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.FLOW_UNPUBLISHED,
        entity_type=EntityType.FLOW,
        entity_id=id,
        description=f"Unpublished flow '{unpublished.name}'",
        metadata=AuditMetadata.standard(actor=user, target=unpublished),
    )
    return assembler.to_public(unpublished)


@router.post(
    "/{id}/assistants/",
    response_model=AssistantPublic,
    status_code=status.HTTP_201_CREATED,
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
    update_payload = _extract_assistant_update_payload(assistant_in)

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


@router.post(
    "/{id}/runs/",
    response_model=FlowRunPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Create flow run",
    description="""
Create a new run for a published flow.

Speech-to-text consumer sequence:
1. Upload one or more files via `POST /api/v1/flows/{id}/files/`
2. Submit the returned `file_ids` in this run request
3. Poll `GET /api/v1/flows/{id}/runs/{run_id}/` and `.../steps/` for progress and outputs
    """,
    responses={
        400: error_response(
            description=(
                "Flow cannot be run in its current state or request payload is invalid. "
                "Representative machine-readable codes include: flow_not_published, "
                "flow_run_input_payload_too_large, flow_run_concurrency_limit_reached, "
                "flow_input_required_field_missing, flow_input_invalid_number."
            ),
            message="Flow must be published before creating runs.",
            intric_error_code=ErrorCodes.BAD_REQUEST,
            code="flow_not_published",
        ),
        403: error_response(
            description="Forbidden: API key scope does not match flow space.",
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
async def create_flow_run(
    id: UUID,
    request: Request,
    run_in: FlowRunCreateRequest,
    background_tasks: BackgroundTasks,
    container: Container = Depends(get_container(with_user=True)),
):
    await enforce_flow_scope(
        request,
        container,
        flow_id=id,
        scope_filter_getter=get_scope_filter,
    )
    assembler = FlowAssembler()
    run_service = container.flow_run_service()
    user = container.user()
    run = await run_service.create_run(
        flow_id=id,
        input_payload_json=run_in.input_payload_json,
        file_ids=run_in.file_ids,
    )

    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.FLOW_RUN_CREATED,
        entity_type=EntityType.FLOW_RUN,
        entity_id=run.id,
        description=f"Created flow run for flow {id}",
        metadata=AuditMetadata.standard(actor=user, target=run),
    )
    background_tasks.add_task(
        _dispatch_flow_run_after_commit,
        run_id=run.id,
        flow_id=id,
        tenant_id=user.tenant_id,
        user_id=user.id,
    )
    return assembler.to_run_public(run)


@router.get(
    "/{id}/input-policy/",
    response_model=FlowInputPolicyPublic,
    status_code=status.HTTP_200_OK,
    summary="Get flow input policy",
    description="""
Return effective runtime input policy for a flow's first `flow_input` step.

Use this endpoint before upload/run to discover:
- whether file upload is accepted
- which mimetypes are allowed
- the effective max file size limit in bytes
- max files per run (when constrained)
- recommended run payload shape for API consumers
    """,
    responses={
        403: error_response(
            description="Forbidden: API key scope does not match flow space.",
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
async def get_flow_input_policy(
    id: UUID,
    request: Request,
    container: Container = Depends(get_container(with_user=True)),
):
    await enforce_flow_scope(
        request,
        container,
        flow_id=id,
        scope_filter_getter=get_scope_filter,
    )
    policy = await _flow_upload_service(container).get_input_policy(flow_id=id)
    return FlowInputPolicyPublic(
        flow_id=id,
        input_type=_coerce_input_type(policy.input_type),
        input_source=_coerce_input_source(policy.input_source),
        accepts_file_upload=policy.accepts_file_upload,
        accepted_mimetypes=policy.accepted_mimetypes,
        max_file_size_bytes=policy.max_file_size_bytes,
        max_files_per_run=policy.max_files_per_run,
        recommended_run_payload=policy.recommended_run_payload,
    )


@router.post(
    "/{id}/files/",
    response_model=FilePublic,
    status_code=status.HTTP_201_CREATED,
    summary="Upload flow input file",
    description="""
Upload a file using flow-specific policy checks.

This endpoint is flow-first and intended for external API consumers that should not call
generic file routes directly. Validation is based on the first `flow_input` step:
- accepted input types: audio/document/image/file
- allowed mimetypes
- effective tenant flow size limits
- multipart form field name: `upload_file`
    """,
    responses={
        400: error_response(
            description=(
                "Upload request is invalid for this flow input policy. "
                "Representative machine-readable codes include: "
                "flow_input_upload_not_supported, flow_input_file_empty, "
                "flow_input_policy_missing_limit."
            ),
            message="Flow input policy does not allow file upload.",
            intric_error_code=ErrorCodes.BAD_REQUEST,
            code="flow_input_upload_not_supported",
        ),
        403: error_response(
            description="Forbidden: API key scope does not match flow space.",
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
        413: error_response(
            description="Uploaded file exceeds effective flow max size limit.",
            message="Uploaded file exceeds effective flow max size limit.",
            intric_error_code=ErrorCodes.FILE_TOO_LARGE,
            code="file_too_large",
        ),
        415: error_response(
            description="Unsupported media type for this flow input policy.",
            message="Unsupported media type for this flow input policy.",
            intric_error_code=ErrorCodes.FILE_NOT_SUPPORTED,
            code="unsupported_media_type",
        ),
    },
)
async def upload_flow_file(
    id: UUID,
    request: Request,
    upload_file: UploadFile,
    container: Container = Depends(get_container(with_user=True)),
):
    await enforce_flow_scope(
        request,
        container,
        flow_id=id,
        scope_filter_getter=get_scope_filter,
    )
    file = await _flow_upload_service(container).upload_file_for_flow(
        flow_id=id,
        upload_file=upload_file,
    )
    user = container.user()
    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.FILE_UPLOADED,
        entity_type=EntityType.FILE,
        entity_id=file.id,
        description=f"Uploaded flow input file '{file.name}' for flow {id}",
        metadata=AuditMetadata.standard(
            actor=user,
            target=file,
            extra={
                "flow_id": str(id),
                "size_bytes": file.size,
                "mimetype": getattr(file, "mimetype", None),
            },
        ),
    )
    return file


@router.get(
    "/{id}/runs/",
    response_model=PaginatedResponse[FlowRunPublic],
    status_code=status.HTTP_200_OK,
    summary="List flow runs (flow-first)",
    description="""
List runs for a specific flow.

This is a flow-first alias for run listing to keep runtime orchestration under `/flows/{id}`.
    """,
    responses={
        403: error_response(
            description="Forbidden: API key scope does not match flow space.",
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
async def list_flow_runs_alias(
    id: UUID,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    container: Container = Depends(get_container(with_user=True)),
):
    await _enforce_flow_scope(
        request,
        container,
        flow_id=id,
        require_flow_lookup_without_scope=True,
    )
    runs = await container.flow_run_service().list_runs(
        flow_id=id,
        limit=limit,
        offset=offset,
    )
    assembler = FlowAssembler()
    return {"count": len(runs), "items": [assembler.to_run_public(item) for item in runs]}


@router.get(
    "/{id}/runs/{run_id}/",
    response_model=FlowRunPublic,
    status_code=status.HTTP_200_OK,
    summary="Get flow run (flow-first)",
    description="""
Get one run for a flow using flow-first routing.

Use this endpoint for run status and top-level output payload when building consumer apps.
    """,
    responses={
        403: error_response(
            description="Forbidden: API key scope does not match flow space.",
            message="API key space scope does not match requested flow.",
            intric_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
        404: error_response(
            description="Run not found for this flow and tenant.",
            message="Flow run not found.",
            intric_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
    },
)
async def get_flow_run_alias(
    id: UUID,
    run_id: UUID,
    request: Request,
    container: Container = Depends(get_container(with_user=True)),
):
    await enforce_flow_scope(
        request,
        container,
        flow_id=id,
        scope_filter_getter=get_scope_filter,
    )
    run = await container.flow_run_service().get_run(run_id=run_id, flow_id=id)
    return FlowAssembler().to_run_public(run)


@router.post(
    "/{id}/runs/{run_id}/cancel/",
    response_model=FlowRunPublic,
    status_code=status.HTTP_200_OK,
    summary="Cancel flow run (flow-first)",
    description="""
Cancel a flow run if it is not already terminal.

This is the canonical run control endpoint for flow consumers.
    """,
    responses={
        403: error_response(
            description="Forbidden: API key scope does not match flow space.",
            message="API key space scope does not match requested flow.",
            intric_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
        404: error_response(
            description="Run not found for this flow and tenant.",
            message="Flow run not found.",
            intric_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
    },
)
async def cancel_flow_run_alias(
    id: UUID,
    run_id: UUID,
    request: Request,
    container: Container = Depends(get_container(with_user=True)),
):
    await _enforce_flow_scope(
        request,
        container,
        flow_id=id,
        require_flow_lookup_without_scope=True,
    )
    user = container.user()
    run_service = container.flow_run_service()
    await run_service.get_run(run_id=run_id, flow_id=id)
    run = await run_service.cancel_run(run_id=run_id)

    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.FLOW_RUN_CANCELLED,
        entity_type=EntityType.FLOW_RUN,
        entity_id=run.id,
        description=f"Cancelled flow run {run.id}",
        metadata=AuditMetadata.standard(actor=user, target=run),
    )
    return FlowAssembler().to_run_public(run)


@router.post(
    "/{id}/runs/{run_id}/redispatch/",
    response_model=FlowRunRedispatchResponse,
    status_code=status.HTTP_200_OK,
    summary="Redispatch stale queued run (flow-first)",
    description="""
Attempt to redispatch a stale queued run.

Returns `redispatched_count` indicating whether dispatch was re-triggered.
    """,
    responses={
        403: error_response(
            description="Forbidden: API key scope does not match flow space.",
            message="API key space scope does not match requested flow.",
            intric_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
        404: error_response(
            description="Run not found for this flow and tenant.",
            message="Flow run not found.",
            intric_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
    },
)
async def redispatch_flow_run_alias(
    id: UUID,
    run_id: UUID,
    request: Request,
    container: Container = Depends(get_container(with_user=True)),
):
    await _enforce_flow_scope(request, container, flow_id=id)
    user = container.user()
    run_service = container.flow_run_service()
    run = await run_service.get_run(run_id=run_id, flow_id=id)

    redispatched = await run_service.redispatch_stale_queued_runs(
        flow_id=id,
        run_id=run.id,
        limit=1,
        execution_backend=container.flow_execution_backend(),
    )
    refreshed = await run_service.get_run(run_id=run_id, flow_id=id)

    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.FLOW_RUN_REDISPATCHED,
        entity_type=EntityType.FLOW_RUN,
        entity_id=refreshed.id,
        description=f"Redispatch requested for flow run {refreshed.id} (dispatch_count={redispatched})",
        metadata=AuditMetadata.standard(actor=user, target=refreshed),
    )
    return {
        "run": FlowAssembler().to_run_public(refreshed),
        "redispatched_count": redispatched,
    }


@router.get(
    "/{id}/runs/{run_id}/evidence/",
    response_model=FlowRunEvidenceResponse,
    status_code=status.HTTP_200_OK,
    summary="Get flow run evidence export (flow-first)",
    description="""
Get redacted debug/evidence payload for one flow run.

Prefer `.../steps/` for consumer UIs unless debug-export fields are required.
    """,
    responses={
        403: error_response(
            description="Forbidden: API key scope does not match flow space.",
            message="API key space scope does not match requested flow.",
            intric_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
        404: error_response(
            description="Run not found for this flow and tenant.",
            message="Flow run not found.",
            intric_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
    },
)
async def get_flow_run_evidence_alias(
    id: UUID,
    run_id: UUID,
    request: Request,
    container: Container = Depends(get_container(with_user=True)),
):
    await _enforce_flow_scope(request, container, flow_id=id)
    run_service = container.flow_run_service()
    await run_service.get_run(run_id=run_id, flow_id=id)
    evidence = await run_service.get_evidence(run_id=run_id)
    return FlowRunEvidenceResponse(**evidence)


@router.get(
    "/{id}/runs/{run_id}/steps/",
    response_model=list[FlowRunStepPublic],
    status_code=status.HTTP_200_OK,
    summary="List flow run step outputs (flow-first)",
    description="""
Return ordered step-level execution results for one flow run.

Designed for consumer UIs that need to inspect intermediate outputs, diagnostics, and token usage
without relying on debug-export internals.
    """,
    responses={
        403: error_response(
            description="Forbidden: API key scope does not match flow space.",
            message="API key space scope does not match requested flow.",
            intric_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
        404: error_response(
            description="Run not found for this flow and tenant.",
            message="Flow run not found.",
            intric_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
    },
)
async def list_flow_run_steps(
    id: UUID,
    run_id: UUID,
    request: Request,
    container: Container = Depends(get_container(with_user=True)),
):
    await enforce_flow_scope(
        request,
        container,
        flow_id=id,
        scope_filter_getter=get_scope_filter,
    )
    step_results = await container.flow_run_service().list_step_results(
        run_id=run_id,
        flow_id=id,
    )
    items: list[FlowRunStepPublic] = []
    for result in step_results:
        diagnostics: list[dict[str, Any]] = []
        input_payload = result.input_payload_json
        if isinstance(input_payload, dict):
            raw_diagnostics = input_payload.get("diagnostics")
            if isinstance(raw_diagnostics, list):
                diagnostics = [item for item in raw_diagnostics if isinstance(item, dict)]
        items.append(
            FlowRunStepPublic.model_validate(result).model_copy(
                update={"diagnostics": diagnostics}
            )
        )
    return items


@router.get("/{id}/graph/", response_model=GraphResponse, status_code=status.HTTP_200_OK)
async def get_flow_graph(
    id: UUID,
    run_id: UUID | None = Query(default=None),
    container: Container = Depends(get_container(with_user=True)),
):
    flow_service = container.flow_service()
    flow_run_service = container.flow_run_service()
    flow_version_repo = container.flow_version_repo()

    if run_id is not None:
        run = await flow_run_service.get_run(run_id=run_id, flow_id=id)
        version = await flow_version_repo.get(
            flow_id=run.flow_id,
            version=run.flow_version,
            tenant_id=run.tenant_id,
        )
        definition_steps = version.definition_json.get("steps", [])
        nodes, edges = build_graph_from_steps(definition_steps)
        evidence = await flow_run_service.get_evidence(run_id=run.id)
        nodes = enrich_nodes_with_run_results(nodes, evidence["step_results"])
        return GraphResponse(nodes=nodes, edges=edges)

    flow = await flow_service.get_flow(id)
    live_steps = [step.model_dump(mode="json") for step in flow.steps]
    nodes, edges = build_graph_from_steps(live_steps)
    return GraphResponse(nodes=nodes, edges=edges)
