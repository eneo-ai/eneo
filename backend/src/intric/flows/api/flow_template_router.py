from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Path, Query, Request, UploadFile, status

from intric.audit.application.audit_metadata import AuditMetadata
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.files.file_models import SignedURLRequest, SignedURLResponse
from intric.files.signed_urls import build_signed_download_response
from intric.flows.api.flow_api_common import error_response
from intric.flows.api.flow_definition_access import require_flow_edit_access
from intric.flows.api.flow_template_asset_models import (
    FlowTemplateAssetPublic,
    FlowTemplateInspectionPublic,
)
from intric.main.container.container import Container
from intric.main.exceptions import ErrorCodes
from intric.server.dependencies.container import get_container

router = APIRouter()


@router.get(
    "/{id}/template-files/",
    response_model=list[FlowTemplateAssetPublic],
    status_code=status.HTTP_200_OK,
    operation_id="list_flow_template_files",
    summary="List Flow Templates",
    description=(
        "List DOCX template assets attached to the current flow draft. Use this "
        "authoring endpoint when building template-fill configuration screens: the "
        "response identifies which stored templates can be selected, inspected, or "
        "downloaded. These files are reusable draft assets, not per-run runtime uploads."
    ),
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
        Path(
            description="Identifier of the draft flow whose template assets should be listed."
        ),
    ],
    request: Request,
    container: Container = Depends(get_container(with_user=True)),
):
    await require_flow_edit_access(request, container, flow_id=id)
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
    description=(
        "Scan one stored DOCX template asset and return placeholders discovered in "
        "the document body, tables, headers, and footers. Use the returned names to "
        "map template-fill output fields before publishing. Inspection is read-only: "
        "it does not mutate the template file or the flow draft."
    ),
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
    await require_flow_edit_access(request, container, flow_id=id)
    inspection = await container.flow_template_asset_service().inspect_asset(
        flow_id=id,
        asset_id=file_id,
    )
    return FlowTemplateInspectionPublic.model_validate(inspection).model_dump(
        mode="json"
    )


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
        Path(
            description="Identifier of the draft flow that will own the uploaded template asset."
        ),
    ],
    request: Request,
    upload_file: UploadFile = File(
        ...,
        description="DOCX template file to store for later template_fill steps.",
    ),
    container: Container = Depends(get_container(with_user=True)),
):
    await require_flow_edit_access(request, container, flow_id=id)

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
        entity_id=asset.file_id,
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
    description=(
        "Generate a temporary signed download URL for a stored flow template asset. "
        "Use this authoring endpoint to preview or download the reusable DOCX template "
        "that belongs to the draft flow. It is separate from run artifact downloads; "
        "run-generated files use the artifact signed-url endpoint under `/runs/{run_id}`."
    ),
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
    await require_flow_edit_access(request, container, flow_id=id)
    asset, file = await container.flow_template_asset_service().get_asset_with_file(
        flow_id=id,
        asset_id=file_id,
    )
    return build_signed_download_response(
        base_url=str(request.base_url),
        file_id=asset.file_id,
        tenant_id=file.tenant_id,
        signed_url_request=signed_url_req,
    )


__all__ = ["router"]
