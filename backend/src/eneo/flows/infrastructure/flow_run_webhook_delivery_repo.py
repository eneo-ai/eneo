from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import cast
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.tables.flow_tables import (
    FlowOutboxDeliveryStatus,
    FlowRunWebhookDeliveries,
)
from eneo.flows.runtime.step_execution_result import WebhookDeliveryIntent


@dataclass(frozen=True, slots=True)
class FlowRunWebhookDeliveryRow:
    id: UUID
    tenant_id: UUID
    flow_id: UUID
    flow_run_id: UUID
    step_id: UUID
    step_order: int
    attempt_no: int
    idempotency_key: str
    payload_ref: str
    delivery_attempts: int
    claim_token: UUID
    created_at: datetime


@dataclass(frozen=True, slots=True)
class FlowRunWebhookDeliveryRead:
    """Tenant-scoped, secret-free delivery lifecycle projection for public reads."""

    id: UUID
    step_id: UUID
    step_order: int
    attempt_no: int
    delivery_status: FlowOutboxDeliveryStatus
    delivery_attempts: int
    next_delivery_at: datetime | None
    delivered_at: datetime | None
    dead_lettered_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class FlowRunWebhookDeliveryEvidenceMeasurement:
    row_count: int

    @classmethod
    def empty(cls) -> "FlowRunWebhookDeliveryEvidenceMeasurement":
        return cls(row_count=0)


class FlowRunWebhookDeliveryRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def measure_evidence_row_count(
        self, *, run_id: UUID, tenant_id: UUID, ceiling: int
    ) -> int:
        candidates = (
            sa.select(FlowRunWebhookDeliveries.id)
            .where(FlowRunWebhookDeliveries.flow_run_id == run_id)
            .where(FlowRunWebhookDeliveries.tenant_id == tenant_id)
            .limit(ceiling + 1)
            .subquery()
        )
        return int(
            await self.session.scalar(
                sa.select(sa.func.count()).select_from(candidates)
            )
            or 0
        )

    async def measure_evidence(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        candidate_limit: int | None = None,
    ) -> FlowRunWebhookDeliveryEvidenceMeasurement:
        candidate_stmt = (
            sa.select(FlowRunWebhookDeliveries.id)
            .where(FlowRunWebhookDeliveries.flow_run_id == run_id)
            .where(FlowRunWebhookDeliveries.tenant_id == tenant_id)
        )
        if candidate_limit is not None:
            candidate_stmt = candidate_stmt.limit(candidate_limit)
        row_count = await self.session.scalar(
            sa.select(sa.func.count()).select_from(candidate_stmt.subquery())
        )
        return FlowRunWebhookDeliveryEvidenceMeasurement(row_count=int(row_count or 0))

    async def insert_pending_delivery(
        self,
        *,
        flow_id: UUID,
        tenant_id: UUID,
        intent: WebhookDeliveryIntent,
    ) -> UUID:
        row_id = await self.session.scalar(
            pg_insert(FlowRunWebhookDeliveries)
            .values(
                tenant_id=tenant_id,
                flow_id=flow_id,
                flow_run_id=intent.flow_run_id,
                step_id=intent.step_id,
                step_order=intent.step_order,
                attempt_no=intent.attempt_no,
                idempotency_key=intent.idempotency_key,
                payload_ref=intent.payload.value,
            )
            .on_conflict_do_nothing(
                constraint="uq_flow_run_webhook_deliveries_attempt",
            )
            .returning(FlowRunWebhookDeliveries.id)
        )
        if row_id is not None:
            return row_id

        existing_id = await self.session.scalar(
            sa.select(FlowRunWebhookDeliveries.id)
            .where(FlowRunWebhookDeliveries.flow_run_id == intent.flow_run_id)
            .where(FlowRunWebhookDeliveries.step_id == intent.step_id)
            .where(FlowRunWebhookDeliveries.attempt_no == intent.attempt_no)
            .where(FlowRunWebhookDeliveries.tenant_id == tenant_id)
        )
        if existing_id is None:
            raise RuntimeError("Webhook delivery insert did not return an id.")
        return existing_id

    async def list_run_delivery_statuses(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        limit: int | None = None,
    ) -> list[FlowRunWebhookDeliveryRead]:
        stmt = (
            sa.select(
                FlowRunWebhookDeliveries.id,
                FlowRunWebhookDeliveries.step_id,
                FlowRunWebhookDeliveries.step_order,
                FlowRunWebhookDeliveries.attempt_no,
                FlowRunWebhookDeliveries.delivery_status,
                FlowRunWebhookDeliveries.delivery_attempts,
                FlowRunWebhookDeliveries.next_delivery_at,
                FlowRunWebhookDeliveries.delivered_at,
                FlowRunWebhookDeliveries.dead_lettered_at,
                FlowRunWebhookDeliveries.created_at,
                FlowRunWebhookDeliveries.updated_at,
            )
            .where(FlowRunWebhookDeliveries.flow_run_id == run_id)
            .where(FlowRunWebhookDeliveries.tenant_id == tenant_id)
            .order_by(
                FlowRunWebhookDeliveries.step_order.asc(),
                FlowRunWebhookDeliveries.attempt_no.asc(),
                FlowRunWebhookDeliveries.id.asc(),
            )
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        rows = (await self.session.execute(stmt)).tuples()
        return [
            FlowRunWebhookDeliveryRead(
                id=row.id,
                step_id=row.step_id,
                step_order=row.step_order,
                attempt_no=row.attempt_no,
                delivery_status=FlowOutboxDeliveryStatus(
                    cast(str, row.delivery_status)
                ),
                delivery_attempts=row.delivery_attempts,
                next_delivery_at=row.next_delivery_at,
                delivered_at=row.delivered_at,
                dead_lettered_at=row.dead_lettered_at,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in rows
        ]

    async def claim_due_delivery_rows(
        self,
        *,
        now: datetime,
        limit: int,
        claim_ttl_seconds: int,
        max_attempts: int,
    ) -> list[FlowRunWebhookDeliveryRow]:
        if limit <= 0:
            return []
        claim_token = uuid4()
        claim_expires_at = now + timedelta(seconds=claim_ttl_seconds)
        candidate_ids = (
            (
                await self.session.execute(
                    sa.select(FlowRunWebhookDeliveries.id)
                    .where(
                        FlowRunWebhookDeliveries.delivery_status
                        == FlowOutboxDeliveryStatus.PENDING.value
                    )
                    .where(FlowRunWebhookDeliveries.delivery_attempts < max_attempts)
                    .where(
                        sa.or_(
                            FlowRunWebhookDeliveries.next_delivery_at.is_(None),
                            FlowRunWebhookDeliveries.next_delivery_at <= now,
                        )
                    )
                    .where(
                        sa.or_(
                            FlowRunWebhookDeliveries.claim_token.is_(None),
                            FlowRunWebhookDeliveries.claim_expires_at <= now,
                        )
                    )
                    .order_by(
                        FlowRunWebhookDeliveries.next_delivery_at.asc().nullsfirst(),
                        FlowRunWebhookDeliveries.created_at.asc(),
                    )
                    .limit(limit)
                    .with_for_update(
                        of=FlowRunWebhookDeliveries,
                        skip_locked=True,
                    )
                )
            )
            .scalars()
            .all()
        )
        if not candidate_ids:
            return []

        rows = (
            (
                await self.session.execute(
                    sa.update(FlowRunWebhookDeliveries)
                    .where(FlowRunWebhookDeliveries.id.in_(candidate_ids))
                    .where(FlowRunWebhookDeliveries.delivery_attempts < max_attempts)
                    .values(
                        claim_token=claim_token,
                        claimed_at=now,
                        claim_expires_at=claim_expires_at,
                        delivery_attempts=(
                            FlowRunWebhookDeliveries.delivery_attempts + 1
                        ),
                        updated_at=datetime.now(timezone.utc),
                    )
                    .returning(FlowRunWebhookDeliveries)
                )
            )
            .scalars()
            .all()
        )
        return [self._to_delivery_row(row) for row in rows]

    async def lock_expired_at_budget_delivery_rows(
        self,
        *,
        now: datetime,
        limit: int,
        max_attempts: int,
    ) -> list[FlowRunWebhookDeliveryRow]:
        if limit <= 0:
            return []
        rows = (
            (
                await self.session.execute(
                    sa.select(FlowRunWebhookDeliveries)
                    .where(
                        FlowRunWebhookDeliveries.delivery_status
                        == FlowOutboxDeliveryStatus.PENDING.value
                    )
                    .where(FlowRunWebhookDeliveries.delivery_attempts >= max_attempts)
                    .where(FlowRunWebhookDeliveries.claim_token.is_not(None))
                    .where(FlowRunWebhookDeliveries.claim_expires_at <= now)
                    .order_by(
                        FlowRunWebhookDeliveries.claim_expires_at.asc(),
                        FlowRunWebhookDeliveries.created_at.asc(),
                    )
                    .limit(limit)
                    .with_for_update(
                        of=FlowRunWebhookDeliveries,
                        skip_locked=True,
                    )
                )
            )
            .scalars()
            .all()
        )
        return [self._to_delivery_row(row) for row in rows]

    async def mark_delivery_succeeded(
        self,
        *,
        delivery_id: UUID,
        claim_token: UUID,
        delivered_at: datetime,
    ) -> bool:
        result = await self.session.execute(
            sa.update(FlowRunWebhookDeliveries)
            .where(FlowRunWebhookDeliveries.id == delivery_id)
            .where(FlowRunWebhookDeliveries.claim_token == claim_token)
            .where(
                FlowRunWebhookDeliveries.delivery_status
                == FlowOutboxDeliveryStatus.PENDING.value
            )
            .values(
                delivery_status=FlowOutboxDeliveryStatus.DELIVERED.value,
                next_delivery_at=None,
                claim_token=None,
                claimed_at=None,
                claim_expires_at=None,
                delivered_at=delivered_at,
                dead_lettered_at=None,
                delivery_last_error=None,
                updated_at=datetime.now(timezone.utc),
            )
        )
        return bool(getattr(result, "rowcount", 0))

    async def record_delivery_failure(
        self,
        *,
        delivery_id: UUID,
        claim_token: UUID,
        error_message: str,
        next_delivery_at: datetime | None,
        dead_lettered_at: datetime | None,
    ) -> bool:
        delivery_status = (
            FlowOutboxDeliveryStatus.DEAD_LETTERED.value
            if dead_lettered_at is not None
            else FlowOutboxDeliveryStatus.PENDING.value
        )
        result = await self.session.execute(
            sa.update(FlowRunWebhookDeliveries)
            .where(FlowRunWebhookDeliveries.id == delivery_id)
            .where(FlowRunWebhookDeliveries.claim_token == claim_token)
            .where(
                FlowRunWebhookDeliveries.delivery_status
                == FlowOutboxDeliveryStatus.PENDING.value
            )
            .values(
                delivery_status=delivery_status,
                next_delivery_at=next_delivery_at,
                claim_token=None,
                claimed_at=None,
                claim_expires_at=None,
                delivered_at=None,
                dead_lettered_at=dead_lettered_at,
                delivery_last_error=error_message,
                updated_at=datetime.now(timezone.utc),
            )
        )
        return bool(getattr(result, "rowcount", 0))

    @staticmethod
    def _to_delivery_row(
        row: FlowRunWebhookDeliveries,
    ) -> FlowRunWebhookDeliveryRow:
        if row.claim_token is None:
            raise RuntimeError("Claimed webhook delivery row has no claim token.")
        return FlowRunWebhookDeliveryRow(
            id=row.id,
            tenant_id=row.tenant_id,
            flow_id=row.flow_id,
            flow_run_id=row.flow_run_id,
            step_id=row.step_id,
            step_order=row.step_order,
            attempt_no=row.attempt_no,
            idempotency_key=row.idempotency_key,
            payload_ref=row.payload_ref,
            delivery_attempts=row.delivery_attempts,
            claim_token=row.claim_token,
            created_at=row.created_at,
        )
