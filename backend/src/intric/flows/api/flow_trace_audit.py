from __future__ import annotations

from typing import Any

from fastapi import status
from fastapi.responses import JSONResponse

from intric.audit.application.audit_metadata import AuditMetadata
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.flows.api.flow_api_common import audit_actor_kwargs
from intric.flows.domain.flow import FlowRun
from intric.main.container.container import Container
from intric.main.exceptions import ErrorCodes
from intric.main.logging import get_logger

logger = get_logger(__name__)


def build_flow_trace_error_payload(
    *,
    message: str,
    intric_error_code: ErrorCodes,
    code: str,
    context: dict[str, object] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "message": message,
        "intric_error_code": int(intric_error_code),
        "code": code,
    }
    if context is not None:
        payload["context"] = context
    return payload


async def log_flow_trace_audit_or_deny(
    *,
    container: Container,
    user: Any,
    run: FlowRun,
    action: ActionType,
    description: str,
    extra: dict[str, Any] | None = None,
) -> JSONResponse | None:
    try:
        actor_kwargs = audit_actor_kwargs(user)
        await container.audit_service().log_async(
            tenant_id=user.tenant_id,
            actor_id=actor_kwargs["actor_id"],
            actor_type=actor_kwargs["actor_type"],
            actor_api_key_id=actor_kwargs["actor_api_key_id"],
            action=action,
            entity_type=EntityType.FLOW_RUN,
            entity_id=run.id,
            description=description,
            metadata=AuditMetadata.standard(actor=user, target=run, extra=extra or {}),
        )
    except Exception:
        logger.exception(
            "Flow trace audit logging failed; denying trace access",
            extra={
                "action": action.value,
                "run_id": str(run.id),
                "flow_id": str(run.flow_id),
                "tenant_id": str(user.tenant_id),
            },
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=build_flow_trace_error_payload(
                message="Evidence audit logging is unavailable.",
                intric_error_code=ErrorCodes.INTERNAL_SERVER_ERROR,
                code="flow_evidence_audit_logging_failed",
                context={"audit_required": True},
            ),
        )
    return None
