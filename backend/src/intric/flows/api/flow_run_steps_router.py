from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request, status

from intric.audit.application.audit_metadata import AuditMetadata
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.files.file_models import SignedURLRequest, SignedURLResponse
from intric.files.signed_urls import build_signed_download_response
from intric.flows.api import flow_access_context
from intric.flows.api.flow_api_common import audit_actor_kwargs, error_response
from intric.flows.api.flow_assembler import FlowAssembler
from intric.flows.api.flow_graph import (
    GraphResponse,
    build_graph_response,
)
from intric.flows.api.flow_models import FlowRunStepPublic
from intric.flows.api.flow_runtime_paths import (
    FLOW_GRAPH_PATH,
    FLOW_RUN_ARTIFACT_SIGNED_URL_PATH,
    FLOW_RUN_STEPS_PATH,
)
from intric.flows.flow_access_policy import FlowApiAction
from intric.flows.flow_api_error_code import FlowApiErrorCode
from intric.flows.principal import FlowPrincipal
from intric.main.container.container import Container
from intric.main.exceptions import ErrorCodes, NotFoundException
from intric.server.dependencies.container import get_container

router = APIRouter()

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
    id: Annotated[
        UUID, Path(description="Identifier of the flow that owns the run step outputs.")
    ],
    run_id: Annotated[
        UUID,
        Path(description="Identifier of the run whose step outputs should be listed."),
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
    )
    step_result_views = await container.flow_run_service().list_step_results_with_files(
        run_id=run_id,
        flow_id=id,
    )
    assembler = FlowAssembler()
    return [
        assembler.to_step_public(
            view.step_result,
            runtime_input_file_ids=view.runtime_input_file_ids,
            result_files=view.result_files,
        )
        for view in step_result_views
    ]


@router.get(
    FLOW_GRAPH_PATH,
    response_model=GraphResponse,
    status_code=status.HTTP_200_OK,
    operation_id="get_flow_graph",
    summary="Get flow graph",
    description="""
Return the graph representation for a flow definition or one version-pinned run snapshot.

When `run_id` is provided, the graph is built from the run's published version snapshot and
annotated with run execution results. Otherwise the current live flow definition is used.

Service-key principals may use this endpoint for published-flow runtime topology and for
their own run snapshots. Authoring still requires a user principal.
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
    container: Container = Depends(get_container(with_user=True)),
):
    await flow_access_context.enforce_flow_scope(
        request,
        container,
        flow_id=id,
        required_access=FlowApiAction.VIEW,
        allow_service_key_principals=True,
    )
    flow_run_service = container.flow_run_service()

    if run_id is not None:
        versioned_view = await flow_run_service.get_run_versioned_view(
            flow_id=id,
            run_id=run_id,
        )
        return build_graph_response(
            versioned_view.published_definition.steps,
            versioned_view.step_results,
        )

    flow_service = container.flow_service()
    flow = await flow_service.get_flow(id)
    if (
        FlowPrincipal.from_user(container.user()).is_service_key
        and flow.published_version is None
    ):
        raise NotFoundException("Flow not found.")
    live_steps = [step.model_dump(mode="json") for step in flow.steps]
    return build_graph_response(live_steps)


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
            intric_error_code=ErrorCodes.UNAUTHORIZED,
            code="insufficient_scope",
            context={"auth_layer": "api_key_scope"},
        ),
        404: error_response(
            description="Flow, run, or artifact not found.",
            message="Artifact not found for this run.",
            intric_error_code=ErrorCodes.NOT_FOUND,
            code=FlowApiErrorCode.RUN_ARTIFACT_NOT_FOUND,
        ),
        410: error_response(
            description="Artifact content was purged by retention policy.",
            message="Artifact content has been purged by retention policy.",
            intric_error_code=ErrorCodes.RESOURCE_GONE,
            code=FlowApiErrorCode.RUN_ARTIFACT_CONTENT_UNAVAILABLE,
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
    container: Container = Depends(get_container(with_user=True)),
):
    await flow_access_context.enforce_flow_scope(
        request,
        container,
        flow_id=id,
        required_access=FlowApiAction.VIEW,
        allow_service_key_principals=True,
    )
    evidence_service = container.flow_run_evidence_service()
    user = container.user()
    actor_kwargs = audit_actor_kwargs(user)

    file = await evidence_service.get_run_artifact_file(
        run_id=run_id,
        flow_id=id,
        file_id=file_id,
    )

    signed_url = build_signed_download_response(
        base_url=str(request.base_url),
        file_id=file_id,
        tenant_id=file.tenant_id,
        signed_url_request=signed_url_req,
    )

    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        actor_id=actor_kwargs["actor_id"],
        actor_type=actor_kwargs["actor_type"],
        actor_api_key_id=actor_kwargs["actor_api_key_id"],
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

    return signed_url


__all__ = ["router"]
