from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence, TypedDict
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from intric.database.tables.flow_tables import FlowRuns, FlowStepAttempts, FlowStepResults
from intric.flows.flow import (
    FlowRun,
    FlowRunStatus,
    FlowStepAttempt,
    FlowStepAttemptStatus,
    FlowStepResult,
    FlowStepResultStatus,
)
from intric.flows.flow_factory import FlowFactory
from intric.main.exceptions import NotFoundException


class PreseedStep(TypedDict):
    step_id: UUID
    assistant_id: UUID
    step_order: int


class FlowRunRepository:
    """Tenant-scoped repository for flow run lifecycle and run evidence."""

    _ACTIVE_STATUSES = (FlowRunStatus.QUEUED.value, FlowRunStatus.RUNNING.value)

    def __init__(self, session: AsyncSession, factory: FlowFactory):
        self.session = session
        self.factory = factory

    async def create(
        self,
        *,
        flow_id: UUID,
        flow_version: int,
        user_id: UUID,
        tenant_id: UUID,
        input_payload_json: dict[str, Any] | None,
        preseed_steps: Sequence["PreseedStep"],
    ) -> FlowRun:
        run_row = await self.session.scalar(
            sa.insert(FlowRuns)
            .values(
                flow_id=flow_id,
                flow_version=flow_version,
                user_id=user_id,
                tenant_id=tenant_id,
                status=FlowRunStatus.QUEUED.value,
                input_payload_json=input_payload_json,
            )
            .returning(FlowRuns)
        )
        if run_row is None:
            raise NotFoundException("Could not create flow run.")

        preseed_rows = [
            {
                "flow_run_id": run_row.id,
                "flow_id": flow_id,
                "tenant_id": tenant_id,
                "step_id": step["step_id"],
                "step_order": step["step_order"],
                "assistant_id": step["assistant_id"],
                "status": FlowStepResultStatus.PENDING.value,
            }
            for step in sorted(preseed_steps, key=lambda item: int(item["step_order"]))
        ]
        if preseed_rows:
            await self.session.execute(sa.insert(FlowStepResults).values(preseed_rows))

        return self.factory.from_flow_run_db(run_row)

    async def get(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        flow_id: UUID | None = None,
    ) -> FlowRun:
        stmt = (
            sa.select(FlowRuns)
            .where(FlowRuns.id == run_id)
            .where(FlowRuns.tenant_id == tenant_id)
        )
        if flow_id is not None:
            stmt = stmt.where(FlowRuns.flow_id == flow_id)

        run_row = await self.session.scalar(stmt)
        if run_row is None:
            raise NotFoundException("Flow run not found.")
        return self.factory.from_flow_run_db(run_row)

    async def count_active_runs(self, *, tenant_id: UUID) -> int:
        count = await self.session.scalar(
            sa.select(sa.func.count())
            .select_from(FlowRuns)
            .where(FlowRuns.tenant_id == tenant_id)
            .where(FlowRuns.status.in_(self._ACTIVE_STATUSES))
        )
        return int(count or 0)

    async def list_runs(
        self,
        *,
        tenant_id: UUID,
        flow_id: UUID | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[FlowRun]:
        stmt = (
            sa.select(FlowRuns)
            .where(FlowRuns.tenant_id == tenant_id)
            .order_by(FlowRuns.created_at.desc())
        )
        if flow_id is not None:
            stmt = stmt.where(FlowRuns.flow_id == flow_id)
        if offset is not None:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)

        rows = (await self.session.execute(stmt)).scalars().all()
        return [self.factory.from_flow_run_db(row) for row in rows]

    async def list_stale_queued_runs(
        self,
        *,
        tenant_id: UUID,
        stale_before: datetime,
        flow_id: UUID | None = None,
        run_id: UUID | None = None,
        limit: int = 25,
    ) -> list[FlowRun]:
        stmt = (
            sa.select(FlowRuns)
            .where(FlowRuns.tenant_id == tenant_id)
            .where(FlowRuns.status == FlowRunStatus.QUEUED.value)
            .where(FlowRuns.updated_at <= stale_before)
            .order_by(FlowRuns.updated_at.asc())
            .limit(limit)
        )
        if flow_id is not None:
            stmt = stmt.where(FlowRuns.flow_id == flow_id)
        if run_id is not None:
            stmt = stmt.where(FlowRuns.id == run_id)

        rows = (await self.session.execute(stmt)).scalars().all()
        return [self.factory.from_flow_run_db(row) for row in rows]

    async def claim_stale_queued_run_for_redispatch(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        stale_before: datetime,
        flow_id: UUID | None = None,
    ) -> FlowRun | None:
        stmt = (
            sa.update(FlowRuns)
            .where(FlowRuns.id == run_id)
            .where(FlowRuns.tenant_id == tenant_id)
            .where(FlowRuns.status == FlowRunStatus.QUEUED.value)
            .where(FlowRuns.updated_at <= stale_before)
        )
        if flow_id is not None:
            stmt = stmt.where(FlowRuns.flow_id == flow_id)

        claimed = await self.session.scalar(
            stmt.values(updated_at=datetime.now(timezone.utc)).returning(FlowRuns)
        )
        if claimed is None:
            return None
        return self.factory.from_flow_run_db(claimed)

    async def update_status(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        status: FlowRunStatus,
        error_message: str | None = None,
        output_payload_json: dict[str, Any] | None = None,
        cancelled_at: datetime | None = None,
        from_statuses: tuple[str, ...] | None = None,
    ) -> FlowRun:
        values: dict[str, Any] = {
            "status": status.value,
            "error_message": error_message,
            "output_payload_json": output_payload_json,
        }
        if cancelled_at is not None:
            values["cancelled_at"] = cancelled_at

        if from_statuses is None and status in (
            FlowRunStatus.COMPLETED,
            FlowRunStatus.FAILED,
            FlowRunStatus.CANCELLED,
        ):
            from_statuses = (FlowRunStatus.QUEUED.value, FlowRunStatus.RUNNING.value)

        stmt = (
            sa.update(FlowRuns)
            .where(FlowRuns.id == run_id)
            .where(FlowRuns.tenant_id == tenant_id)
        )
        if from_statuses is not None:
            stmt = stmt.where(FlowRuns.status.in_(from_statuses))
        run_row = await self.session.scalar(stmt.values(**values).returning(FlowRuns))
        if run_row is None:
            existing = await self.session.scalar(
                sa.select(FlowRuns)
                .where(FlowRuns.id == run_id)
                .where(FlowRuns.tenant_id == tenant_id)
            )
            if existing is None:
                raise NotFoundException("Flow run not found.")
            return self.factory.from_flow_run_db(existing)
        return self.factory.from_flow_run_db(run_row)

    async def cancel(self, *, run_id: UUID, tenant_id: UUID) -> FlowRun:
        return await self.update_status(
            run_id=run_id,
            tenant_id=tenant_id,
            status=FlowRunStatus.CANCELLED,
            cancelled_at=datetime.now(timezone.utc),
            from_statuses=(FlowRunStatus.QUEUED.value, FlowRunStatus.RUNNING.value),
        )

    async def list_step_results(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
    ) -> list[FlowStepResult]:
        rows = (
            await self.session.execute(
                sa.select(FlowStepResults)
                .where(FlowStepResults.flow_run_id == run_id)
                .where(FlowStepResults.tenant_id == tenant_id)
                .order_by(FlowStepResults.step_order.asc())
            )
        ).scalars().all()
        return [self.factory.from_flow_step_result_db(row) for row in rows]

    async def list_step_attempts(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
    ) -> list[FlowStepAttempt]:
        rows = (
            await self.session.execute(
                sa.select(FlowStepAttempts)
                .where(FlowStepAttempts.flow_run_id == run_id)
                .where(FlowStepAttempts.tenant_id == tenant_id)
                .order_by(
                    FlowStepAttempts.step_order.asc(),
                    FlowStepAttempts.attempt_no.asc(),
                )
            )
        ).scalars().all()
        return [self.factory.from_flow_step_attempt_db(row) for row in rows]

    async def mark_running_if_claimable(self, *, run_id: UUID, tenant_id: UUID) -> bool:
        result = await self.session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == run_id)
            .where(FlowRuns.tenant_id == tenant_id)
            .where(FlowRuns.status == FlowRunStatus.QUEUED.value)
            .values(status=FlowRunStatus.RUNNING.value)
        )
        return bool(getattr(result, "rowcount", 0))

    async def get_step_result(
        self,
        *,
        run_id: UUID,
        step_id: UUID,
        tenant_id: UUID,
    ) -> FlowStepResult | None:
        row = await self.session.scalar(
            sa.select(FlowStepResults)
            .where(FlowStepResults.flow_run_id == run_id)
            .where(FlowStepResults.step_id == step_id)
            .where(FlowStepResults.tenant_id == tenant_id)
        )
        if row is None:
            return None
        return self.factory.from_flow_step_result_db(row)

    async def claim_step_result(
        self,
        *,
        run_id: UUID,
        step_id: UUID,
        tenant_id: UUID,
    ) -> FlowStepResult | None:
        row = await self.session.scalar(
            sa.update(FlowStepResults)
            .where(FlowStepResults.flow_run_id == run_id)
            .where(FlowStepResults.step_id == step_id)
            .where(FlowStepResults.tenant_id == tenant_id)
            .where(
                FlowStepResults.status.in_(
                    (
                        FlowStepResultStatus.PENDING.value,
                        FlowStepResultStatus.FAILED.value,
                    )
                )
            )
            .values(
                status=FlowStepResultStatus.RUNNING.value,
                error_message=None,
            )
            .returning(FlowStepResults)
        )
        if row is None:
            return None
        return self.factory.from_flow_step_result_db(row)

    async def mark_pending_steps_cancelled(
        self,
        *,
        run_id: UUID,
        tenant_id: UUID,
        error_message: str | None = None,
    ) -> None:
        await self.session.execute(
            sa.update(FlowStepResults)
            .where(FlowStepResults.flow_run_id == run_id)
            .where(FlowStepResults.tenant_id == tenant_id)
            .where(
                FlowStepResults.status.in_(
                    (
                        FlowStepResultStatus.PENDING.value,
                        FlowStepResultStatus.RUNNING.value,
                    )
                )
            )
            .values(
                status=FlowStepResultStatus.CANCELLED.value,
                error_message=error_message,
            )
        )

    async def create_or_get_attempt_started(
        self,
        *,
        run_id: UUID,
        flow_id: UUID,
        tenant_id: UUID,
        step_id: UUID,
        step_order: int,
        attempt_no: int,
        celery_task_id: str | None,
    ) -> FlowStepAttempt:
        started_at = datetime.now(timezone.utc)
        insert_stmt = (
            pg_insert(FlowStepAttempts)
            .values(
                flow_run_id=run_id,
                flow_id=flow_id,
                tenant_id=tenant_id,
                step_id=step_id,
                step_order=step_order,
                attempt_no=attempt_no,
                celery_task_id=celery_task_id,
                status=FlowStepAttemptStatus.STARTED.value,
                started_at=started_at,
            )
            .on_conflict_do_nothing(
                constraint="uq_flow_step_attempts_run_step_attempt",
            )
            .returning(FlowStepAttempts)
        )
        row = await self.session.scalar(insert_stmt)
        if row is None:
            row = await self.session.scalar(
                sa.select(FlowStepAttempts)
                .where(FlowStepAttempts.flow_run_id == run_id)
                .where(FlowStepAttempts.step_id == step_id)
                .where(FlowStepAttempts.attempt_no == attempt_no)
                .where(FlowStepAttempts.tenant_id == tenant_id)
            )
        if row is None:
            raise NotFoundException("Could not create or fetch flow step attempt.")
        return self.factory.from_flow_step_attempt_db(row)

    async def finish_attempt(
        self,
        *,
        run_id: UUID,
        step_id: UUID,
        attempt_no: int,
        tenant_id: UUID,
        status: FlowStepAttemptStatus,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> FlowStepAttempt | None:
        row = await self.session.scalar(
            sa.update(FlowStepAttempts)
            .where(FlowStepAttempts.flow_run_id == run_id)
            .where(FlowStepAttempts.step_id == step_id)
            .where(FlowStepAttempts.attempt_no == attempt_no)
            .where(FlowStepAttempts.tenant_id == tenant_id)
            .where(
                FlowStepAttempts.status.in_(
                    (
                        FlowStepAttemptStatus.STARTED.value,
                        FlowStepAttemptStatus.RETRIED.value,
                    )
                )
            )
            .values(
                status=status.value,
                error_code=error_code,
                error_message=error_message,
                finished_at=datetime.now(timezone.utc),
            )
            .returning(FlowStepAttempts)
        )
        if row is None:
            return None
        return self.factory.from_flow_step_attempt_db(row)
