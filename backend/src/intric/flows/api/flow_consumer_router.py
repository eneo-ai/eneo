from __future__ import annotations

import time
from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Query, Request, UploadFile, status

from intric.audit.application.audit_metadata import AuditMetadata
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.authentication.signed_urls import generate_signed_token
from intric.files.file_models import FilePublic, SignedURLRequest, SignedURLResponse
from intric.flows.api import flow_router_common as common
from intric.flows.api.flow_api_common import error_response
from intric.flows.api.flow_assembler import FlowAssembler
from intric.flows.api.flow_graph import build_graph_from_steps, enrich_nodes_with_run_results
from intric.flows.api.flow_models import (
    FlowInputPolicyPublic,
    FlowRunContractPublic,
    FlowRunCreateRequest,
    FlowRunEvidenceResponse,
    FlowRunPublic,
    FlowRunRedispatchResponse,
    FlowRunStepPublic,
    GraphResponse,
)
from intric.main.container.container import Container
from intric.main.exceptions import ErrorCodes
from intric.main.models import PaginatedResponse
from intric.server.dependencies.container import get_container

router = APIRouter()


@router.post(
    "/{id}/runs/",
    response_model=FlowRunPublic,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_flow_run",
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
    await common.enforce_flow_scope_for_request(request, container, flow_id=id)
    assembler = FlowAssembler()
    run_service = container.flow_run_service()
    user = container.user()
    run = await run_service.create_run(
        flow_id=id,
        input_payload_json=run_in.input_payload_json,
        expected_flow_version=run_in.expected_flow_version,
        step_inputs=run_in.step_inputs,
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
        common.dispatch_flow_run_after_commit,
        run_id=run.id,
        flow_id=id,
        tenant_id=user.tenant_id,
        user_id=user.id,
    )
    return assembler.to_run_public(run)


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
    id: UUID,
    request: Request,
    container: Container = Depends(get_container(with_user=True)),
):
    await common.enforce_flow_scope_for_request(request, container, flow_id=id)
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
    id: UUID,
    request: Request,
    container: Container = Depends(get_container(with_user=True)),
):
    await common.enforce_flow_scope_for_request(request, container, flow_id=id)
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
    id: UUID,
    request: Request,
    upload_file: UploadFile = File(...),
    container: Container = Depends(get_container(with_user=True)),
):
    await common.enforce_flow_scope_for_request(request, container, flow_id=id)
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
    id: UUID,
    step_id: UUID,
    request: Request,
    upload_file: UploadFile = File(...),
    container: Container = Depends(get_container(with_user=True)),
):
    await common.enforce_flow_scope_for_request(request, container, flow_id=id)
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


@router.get(
    "/{id}/runs/",
    response_model=PaginatedResponse[FlowRunPublic],
    status_code=status.HTTP_200_OK,
    operation_id="list_flow_runs_alias",
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
    await common.enforce_flow_scope_for_request(
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
    operation_id="get_flow_run_alias",
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
    await common.enforce_flow_scope_for_request(request, container, flow_id=id)
    run = await container.flow_run_service().get_run(run_id=run_id, flow_id=id)
    return FlowAssembler().to_run_public(run)


@router.post(
    "/{id}/runs/{run_id}/cancel/",
    response_model=FlowRunPublic,
    status_code=status.HTTP_200_OK,
    operation_id="cancel_flow_run_alias",
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
    await common.enforce_flow_scope_for_request(request, container, flow_id=id)
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
    operation_id="redispatch_flow_run_alias",
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
    await common.enforce_flow_scope_for_request(request, container, flow_id=id)
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
    operation_id="get_flow_run_evidence_alias",
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
    await common.enforce_flow_scope_for_request(request, container, flow_id=id)
    run_service = container.flow_run_service()
    await run_service.get_run(run_id=run_id, flow_id=id)
    evidence = await run_service.get_evidence(run_id=run_id)
    return FlowRunEvidenceResponse(**evidence)


@router.get(
    "/{id}/runs/{run_id}/steps/",
    response_model=list[FlowRunStepPublic],
    status_code=status.HTTP_200_OK,
    operation_id="list_flow_run_steps",
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
    await common.enforce_flow_scope_for_request(request, container, flow_id=id)
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


@router.get(
    "/{id}/graph/",
    response_model=GraphResponse,
    status_code=status.HTTP_200_OK,
    operation_id="get_flow_graph",
    summary="Get flow graph",
    description="""
Return the graph representation for a flow definition or one version-pinned run snapshot.

When `run_id` is provided, the graph is built from the run's published version snapshot and
annotated with run execution results. Otherwise the current live flow definition is used.
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
            description="Flow or run not found in tenant scope.",
            message="Flow not found.",
            intric_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
    },
)
async def get_flow_graph(
    id: UUID,
    request: Request,
    run_id: UUID | None = Query(default=None),
    container: Container = Depends(get_container(with_user=True)),
):
    await common.enforce_flow_scope_for_request(request, container, flow_id=id)
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


@router.post(
    "/{id}/runs/{run_id}/artifacts/{file_id}/signed-url/",
    response_model=SignedURLResponse,
    status_code=status.HTTP_200_OK,
    operation_id="generate_flow_run_artifact_signed_url",
    summary="Generate signed URL for a flow run artifact",
    description="""
Generate a time-limited signed download URL for a file produced by a flow run.

This endpoint uses tenant-scoped access so that any user with access to the flow
can download artifacts from any run, regardless of who created the run.

The file_id must reference an artifact that was actually produced by a step in the
specified run.
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
            description="Flow, run, or artifact not found.",
            message="Artifact not found for this run.",
            intric_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
    },
)
async def generate_flow_run_artifact_signed_url(
    id: UUID,
    run_id: UUID,
    file_id: UUID,
    request: Request,
    signed_url_req: SignedURLRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    await common.enforce_flow_scope_for_request(request, container, flow_id=id)
    run_service = container.flow_run_service()
    user = container.user()

    file = await run_service.get_run_artifact_file(
        run_id=run_id, flow_id=id, file_id=file_id,
    )

    expires_at = int(time.time()) + signed_url_req.expires_in
    token = generate_signed_token(
        file_id=file_id,
        expires_at=expires_at,
        content_disposition=signed_url_req.content_disposition,
    )
    base_url = str(request.base_url).rstrip("/")
    url = f"{base_url}/api/v1/files/{file_id}/download/?token={token}"

    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.FLOW_RUN_ARTIFACT_DOWNLOADED,
        entity_type=EntityType.FILE,
        entity_id=file_id,
        description=f"Downloaded artifact '{file.name}' from flow run",
        metadata=AuditMetadata.standard(
            actor=user,
            target=file,
            extra={
                "flow_id": str(id),
                "run_id": str(run_id),
                "artifact_name": file.name,
                "artifact_mimetype": getattr(file, "mimetype", None),
                "artifact_size_bytes": getattr(file, "size", None),
            },
        ),
    )

    return SignedURLResponse(url=url, expires_at=expires_at)
