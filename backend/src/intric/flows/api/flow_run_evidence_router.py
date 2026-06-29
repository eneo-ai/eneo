from __future__ import annotations

from typing import Annotated, Final, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request, Response, status

from intric.audit.domain.action_types import ActionType
from intric.authentication.auth_models import (
    FLOW_EVIDENCE_SERVICE_KEY_PERMISSION_RECIPE,
)
from intric.flows.api import flow_access_context
from intric.flows.api.flow_api_common import error_response
from intric.flows.api.flow_models import (
    FlowRunEvidenceExportResponse,
    FlowRunEvidenceResponse,
)
from intric.flows.api.flow_runtime_paths import (
    FLOW_RUN_EVIDENCE_EXPORT_PATH,
    FLOW_RUN_EVIDENCE_PATH,
)
from intric.flows.api.flow_service_principal_actor_read_model import (
    FlowServicePrincipalActorPresenter,
)
from intric.flows.api.flow_trace_audit import log_flow_trace_audit_or_raise
from intric.flows.flow_access_policy import FlowApiAction
from intric.flows.flow_api_error_code import FlowApiErrorCode
from intric.main.container.container import Container
from intric.main.exceptions import BadRequestException, ErrorCodes
from intric.server.dependencies.container import get_container

router = APIRouter()

_FLOW_TRACE_FORBIDDEN_DESCRIPTION = (
    f"Forbidden. {FLOW_EVIDENCE_SERVICE_KEY_PERMISSION_RECIPE} Scope, resource "
    "permission, tenant permission, run ownership, and evidence policy are "
    "evaluated before returning Flow evidence. Machine-readable codes include "
    "`insufficient_scope`, `insufficient_resource_permission`, and "
    "`flow_run_evidence_forbidden`."
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

_DEFAULT_EVIDENCE_EXPORT_REASON: Final[str] = "support_debug"
_RAW_REASON_REQUIRED_MESSAGE: Final[str] = (
    "Raw evidence export requires an explicit non-default reason."
)


@router.get(
    FLOW_RUN_EVIDENCE_PATH,
    response_model=FlowRunEvidenceResponse,
    status_code=status.HTTP_200_OK,
    operation_id="get_flow_run_evidence",
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
            code=FlowApiErrorCode.EVIDENCE_AUDIT_LOGGING_FAILED,
            context={"audit_required": True},
        ),
    },
)
async def get_flow_run_evidence(
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
    await flow_access_context.enforce_flow_scope(
        request,
        container,
        flow_id=id,
        required_access=FlowApiAction.VIEW,
        allow_service_key_principals=True,
    )
    user = container.user()
    evidence_service = container.flow_run_evidence_service()
    run = await evidence_service.get_run(
        run_id=run_id,
        flow_id=id,
        access_kind="evidence_view",
    )
    evidence = await evidence_service.get_redacted_evidence_bundle(
        run_id=run_id,
        run=run,
    )
    await log_flow_trace_audit_or_raise(
        container=container,
        user=user,
        run=run,
        action=ActionType.FLOW_EVIDENCE_VIEWED,
        description=f"Viewed evidence for flow run {run.id}",
        extra={"evidence_detail": "view"},
    )
    presenter = FlowServicePrincipalActorPresenter(
        api_key_repo=container.api_key_v2_repo(),
        tenant_id=user.tenant_id,
    )
    payload = await presenter.present_evidence(evidence.to_dict())
    return FlowRunEvidenceResponse.model_validate(payload)


@router.get(
    FLOW_RUN_EVIDENCE_EXPORT_PATH,
    response_model=None,
    status_code=status.HTTP_200_OK,
    operation_id="export_flow_run_evidence",
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
            description="Raw evidence export requires an explicit non-default reason.",
            message=_RAW_REASON_REQUIRED_MESSAGE,
            intric_error_code=ErrorCodes.BAD_REQUEST,
            code=FlowApiErrorCode.EVIDENCE_EXPORT_REASON_REQUIRED,
            context={
                "detail": "raw",
                "default_reason": _DEFAULT_EVIDENCE_EXPORT_REASON,
            },
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
            code=FlowApiErrorCode.EVIDENCE_AUDIT_LOGGING_FAILED,
            context={"audit_required": True},
        ),
    },
)
async def export_flow_run_evidence(
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
            description=(
                "Reason or purpose for exporting evidence. Raw exports require an "
                "explicit non-default reason."
            ),
        ),
    ] = _DEFAULT_EVIDENCE_EXPORT_REASON,
    container: Container = Depends(get_container(with_user=True)),
):
    await flow_access_context.enforce_flow_scope(
        request,
        container,
        flow_id=id,
        required_access=FlowApiAction.VIEW,
        allow_service_key_principals=True,
    )
    access_kind = (
        "evidence_export_raw" if detail == "raw" else "evidence_export_redacted"
    )
    export_reason = reason.strip()
    if detail == "raw" and (
        not export_reason or export_reason == _DEFAULT_EVIDENCE_EXPORT_REASON
    ):
        raise BadRequestException(
            _RAW_REASON_REQUIRED_MESSAGE,
            code=FlowApiErrorCode.EVIDENCE_EXPORT_REASON_REQUIRED.value,
            context={
                "detail": "raw",
                "default_reason": _DEFAULT_EVIDENCE_EXPORT_REASON,
            },
        )
    user = container.user()
    evidence_service = container.flow_run_evidence_service()
    run = await evidence_service.get_run(
        run_id=run_id,
        flow_id=id,
        access_kind=access_kind,
    )
    export_payload = await evidence_service.export_evidence_json(
        run_id=run_id,
        detail=detail,
        run=run,
        export_reason=export_reason,
    )
    await log_flow_trace_audit_or_raise(
        container=container,
        user=user,
        run=run,
        action=ActionType.FLOW_EVIDENCE_EXPORTED_JSON,
        description=f"Exported evidence JSON for flow run {run.id}",
        extra={"evidence_detail": detail, "export_reason": export_reason},
    )
    filename = f"flow-run-evidence-{run_id}.json"
    validated_export = FlowRunEvidenceExportResponse.model_validate(export_payload)
    return Response(
        content=validated_export.model_dump_json(indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


__all__ = ["router"]
