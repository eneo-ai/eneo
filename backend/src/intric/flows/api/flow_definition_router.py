from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Path, Query, Request, UploadFile, status

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
from intric.flows.http_transport import HttpAuthoredConfig, is_authored_config
from intric.flows.http_transport.test_action import execute_http_test
from intric.authentication.signed_urls import generate_signed_token
import time
from intric.main.models import NOT_PROVIDED, PaginatedResponse
from intric.main.exceptions import ErrorCodes, UnauthorizedException
from intric.server.dependencies.container import get_container

from intric.main.container.container import Container

router = APIRouter()


async def _require_flow_edit_access(
    request: Request,
    container: Container,
    *,
    flow_id: UUID,
    require_flow_lookup_without_scope: bool = False,
) -> common.FlowAccessContext:
    access_context = await common.get_flow_access_context_for_request(
        request,
        container,
        flow_id=flow_id,
        required_access="manage",
    )
    if require_flow_lookup_without_scope:
        # Kept for call-site compatibility; scope is still enforced by the shared access guard.
        pass
    if access_context.actor is None or not access_context.actor.can_edit_flows():
        raise UnauthorizedException(
            "You do not have permission to edit flows in this space.",
            code="insufficient_space_permission",
            context={"auth_layer": "space_membership"},
        )
    return access_context


