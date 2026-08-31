from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, NoReturn, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.files.file_models import FileMetadata, SignedURLRequest, SignedURLResponse
from eneo.files.signed_urls import build_signed_download_response
from eneo.flows.api import flow_access_context
from eneo.flows.api.flow_api_common import (
    error_response,
    flow_run_evidence_snapshot_transaction,
)
from eneo.flows.api.flow_assembler import FlowAssembler
from eneo.flows.api.flow_definition_access import require_flow_published_runtime_access
from eneo.flows.api.flow_graph import (
    GraphResponse,
    build_graph_response,
)
from eneo.flows.api.flow_models import FlowRunStepPublic
from eneo.flows.api.flow_runtime_paths import (
    FLOW_GRAPH_PATH,
    FLOW_RUN_ARTIFACT_SIGNED_URL_PATH,
    FLOW_RUN_INPUT_FILE_SIGNED_URL_PATH,
    FLOW_RUN_STEPS_PATH,
)
from eneo.flows.api.flow_trace_audit import (
    log_flow_trace_audit_or_raise,
    raise_flow_trace_audit_unavailable,
)
from eneo.flows.domain.flow import FlowRun
from eneo.flows.flow_access_policy import FlowApiAction
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.published_runtime import load_published_definition
from eneo.main.config import get_settings
from eneo.main.container.container import Container
from eneo.main.exceptions import AuditLoggingUnavailableException, ErrorCodes
from eneo.main.logging import get_logger
from eneo.server.dependencies.container import (
    get_container,
    get_container_for_explicit_transaction,
)
from eneo.users.user import UserInDB

router = APIRouter()
logger = get_logger(__name__)

_FLOW_RUNTIME_FORBIDDEN_DESCRIPTION = (
    "Forbidden. Caller scope, tenant or space permission, and run visibility are "
    "evaluated before returning Flow runtime data."
)

_FLOW_RUN_STEPS_DESCRIPTION = """
Return ordered step-level execution results for one flow run.

Designed for consumer UIs that need to inspect intermediate outputs, diagnostics, and token usage
without relying on debug-export internals.

Current content visibility is policy-based: callers can inspect their own runs, tenant admins can
inspect runs across the tenant, trusted in-space operators (space owner and space admin) can
inspect content for runs in their space, and service-key principals can inspect only their own
runs.
    """

_FLOW_RUN_ARTIFACT_DESCRIPTION = """
Generate a time-limited signed download URL for a file produced by a flow run.

Artifact visibility is policy-based: callers can download artifacts from their own runs, tenant
admins can download artifacts across the tenant, trusted in-space operators (space owner and space
admin) can download artifacts for runs in their space, and service-key principals can download only
their own run artifacts.

The file_id must reference an artifact that was actually produced by a step in the specified run.

Service-key principals are supported for their own runtime artifacts in v1.
    """


async def _log_required_run_file_access(
    *,
    container: Container,
    file: FileMetadata,
    description: str,
    extra: Mapping[str, object],
) -> None:
    user = container.user()
    await container.audit_service().log(
        tenant_id=user.tenant_id,
        user=user,
        action=ActionType.FILE_SIGNED_URL_MINTED,
        entity_type=EntityType.FILE,
        entity_id=file.id,
        description=description,
        metadata=AuditMetadata.standard(actor=user, target=file, extra=extra),
        required=True,
    )


def _raise_run_file_access_audit_unavailable(
    *,
    tenant_id: UUID,
    flow_id: UUID,
    run_id: UUID,
    file_id: UUID,
    cause: BaseException,
) -> NoReturn:
    logger.exception(
        "Required Flow run file access audit logging failed",
        extra={
            "tenant_id": str(tenant_id),
            "flow_id": str(flow_id),
            "run_id": str(run_id),
            "file_id": str(file_id),
        },
    )
    raise AuditLoggingUnavailableException(
        "Flow run file access audit logging is unavailable.",
        code=FlowApiErrorCode.RUN_FILE_ACCESS_AUDIT_UNAVAILABLE.value,
        context={"audit_required": True},
    ) from cause


