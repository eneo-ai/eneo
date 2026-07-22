from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Literal, TypeAlias
from uuid import UUID, uuid4

from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.actor_types import ActorType
from eneo.audit.domain.audit_log import AuditLog
from eneo.audit.domain.constants import MAX_ERROR_MESSAGE_LENGTH
from eneo.audit.domain.entity_types import EntityType
from eneo.audit.domain.outcome import Outcome
from eneo.audit.domain.repositories.audit_log_repository import AuditLogRepository
from eneo.flows.application.flow_run_audit_outbox_policy import (
    FLOW_AUDIT_OUTBOX_DELIVERY_BATCH_SIZE,
    flow_audit_outbox_retry_delay_seconds,
)
from eneo.flows.flow_run_redaction import redact_string
from eneo.flows.infrastructure.flow_run_audit_outbox_repo import (
    FlowRunAuditOutboxDeadLetterPage,
    FlowRunAuditOutboxDeliveryRow,
    FlowRunAuditOutboxRedriveGenerationConflict,
    FlowRunAuditOutboxRedriveStateConflict,
    FlowRunAuditOutboxRepository,
)

FlowAuditOutboxMetadataValue: TypeAlias = str | int | None


@dataclass(frozen=True, slots=True)
class FlowRunAuditOutboxDeliveryResult:
    attempted_count: int = 0
    delivered_count: int = 0
    retry_scheduled_count: int = 0
    dead_lettered_count: int = 0

    def to_task_payload(self) -> dict[str, int | str]:
        return {
            "status": "ok",
            "attempted": self.attempted_count,
            "delivered": self.delivered_count,
            "retry_scheduled": self.retry_scheduled_count,
            "dead_lettered": self.dead_lettered_count,
        }


@dataclass(frozen=True, slots=True)
class FlowRunAuditOutboxRedriveResult:
    outbox_id: UUID
    flow_run_id: UUID
    delivery_status: Literal["pending"]
    delivery_attempts: Literal[0]
    next_delivery_at: datetime
    operator_audit_id: UUID


class FlowRunAuditOutboxNotFoundError(Exception):
    pass


class FlowRunAuditOutboxStateConflictError(Exception):
    def __init__(self, *, delivery_status: str):
        super().__init__(
            "Flow audit outbox delivery is not dead-lettered "
            f"(current status: {delivery_status})."
        )
        self.delivery_status = delivery_status


class FlowRunAuditOutboxGenerationConflictError(Exception):
    def __init__(self, *, current_dead_lettered_at: datetime):
        super().__init__(
            "Flow audit outbox dead-letter generation changed; list the row again "
            "before redriving."
        )
        self.current_dead_lettered_at = current_dead_lettered_at


