from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Path, Request, UploadFile, status

from intric.audit.application.audit_metadata import AuditMetadata
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.files.file_models import FilePublic
from intric.flows.api import flow_router_common as common
from intric.flows.api.flow_api_common import error_response
from intric.flows.api.flow_models import FlowInputPolicyPublic, FlowRunContractPublic
from intric.main.container.container import Container
from intric.main.exceptions import ErrorCodes
from intric.server.dependencies.container import get_container

router = APIRouter()


@router.get(
    "/{id}/run-contract/",
    response_model=FlowRunContractPublic,
    status_code=status.HTTP_200_OK,
    operation_id="get_flow_run_contract",
    summary="Get flow run contract",
    description="""
Return the canonical run-time contract for a published flow.

Use this endpoint before rendering a run form to discover:
- published flow version for stale-submit protection
- structured form fields
- step-specific runtime input requirements
- aggregate file limits
- published template readiness and capability state
    """,
    responses={
        400: error_response(
            description="Flow is not published or runtime contract could not be resolved.",
            message="Flow must be published before a run contract can be created.",
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
async def get_flow_run_contract(
    id: Annotated[
        UUID,
        Path(description="Identifier of the published flow whose run contract should be returned."),
    ],
    request: Request,
    container: Container = Depends(get_container(with_user=True)),
):
    await common.enforce_flow_scope_for_request(
        request,
        container,
        flow_id=id,
        required_access="view",
    )
    contract = await common.flow_upload_service(container).get_run_contract(flow_id=id)
    return FlowRunContractPublic.model_validate(contract)


@router.get(
    "/{id}/input-policy/",
    response_model=FlowInputPolicyPublic,
    status_code=status.HTTP_200_OK,
    operation_id="get_flow_input_policy",
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
    id: Annotated[
        UUID,
        Path(description="Identifier of the flow whose effective input policy should be returned."),
    ],
    request: Request,
    container: Container = Depends(get_container(with_user=True)),
):
    await common.enforce_flow_scope_for_request(
        request,
        container,
        flow_id=id,
        required_access="view",
    )
    policy = await common.flow_upload_service(container).get_input_policy(flow_id=id)
    return FlowInputPolicyPublic(
        flow_id=id,
        input_type=common.coerce_input_type(policy.input_type),
        input_source=common.coerce_input_source(policy.input_source),
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
    operation_id="upload_flow_file",
    openapi_extra={
        "requestBody": {
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["upload_file"],
                        "properties": {
                            "upload_file": {
                                "type": "string",
                                "format": "binary",
                            }
                        },
                    }
                }
            }
        }
    },
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
    id: Annotated[
        UUID,
        Path(description="Identifier of the published flow that should receive the uploaded run input file."),
    ],
    request: Request,
    upload_file: UploadFile = File(...),
    container: Container = Depends(get_container(with_user=True)),
):
    await common.enforce_flow_scope_for_request(
        request,
        container,
        flow_id=id,
        required_access="run",
    )
    file = await common.flow_upload_service(container).upload_file_for_flow(
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


@router.post(
    "/{id}/steps/{step_id}/runtime-files/",
    response_model=FilePublic,
    status_code=status.HTTP_201_CREATED,
    operation_id="upload_flow_runtime_file",
    openapi_extra={
        "requestBody": {
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["upload_file"],
                        "properties": {
                            "upload_file": {
                                "type": "string",
                                "format": "binary",
                            }
                        },
                    }
                }
            }
        }
    },
    summary="Upload step runtime file",
    description="""
Upload a file for a specific published runtime-input step.

The backend validates the step id, runtime-input enablement, MIME policy, and
effective size limits for the published flow version before storing the file.
    """,
    responses={
        400: error_response(
            description="Runtime step input is unknown, disabled, or invalid for upload.",
            message="Runtime input is not available for this step.",
            intric_error_code=ErrorCodes.BAD_REQUEST,
            code="flow_run_runtime_input_disabled",
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
            description="Uploaded file exceeds the effective runtime-input limit.",
            message="Uploaded file exceeds effective flow max size limit.",
            intric_error_code=ErrorCodes.FILE_TOO_LARGE,
            code="file_too_large",
        ),
        415: error_response(
            description="Unsupported media type for the selected runtime step.",
            message="Unsupported media type for this flow input policy.",
            intric_error_code=ErrorCodes.FILE_NOT_SUPPORTED,
            code="unsupported_media_type",
        ),
    },
)
async def upload_flow_runtime_file(
    id: Annotated[
        UUID,
        Path(description="Identifier of the published flow that owns the runtime-input step."),
    ],
    step_id: Annotated[
        UUID,
        Path(description="Identifier of the published step that should receive the uploaded runtime file."),
    ],
    request: Request,
    upload_file: UploadFile = File(...),
    container: Container = Depends(get_container(with_user=True)),
):
    await common.enforce_flow_scope_for_request(
        request,
        container,
        flow_id=id,
        required_access="run",
    )
    file = await common.flow_upload_service(container).upload_runtime_file_for_step(
        flow_id=id,
        step_id=step_id,
        upload_file=upload_file,
    )
    user = container.user()
    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.FILE_UPLOADED,
        entity_type=EntityType.FILE,
        entity_id=file.id,
        description=f"Uploaded runtime input file '{file.name}' for flow step {step_id}",
        metadata=AuditMetadata.standard(
            actor=user,
            target=file,
            extra={
                "flow_id": str(id),
                "step_id": str(step_id),
                "size_bytes": file.size,
                "mimetype": getattr(file, "mimetype", None),
                "upload_purpose": "flow_runtime_step_input",
            },
        ),
    )
    return file
