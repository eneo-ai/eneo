from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import cast
from uuid import UUID, uuid4

from eneo.audit.application.guaranteed_delivery import (
    GuaranteedAuditDeliveryService,
)
from eneo.audit.domain.audit_log import AuditLog


@dataclass
class _Row:
    id: UUID
    delivery_attempts: int


class _Transaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_args: object) -> None:
        return None


class _Session:
    def begin_nested(self) -> _Transaction:
        return _Transaction()


class _OutboxRepository:
    def __init__(self, rows: list[_Row]) -> None:
        self.session = _Session()
        self.rows = rows
        self.succeeded: list[tuple[UUID, int]] = []
        self.failures: list[dict[str, object]] = []

    async def list_due_delivery_rows(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> list[_Row]:
        del now
        return self.rows[:limit]

    async def mark_delivery_succeeded(
        self,
        *,
        outbox_id: UUID,
        delivered_at: datetime,
        attempt_no: int,
    ) -> None:
        del delivered_at
        self.succeeded.append((outbox_id, attempt_no))

    async def record_delivery_failure(self, **values: object) -> None:
        self.failures.append(values)


class _AuditRepository:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.created = 0

    async def create_if_absent(self, audit_log: AuditLog) -> AuditLog:
        del audit_log
        if self.error is not None:
            raise self.error
        self.created += 1
        return cast(AuditLog, object())


async def test_guaranteed_delivery_marks_idempotent_audit_write_succeeded() -> None:
    row = _Row(id=uuid4(), delivery_attempts=2)
    outbox = _OutboxRepository([row])
    audit = _AuditRepository()
    service = GuaranteedAuditDeliveryService(
        audit_outbox_repo=outbox,  # type: ignore[arg-type]
        audit_log_repo=audit,  # type: ignore[arg-type]
        build_audit_log=lambda _: cast(AuditLog, object()),
        retry_delay_seconds=lambda _: 30,
        sanitize_error=lambda error: str(error),
        default_batch_size=10,
    )

    result = await service.deliver_due(now=datetime.now(timezone.utc))

    assert result.delivered_count == 1
    assert result.to_task_payload()["delivered"] == 1
    assert outbox.succeeded == [(row.id, 3)]
    assert outbox.failures == []


async def test_guaranteed_delivery_schedules_retry_without_losing_outbox_row() -> None:
    now = datetime.now(timezone.utc)
    row = _Row(id=uuid4(), delivery_attempts=0)
    outbox = _OutboxRepository([row])
    service = GuaranteedAuditDeliveryService(
        audit_outbox_repo=outbox,  # type: ignore[arg-type]
        audit_log_repo=_AuditRepository(RuntimeError("temporary")),  # type: ignore[arg-type]
        build_audit_log=lambda _: cast(AuditLog, object()),
        retry_delay_seconds=lambda _: 30,
        sanitize_error=lambda error: f"safe:{error}",
        default_batch_size=10,
    )

    result = await service.deliver_due(now=now)

    assert result.retry_scheduled_count == 1
    assert result.dead_lettered_count == 0
    assert outbox.failures == [
        {
            "outbox_id": row.id,
            "attempt_no": 1,
            "error_message": "safe:temporary",
            "next_delivery_at": now + timedelta(seconds=30),
            "dead_lettered_at": None,
        }
    ]