class FlowRunAuditOutboxDeliveryService:
    """Deliver Flow lifecycle audit rows outside tenant audit feature flags.

    PRD-003 treats lifecycle audit as part of the committed runtime state, so
    delivery writes directly through the audit repository instead of the
    configurable `AuditService` path that can intentionally skip product audit.
    """

    def __init__(
        self,
        *,
        audit_outbox_repo: FlowRunAuditOutboxRepository,
        audit_log_repo: AuditLogRepository,
    ):
        self.audit_outbox_repo = audit_outbox_repo
        self.audit_log_repo = audit_log_repo

    async def deliver_due(
        self,
        *,
        now: datetime,
        limit: int = FLOW_AUDIT_OUTBOX_DELIVERY_BATCH_SIZE,
    ) -> FlowRunAuditOutboxDeliveryResult:
        rows = await self.audit_outbox_repo.list_due_delivery_rows(
            now=now,
            limit=limit,
        )
        delivered = 0
        retry_scheduled = 0
        dead_lettered = 0
        for row in rows:
            try:
                async with self.audit_outbox_repo.session.begin_nested():
                    await self._deliver_row(row=row, now=now)
            except ValueError as exc:
                async with self.audit_outbox_repo.session.begin_nested():
                    await self._record_failure(
                        row=row,
                        now=now,
                        error=exc,
                        force_dead_letter=True,
                    )
                dead_lettered += 1
            except Exception as exc:
                async with self.audit_outbox_repo.session.begin_nested():
                    did_dead_letter = await self._record_failure(
                        row=row,
                        now=now,
                        error=exc,
                        force_dead_letter=False,
                    )
                if did_dead_letter:
                    dead_lettered += 1
                else:
                    retry_scheduled += 1
            else:
                delivered += 1
        return FlowRunAuditOutboxDeliveryResult(
            attempted_count=len(rows),
            delivered_count=delivered,
            retry_scheduled_count=retry_scheduled,
            dead_lettered_count=dead_lettered,
        )

    async def list_dead_letters(
        self,
        *,
        limit: int,
        offset: int,
    ) -> FlowRunAuditOutboxDeadLetterPage:
        page = await self.audit_outbox_repo.list_dead_letters(
            limit=limit,
            offset=offset,
        )
        return FlowRunAuditOutboxDeadLetterPage(
            items=tuple(
                replace(
                    row,
                    delivery_last_error=sanitize_persisted_delivery_error(
                        row.delivery_last_error
                    ),
                )
                for row in page.items
            ),
            has_more=page.has_more,
        )

    async def redrive_dead_lettered(
        self,
        *,
        outbox_id: UUID,
        expected_dead_lettered_at: datetime,
        reason: str,
        now: datetime,
    ) -> FlowRunAuditOutboxRedriveResult:
        session = self.audit_outbox_repo.session
        transaction = (
            session.begin_nested() if session.in_transaction() else session.begin()
        )
        async with transaction:
            return await self._redrive_dead_lettered_in_transaction(
                outbox_id=outbox_id,
                expected_dead_lettered_at=expected_dead_lettered_at,
                reason=reason,
                now=now,
            )

    async def _redrive_dead_lettered_in_transaction(
        self,
        *,
        outbox_id: UUID,
        expected_dead_lettered_at: datetime,
        reason: str,
        now: datetime,
    ) -> FlowRunAuditOutboxRedriveResult:
        transition = await self.audit_outbox_repo.redrive_dead_lettered(
            outbox_id=outbox_id,
            expected_dead_lettered_at=expected_dead_lettered_at,
            now=now,
        )
        if transition is None:
            raise FlowRunAuditOutboxNotFoundError(str(outbox_id))
        if isinstance(transition, FlowRunAuditOutboxRedriveGenerationConflict):
            raise FlowRunAuditOutboxGenerationConflictError(
                current_dead_lettered_at=transition.current_dead_lettered_at
            )
        if isinstance(transition, FlowRunAuditOutboxRedriveStateConflict):
            raise FlowRunAuditOutboxStateConflictError(
                delivery_status=transition.delivery_status
            )

        operator_audit_id = uuid4()
        await self.audit_log_repo.create(
            AuditLog(
                id=operator_audit_id,
                tenant_id=transition.tenant_id,
                actor_id=None,
                actor_type=ActorType.SYSTEM,
                actor_api_key_id=None,
                action=ActionType.FLOW_RUN_AUDIT_DELIVERY_REDRIVEN,
                entity_type=EntityType.FLOW_RUN,
                entity_id=transition.flow_run_id,
                timestamp=now,
                description="Flow run audit delivery redriven by a system operator.",
                metadata={
                    "flow_id": str(transition.flow_id),
                    "flow_run_id": str(transition.flow_run_id),
                    "outbox_id": str(transition.outbox_id),
                    "reason": redact_string(reason, key=None),
                    "prior_delivery_attempts": transition.previous_delivery_attempts,
                    "prior_dead_lettered_at": (
                        transition.previous_dead_lettered_at.isoformat()
                    ),
                    "prior_delivery_last_error": sanitize_persisted_delivery_error(
                        transition.previous_delivery_last_error
                    ),
                },
                outcome=Outcome.SUCCESS,
            )
        )
        return FlowRunAuditOutboxRedriveResult(
            outbox_id=transition.outbox_id,
            flow_run_id=transition.flow_run_id,
            delivery_status="pending",
            delivery_attempts=0,
            next_delivery_at=transition.next_delivery_at,
            operator_audit_id=operator_audit_id,
        )

    async def _deliver_row(
        self,
        *,
        row: FlowRunAuditOutboxDeliveryRow,
        now: datetime,
    ) -> None:
        audit_log = build_audit_log_from_outbox(row)
        await self.audit_log_repo.create_if_absent(audit_log)
        await self.audit_outbox_repo.mark_delivery_succeeded(
            outbox_id=row.id,
            delivered_at=now,
            attempt_no=row.delivery_attempts + 1,
        )

    async def _record_failure(
        self,
        *,
        row: FlowRunAuditOutboxDeliveryRow,
        now: datetime,
        error: Exception,
        force_dead_letter: bool,
    ) -> bool:
        attempt_no = row.delivery_attempts + 1
        retry_delay = (
            None
            if force_dead_letter
            else flow_audit_outbox_retry_delay_seconds(failed_attempt_no=attempt_no)
        )
        dead_lettered_at = now if retry_delay is None else None
        next_delivery_at = (
            None if retry_delay is None else now + timedelta(seconds=retry_delay)
        )
        await self.audit_outbox_repo.record_delivery_failure(
            outbox_id=row.id,
            attempt_no=attempt_no,
            error_message=sanitize_delivery_error(error),
            next_delivery_at=next_delivery_at,
            dead_lettered_at=dead_lettered_at,
        )
        return dead_lettered_at is not None


