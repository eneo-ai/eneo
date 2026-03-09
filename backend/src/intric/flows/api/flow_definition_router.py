from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, status

from intric.audit.application.audit_metadata import AuditMetadata
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.files.file_models import SignedURLRequest, SignedURLResponse
from intric.flows.api import flow_router_common as common
from intric.flows.api.flow_api_common import error_response
from intric.flows.api.flow_assembler import FlowAssembler
from intric.flows.api.flow_models import (
    FlowCreateRequest,
    FlowPublic,
    FlowSparsePublic,
    FlowTemplateAssetPublic,
    FlowTemplateInspectionPublic,
    FlowUpdateRequest,
)
from intric.authentication.signed_urls import generate_signed_token
import time
from intric.main.models import NOT_PROVIDED, PaginatedResponse
from intric.main.exceptions import ErrorCodes
from intric.server.dependencies.container import get_container

from intric.main.container.container import Container

router = APIRouter()


@router.post(
    "/",
    response_model=FlowPublic,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_flow",
)
async def create_flow(
    request: Request,
    flow_in: FlowCreateRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    scope_filter = common.get_scope_filter(request)
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
        entity_id=common.required_uuid(created.id, field="flow.id"),
        description=f"Created flow '{created.name}'",
        metadata=AuditMetadata.standard(actor=user, target=created),
    )
    overrides = common.find_classification_overrides(flow_in)
    if overrides:
        await audit_service.log_async(
            tenant_id=user.tenant_id,
            actor_id=user.id,
            action=ActionType.FLOW_CLASSIFICATION_OVERRIDE,
            entity_type=EntityType.FLOW,
            entity_id=common.required_uuid(created.id, field="flow.id"),
            description="Configured output classification overrides for flow steps.",
            metadata=AuditMetadata.standard(
                actor=user,
                target=created,
                changes={"step_orders": overrides},
            ),
        )

    return assembler.to_public(created)


@router.get(
    "/",
    response_model=PaginatedResponse[FlowSparsePublic],
    status_code=status.HTTP_200_OK,
    operation_id="list_flows",
)
async def list_flows(
    request: Request,
    space_id: UUID = Query(...),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    container: Container = Depends(get_container(with_user=True)),
):
    scope_filter = common.get_scope_filter(request)
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


@router.get(
    "/{id}/",
    response_model=FlowPublic,
    status_code=status.HTTP_200_OK,
    operation_id="get_flow",
)
async def get_flow(
    id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    assembler = FlowAssembler()
    flow = await container.flow_service().get_flow(id)
    return assembler.to_public(flow)


@router.patch(
    "/{id}/",
    response_model=FlowPublic,
    status_code=status.HTTP_200_OK,
    operation_id="update_flow",
)
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
        entity_id=common.required_uuid(updated.id, field="flow.id"),
        description=f"Updated flow '{updated.name}'",
        metadata=AuditMetadata.standard(actor=user, target=updated),
    )
    overrides = common.find_classification_overrides(flow_in)
    if overrides:
        await audit_service.log_async(
            tenant_id=user.tenant_id,
            actor_id=user.id,
            action=ActionType.FLOW_CLASSIFICATION_OVERRIDE,
            entity_type=EntityType.FLOW,
            entity_id=common.required_uuid(updated.id, field="flow.id"),
            description="Updated output classification overrides for flow steps.",
            metadata=AuditMetadata.standard(
                actor=user,
                target=updated,
                changes={"step_orders": overrides},
            ),
        )

    return assembler.to_public(updated)


@router.delete(
    "/{id}/",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="delete_flow",
)
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


@router.post(
    "/{id}/publish/",
    response_model=FlowPublic,
    status_code=status.HTTP_200_OK,
    operation_id="publish_flow",
)
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


@router.post(
    "/{id}/unpublish/",
    response_model=FlowPublic,
    status_code=status.HTTP_200_OK,
    operation_id="unpublish_flow",
)
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


@router.get(
    "/{id}/template-files/",
    response_model=list[FlowTemplateAssetPublic],
    status_code=status.HTTP_200_OK,
    operation_id="list_flow_template_files",
)
async def list_flow_template_files(
    id: UUID,
    request: Request,
    container: Container = Depends(get_container(with_user=True)),
):
    await common.enforce_flow_scope_for_request(request, container, flow_id=id)
    assets = await container.flow_template_asset_service().list_assets(
        flow_id=id,
        can_edit=True,
        can_download=True,
    )
    return [FlowTemplateAssetPublic.model_validate(item) for item in assets]


