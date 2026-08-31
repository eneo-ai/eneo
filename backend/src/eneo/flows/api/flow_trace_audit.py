from __future__ import annotations

from collections.abc import Mapping
from typing import NoReturn

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.flows.domain.flow import FlowRun
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.main.container.container import Container
from eneo.main.exceptions import AuditLoggingUnavailableException
from eneo.main.logging import get_logger
from eneo.users.user import UserInDB

logger = get_logger(__name__)


async def log_flow_trace_audit_or_raise(
    *,
    container: Container,
    user: UserInDB,
    run: FlowRun,
    action: ActionType,
    description: str,
    extra: Mapping[str, object] | None = None,
) -> None:
    try:
        audit_context = dict(extra or {})
        audit_context["flow_id"] = str(run.flow_id)
        audit_context["run_id"] = str(run.id)
        await container.audit_service().log(
            tenant_id=user.tenant_id,
            user=user,
            action=action,
            entity_type=EntityType.FLOW_RUN,
            entity_id=run.id,
            description=description,
            metadata=AuditMetadata.standard(
                actor=user,
                target=run,
                extra=audit_context,
            ),
            required=True,
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
    user: UserInDB,
    run: FlowRun,
    action: ActionType,
    cause: BaseException,
) -> NoReturn:
    log_context = {
        "action": action.value,
        "run_id": str(run.id),
        "flow_id": str(run.flow_id),
        "tenant_id": str(user.tenant_id),
    }
    logger.exception(
        "Flow trace audit logging failed; denying trace access",
        extra=log_context,
    )
    error = AuditLoggingUnavailableException(
        "Evidence audit logging is unavailable.",
        code=FlowApiErrorCode.EVIDENCE_AUDIT_LOGGING_FAILED.value,
        context={"audit_required": True},
    )
    raise error from cause