@router.post(
    "/",
    response_model=FlowPublic,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_flow",
    summary="Create Flow",
    description="Create a new draft flow definition, including its initial ordered steps, inside a space.",
    responses={
        400: error_response(
            description="The submitted draft flow definition is invalid.",
            message="Flow definition is invalid.",
            intric_error_code=ErrorCodes.BAD_REQUEST,
            code="bad_request",
        ),
        403: error_response(
            description="Caller lacks permission or API key scope to create flows in this space.",
            message="API key space scope does not match requested flow.",
            intric_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
    },
)
async def create_flow(
    request: Request,
    flow_in: FlowCreateRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    access_context = await common.get_space_access_context_for_request(
        request,
        container,
        space_id=flow_in.space_id,
        required_access="manage",
        scope_mismatch_message=(
            f"API key is scoped to space '{common.get_scope_filter(request).space_id}'. "
            f"Cannot create flow in space '{flow_in.space_id}'."
        ),
    )
    if not access_context.actor.can_create_flows():
        raise UnauthorizedException(
            "You do not have permission to create flows in this space.",
            code="insufficient_space_permission",
            context={"auth_layer": "space_membership"},
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
    summary="List Flows",
    description=(
        "List flow definitions in a space with pagination-friendly sparse metadata. "
        "The `count` field in the paginated response reports the number of items returned "
        "in the current page, not the total number of matching flows across all pages."
    ),
    responses={
        403: error_response(
            description="Caller lacks permission or API key scope to list flows in this space.",
            message="API key space scope does not match requested flow.",
            intric_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
    },
)
async def list_flows(
    request: Request,
    space_id: UUID = Query(..., description="Only return flows that belong to this space."),
    limit: int = Query(default=50, ge=1, le=200, description="Maximum number of flows to return."),
    offset: int = Query(default=0, ge=0, description="Number of flows to skip before returning results."),
    container: Container = Depends(get_container(with_user=True)),
):
    access_context = await common.get_space_access_context_for_request(
        request,
        container,
        space_id=space_id,
        required_access="view",
        scope_mismatch_message="API key space scope does not match requested space.",
    )
    if not access_context.actor.can_read_flows():
        raise UnauthorizedException(
            "You do not have permission to access flows in this space.",
            code="insufficient_space_permission",
            context={"auth_layer": "space_membership"},
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
    summary="Get Flow",
    description="Return the full draft representation of a flow, including all configured steps and metadata.",
    responses={
        403: error_response(
            description="Caller lacks permission or API key scope to view this flow.",
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
async def get_flow(
    id: Annotated[UUID, Path(description="Identifier of the draft flow definition to return.")],
    request: Request,
    container: Container = Depends(get_container(with_user=True)),
):
    access_context = await common.get_flow_access_context_for_request(
        request,
        container,
        flow_id=id,
        required_access="view",
    )
    assembler = FlowAssembler()
    if access_context.actor is None or not access_context.actor.can_read_flow(access_context.flow):
        raise UnauthorizedException(
            "You do not have permission to access this flow.",
            code="insufficient_space_permission",
            context={"auth_layer": "space_membership"},
        )

    return assembler.to_public(access_context.flow)


@router.patch(
    "/{id}/",
    response_model=FlowPublic,
    status_code=status.HTTP_200_OK,
    operation_id="update_flow",
    summary="Update Flow",
    description="Update a draft flow definition, including steps, metadata, and retention settings.",
    responses={
        400: error_response(
            description="The submitted draft flow update is invalid or the flow cannot be updated in its current state.",
            message="Flow update is invalid.",
            intric_error_code=ErrorCodes.BAD_REQUEST,
            code="bad_request",
        ),
        403: error_response(
            description="Caller lacks permission or API key scope to update this flow.",
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
async def update_flow(
    id: Annotated[UUID, Path(description="Identifier of the draft flow definition to update.")],
    request: Request,
    flow_in: FlowUpdateRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    await _require_flow_edit_access(request, container, flow_id=id)

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
    summary="Delete Flow",
    description="Soft-delete a flow definition so it is no longer available for editing or execution.",
    responses={
        403: error_response(
            description="Caller lacks permission or API key scope to delete this flow.",
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
async def delete_flow(
    id: Annotated[UUID, Path(description="Identifier of the draft flow definition to delete.")],
    request: Request,
    container: Container = Depends(get_container(with_user=True)),
):
    flow_service = container.flow_service()
    user = container.user()
    access_context = await common.get_flow_access_context_for_request(
        request,
        container,
        flow_id=id,
        required_access="manage",
    )
    if access_context.actor is None or not access_context.actor.can_delete_flows():
        raise UnauthorizedException(
            "You do not have permission to delete flows in this space.",
            code="insufficient_space_permission",
            context={"auth_layer": "space_membership"},
        )

    await flow_service.delete_flow(id)

    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.FLOW_DELETED,
        entity_type=EntityType.FLOW,
        entity_id=id,
        description=f"Deleted flow '{access_context.flow.name}'",
        metadata=AuditMetadata.standard(actor=user, target=access_context.flow),
    )


@router.post(
    "/{id}/publish/",
    response_model=FlowPublic,
    status_code=status.HTTP_200_OK,
    operation_id="publish_flow",
    summary="Publish Flow",
    description="Publish the current draft revision so new runs use a version-pinned definition.",
    responses={
        400: error_response(
            description="The flow cannot be published because its draft definition is incomplete or invalid.",
            message="Flow cannot be published in its current state.",
            intric_error_code=ErrorCodes.BAD_REQUEST,
            code="bad_request",
        ),
        403: error_response(
            description="Caller lacks permission or API key scope to publish this flow.",
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
async def publish_flow(
    id: Annotated[UUID, Path(description="Identifier of the draft flow definition to publish.")],
    request: Request,
    container: Container = Depends(get_container(with_user=True)),
):
    access_context = await common.get_flow_access_context_for_request(
        request,
        container,
        flow_id=id,
        required_access="manage",
    )
    if access_context.actor is None or not access_context.actor.can_publish_flows():
        raise UnauthorizedException(
            "You do not have permission to publish flows in this space.",
            code="insufficient_space_permission",
            context={"auth_layer": "space_membership"},
        )

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
    summary="Unpublish Flow",
    description="Remove the active published revision while keeping the draft definition available for editing.",
    responses={
        400: error_response(
            description="The flow cannot be unpublished in its current state.",
            message="Flow cannot be unpublished in its current state.",
            intric_error_code=ErrorCodes.BAD_REQUEST,
            code="bad_request",
        ),
        403: error_response(
            description="Caller lacks permission or API key scope to unpublish this flow.",
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
async def unpublish_flow(
    id: Annotated[UUID, Path(description="Identifier of the published flow definition to unpublish.")],
    request: Request,
    container: Container = Depends(get_container(with_user=True)),
):
    access_context = await common.get_flow_access_context_for_request(
        request,
        container,
        flow_id=id,
        required_access="manage",
    )
    if access_context.actor is None or not access_context.actor.can_publish_flows():
        raise UnauthorizedException(
            "You do not have permission to unpublish flows in this space.",
            code="insufficient_space_permission",
            context={"auth_layer": "space_membership"},
        )

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
    summary="List Flow Templates",
    description="List template assets attached to a flow draft for template-fill steps.",
    responses={
        403: error_response(
            description="Caller lacks permission or API key scope to list template assets for this flow.",
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
async def list_flow_template_files(
    id: Annotated[
        UUID,
        Path(description="Identifier of the draft flow whose template assets should be listed."),
    ],
    request: Request,
    container: Container = Depends(get_container(with_user=True)),
):
    await _require_flow_edit_access(request, container, flow_id=id)
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
    id: Annotated[
        UUID,
        Path(description="Identifier of the draft flow that owns the template asset."),
    ],
    request: Request,
    file_id: Annotated[
        UUID,
        Query(description="Identifier of the stored template asset to inspect."),
    ],
    container: Container = Depends(get_container(with_user=True)),
):
    await _require_flow_edit_access(request, container, flow_id=id)
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
    id: Annotated[
        UUID,
        Path(description="Identifier of the draft flow that will own the uploaded template asset."),
    ],
    request: Request,
    upload_file: UploadFile = File(..., description="DOCX template file to store for later template_fill steps."),
    container: Container = Depends(get_container(with_user=True)),
):
    await _require_flow_edit_access(
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
    summary="Generate Template Download URL",
    description="Generate a temporary signed download URL for a stored flow template asset.",
    responses={
        403: error_response(
            description="Caller lacks permission or API key scope to access this flow template asset.",
            message="API key space scope does not match requested flow.",
            intric_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
        404: error_response(
            description="Flow or template asset not found in tenant scope.",
            message="Flow not found.",
            intric_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
    },
)
async def generate_flow_template_signed_url(
    id: Annotated[
        UUID,
        Path(description="Identifier of the draft flow that owns the template asset."),
    ],
    file_id: Annotated[
        UUID,
        Path(description="Identifier of the stored template asset to download."),
    ],
    request: Request,
    signed_url_req: SignedURLRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    await _require_flow_edit_access(request, container, flow_id=id)
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


from pydantic import BaseModel as _BaseModel


class HttpTestRequest(_BaseModel):
    config: dict  # authored config shape
    direction: str = "output"
    method: str = "POST"
    test_variables: dict | None = None


@router.post(
    "/{id}/http-test",
    status_code=status.HTTP_200_OK,
    operation_id="test_flow_http",
    summary="Test HTTP Connection",
    description="Send a test HTTP request using the provided config snapshot. Does not persist anything.",
    responses={
        403: error_response(
            description="Caller lacks permission to edit this flow.",
            message="Insufficient permissions.",
            intric_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "space_membership"},
        ),
    },
)
async def test_flow_http(
    id: Annotated[UUID, Path(description="Flow ID")],
    request: Request,
    body: HttpTestRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    import httpx as _httpx

    await _require_flow_edit_access(request, container, flow_id=id)

    try:
        config = HttpAuthoredConfig.model_validate(body.config)
    except Exception as exc:
        return {"success": False, "error_code": "INVALID_CONFIG", "error_message": str(exc)}

    # Resolve stored config for secret merging
    flow_service = container.flow_service()
    flow = await flow_service.get_flow(id)
    stored_config = _find_stored_http_config(flow, body.direction)

    encryption_service = container.encryption_service() if hasattr(container, "encryption_service") else None

    async def _send(
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        timeout_seconds: float,
        body_bytes: bytes | None = None,
        json_body: dict | list | None = None,
        **_kwargs: object,
    ) -> _httpx.Response:
        async with _httpx.AsyncClient() as client:
            return await client.request(
                method=method,
                url=url,
                headers=headers,
                content=body_bytes,
                json=json_body,
                timeout=timeout_seconds,
            )

    from intric.main.config import get_settings

    result = await execute_http_test(
        config=config,
        direction=body.direction,
        method=body.method,
        test_variables=body.test_variables,
        stored_config=stored_config,
        encryption_service=encryption_service,
        send_http_request=_send,
        max_timeout=float(get_settings().flow_http_max_timeout_seconds),
    )

    user = container.user()
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.FLOW_UPDATED,
        entity_type=EntityType.FLOW,
        entity_id=id,
        description=f"Tested HTTP {body.method} connection for flow",
        metadata=AuditMetadata.standard(
            actor=user,
            target=flow,
            extra={"test_direction": body.direction, "test_success": result.success},
        ),
    )

    return {
        "success": result.success,
        "status_code": result.status_code,
        "duration_ms": result.duration_ms,
        "response_preview": result.response_preview,
        "request_preview": result.request_preview,
        "error_code": result.error_code,
        "error_message": result.error_message,
    }


def _find_stored_http_config(flow: Any, direction: str) -> HttpAuthoredConfig | None:
    """Find the first stored HTTP authored config in the flow steps for secret merging."""
    for step in flow.steps:
        config = step.output_config if direction == "output" else step.input_config
        if isinstance(config, dict) and is_authored_config(config):
            try:
                return HttpAuthoredConfig.model_validate(config)
            except Exception:
                pass
    return None