def build_audit_log_from_outbox(row: FlowRunAuditOutboxDeliveryRow) -> AuditLog:
    action = ActionType(row.action)
    outcome = (
        Outcome.FAILURE if action == ActionType.FLOW_RUN_FAILED else Outcome.SUCCESS
    )
    return AuditLog(
        id=row.id,
        tenant_id=row.tenant_id,
        actor_id=row.actor_id,
        actor_type=ActorType(row.actor_type),
        actor_api_key_id=row.actor_api_key_id,
        action=action,
        entity_type=EntityType(row.entity_type),
        entity_id=row.entity_id,
        timestamp=_normalize_datetime(row.created_at),
        description=_audit_description(action=action, source=row.source),
        metadata=_audit_metadata(row),
        outcome=outcome,
        error_message=(
            _failure_error_message(row) if outcome == Outcome.FAILURE else None
        ),
    )


def sanitize_delivery_error(error: Exception) -> str:
    message = " ".join(str(error).split())
    if not message:
        message = error.__class__.__name__
    return (
        sanitize_persisted_delivery_error(f"{error.__class__.__name__}: {message}")
        or error.__class__.__name__
    )


def sanitize_persisted_delivery_error(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split())
    if not normalized:
        return None
    return redact_string(normalized, key=None)[:MAX_ERROR_MESSAGE_LENGTH]


def _audit_description(*, action: ActionType, source: str) -> str:
    label = {
        ActionType.FLOW_RUN_COMPLETED: "Flow run completed",
        ActionType.FLOW_RUN_FAILED: "Flow run failed",
        ActionType.FLOW_RUN_CANCELLED: "Flow run cancelled",
        ActionType.FLOW_RUN_REVIEW_CHECKPOINT_OPENED: (
            "Flow run review checkpoint opened"
        ),
        ActionType.FLOW_RUN_REVIEW_CHECKPOINT_EDITED: (
            "Flow run review checkpoint edited"
        ),
        ActionType.FLOW_RUN_REVIEW_CHECKPOINT_APPROVED: (
            "Flow run review checkpoint approved"
        ),
        ActionType.FLOW_RUN_REVIEW_CHECKPOINT_REJECTED: (
            "Flow run review checkpoint rejected"
        ),
        ActionType.FLOW_RUN_REVIEW_CHECKPOINT_RESUMED: (
            "Flow run review checkpoint resumed"
        ),
        ActionType.FLOW_RUN_REVIEW_CHECKPOINT_CANCELLED: (
            "Flow run review checkpoint cancelled"
        ),
        ActionType.FLOW_RUN_REVIEW_CHECKPOINT_EXPIRED: (
            "Flow run review checkpoint expired"
        ),
    }.get(action)
    if label is None:
        raise ValueError(f"Unsupported Flow audit outbox action: {action.value}")
    return f"{label} by {source}."


def _audit_metadata(
    row: FlowRunAuditOutboxDeliveryRow,
) -> dict[str, FlowAuditOutboxMetadataValue]:
    return {
        "flow_id": str(row.flow_id),
        "flow_run_id": str(row.flow_run_id),
        "run_revision": row.run_revision,
        "source": row.source,
        "target_status": row.target_status,
        "review_checkpoint_id": (
            str(row.review_checkpoint_id)
            if row.review_checkpoint_id is not None
            else None
        ),
        "checkpoint_revision": row.checkpoint_revision,
        "error_code": row.error_code,
        "outbox_description": row.description,
    }


def _failure_error_message(row: FlowRunAuditOutboxDeliveryRow) -> str:
    return (
        _non_empty(row.error_message)
        or _non_empty(row.error_code)
        or f"{row.action}:{row.source}"
    )


def _non_empty(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
