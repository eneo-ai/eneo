from __future__ import annotations

from collections.abc import Mapping
from typing import NoReturn, Protocol
from uuid import UUID

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.flows.api.flow_api_common import audit_actor_kwargs
from eneo.flows.domain.flow import FlowRun
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.main.container.container import Container
from eneo.main.exceptions import AuditLoggingUnavailableException
from eneo.main.logging import get_logger

logger = get_logger(__name__)


class FlowTraceAuditActor(Protocol):
    tenant_id: UUID


async def log_flow_trace_audit_or_raise(
    *,
    container: Container,
    user: FlowTraceAuditActor,
    run: FlowRun,
    action: ActionType,
    description: str,
    extra: Mapping[str, object] | None = None,
) -> None:
    try:
        actor_kwargs = audit_actor_kwargs(user)
        audit_log = await container.audit_service().log(
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
        if audit_log is None:
            raise_flow_trace_audit_unavailable(
                user=user,
                run=run,
                action=action,
                cause=None,
            )
    except AuditLoggingUnavailableException:
        raise
    except Exception as exc:
        raise_flow_trace_audit_unavailable(
            user=user,
            run=run,
            action=action,
            cause=exc,
        )


def raise_flow_trace_audit_unavailable(
    *,
    user: FlowTraceAuditActor,
    run: FlowRun,
    action: ActionType,
    cause: BaseException | None,
) -> NoReturn:
    log_context = {
        "action": action.value,
        "run_id": str(run.id),
        "flow_id": str(run.flow_id),
        "tenant_id": str(user.tenant_id),
    }
    if cause is None:
        logger.error(
            "Required Flow trace audit was disabled; denying trace access",
            extra=log_context,
        )
    else:
        logger.exception(
            "Flow trace audit logging failed; denying trace access",
            extra=log_context,
        )
    error = AuditLoggingUnavailableException(
        "Evidence audit logging is unavailable.",
        code=FlowApiErrorCode.EVIDENCE_AUDIT_LOGGING_FAILED.value,
        context={"audit_required": True},
    )
    if cause is None:
        raise error
    raise error from cause
