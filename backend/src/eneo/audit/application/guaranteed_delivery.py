from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Generic, Protocol, TypeVar
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from eneo.audit.domain.audit_log import AuditLog
from eneo.audit.domain.repositories.audit_log_repository import AuditLogRepository


class AuditDeliveryRow(Protocol):
    @property
    def id(self) -> UUID: ...

    @property
    def delivery_attempts(self) -> int: ...


RowT = TypeVar("RowT", bound=AuditDeliveryRow)


class GuaranteedAuditOutboxRepository(Protocol[RowT]):
    session: AsyncSession

    async def list_due_delivery_rows(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> list[RowT]: ...

    async def mark_delivery_succeeded(
        self,
        *,
        outbox_id: UUID,
        delivered_at: datetime,
        attempt_no: int,
    ) -> None: ...

    async def record_delivery_failure(
        self,
        *,
        outbox_id: UUID,
        attempt_no: int,
        error_message: str,
        next_delivery_at: datetime | None,
        dead_lettered_at: datetime | None,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class GuaranteedAuditDeliveryResult:
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


class GuaranteedAuditDeliveryService(Generic[RowT]):
    """Reusable at-least-once audit delivery with idempotent audit writes."""

    def __init__(
        self,
        *,
        audit_outbox_repo: GuaranteedAuditOutboxRepository[RowT],
        audit_log_repo: AuditLogRepository,
        build_audit_log: Callable[[RowT], AuditLog],
        retry_delay_seconds: Callable[[int], int | None],
        sanitize_error: Callable[[Exception], str],
        default_batch_size: int,
    ) -> None:
        self.audit_outbox_repo = audit_outbox_repo
        self.audit_log_repo = audit_log_repo
        self._build_audit_log = build_audit_log
        self._retry_delay_seconds = retry_delay_seconds
        self._sanitize_error = sanitize_error
        self._default_batch_size = default_batch_size

    async def deliver_due(
        self,
        *,
        now: datetime,
        limit: int | None = None,
    ) -> GuaranteedAuditDeliveryResult:
        rows = await self.audit_outbox_repo.list_due_delivery_rows(
            now=now,
            limit=self._default_batch_size if limit is None else limit,
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
        return GuaranteedAuditDeliveryResult(
            attempted_count=len(rows),
            delivered_count=delivered,
            retry_scheduled_count=retry_scheduled,
            dead_lettered_count=dead_lettered,
        )

    async def _deliver_row(self, *, row: RowT, now: datetime) -> None:
        await self.audit_log_repo.create_if_absent(self._build_audit_log(row))
        await self.audit_outbox_repo.mark_delivery_succeeded(
            outbox_id=row.id,
            delivered_at=now,
            attempt_no=row.delivery_attempts + 1,
        )

    async def _record_failure(
        self,
        *,
        row: RowT,
        now: datetime,
        error: Exception,
        force_dead_letter: bool,
    ) -> bool:
        attempt_no = row.delivery_attempts + 1
        retry_delay = (
            None if force_dead_letter else self._retry_delay_seconds(attempt_no)
        )
        dead_lettered_at = now if retry_delay is None else None
        next_delivery_at = (
            None if retry_delay is None else now + timedelta(seconds=retry_delay)
        )
        await self.audit_outbox_repo.record_delivery_failure(
            outbox_id=row.id,
            attempt_no=attempt_no,
            error_message=self._sanitize_error(error),
            next_delivery_at=next_delivery_at,
            dead_lettered_at=dead_lettered_at,
        )
        return dead_lettered_at is not None
