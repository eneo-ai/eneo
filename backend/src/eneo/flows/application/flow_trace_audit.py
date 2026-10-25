from __future__ import annotations

from collections.abc import Mapping
from typing import NoReturn
from uuid import UUID

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.flows.domain.flow import Flow, FlowRun
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
    _raise_audit_unavailable(log_context, cause=cause)


async def log_flow_evidence_read_audit_or_raise(
    *,
    container: Container,
    user: UserInDB,
    flow: Flow,
    action: ActionType,
    description: str,
    extra: Mapping[str, object] | None = None,
) -> None:
    """One audit entry on the flow for a read of evidence across several of
    its runs, which the entry names in ``extra``. Fails closed like the trace
    audit of one run: an entry that cannot be written refuses the read."""
    flow_id = flow.require_persisted_id()
    try:
        audit_context = dict(extra or {})
        audit_context["flow_id"] = str(flow_id)
        await container.audit_service().log(
            tenant_id=user.tenant_id,
            user=user,
            action=action,
            entity_type=EntityType.FLOW,
            entity_id=flow_id,
            description=description,
            metadata=AuditMetadata.standard(
                actor=user,
                target=flow,
                extra=audit_context,
            ),
            required=True,
        )
    except AuditLoggingUnavailableException:
        raise
    except Exception as exc:
        raise_flow_evidence_read_audit_unavailable(
            user=user, flow_id=flow_id, action=action, cause=exc
        )


def raise_flow_evidence_read_audit_unavailable(
    *,
    user: UserInDB,
    flow_id: UUID,
    action: ActionType,
    cause: BaseException,
) -> NoReturn:
    _raise_audit_unavailable(
        {
            "action": action.value,
            "flow_id": str(flow_id),
            "tenant_id": str(user.tenant_id),
        },
        cause=cause,
    )


def _raise_audit_unavailable(
    log_context: Mapping[str, object], *, cause: BaseException
) -> NoReturn:
    logger.exception(
        "Flow trace audit logging failed; denying trace access",
        extra=dict(log_context),
    )
    error = AuditLoggingUnavailableException(
        "Evidence audit logging is unavailable.",
        code=FlowApiErrorCode.EVIDENCE_AUDIT_LOGGING_FAILED.value,
        context={"audit_required": True},
    )
    raise error from cause
