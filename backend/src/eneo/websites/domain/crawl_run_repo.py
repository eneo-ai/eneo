from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from eneo.database.tables.job_table import Jobs
from eneo.database.tables.websites_table import CrawlAttempts
from eneo.database.tables.websites_table import CrawlRuns as CrawlRunsTable
from eneo.jobs.job_models import Task
from eneo.main.exceptions import NotFoundException
from eneo.main.models import Status
from eneo.websites.crawl_dependencies.crawl_models import CrawlTask
from eneo.websites.domain.crawl_run import (
    CrawlFailureCode,
    CrawlOutcome,
    CrawlPhase,
    CrawlRun,
)

LEASE_SWEEP_BATCH_SIZE = 100
DISPATCH_PAGE_SIZE = 50
_DISPATCH_ADVISORY_LOCK = 1_836_472_911
_LEASED_PHASES = (
    CrawlPhase.RUNNING.value,
    CrawlPhase.FINALIZING.value,
    CrawlPhase.STOPPING.value,
)
_SUCCESSFUL_OUTCOMES = {
    CrawlOutcome.SUCCEEDED,
    CrawlOutcome.UNCHANGED,
    CrawlOutcome.EMPTY,
    CrawlOutcome.PARTIAL,
}
_CLEAN_OUTCOMES = {
    CrawlOutcome.SUCCEEDED,
    CrawlOutcome.UNCHANGED,
    CrawlOutcome.EMPTY,
}

if TYPE_CHECKING:
    from eneo.database.database import AsyncSession


@dataclass(frozen=True, slots=True)
class CrawlDispatchCandidate:
    attempt_id: UUID
    attempt_number: int
    run_id: UUID
    dispatch_id: UUID
    payload: dict[str, object]
    website_id: UUID
    tenant_id: UUID
    origin: str


