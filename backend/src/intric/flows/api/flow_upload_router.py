from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Path,
    Request,
    Response,
    UploadFile,
    status,
)

from intric.audit.application.audit_metadata import AuditMetadata
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.files.file_models import FilePublic
from intric.flows.api import flow_access_context
from intric.flows.api.flow_api_common import audit_actor_kwargs, error_response
from intric.flows.api.flow_models import FlowRunContractPublic
from intric.flows.api.flow_runtime_paths import (
    DELETE_RUNTIME_FILE_PATH,
    RUN_CONTRACT_PATH,
    UPLOAD_STEP_RUNTIME_FILE_PATH,
)
from intric.flows.flow_access_policy import FlowApiAction
from intric.flows.flow_api_error_code import FlowApiErrorCode
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


_FLOW_RUNTIME_UPLOAD_BAD_REQUEST_EXAMPLES: dict[str, dict[str, object]] = {
    FlowApiErrorCode.FLOW_NOT_PUBLISHED.value: {
        "summary": "Flow is not published.",
        "value": {
            "message": "Flow must be published before runtime files can be uploaded.",
            "intric_error_code": int(ErrorCodes.BAD_REQUEST),
            "code": FlowApiErrorCode.FLOW_NOT_PUBLISHED.value,
        },
    },
    FlowApiErrorCode.RUN_UNKNOWN_STEP_INPUT.value: {
        "summary": "Runtime step id is not in the published contract.",
        "value": {
            "message": "Unknown runtime step id.",
            "intric_error_code": int(ErrorCodes.BAD_REQUEST),
            "code": FlowApiErrorCode.RUN_UNKNOWN_STEP_INPUT.value,
            "context": {"step_id": "3a6610d2-8b8b-4837-b260-8e66d2155405"},
        },
    },
    FlowApiErrorCode.RUN_RUNTIME_INPUT_DISABLED.value: {
        "summary": "Runtime input is disabled for the step.",
        "value": {
            "message": "Runtime input is not enabled for this step.",
            "intric_error_code": int(ErrorCodes.BAD_REQUEST),
            "code": FlowApiErrorCode.RUN_RUNTIME_INPUT_DISABLED.value,
        },
    },
    FlowApiErrorCode.RUNTIME_FILE_EMPTY.value: {
        "summary": "Uploaded file is empty.",
        "value": {
            "message": "Uploaded file is empty.",
            "intric_error_code": int(ErrorCodes.BAD_REQUEST),
            "code": FlowApiErrorCode.RUNTIME_FILE_EMPTY.value,
            "context": {"flow_id": "d4f60ea3-8fb7-4ab5-9d89-73e9d9a9f818"},
        },
    },
}


@router.get(
    RUN_CONTRACT_PATH,
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
            code=FlowApiErrorCode.FLOW_NOT_PUBLISHED,
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
    await flow_access_context.enforce_flow_scope(
        request,
        container,
        flow_id=id,
        required_access=FlowApiAction.VIEW,
        allow_service_key_principals=True,
        require_published_for_service_key=True,
    )
    return await container.flow_run_contract_service().get_run_contract(flow_id=id)


@router.post(
    UPLOAD_STEP_RUNTIME_FILE_PATH,
    response_model=FilePublic,
    status_code=status.HTTP_201_CREATED,
    operation_id="upload_flow_runtime_file",
    openapi_extra=_upload_file_multipart_openapi_extra(),
    summary="Upload step runtime file",
    description="""
Upload a file for a specific published runtime-input step.

The backend validates the step id, runtime-input enablement, MIME policy, and
effective size limits for the published flow version before storing the file.
Use the returned file id in `step_inputs[step_id].file_ids` when creating the
run. The same file id may be reused for other compatible runtime-input steps
within this Flow. To use the same local source with another Flow, upload it
through that Flow's runtime upload endpoint.
    """,
    responses={
        400: error_response(
            description="Runtime step input is unknown, disabled, or invalid for upload.",
            examples=_FLOW_RUNTIME_UPLOAD_BAD_REQUEST_EXAMPLES,
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
    await flow_access_context.enforce_flow_scope(
        request,
        container,
        flow_id=id,
        required_access=FlowApiAction.RUN,
        allow_service_key_principals=True,
        require_published_for_service_key=True,
    )
    file = await container.flow_runtime_file_service().upload_runtime_file_for_step(
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


@router.delete(
    DELETE_RUNTIME_FILE_PATH,
    response_model=None,
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    operation_id="delete_flow_runtime_file",
    summary="Delete orphan runtime file",
    description="""
Delete an owned runtime file that was uploaded for a published Flow run but has not
been attached to persisted run state. Use this to clean up an abandoned pre-run
upload before creating a run. The file must be owned by the caller and bound to the
Flow id in the path. Files already attached to Flow run inputs or outputs return a
typed 409 conflict.
    """,
    responses={
        204: {
            "description": "Runtime file deleted successfully. No response body is returned."
        },
        400: error_response(
            description="Flow is not published for runtime file deletion.",
            message="Flow must be published before runtime files can be deleted.",
            intric_error_code=ErrorCodes.BAD_REQUEST,
            code=FlowApiErrorCode.FLOW_NOT_PUBLISHED,
        ),
        403: error_response(
            description="Forbidden: API key scope does not match flow space.",
            message="API key space scope does not match requested flow.",
            intric_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
        404: error_response(
            description=(
                "Flow not found, or runtime file is not owned by the caller or "
                "was not uploaded for this Flow."
            ),
            message="Not found",
            intric_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
        409: error_response(
            description="Runtime file is already attached to persisted Flow run state.",
            message="Runtime file is already attached to a flow run.",
            intric_error_code=ErrorCodes.CONFLICT,
            code=FlowApiErrorCode.RUNTIME_FILE_ATTACHED,
        ),
    },
)
async def delete_flow_runtime_file(
    id: Annotated[
        UUID,
        Path(description="Identifier of the published flow used for runtime access."),
    ],
    file_id: Annotated[
        UUID,
        Path(description="Identifier of the owned orphan runtime file to delete."),
    ],
    request: Request,
    container: Container = Depends(get_container(with_user=True)),
) -> None:
    await flow_access_context.enforce_flow_scope(
        request,
        container,
        flow_id=id,
        required_access=FlowApiAction.RUN,
        allow_service_key_principals=True,
        require_published_for_service_key=True,
    )
    file = await container.flow_runtime_file_service().delete_runtime_file(
        flow_id=id,
        file_id=file_id,
    )
    user = container.user()
    actor_kwargs = audit_actor_kwargs(user)
    file_type = getattr(file, "file_type", None)
    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        actor_id=actor_kwargs["actor_id"],
        actor_type=actor_kwargs["actor_type"],
        actor_api_key_id=actor_kwargs["actor_api_key_id"],
        action=ActionType.FILE_DELETED,
        entity_type=EntityType.FILE,
        entity_id=file.id,
        description=f"Deleted runtime input file '{file.name}' for flow {id}",
        metadata=AuditMetadata.standard(
            actor=user,
            target=file,
            extra={
                "flow_id": str(id),
                "file_id": str(file_id),
                "size_bytes": file.size,
                "mimetype": getattr(file, "mimetype", None),
                "file_type": getattr(file_type, "value", file_type),
                "runtime_role": "flow_runtime_step_input",
            },
        ),
    )


__all__ = ["router"]
