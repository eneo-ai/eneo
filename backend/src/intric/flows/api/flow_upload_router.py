from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Path, Request, UploadFile, status

from intric.audit.application.audit_metadata import AuditMetadata
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.files.file_models import FilePublic
from intric.flows.api import flow_router_common as common
from intric.flows.api.flow_api_common import audit_actor_kwargs, error_response
from intric.flows.api.flow_models import FlowRunContractPublic
from intric.main.container.container import Container
from intric.main.exceptions import ErrorCodes
from intric.server.dependencies.container import get_container

router = APIRouter()


def _upload_file_multipart_openapi_extra() -> dict[str, object]:
    return {
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
    }


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
- terminal output type and delivery mode, so clients know whether the successful run
  yields a payload, generated file, or outbound HTTP delivery
- structured form fields
- step-specific runtime input requirements
- runtime upload timeout policy for browser and API clients
- steps that can pause for human review, including the output shape a review UI should render
  and the effective `expires_after_seconds` review window
- aggregate file limits
- published template readiness and capability state

Recommended consumer flow:
1. Render `form_fields` as the run form.
2. Upload files before run creation and attach each file id through `step_inputs[step_id].file_ids`.
   For browser uploads, compute the initial timeout from the actual file size using
   `runtime_upload_policy`, then keep the upload alive while progress events continue.
3. Prebuild optional review screens from `steps_requiring_review`; use
   `expires_after_seconds` to show the review deadline once the checkpoint opens.
4. Start the run with `expected_flow_version=published_flow_version`.
5. When a run reaches `awaiting_review`, call the active checkpoint endpoint for the immutable
   step snapshot and editable payload.

Service-key principals may use this endpoint for published-flow runtime only.
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
        Path(
            description="Identifier of the published flow whose run contract should be returned."
        ),
    ],
    request: Request,
    container: Container = Depends(get_container(with_user=True)),
):
    await common.enforce_flow_scope_for_request(
        request,
        container,
        flow_id=id,
        required_access=common.FlowApiAction.VIEW,
        allow_service_key_principals=True,
        require_published_for_service_key=True,
    )
    return await common.flow_run_contract_service(container).get_run_contract(
        flow_id=id
    )


@router.post(
    "/{id}/files/",
    response_model=FilePublic,
    status_code=status.HTTP_201_CREATED,
    operation_id="upload_flow_file",
    openapi_extra=_upload_file_multipart_openapi_extra(),
    summary="Upload flow input file",
    description="""
Upload a file using published runtime input checks.

This endpoint is a compatibility shortcut for external API consumers. Validation is based
on the first `flow_input` runtime step in the published run contract; draft edits take
effect only after republish.
- accepted input types: audio/document/file
- allowed mimetypes
- effective tenant flow size limits
- multipart form field name: `upload_file`
    """,
    responses={
        400: error_response(
            description=(
                "Upload request is invalid for the published runtime input contract. "
                "Representative machine-readable codes include: "
                "flow_input_upload_not_supported and flow_input_file_empty."
            ),
            message="Published runtime input contract does not allow file upload.",
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
            description="Unsupported media type for the published runtime input contract.",
            message="Unsupported media type for the published runtime input contract.",
            intric_error_code=ErrorCodes.FILE_NOT_SUPPORTED,
            code="unsupported_media_type",
        ),
    },
)
async def upload_flow_file(
    id: Annotated[
        UUID,
        Path(
            description="Identifier of the published flow that should receive the uploaded run input file."
        ),
    ],
    request: Request,
    upload_file: UploadFile = File(...),
    container: Container = Depends(get_container(with_user=True)),
):
    await common.enforce_flow_scope_for_request(
        request,
        container,
        flow_id=id,
        required_access=common.FlowApiAction.RUN,
        allow_service_key_principals=True,
        require_published_for_service_key=True,
    )
    file = await common.flow_upload_service(container).upload_file_for_flow(
        flow_id=id,
        upload_file=upload_file,
    )
    user = container.user()
    actor_kwargs = audit_actor_kwargs(user)
    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        actor_id=actor_kwargs["actor_id"],
        actor_type=actor_kwargs["actor_type"],
        actor_api_key_id=actor_kwargs["actor_api_key_id"],
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
    openapi_extra=_upload_file_multipart_openapi_extra(),
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
            message="Unsupported media type for the selected runtime step.",
            intric_error_code=ErrorCodes.FILE_NOT_SUPPORTED,
            code="unsupported_media_type",
        ),
    },
)
async def upload_flow_runtime_file(
    id: Annotated[
        UUID,
        Path(
            description="Identifier of the published flow that owns the runtime-input step."
        ),
    ],
    step_id: Annotated[
        UUID,
        Path(
            description="Identifier of the published step that should receive the uploaded runtime file."
        ),
    ],
    request: Request,
    upload_file: UploadFile = File(...),
    container: Container = Depends(get_container(with_user=True)),
):
    await common.enforce_flow_scope_for_request(
        request,
        container,
        flow_id=id,
        required_access=common.FlowApiAction.RUN,
        allow_service_key_principals=True,
        require_published_for_service_key=True,
    )
    file = await common.flow_upload_service(container).upload_runtime_file_for_step(
        flow_id=id,
        step_id=step_id,
        upload_file=upload_file,
    )
    user = container.user()
    actor_kwargs = audit_actor_kwargs(user)
    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        actor_id=actor_kwargs["actor_id"],
        actor_type=actor_kwargs["actor_type"],
        actor_api_key_id=actor_kwargs["actor_api_key_id"],
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
