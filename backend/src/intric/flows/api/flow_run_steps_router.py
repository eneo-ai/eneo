from __future__ import annotations

import time
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request, status

from intric.audit.application.audit_metadata import AuditMetadata
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.authentication.signed_urls import generate_signed_token
from intric.files.file_models import SignedURLRequest, SignedURLResponse
from intric.flows.api import flow_router_common as common
from intric.flows.api.flow_api_common import audit_actor_kwargs, error_response
from intric.flows.api.flow_assembler import FlowAssembler
from intric.flows.api.flow_graph import (
    build_graph_from_steps,
    enrich_nodes_with_run_results,
)
from intric.flows.api.flow_models import FlowRunStepPublic, GraphResponse
from intric.flows.flow_run_step_result_file import FlowRunStepResultFile
from intric.flows.infrastructure.flow_version_repo import FlowVersionRepository
from intric.flows.principal import FlowPrincipal
from intric.flows.published_definition import parse_published_definition
from intric.main.container.container import Container
from intric.main.exceptions import ErrorCodes, NotFoundException
from intric.server.dependencies.container import get_container

router = APIRouter()

_FLOW_RUNTIME_FORBIDDEN_DESCRIPTION = (
    "Forbidden. Machine-readable codes include `insufficient_scope` when the API key "
    "space scope does not match the flow, `insufficient_tenant_permission` or "
    "`insufficient_space_permission` for callers without the required access, "
    "`flow_run_access_denied` when a caller tries to inspect another user's run, "
    "and `flow_service_key_principal_not_supported` on flow surfaces that still require a user principal."
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


def _get_flow_version_repo(container: Container) -> FlowVersionRepository:
    return container.flow_version_repo()  # pyright: ignore[reportUnknownMemberType]


def _result_files_by_step_result_id(
    result_files: list[FlowRunStepResultFile],
) -> dict[UUID, list[FlowRunStepResultFile]]:
    grouped: dict[UUID, list[FlowRunStepResultFile]] = {}
    for result_file in result_files:
        grouped.setdefault(result_file.step_result_id, []).append(result_file)
    return grouped


@router.get(
    "/{id}/runs/{run_id}/steps/",
    response_model=list[FlowRunStepPublic],
    status_code=status.HTTP_200_OK,
    operation_id="list_flow_run_steps",
    summary="List flow run step outputs (flow-first)",
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
    await common.enforce_flow_scope_for_request(
        request,
        container,
        flow_id=id,
        required_access=common.FlowApiAction.VIEW,
        allow_service_key_principals=True,
    )
    step_results_with_files = (
        await container.flow_run_service().list_step_results_with_files(
            run_id=run_id,
            flow_id=id,
        )
    )
    result_files_by_step_result_id = _result_files_by_step_result_id(
        list(step_results_with_files.result_files)
    )
    assembler = FlowAssembler()
    items: list[FlowRunStepPublic] = []
    for result in step_results_with_files.step_results:
        diagnostics: list[dict[str, Any]] = []
        input_payload = result.input_payload_json
        if isinstance(input_payload, dict):
            raw_diagnostics = input_payload.get("diagnostics")
            if isinstance(raw_diagnostics, list):
                diagnostics = [
                    item
                    for item in cast(list[object], raw_diagnostics)
                    if isinstance(item, dict)
                ]
        result_id = result.id
        items.append(
            assembler.to_step_public(
                result,
                diagnostics=diagnostics,
                result_files=(
                    result_files_by_step_result_id.get(result_id, [])
                    if result_id is not None
                    else []
                ),
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
    await common.enforce_flow_scope_for_request(
        request,
        container,
        flow_id=id,
        required_access=common.FlowApiAction.VIEW,
        allow_service_key_principals=True,
    )
    flow_service = container.flow_service()
    flow_run_service = container.flow_run_service()
    flow_version_repo = _get_flow_version_repo(container)

    if run_id is not None:
        run = await flow_run_service.get_run(
            run_id=run_id,
            flow_id=id,
            access_kind="content",
        )
        version = await flow_version_repo.get(
            flow_id=run.flow_id,
            version=run.flow_version,
            tenant_id=run.tenant_id,
        )
        definition_steps = parse_published_definition(version.definition_json).steps
        nodes, edges = build_graph_from_steps(definition_steps)
        step_results = await flow_run_service.list_step_results(
            run_id=run.id,
            flow_id=id,
        )
        nodes = enrich_nodes_with_run_results(
            nodes,
            [item.model_dump(mode="json") for item in step_results],
        )
        return GraphResponse.model_validate({"nodes": nodes, "edges": edges})

    flow = await flow_service.get_flow(id)
    if (
        FlowPrincipal.from_user(container.user()).is_service_key
        and flow.published_version is None
    ):
        raise NotFoundException("Flow not found.")
    live_steps = [step.model_dump(mode="json") for step in flow.steps]
    nodes, edges = build_graph_from_steps(live_steps)
    return GraphResponse.model_validate({"nodes": nodes, "edges": edges})


@router.post(
    "/{id}/runs/{run_id}/artifacts/{file_id}/signed-url/",
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
            code="flow_run_artifact_not_found",
        ),
        410: error_response(
            description="Artifact content was purged by retention policy.",
            message="Artifact content has been purged by retention policy.",
            intric_error_code=ErrorCodes.RESOURCE_GONE,
            code="flow_run_artifact_content_unavailable",
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
    await common.enforce_flow_scope_for_request(
        request,
        container,
        flow_id=id,
        required_access=common.FlowApiAction.VIEW,
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

    expires_at = int(time.time()) + signed_url_req.expires_in
    token = generate_signed_token(
        file_id=file_id,
        expires_at=expires_at,
        content_disposition=signed_url_req.content_disposition,
        tenant_id=file.tenant_id,
    )
    base_url = str(request.base_url).rstrip("/")
    url = f"{base_url}/api/v1/files/{file_id}/download/?token={token}"

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

    return SignedURLResponse(url=url, expires_at=expires_at)