class CrawlRunRepository:
    """Canonical persistence owner for crawl admission and execution state."""

    def __init__(self, session: "AsyncSession"):
        super().__init__()
        self.session = session

    async def one(self, id: UUID) -> CrawlRun:
        crawl_run = await self.one_or_none(id)
        if crawl_run is None:
            raise NotFoundException()
        return crawl_run

    async def one_or_none(self, id: UUID) -> CrawlRun | None:
        record = await self.session.scalar(
            sa.select(CrawlRunsTable).where(CrawlRunsTable.id == id)
        )
        return CrawlRun.to_domain(record=record) if record is not None else None

    @staticmethod
    def _values(crawl_run: CrawlRun) -> dict[str, object]:
        assert crawl_run.id is not None
        return {
            "id": crawl_run.id,
            "website_id": crawl_run.website_id,
            "tenant_id": crawl_run.tenant_id,
            "pages_crawled": crawl_run.pages_crawled,
            "files_downloaded": crawl_run.files_downloaded,
            "pages_failed": crawl_run.pages_failed,
            "files_failed": crawl_run.files_failed,
            "failure_summary": crawl_run.failure_summary,
            "phase": crawl_run.phase.value,
            "outcome": crawl_run.outcome.value if crawl_run.outcome else None,
            "origin": crawl_run.origin.value,
            "result_location": crawl_run.result_location,
            "finished_at": crawl_run.finished_at,
            "failure_code": crawl_run.failure_code,
            "failure_detail": crawl_run.failure_detail,
            "cancel_requested_at": crawl_run.cancel_requested_at,
            "attempt_count": crawl_run.attempt_count,
            "job_id": crawl_run.job_id,
        }

    async def add_or_get_active(self, crawl_run: CrawlRun) -> tuple[CrawlRun, bool]:
        for _attempt in range(2):
            statement = (
                pg_insert(CrawlRunsTable)
                .values(**self._values(crawl_run))
                .on_conflict_do_nothing(
                    index_elements=[CrawlRunsTable.website_id],
                    index_where=sa.text("phase <> 'terminal'"),
                )
                .returning(CrawlRunsTable)
            )
            record = await self.session.scalar(statement)
            if record is not None:
                return CrawlRun.to_domain(record=record), True

            record = await self.session.scalar(
                sa.select(CrawlRunsTable)
                .where(CrawlRunsTable.website_id == crawl_run.website_id)
                .where(CrawlRunsTable.phase != CrawlPhase.TERMINAL.value)
                .order_by(CrawlRunsTable.created_at.asc(), CrawlRunsTable.id.asc())
                .limit(1)
            )
            if record is not None:
                return CrawlRun.to_domain(record=record), False

        raise RuntimeError("Active crawl changed repeatedly during admission")

    async def get_crawl_runs(self, website_id: UUID) -> list[CrawlRun]:
        records = await self.session.scalars(
            sa.select(CrawlRunsTable)
            .where(CrawlRunsTable.website_id == website_id)
            .order_by(CrawlRunsTable.created_at.desc(), CrawlRunsTable.id.desc())
        )
        return [CrawlRun.to_domain(record=record) for record in records]

    async def add_attempt(
        self,
        *,
        run_id: UUID,
        attempt_id: UUID,
        dispatch_id: UUID,
        task: CrawlTask,
    ) -> None:
        run = await self.session.scalar(
            sa.select(CrawlRunsTable)
            .where(CrawlRunsTable.id == run_id)
            .with_for_update()
        )
        if run is None:
            raise NotFoundException()
        if run.phase != CrawlPhase.PENDING_DISPATCH.value:
            raise ValueError("Attempts can only be added to pending crawl runs")

        job = await self.session.scalar(
            sa.select(Jobs).where(Jobs.id == dispatch_id).with_for_update()
        )
        if job is None or job.task != Task.CRAWL.value:
            raise ValueError("A crawl attempt requires its crawl job projection")

        attempt_number = run.attempt_count + 1
        if task.attempt_id != attempt_id or task.attempt_number != attempt_number:
            raise ValueError("Crawl task does not match the admitted attempt")
        if task.run_id != run_id or task.website_id != run.website_id:
            raise ValueError("Crawl task does not match the crawl run")
        if task.origin.value != run.origin or task.user_id != job.user_id:
            raise ValueError("Crawl task identity does not match persisted ownership")

        await self.session.execute(
            sa.insert(CrawlAttempts).values(
                id=attempt_id,
                crawl_run_id=run_id,
                attempt_number=attempt_number,
                dispatch_id=dispatch_id,
                dispatch_payload=task.model_dump(mode="json"),
            )
        )
        run.attempt_count = attempt_number
        run.job_id = dispatch_id
        await self.session.flush()

    async def claim_dispatch_candidates(
        self,
        *,
        concurrency_limit: int,
        retry_after: timedelta,
        redeliver_after: timedelta,
    ) -> list[CrawlDispatchCandidate]:
        if concurrency_limit <= 0:
            return []
        if retry_after <= timedelta(0):
            raise ValueError("Dispatch retry interval must be positive")
        if redeliver_after <= retry_after:
            raise ValueError(
                "Queue redelivery interval must exceed the dispatch retry interval"
            )

        locked = await self.session.scalar(
            sa.select(sa.func.pg_try_advisory_xact_lock(_DISPATCH_ADVISORY_LOCK))
        )
        if not locked:
            return []

        now = await self._database_now()
        stale_before = now - retry_after
        redeliver_before = now - redeliver_after
        leased_units = sa.select(
            CrawlRunsTable.tenant_id.label("tenant_id"),
            sa.literal(1).label("units"),
        ).where(CrawlRunsTable.phase.in_(_LEASED_PHASES))
        pending_units = (
            sa.select(
                CrawlRunsTable.tenant_id.label("tenant_id"),
                sa.literal(1).label("units"),
            )
            .join(
                CrawlAttempts,
                CrawlAttempts.crawl_run_id == CrawlRunsTable.id,
            )
            .where(CrawlRunsTable.phase == CrawlPhase.PENDING_DISPATCH.value)
            .where(CrawlAttempts.finished_at.is_(None))
            .where(CrawlAttempts.dispatched_at.is_(None))
            .where(CrawlAttempts.dispatch_attempted_at.is_not(None))
        )
        queued_units = (
            sa.select(
                CrawlRunsTable.tenant_id.label("tenant_id"),
                sa.literal(1).label("units"),
            )
            .join(
                CrawlAttempts,
                CrawlAttempts.crawl_run_id == CrawlRunsTable.id,
            )
            .where(CrawlRunsTable.phase == CrawlPhase.QUEUED.value)
            .where(CrawlAttempts.finished_at.is_(None))
            .where(CrawlAttempts.started_at.is_(None))
            .where(CrawlAttempts.dispatch_attempted_at.is_not(None))
        )
        active_units = sa.union_all(
            leased_units,
            pending_units,
            queued_units,
        ).cte("crawl_admission_units")
        tenant_load = (
            sa.select(
                active_units.c.tenant_id,
                sa.func.sum(active_units.c.units).label("units"),
            )
            .group_by(active_units.c.tenant_id)
            .cte("crawl_tenant_load")
        )
        reserved = int(
            await self.session.scalar(
                sa.select(sa.func.count()).select_from(active_units)
            )
            or 0
        )
        # A timed-out enqueue is ambiguous: PostgreSQL cannot prove that the
        # prior Redis delivery disappeared. It therefore continues to reserve
        # one logical slot while the same dispatch ID is repaired. Only work
        # that has never been attempted may consume newly available capacity.
        repair_position = sa.func.row_number().over(
            partition_by=CrawlRunsTable.tenant_id,
            order_by=(CrawlAttempts.created_at.asc(), CrawlAttempts.id.asc()),
        )
        repair_ranked = (
            sa.select(
                CrawlAttempts.id.label("attempt_id"),
                CrawlRunsTable.tenant_id.label("tenant_id"),
                CrawlAttempts.created_at.label("created_at"),
                repair_position.label("tenant_position"),
            )
            .join(CrawlRunsTable, CrawlRunsTable.id == CrawlAttempts.crawl_run_id)
            .where(CrawlAttempts.finished_at.is_(None))
            .where(CrawlAttempts.started_at.is_(None))
            .where(CrawlAttempts.dispatch_attempted_at <= stale_before)
            .where(
                sa.or_(
                    sa.and_(
                        CrawlRunsTable.phase == CrawlPhase.PENDING_DISPATCH.value,
                        CrawlAttempts.dispatched_at.is_(None),
                    ),
                    sa.and_(
                        CrawlRunsTable.phase == CrawlPhase.QUEUED.value,
                        CrawlAttempts.started_at.is_(None),
                        CrawlAttempts.dispatched_at <= redeliver_before,
                    ),
                )
            )
            .cte("ranked_crawl_repairs")
        )
        repair_chosen = (
            sa.select(repair_ranked.c.attempt_id)
            .outerjoin(
                tenant_load,
                tenant_load.c.tenant_id == repair_ranked.c.tenant_id,
            )
            .order_by(
                (
                    sa.func.coalesce(tenant_load.c.units, 0)
                    + repair_ranked.c.tenant_position
                ).asc(),
                repair_ranked.c.created_at.asc(),
                repair_ranked.c.attempt_id.asc(),
            )
            .limit(DISPATCH_PAGE_SIZE)
            .cte("chosen_crawl_repairs")
        )
        repair_rows = (
            await self.session.execute(
                sa.select(CrawlAttempts, CrawlRunsTable)
                .join(
                    repair_chosen,
                    repair_chosen.c.attempt_id == CrawlAttempts.id,
                )
                .join(
                    CrawlRunsTable,
                    CrawlRunsTable.id == CrawlAttempts.crawl_run_id,
                )
                .order_by(CrawlAttempts.created_at.asc(), CrawlAttempts.id.asc())
                .with_for_update(of=CrawlAttempts, skip_locked=True)
            )
        ).all()

        fresh_limit = min(
            max(concurrency_limit - reserved, 0),
            DISPATCH_PAGE_SIZE - len(repair_rows),
        )
        fresh_rows = repair_rows[:0]
        if fresh_limit > 0:
            fresh_position = sa.func.row_number().over(
                partition_by=CrawlRunsTable.tenant_id,
                order_by=(CrawlAttempts.created_at.asc(), CrawlAttempts.id.asc()),
            )
            fresh_ranked = (
                sa.select(
                    CrawlAttempts.id.label("attempt_id"),
                    CrawlRunsTable.tenant_id.label("tenant_id"),
                    CrawlAttempts.created_at.label("created_at"),
                    fresh_position.label("tenant_position"),
                )
                .join(
                    CrawlRunsTable,
                    CrawlRunsTable.id == CrawlAttempts.crawl_run_id,
                )
                .where(
                    CrawlRunsTable.phase == CrawlPhase.PENDING_DISPATCH.value,
                    CrawlAttempts.finished_at.is_(None),
                    CrawlAttempts.started_at.is_(None),
                    CrawlAttempts.dispatched_at.is_(None),
                    CrawlAttempts.dispatch_attempted_at.is_(None),
                )
                .cte("ranked_fresh_crawl_dispatches")
            )
            fresh_chosen = (
                sa.select(fresh_ranked.c.attempt_id)
                .outerjoin(
                    tenant_load,
                    tenant_load.c.tenant_id == fresh_ranked.c.tenant_id,
                )
                .order_by(
                    (
                        sa.func.coalesce(tenant_load.c.units, 0)
                        + fresh_ranked.c.tenant_position
                    ).asc(),
                    fresh_ranked.c.created_at.asc(),
                    fresh_ranked.c.attempt_id.asc(),
                )
                .limit(fresh_limit)
                .cte("chosen_fresh_crawl_dispatches")
            )
            fresh_rows = list(
                (
                    await self.session.execute(
                        sa.select(CrawlAttempts, CrawlRunsTable)
                        .join(
                            fresh_chosen,
                            fresh_chosen.c.attempt_id == CrawlAttempts.id,
                        )
                        .join(
                            CrawlRunsTable,
                            CrawlRunsTable.id == CrawlAttempts.crawl_run_id,
                        )
                        .order_by(
                            CrawlAttempts.created_at.asc(),
                            CrawlAttempts.id.asc(),
                        )
                        .with_for_update(of=CrawlAttempts, skip_locked=True)
                    )
                ).all()
            )

        rows = [*repair_rows, *fresh_rows]

        candidates: list[CrawlDispatchCandidate] = []
        for attempt, run in rows:
            attempt.dispatch_attempted_at = now
            candidates.append(
                CrawlDispatchCandidate(
                    attempt_id=attempt.id,
                    attempt_number=attempt.attempt_number,
                    run_id=run.id,
                    dispatch_id=attempt.dispatch_id,
                    payload=cast(dict[str, object], attempt.dispatch_payload),
                    website_id=run.website_id,
                    tenant_id=run.tenant_id,
                    origin=run.origin,
                )
            )
        await self.session.flush()
        return candidates

    async def mark_dispatched(self, attempt_id: UUID) -> bool:
        pair = await self._lock_current_attempt(attempt_id)
        if pair is None:
            return False
        attempt, run = pair
        if attempt.finished_at is not None or run.phase == CrawlPhase.TERMINAL.value:
            return False
        now = await self._database_now()
        attempt.dispatch_attempted_at = attempt.dispatch_attempted_at or now
        attempt.dispatched_at = attempt.dispatched_at or now
        if run.phase == CrawlPhase.PENDING_DISPATCH.value:
            run.phase = CrawlPhase.QUEUED.value
        await self.session.flush()
        return True

    async def reject_pending_attempt(
        self,
        attempt_id: UUID,
        *,
        failure_code: CrawlFailureCode,
        failure_detail: str,
    ) -> bool:
        pair = await self._lock_current_attempt(attempt_id)
        if pair is None:
            return False
        attempt, run = pair
        if (
            attempt.finished_at is not None
            or attempt.started_at is not None
            or run.phase == CrawlPhase.TERMINAL.value
        ):
            return False
        now = await self._database_now()
        detail = failure_detail[:512]
        self._finish_records(
            attempt,
            run,
            outcome=CrawlOutcome.FAILED,
            finished_at=now,
            failure_code=failure_code.value,
            failure_detail=detail,
            result_location=None,
        )
        await self._project_job_terminal(
            attempt.dispatch_id,
            outcome=CrawlOutcome.FAILED,
            finished_at=now,
            failure_code=failure_code.value,
            failure_detail=detail,
            result_location=None,
        )
        await self.session.flush()
        return True

    async def claim_attempt(
        self,
        attempt_id: UUID,
        *,
        dispatch_id: UUID,
        lease_owner: str,
        lease_duration: timedelta,
    ) -> CrawlTask | None:
        if not lease_owner:
            raise ValueError("A crawl lease owner cannot be empty")
        if lease_duration <= timedelta(0):
            raise ValueError("A crawl lease duration must be positive")

        pair = await self._lock_current_attempt(attempt_id)
        if pair is None:
            return None
        attempt, run = pair
        if dispatch_id != attempt.dispatch_id:
            return None
        if (
            attempt.finished_at is not None
            or attempt.lease_owner is not None
            or run.phase == CrawlPhase.TERMINAL.value
            or run.phase
            not in {
                CrawlPhase.PENDING_DISPATCH.value,
                CrawlPhase.QUEUED.value,
            }
        ):
            return None

        task = CrawlTask.model_validate(attempt.dispatch_payload)
        self._validate_execution(attempt, run, task=task)

        now = await self._database_now()
        attempt.dispatch_attempted_at = attempt.dispatch_attempted_at or now
        attempt.dispatched_at = attempt.dispatched_at or now
        attempt.lease_owner = lease_owner
        attempt.lease_expires_at = now + lease_duration
        attempt.started_at = now
        run.phase = CrawlPhase.RUNNING.value
        await self.session.execute(
            sa.update(Jobs)
            .where(Jobs.id == dispatch_id)
            .values(status=Status.IN_PROGRESS.value, updated_at=now)
        )
        await self.session.flush()
        return task

    async def renew_attempt_lease(
        self,
        attempt_id: UUID,
        *,
        lease_owner: str,
        lease_duration: timedelta,
    ) -> bool:
        if lease_duration <= timedelta(0):
            raise ValueError("A crawl lease duration must be positive")
        renewed = (
            await self.session.execute(
                sa.update(CrawlAttempts)
                .where(CrawlAttempts.id == attempt_id)
                .where(CrawlAttempts.finished_at.is_(None))
                .where(CrawlAttempts.lease_owner == lease_owner)
                .where(CrawlAttempts.lease_expires_at > sa.func.now())
                .values(lease_expires_at=sa.func.now() + lease_duration)
                .returning(CrawlAttempts.dispatch_id)
            )
        ).scalar_one_or_none()
        if renewed is None:
            return False
        await self.session.execute(
            sa.update(Jobs).where(Jobs.id == renewed).values(updated_at=sa.func.now())
        )
        return True

    async def mark_finalizing(
        self,
        attempt_id: UUID,
        *,
        lease_owner: str,
    ) -> bool:
        pair = await self._lock_current_attempt(attempt_id)
        if pair is None:
            return False
        attempt, run = pair
        now = await self._database_now()
        if not self._lease_is_current(attempt, lease_owner=lease_owner, now=now):
            return False
        if run.phase != CrawlPhase.RUNNING.value:
            return False
        run.phase = CrawlPhase.FINALIZING.value
        await self.session.flush()
        return True

    async def lock_attempt_lease(
        self,
        attempt_id: UUID,
        *,
        lease_owner: str,
        expected_phase: CrawlPhase,
    ) -> bool:
        """Fence a crawl mutation to the current worker for this transaction."""
        pair = await self._lock_current_attempt(attempt_id)
        if pair is None:
            return False
        attempt, run = pair
        now = await self._database_now()
        return bool(
            run.phase == expected_phase.value
            and self._lease_is_current(
                attempt,
                lease_owner=lease_owner,
                now=now,
            )
        )

    async def finish_attempt(
        self,
        attempt_id: UUID,
        *,
        lease_owner: str,
        outcome: CrawlOutcome,
        failure_code: CrawlFailureCode | None = None,
        failure_detail: str | None = None,
        result_location: str | None = None,
        pages_crawled: int | None = None,
        files_downloaded: int | None = None,
        pages_failed: int | None = None,
        files_failed: int | None = None,
        failure_summary: dict[str, int] | None = None,
    ) -> bool:
        code = self._validate_terminal_facts(
            outcome,
            failure_code,
            failure_detail,
        )
        counters = (
            pages_crawled,
            files_downloaded,
            pages_failed,
            files_failed,
        )
        if any(value is not None and value < 0 for value in counters):
            raise ValueError("Crawl counters cannot be negative")

        pair = await self._lock_current_attempt(attempt_id)
        if pair is None:
            return False
        attempt, run = pair
        now = await self._database_now()
        if run.phase not in {
            CrawlPhase.RUNNING.value,
            CrawlPhase.FINALIZING.value,
        } or not self._lease_is_current(attempt, lease_owner=lease_owner, now=now):
            return False

        detail = failure_detail[:512] if failure_detail else None
        self._finish_records(
            attempt,
            run,
            outcome=outcome,
            finished_at=now,
            failure_code=code,
            failure_detail=detail,
            result_location=result_location,
        )
        if pages_crawled is not None:
            run.pages_crawled = pages_crawled
        if files_downloaded is not None:
            run.files_downloaded = files_downloaded
        if pages_failed is not None:
            run.pages_failed = pages_failed
        if files_failed is not None:
            run.files_failed = files_failed
        if failure_summary is not None:
            run.failure_summary = failure_summary
        await self._project_job_terminal(
            attempt.dispatch_id,
            outcome=outcome,
            finished_at=now,
            failure_code=code,
            failure_detail=detail,
            result_location=result_location,
        )
        await self.session.flush()
        return True

    async def interrupt_expired_attempts(self) -> int:
        now = await self._database_now()
        rows = (
            await self.session.execute(
                sa.select(CrawlAttempts, CrawlRunsTable)
                .join(CrawlRunsTable, CrawlRunsTable.id == CrawlAttempts.crawl_run_id)
                .where(CrawlAttempts.finished_at.is_(None))
                .where(CrawlAttempts.lease_expires_at < now)
                .where(CrawlRunsTable.phase != CrawlPhase.TERMINAL.value)
                .where(CrawlRunsTable.attempt_count == CrawlAttempts.attempt_number)
                .order_by(CrawlAttempts.lease_expires_at.asc(), CrawlAttempts.id.asc())
                .limit(LEASE_SWEEP_BATCH_SIZE)
                .with_for_update(skip_locked=True)
            )
        ).all()
        detail = "Crawler worker lease expired before completion"
        for attempt, run in rows:
            self._finish_records(
                attempt,
                run,
                outcome=CrawlOutcome.INTERRUPTED,
                finished_at=now,
                failure_code=CrawlFailureCode.LEASE_EXPIRED.value,
                failure_detail=detail,
                result_location=None,
            )
            await self._project_job_terminal(
                attempt.dispatch_id,
                outcome=CrawlOutcome.INTERRUPTED,
                finished_at=now,
                failure_code=CrawlFailureCode.LEASE_EXPIRED.value,
                failure_detail=detail,
                result_location=None,
            )
        await self.session.flush()
        return len(rows)

    async def _lock_current_attempt(
        self,
        attempt_id: UUID,
    ) -> tuple[CrawlAttempts, CrawlRunsTable] | None:
        row = (
            await self.session.execute(
                sa.select(CrawlAttempts, CrawlRunsTable)
                .join(CrawlRunsTable, CrawlRunsTable.id == CrawlAttempts.crawl_run_id)
                .where(CrawlAttempts.id == attempt_id)
                .where(CrawlRunsTable.attempt_count == CrawlAttempts.attempt_number)
                .with_for_update()
            )
        ).one_or_none()
        return (row[0], row[1]) if row is not None else None

    @staticmethod
    def _validate_execution(
        attempt: CrawlAttempts,
        run: CrawlRunsTable,
        *,
        task: CrawlTask,
    ) -> None:
        if (
            task.attempt_id != attempt.id
            or task.attempt_number != attempt.attempt_number
            or task.run_id != run.id
            or task.website_id != run.website_id
            or task.origin.value != run.origin
        ):
            raise ValueError("Crawl execution payload does not match persisted state")

    @staticmethod
    def _lease_is_current(
        attempt: CrawlAttempts,
        *,
        lease_owner: str,
        now: datetime,
    ) -> bool:
        return bool(
            attempt.finished_at is None
            and attempt.lease_owner == lease_owner
            and attempt.lease_expires_at is not None
            and attempt.lease_expires_at > now
        )

    @staticmethod
    def _validate_terminal_facts(
        outcome: CrawlOutcome,
        failure_code: CrawlFailureCode | None,
        failure_detail: str | None,
    ) -> str | None:
        code = failure_code.value if failure_code is not None else None
        if outcome in _CLEAN_OUTCOMES and (
            code is not None or failure_detail is not None
        ):
            raise ValueError("Clean crawl outcomes cannot have failure details")
        if outcome not in _CLEAN_OUTCOMES and code is None:
            raise ValueError("Non-clean crawl outcomes require a failure code")
        return code

    @staticmethod
    def _finish_records(
        attempt: CrawlAttempts,
        run: CrawlRunsTable,
        *,
        outcome: CrawlOutcome,
        finished_at: datetime,
        failure_code: str | None,
        failure_detail: str | None,
        result_location: str | None,
    ) -> None:
        attempt.finished_at = finished_at
        attempt.failure_code = failure_code
        attempt.failure_detail = failure_detail
        attempt.lease_owner = None
        attempt.lease_expires_at = None
        run.phase = CrawlPhase.TERMINAL.value
        run.outcome = outcome.value
        run.finished_at = finished_at
        run.failure_code = failure_code
        run.failure_detail = failure_detail
        run.result_location = result_location

    async def _project_job_terminal(
        self,
        dispatch_id: UUID,
        *,
        outcome: CrawlOutcome,
        finished_at: datetime,
        failure_code: str | None,
        failure_detail: str | None,
        result_location: str | None,
    ) -> None:
        successful = outcome in _SUCCESSFUL_OUTCOMES
        await self.session.execute(
            sa.update(Jobs)
            .where(Jobs.id == dispatch_id)
            .values(
                status=(Status.COMPLETE if successful else Status.FAILED).value,
                finished_at=finished_at,
                failure_code=failure_code,
                result_location=result_location if successful else failure_detail,
                updated_at=finished_at,
            )
        )

    async def _database_now(self) -> datetime:
        now = await self.session.scalar(sa.select(sa.func.now()))
        assert isinstance(now, datetime)
        return now
