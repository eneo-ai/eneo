from __future__ import annotations

import json
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request, Response, status
from fastapi.responses import JSONResponse

from intric.audit.domain.action_types import ActionType
from intric.flows.api import flow_router_common as common
from intric.flows.api.flow_api_common import error_response
from intric.flows.api.flow_models import FlowRunEvidenceExportResponse, FlowRunEvidenceResponse
from intric.flows.api.flow_trace_audit import (
    build_flow_trace_error_payload,
    log_flow_trace_audit_or_deny,
)
from intric.flows.flow_permissions import ensure_can_view_flow_trace
from intric.main.container.container import Container
from intric.main.exceptions import ErrorCodes
from intric.server.dependencies.container import get_container

router = APIRouter()


@router.get(
    "/{id}/runs/{run_id}/evidence/",
    response_model=FlowRunEvidenceResponse,
    status_code=status.HTTP_200_OK,
    operation_id="get_flow_run_evidence_alias",
    summary="Get flow run evidence trace",
    description="""
Get the redacted rich evidence trace for one flow run.

Use `/steps/` for baseline consumer step inspection and `/evidence/` for rich traceability,
attempt history, and debug-export provenance.
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
        503: error_response(
            description="Evidence audit logging is unavailable for this request.",
            message="Evidence audit logging is unavailable.",
            intric_error_code=ErrorCodes.INTERNAL_SERVER_ERROR,
            code="flow_evidence_audit_logging_failed",
            context={"audit_required": True},
        ),
    },
)
async def get_flow_run_evidence_alias(
    id: Annotated[UUID, Path(description="Identifier of the flow that owns the run evidence export.")],
    run_id: Annotated[UUID, Path(description="Identifier of the run whose evidence export should be returned.")],
    request: Request,
    container: Container = Depends(get_container(with_user=True)),
):
    await common.enforce_flow_scope_for_request(
        request,
        container,
        flow_id=id,
        required_access="view",
    )
    user = container.user()
    ensure_can_view_flow_trace(user)
    run_service = container.flow_run_service()
    run = await run_service.get_run(run_id=run_id, flow_id=id)
    evidence = await run_service.get_evidence(run_id=run_id)
    audit_failure = await log_flow_trace_audit_or_deny(
        container=container,
        user=user,
        run=run,
        action=ActionType.FLOW_EVIDENCE_VIEWED,
        description=f"Viewed evidence for flow run {run.id}",
    )
    if audit_failure is not None:
        return audit_failure
    return FlowRunEvidenceResponse(**evidence)


@router.get(
    "/{id}/runs/{run_id}/evidence/export",
    response_model=FlowRunEvidenceExportResponse,
    status_code=status.HTTP_200_OK,
    operation_id="export_flow_run_evidence_alias",
    summary="Export flow run evidence bundle",
    description="""
Export the redacted rich evidence bundle for one flow run as a JSON attachment.
    """,
    responses={
        400: error_response(
            description="Requested evidence export format is not supported.",
            message="Evidence export format is not supported.",
            intric_error_code=ErrorCodes.BAD_REQUEST,
            code="flow_evidence_export_format_not_supported",
            context={"supported_formats": ["json"]},
        ),
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
        503: error_response(
            description="Evidence audit logging is unavailable for this request.",
            message="Evidence audit logging is unavailable.",
            intric_error_code=ErrorCodes.INTERNAL_SERVER_ERROR,
            code="flow_evidence_audit_logging_failed",
            context={"audit_required": True},
        ),
    },
)
async def export_flow_run_evidence_alias(
    id: Annotated[UUID, Path(description="Identifier of the flow that owns the run evidence export.")],
    run_id: Annotated[UUID, Path(description="Identifier of the run whose evidence export should be downloaded.")],
    request: Request,
    format: Annotated[Literal["json"], Query(description="Export format.")] = "json",
    container: Container = Depends(get_container(with_user=True)),
):
    await common.enforce_flow_scope_for_request(
        request,
        container,
        flow_id=id,
        required_access="view",
    )
    user = container.user()
    ensure_can_view_flow_trace(user)
    run_service = container.flow_run_service()
    run = await run_service.get_run(run_id=run_id, flow_id=id)
    if format != "json":
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=build_flow_trace_error_payload(
                message="Evidence export format is not supported.",
                intric_error_code=ErrorCodes.BAD_REQUEST,
                code="flow_evidence_export_format_not_supported",
                context={"supported_formats": ["json"]},
            ),
        )
    export_payload = await run_service.export_evidence_json(run_id=run_id)
    audit_failure = await log_flow_trace_audit_or_deny(
        container=container,
        user=user,
        run=run,
        action=ActionType.FLOW_EVIDENCE_EXPORTED_JSON,
        description=f"Exported evidence JSON for flow run {run.id}",
    )
    if audit_failure is not None:
        return audit_failure
    filename = f"flow-run-evidence-{run_id}.json"
    return Response(
        content=json.dumps(export_payload, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
