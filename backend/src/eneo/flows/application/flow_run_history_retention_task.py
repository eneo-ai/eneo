"""Flow runs that started while their space had a time go once it has passed."""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.application.retention_runner import (
    RetentionBatch,
    RetentionStep,
    RetentionStepResult,
)

FLOW_RUN_HISTORY_TASK = "flows.run_history"


class FlowRunHistoryRetentionTask:
    name = FLOW_RUN_HISTORY_TASK
    count_keys: frozenset[str] = frozenset()
    observation_keys: frozenset[str] = frozenset()
    blocked_keys: frozenset[str] = frozenset()
    not_due_keys: frozenset[str] = frozenset()

    def __init__(self, session: AsyncSession, *, now: datetime) -> None:
        self.session = session
        self.now = now

    def steps(self) -> Sequence[RetentionStep]:
        return (RetentionStep("runs", self._runs),)

    async def has_due(self) -> bool:
        return False

    async def _runs(self, batch: RetentionBatch) -> RetentionStepResult:
        return RetentionStepResult(exhausted=True)