@router.get(
    FLOW_RUN_STEPS_PATH,
    response_model=list[FlowRunStepPublic],
    status_code=status.HTTP_200_OK,
    operation_id="list_flow_run_steps",
    summary="List flow run step outputs",
    description=_FLOW_RUN_STEPS_DESCRIPTION,
    responses={
        403: error_response(
            description=_FLOW_RUNTIME_FORBIDDEN_DESCRIPTION,
            message="API key space scope does not match requested flow.",
            eneo_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
        404: error_response(
            description="Run not found for this flow and tenant.",
            message="Flow run not found.",
            eneo_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
        503: error_response(
            description=(
                "Required access audit logging is unavailable, so no step "
                "outputs were returned."
            ),
            message="Evidence audit logging is unavailable.",
            eneo_error_code=ErrorCodes.INTERNAL_SERVER_ERROR,
            code=FlowApiErrorCode.EVIDENCE_AUDIT_LOGGING_FAILED,
            context={"audit_required": True},
        ),
    },
)
async def list_flow_run_steps(
    id: Annotated[
        UUID, Path(description="Identifier of the flow that owns the run step outputs.")
    ],
    run_id: Annotated[
        UUID,
        Path(description="Identifier of the run whose step outputs should be listed."),
    ],
    request: Request,
    container: Container = Depends(
        get_container_for_explicit_transaction(
            with_user=True,
            with_upload_admission=True,
        )
    ),
):
    committed_audit_context: tuple[UserInDB, FlowRun] | None = None
    try:
        async with flow_run_evidence_snapshot_transaction(container):
            await flow_access_context.enforce_flow_scope(
                request,
                container,
                flow_id=id,
                required_access=FlowApiAction.VIEW,
                allow_service_key_principals=True,
            )
            run_service = container.flow_run_service()
            run = await run_service.get_run(
                run_id=run_id,
                flow_id=id,
                access_kind="content",
            )
            step_result_views = await run_service.list_step_results_with_files(
                run_id=run_id,
                flow_id=id,
            )
            assembler = FlowAssembler()
            response = [
                assembler.to_step_public(
                    view.step_result,
                    runtime_input_file_ids=view.runtime_input_file_ids,
                    result_files=view.result_files,
                )
                for view in step_result_views
            ]
            user = container.user()
            await log_flow_trace_audit_or_raise(
                container=container,
                user=user,
                run=run,
                action=ActionType.FLOW_EVIDENCE_VIEWED,
                description=f"Viewed step outputs for flow run {run.id}",
                extra={"evidence_detail": "step_outputs"},
            )
            committed_audit_context = (user, run)
    except AuditLoggingUnavailableException:
        raise
    except Exception as exc:
        if committed_audit_context is not None:
            audit_user, audited_run = committed_audit_context
            raise_flow_trace_audit_unavailable(
                user=audit_user,
                run=audited_run,
                action=ActionType.FLOW_EVIDENCE_VIEWED,
                cause=exc,
            )
        raise
    return response


@router.get(
    FLOW_GRAPH_PATH,
    response_model=GraphResponse,
    status_code=status.HTTP_200_OK,
    operation_id="get_flow_graph",
    summary="Get flow graph",
    description="""
Return the graph representation for the current published Flow version or one version-pinned run.

When `run_id` is provided, the graph is built from the run's published version snapshot and
annotated with run execution results. Without `run_id`, the graph is built from the current
published snapshot and contains no run annotations. Unpublished draft changes are never exposed
through this runtime endpoint.

Service-key principals may use this endpoint for published-flow runtime topology and for
their own run snapshots. Authoring still requires a user principal.
    """,
    responses={
        400: error_response(
            description=(
                "The published snapshot failed integrity verification. "
                "The machine-readable code is `flow_definition_checksum_mismatch`."
            ),
            message="Published Flow definition integrity verification failed.",
            eneo_error_code=ErrorCodes.BAD_REQUEST,
            code=FlowApiErrorCode.DEFINITION_CHECKSUM_MISMATCH,
        ),
        403: error_response(
            description="Forbidden: API key scope does not match flow space.",
            message="API key space scope does not match requested flow.",
            eneo_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
        404: error_response(
            description=(
                "Published Flow or run not found in tenant scope. Without `run_id`, "
                "an unpublished Flow is hidden. A version-pinned run graph remains "
                "readable subject to run access."
            ),
            message="Flow not found.",
            eneo_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
    },
)
async def get_flow_graph(
    id: Annotated[
        UUID, Path(description="Identifier of the flow whose graph should be returned.")
    ],
    request: Request,
    run_id: UUID | None = Query(
        default=None,
        description=(
            "Optional run identifier. When provided, the graph is resolved from "
            "that run's version-pinned snapshot and annotated with run results."
        ),
    ),
    container: Container = Depends(
        get_container(with_user=True, with_upload_admission=True)
    ),
):
    if run_id is not None:
        await flow_access_context.enforce_flow_scope(
            request,
            container,
            flow_id=id,
            required_access=FlowApiAction.VIEW,
            allow_service_key_principals=True,
        )
        flow_run_service = container.flow_run_service()
        versioned_view = await flow_run_service.get_run_versioned_view(
            flow_id=id,
            run_id=run_id,
        )
        return build_graph_response(
            versioned_view.published_definition.steps,
            versioned_view.step_results,
            wizard_metadata=versioned_view.published_definition.metadata().wizard,
            speaker_identification_available=(
                get_settings().flow_transcription_service_configured
            ),
        )

    published_access = await require_flow_published_runtime_access(
        request,
        container,
        flow_id=id,
    )
    published_definition = await load_published_definition(
        flow_version_repo=container.flow_version_repo(),
        flow_id=id,
        version=published_access.published_version,
        tenant_id=published_access.flow.tenant_id,
    )
    return build_graph_response(
        published_definition.steps,
        wizard_metadata=published_definition.metadata().wizard,
        speaker_identification_available=(
            get_settings().flow_transcription_service_configured
        ),
    )


@router.post(
    FLOW_RUN_ARTIFACT_SIGNED_URL_PATH,
    response_model=SignedURLResponse,
    status_code=status.HTTP_200_OK,
    operation_id="generate_flow_run_artifact_signed_url",
    summary="Generate signed URL for a flow run artifact",
    description=_FLOW_RUN_ARTIFACT_DESCRIPTION,
    responses={
        403: error_response(
            description=_FLOW_RUNTIME_FORBIDDEN_DESCRIPTION,
            message="API key space scope does not match requested flow.",
            eneo_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
        404: error_response(
            description="Flow, run, or artifact not found.",
            message="Artifact not found for this run.",
            eneo_error_code=ErrorCodes.NOT_FOUND,
            code=FlowApiErrorCode.RUN_ARTIFACT_NOT_FOUND,
        ),
        410: error_response(
            description="Artifact content was purged by retention policy.",
            message="Artifact content has been purged by retention policy.",
            eneo_error_code=ErrorCodes.RESOURCE_GONE,
            code=FlowApiErrorCode.RUN_ARTIFACT_CONTENT_UNAVAILABLE,
        ),
        503: error_response(
            description=(
                "Required access audit logging is unavailable, so no artifact "
                "download URL was minted."
            ),
            message="Flow run file access audit logging is unavailable.",
            eneo_error_code=ErrorCodes.INTERNAL_SERVER_ERROR,
            code=FlowApiErrorCode.RUN_FILE_ACCESS_AUDIT_UNAVAILABLE,
            context={"audit_required": True},
        ),
    },
)
async def generate_flow_run_artifact_signed_url(
    id: Annotated[
        UUID,
        Path(
            description="Identifier of the flow that owns the requested run artifact."
        ),
    ],
    run_id: Annotated[
        UUID, Path(description="Identifier of the run that produced the artifact.")
    ],
    file_id: Annotated[
        UUID, Path(description="Identifier of the run artifact file to download.")
    ],
    request: Request,
    signed_url_req: SignedURLRequest,
    container: Container = Depends(
        get_container_for_explicit_transaction(
            with_user=True,
            with_upload_admission=True,
        )
    ),
):
    session = cast(AsyncSession, container.session())
    audit_tenant_id: UUID | None = None
    file: FileMetadata | None = None
    try:
        async with session.begin():
            await flow_access_context.enforce_flow_scope(
                request,
                container,
                flow_id=id,
                required_access=FlowApiAction.VIEW,
                allow_service_key_principals=True,
            )
            file = await container.flow_run_evidence_service().get_run_artifact_file(
                run_id=run_id,
                flow_id=id,
                file_id=file_id,
            )
            audit_tenant_id = container.user().tenant_id
            await _log_required_run_file_access(
                container=container,
                file=file,
                description=f"Minted a download URL for Flow run artifact '{file.name}'",
                extra={
                    "flow_id": str(id),
                    "run_id": str(run_id),
                    "file_id": str(file.id),
                    "download_purpose": "flow_run_artifact",
                    "artifact_name": file.name,
                    "mimetype": getattr(file, "mimetype", None),
                    "size_bytes": getattr(file, "size", None),
                },
            )
    except AuditLoggingUnavailableException:
        raise
    except Exception as exc:
        if audit_tenant_id is None:
            raise
        _raise_run_file_access_audit_unavailable(
            tenant_id=audit_tenant_id,
            flow_id=id,
            run_id=run_id,
            file_id=file_id,
            cause=exc,
        )

    assert file is not None
    return build_signed_download_response(
        base_url=str(request.base_url),
        file_id=file_id,
        tenant_id=file.tenant_id,
        signed_url_request=signed_url_req,
    )


_FLOW_RUN_INPUT_FILE_DESCRIPTION = """
Generate a time-limited signed download URL for a file the run received as step input, such as
the audio recording a transcription step read.

Visibility follows the run's artifact policy: callers can download input files from their own
runs, tenant admins across the tenant, trusted in-space operators (space owner and space admin)
for runs in their space, and service-key principals only for their own runs. The uploader need
not be the caller: a reviewer confirming a transcript needs the recording behind it.

The file_id must be listed in a step result's `runtime_input_file_ids` for the specified run.
Audio downloads honour HTTP Range requests, so the URL can be used directly as a media source.
"""


@router.post(
    FLOW_RUN_INPUT_FILE_SIGNED_URL_PATH,
    response_model=SignedURLResponse,
    status_code=status.HTTP_200_OK,
    operation_id="generate_flow_run_input_file_signed_url",
    summary="Generate signed URL for a flow run input file",
    description=_FLOW_RUN_INPUT_FILE_DESCRIPTION,
    responses={
        403: error_response(
            description=_FLOW_RUNTIME_FORBIDDEN_DESCRIPTION,
            message="API key space scope does not match requested flow.",
            eneo_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
        404: error_response(
            description="Flow, run, or input file not found.",
            message="Input file not found for this run.",
            eneo_error_code=ErrorCodes.NOT_FOUND,
            code=FlowApiErrorCode.RUN_INPUT_FILE_NOT_FOUND,
        ),
        410: error_response(
            description="Input file content was purged by retention policy.",
            message="Input file content has been purged by retention policy.",
            eneo_error_code=ErrorCodes.RESOURCE_GONE,
            code=FlowApiErrorCode.RUN_INPUT_FILE_CONTENT_UNAVAILABLE,
        ),
        503: error_response(
            description=(
                "Required access audit logging is unavailable, so no input-file "
                "download URL was minted."
            ),
            message="Flow run file access audit logging is unavailable.",
            eneo_error_code=ErrorCodes.INTERNAL_SERVER_ERROR,
            code=FlowApiErrorCode.RUN_FILE_ACCESS_AUDIT_UNAVAILABLE,
            context={"audit_required": True},
        ),
    },
)
async def generate_flow_run_input_file_signed_url(
    id: Annotated[
        UUID,
        Path(description="Identifier of the flow that owns the requested run."),
    ],
    run_id: Annotated[
        UUID, Path(description="Identifier of the run that received the file.")
    ],
    file_id: Annotated[
        UUID, Path(description="Identifier of the run input file to download.")
    ],
    request: Request,
    signed_url_req: SignedURLRequest,
    container: Container = Depends(
        get_container_for_explicit_transaction(
            with_user=True,
            with_upload_admission=True,
        )
    ),
):
    session = cast(AsyncSession, container.session())
    audit_tenant_id: UUID | None = None
    file: FileMetadata | None = None
    try:
        async with session.begin():
            await flow_access_context.enforce_flow_scope(
                request,
                container,
                flow_id=id,
                required_access=FlowApiAction.VIEW,
                allow_service_key_principals=True,
            )
            file = await container.flow_run_evidence_service().get_run_input_file(
                run_id=run_id,
                flow_id=id,
                file_id=file_id,
            )
            audit_tenant_id = container.user().tenant_id
            await _log_required_run_file_access(
                container=container,
                file=file,
                description=f"Minted a download URL for Flow run input '{file.name}'",
                extra={
                    "flow_id": str(id),
                    "run_id": str(run_id),
                    "file_id": str(file.id),
                    "download_purpose": "flow_run_input",
                    "file_name": file.name,
                    "mimetype": getattr(file, "mimetype", None),
                    "size_bytes": getattr(file, "size", None),
                    "content_disposition": signed_url_req.content_disposition.value,
                    "expires_in_seconds": signed_url_req.expires_in,
                },
            )
    except AuditLoggingUnavailableException:
        raise
    except Exception as exc:
        if audit_tenant_id is None:
            raise
        _raise_run_file_access_audit_unavailable(
            tenant_id=audit_tenant_id,
            flow_id=id,
            run_id=run_id,
            file_id=file_id,
            cause=exc,
        )

    assert file is not None
    return build_signed_download_response(
        base_url=str(request.base_url),
        file_id=file_id,
        tenant_id=file.tenant_id,
        signed_url_request=signed_url_req,
    )


__all__ = ["router"]
