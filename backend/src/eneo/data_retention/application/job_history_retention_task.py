"""Execution history follows the deployment's audit retention policy."""

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.application.retention_runner import (
    RetentionBatch,
    RetentionStep,
    RetentionStepResult,
)
from eneo.data_retention.application.retention_units import RetentionEffects
from eneo.data_retention.infrastructure.retention_job_run_repo import (
    RetentionJobRunRepository,
)

JOB_HISTORY_TASK = "retention.jobs"


class JobHistoryRetentionTask:
    name = JOB_HISTORY_TASK
    count_keys = frozenset({"job_runs_deleted"})
    observation_keys = frozenset({"job_runs_examined"})
    blocked_keys: frozenset[str] = frozenset()

    def __init__(self, session: AsyncSession) -> None:
        self.repository = RetentionJobRunRepository(session)

    def steps(self) -> Sequence[RetentionStep]:
        return (RetentionStep("history", self._history, max_files=0),)

    async def _history(self, batch: RetentionBatch) -> RetentionStepResult:
        out = RetentionEffects()
        # Every admitted row reserves both its discovery and its deletion.
        limit = batch.rows // 2
        if limit == 0:
            return out.result(rows=0, exhausted=False, deferred=True)
        result = await self.repository.prune_after_audit_retention(limit=limit)
        out.add(None, "job_runs_examined", result.examined)
        out.add(None, "job_runs_deleted", result.deleted)
        return out.result(
            rows=result.examined + result.deleted,
            exhausted=result.examined < limit,
        )
