from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request, Response, status
from fastapi.responses import JSONResponse

from intric.audit.domain.action_types import ActionType
from intric.flows.api import flow_router_common as common
from intric.flows.api.flow_api_common import error_response
from intric.flows.api.flow_models import (
    FlowRunEvidenceExportResponse,
    FlowRunEvidenceResponse,
)
from intric.flows.api.flow_trace_audit import (
    build_flow_trace_error_payload,
    log_flow_trace_audit_or_deny,
)
from intric.flows.application.flow_run_service import FlowRunService
from intric.main.container.container import Container
from intric.main.exceptions import ErrorCodes
from intric.server.dependencies.container import get_container

router = APIRouter()

_FLOW_TRACE_FORBIDDEN_DESCRIPTION = (
    "Forbidden. Machine-readable codes include `insufficient_scope` when the API key "
    "space scope does not match the flow, `insufficient_tenant_permission` when an "
    "ordinary principal lacks trace permission, `flow_run_access_denied` when a caller "
    "tries to inspect another principal's run, `flow_run_evidence_forbidden` when a "
    "service key lacks explicit own-run evidence capability, and "
    "`flow_run_evidence_raw_export_forbidden` when raw export is blocked by "
    "classification-aware policy."
)

_FLOW_EVIDENCE_DESCRIPTION = """
Get the redacted rich evidence trace for one flow run.

Use `/steps/` for baseline consumer step inspection and `/evidence/` for rich traceability,
attempt history, and debug-export provenance.

Evidence visibility is policy-based:
- trusted operators (tenant admin, space owner, space admin) may inspect in-scope evidence
- user-principal run owners may inspect own-run evidence when `FLOWS_TRACE` permits it
- service keys may inspect only their own-run evidence when explicit machine evidence capability
  allows it
    """

_FLOW_EVIDENCE_EXPORT_DESCRIPTION = """
Export the redacted rich evidence bundle for one flow run as a JSON attachment.

Evidence export is policy-based and tiered:
- redacted/default export is the standard support/compliance export
- raw/full export is a stricter surface, especially for classification 3 spaces
- service keys may export only their own-run evidence and only when explicit machine evidence
  capability allows it
    """


def _get_flow_run_service(container: Container) -> FlowRunService:
    return container.flow_run_service()


@router.get(
    "/{id}/runs/{run_id}/evidence/",
    response_model=FlowRunEvidenceResponse,
    status_code=status.HTTP_200_OK,
    operation_id="get_flow_run_evidence_alias",
    summary="Get flow run evidence trace",
    description=_FLOW_EVIDENCE_DESCRIPTION,
    responses={
        403: error_response(
            description=_FLOW_TRACE_FORBIDDEN_DESCRIPTION,
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
    id: Annotated[
        UUID,
        Path(description="Identifier of the flow that owns the run evidence export."),
    ],
    run_id: Annotated[
        UUID,
        Path(
            description="Identifier of the run whose evidence export should be returned."
        ),
    ],
    request: Request,
    container: Container = Depends(get_container(with_user=True)),
):
    await common.enforce_flow_scope_for_request(
        request,
        container,
        flow_id=id,
        required_access="view",
        allow_service_key_principals=True,
    )
    user = container.user()
    run_service = _get_flow_run_service(container)
    run = await run_service.get_run(
        run_id=run_id,
        flow_id=id,
        access_kind="evidence_view",
    )
    evidence = await run_service.get_evidence(run_id=run_id, run=run)
    audit_failure = await log_flow_trace_audit_or_deny(
        container=container,
        user=user,
        run=run,
        action=ActionType.FLOW_EVIDENCE_VIEWED,
        description=f"Viewed evidence for flow run {run.id}",
        extra={"evidence_detail": "view"},
    )
    if audit_failure is not None:
        return audit_failure
    return FlowRunEvidenceResponse.model_validate(evidence)


@router.get(
    "/{id}/runs/{run_id}/evidence/export",
    status_code=status.HTTP_200_OK,
    operation_id="export_flow_run_evidence_alias",
    summary="Export flow run evidence bundle",
    description=_FLOW_EVIDENCE_EXPORT_DESCRIPTION,
    responses={
        200: {
            "model": FlowRunEvidenceExportResponse,
            "description": "Redacted JSON evidence bundle returned as a downloadable attachment.",
            "headers": {
                "Content-Disposition": {
                    "description": "Attachment filename for the JSON evidence bundle.",
                    "schema": {
                        "type": "string",
                        "example": 'attachment; filename="flow-run-evidence-00000000-0000-0000-0000-000000000000.json"',
                    },
                }
            },
        },
        400: error_response(
            description="Requested evidence export format is not supported.",
            message="Evidence export format is not supported.",
            intric_error_code=ErrorCodes.BAD_REQUEST,
            code="flow_evidence_export_format_not_supported",
            context={"supported_formats": ["json"]},
        ),
        403: error_response(
            description=_FLOW_TRACE_FORBIDDEN_DESCRIPTION,
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
    id: Annotated[
        UUID,
        Path(description="Identifier of the flow that owns the run evidence export."),
    ],
    run_id: Annotated[
        UUID,
        Path(
            description="Identifier of the run whose evidence export should be downloaded."
        ),
    ],
    request: Request,
    format: Annotated[Literal["json"], Query(description="Export format.")] = "json",
    detail: Annotated[
        Literal["redacted", "raw"],
        Query(
            description="Export detail. `redacted` is the default support/compliance export; `raw` requests the full unredacted bundle."
        ),
    ] = "redacted",
    reason: Annotated[
        str,
        Query(
            min_length=3,
            max_length=500,
            description="Reason or purpose for exporting evidence.",
        ),
    ] = "support_debug",
    container: Container = Depends(get_container(with_user=True)),
):
    await common.enforce_flow_scope_for_request(
        request,
        container,
        flow_id=id,
        required_access="view",
        allow_service_key_principals=True,
    )
    user = container.user()
    run_service = _get_flow_run_service(container)
    access_kind = (
        "evidence_export_raw" if detail == "raw" else "evidence_export_redacted"
    )
    run = await run_service.get_run(
        run_id=run_id,
        flow_id=id,
        access_kind=access_kind,
    )
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
    export_payload = await run_service.export_evidence_json(
        run_id=run_id,
        detail=detail,
        run=run,
    )
    audit_failure = await log_flow_trace_audit_or_deny(
        container=container,
        user=user,
        run=run,
        action=ActionType.FLOW_EVIDENCE_EXPORTED_JSON,
        description=f"Exported evidence JSON for flow run {run.id}",
        extra={"evidence_detail": detail, "export_reason": reason},
    )
    if audit_failure is not None:
        return audit_failure
    filename = f"flow-run-evidence-{run_id}.json"
    validated_export = FlowRunEvidenceExportResponse.model_validate(export_payload)
    return Response(
        content=validated_export.model_dump_json(indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