@router.get(
    "/{id}/template-inspect/",
    response_model=FlowTemplateInspectionPublic,
    status_code=status.HTTP_200_OK,
    operation_id="inspect_flow_template",
    summary="Inspect DOCX template placeholders for a flow",
    description="Scan an uploaded DOCX template and return placeholders discovered in the document body, tables, headers, and footers.",
    responses={
        400: error_response(
            description="The selected file is not a valid DOCX template or is not safe to inspect.",
            message="Invalid DOCX template.",
            intric_error_code=ErrorCodes.BAD_REQUEST,
            code="bad_request",
        ),
        403: error_response(
            description="Forbidden: API key scope does not match flow space.",
            message="API key space scope does not match requested flow.",
            intric_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
        404: error_response(
            description="Flow or template file not found in tenant scope.",
            message="Flow not found.",
            intric_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
    },
)
async def inspect_flow_template(
    id: UUID,
    request: Request,
    file_id: UUID = Query(...),
    container: Container = Depends(get_container(with_user=True)),
):
    await common.enforce_flow_scope_for_request(request, container, flow_id=id)
    return await container.flow_template_asset_service().inspect_asset(flow_id=id, asset_id=file_id)


@router.post(
    "/{id}/template-files/",
    response_model=FlowTemplateAssetPublic,
    status_code=status.HTTP_201_CREATED,
    operation_id="upload_flow_template_file",
    summary="Upload a DOCX template asset for a flow",
    description="Upload a reusable DOCX template for Flow document assembly. This preserves the original DOCX file for placeholder inspection and deterministic template_fill steps. It is separate from flow input uploads and does not use the flow run input policy.",
    responses={
        400: error_response(
            description="The uploaded file is not a valid DOCX template for Flow assembly.",
            message="Only .docx files can be uploaded as Flow templates.",
            intric_error_code=ErrorCodes.BAD_REQUEST,
            code="bad_request",
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
            description="The uploaded template exceeds the allowed file size.",
            message="Uploaded file is too large.",
            intric_error_code=ErrorCodes.FILE_TOO_LARGE,
            code="file_too_large",
        ),
        415: error_response(
            description="The uploaded file is not a supported DOCX template.",
            message="Only .docx files can be uploaded as Flow templates.",
            intric_error_code=ErrorCodes.FILE_NOT_SUPPORTED,
            code="unsupported_media_type",
        ),
    },
)
async def upload_flow_template_file(
    id: UUID,
    request: Request,
    upload_file: UploadFile,
    container: Container = Depends(get_container(with_user=True)),
):
    await common.enforce_flow_scope_for_request(
        request,
        container,
        flow_id=id,
        require_flow_lookup_without_scope=True,
    )

    asset = await container.flow_template_asset_service().upload_asset(
        flow_id=id,
        upload_file=upload_file,
    )
    user = container.user()
    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.FILE_UPLOADED,
        entity_type=EntityType.FILE,
        entity_id=common.required_uuid(asset.file_id, field="flow_template_asset.file_id"),
        description=f"Uploaded DOCX template '{asset.name}' for flow authoring",
        metadata=AuditMetadata.standard(
            actor=user,
            target=asset,
            extra={
                "template_asset_id": str(asset.id),
                "mimetype": asset.mimetype,
                "flow_id": str(id),
                "upload_purpose": "flow_template",
            },
        ),
    )
    return FlowTemplateAssetPublic.model_validate(asset)


@router.post(
    "/{id}/template-files/{file_id}/signed-url/",
    response_model=SignedURLResponse,
    status_code=status.HTTP_200_OK,
    operation_id="generate_flow_template_signed_url",
)
async def generate_flow_template_signed_url(
    id: UUID,
    file_id: UUID,
    request: Request,
    signed_url_req: SignedURLRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    await common.enforce_flow_scope_for_request(request, container, flow_id=id)
    asset, _ = await container.flow_template_asset_service().get_asset_with_file(
        flow_id=id,
        asset_id=file_id,
    )
    expires_at = int(time.time()) + signed_url_req.expires_in
    token = generate_signed_token(
        file_id=asset.file_id,
        expires_at=expires_at,
        content_disposition=signed_url_req.content_disposition,
    )
    base_url = str(request.base_url).rstrip("/")
    url = f"{base_url}/api/v1/files/{asset.file_id}/download/?token={token}"
    return SignedURLResponse(url=url, expires_at=expires_at)
