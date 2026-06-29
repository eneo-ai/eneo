from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol
from uuid import UUID

from intric.audit.application.audit_metadata import AuditMetadata
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.flows.api.flow_api_common import audit_actor_kwargs
from intric.flows.domain.flow import FlowRun
from intric.flows.flow_api_error_code import FlowApiErrorCode
from intric.main.container.container import Container
from intric.main.exceptions import AuditLoggingUnavailableException
from intric.main.logging import get_logger

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
    except Exception as exc:
        logger.exception(
            "Flow trace audit logging failed; denying trace access",
            extra={
                "action": action.value,
                "run_id": str(run.id),
                "flow_id": str(run.flow_id),
                "tenant_id": str(user.tenant_id),
            },
        )
        raise AuditLoggingUnavailableException(
            "Evidence audit logging is unavailable.",
            code=FlowApiErrorCode.EVIDENCE_AUDIT_LOGGING_FAILED.value,
            context={"audit_required": True},
        ) from exc
