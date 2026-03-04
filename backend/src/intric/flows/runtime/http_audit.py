from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit

from intric.audit.application.audit_metadata import AuditMetadata
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.audit.domain.outcome import Outcome


class RuntimeAuditRun(Protocol):
    @property
    def id(self) -> Any: ...

    @property
    def flow_id(self) -> Any: ...

    @property
    def tenant_id(self) -> Any: ...


class RuntimeAuditStep(Protocol):
    @property
    def step_order(self) -> int: ...

    @property
    def step_id(self) -> Any: ...

    @property
    def user_description(self) -> str | None: ...


@dataclass(frozen=True)
class HttpAuditDeps:
    audit_service: Any | None
    user: Any
    logger: Any


async def audit_http_outbound(
    *,
    run: RuntimeAuditRun,
    step: RuntimeAuditStep,
    url: str,
    method: str,
    call_type: str,
    outcome: Outcome,
    error_message: str | None = None,
    status_code: int | None = None,
    duration_ms: float | None = None,
    deps: HttpAuditDeps,
) -> None:
    if deps.audit_service is None:
        return
    try:
        parts = urlsplit(url)
        safe_url_host = f"{parts.scheme}://{parts.hostname}" if parts.hostname else ""
        safe_url_path = parts.path or "/"
        extra: dict[str, Any] = {
            "call_type": call_type,
            "http_method": method,
            "url_host": safe_url_host,
            "url_path": safe_url_path,
            "flow_id": str(run.flow_id),
            "step_order": step.step_order,
            "step_id": str(step.step_id),
        }
        if step.user_description:
            extra["step_description"] = step.user_description
        if status_code is not None:
            extra["status_code"] = status_code
        if duration_ms is not None:
            extra["duration_ms"] = round(duration_ms, 2)
        await deps.audit_service.log_async(
            tenant_id=run.tenant_id,
            actor_id=deps.user.id,
            action=ActionType.FLOW_HTTP_OUTBOUND_CALL,
            entity_type=EntityType.FLOW_RUN,
            entity_id=run.id,
            description=f"Flow HTTP {call_type} {method} to {safe_url_host}{safe_url_path}",
            metadata=AuditMetadata.standard(actor=deps.user, target=run, extra=extra),
            outcome=outcome,
            error_message=error_message,
        )
    except Exception:
        deps.logger.warning(
            "flow_executor.audit_http_outbound_failed run_id=%s step_order=%d",
            run.id,
            step.step_order,
            exc_info=True,
        )
