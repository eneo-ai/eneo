from __future__ import annotations

import inspect
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.application.conversation_history_retention_task import (
    CONVERSATION_HISTORY_TASK,
    ConversationHistoryRetentionTask,
)
from eneo.data_retention.application.conversation_retention import (
    conversation_page_allocation,
)
from eneo.data_retention.application.retention_runner import RetentionRunReport
from eneo.data_retention.domain.retention import RetentionBudget, RetentionJobOutcome
from eneo.data_retention.infrastructure import retention_tasks, retention_worker
from eneo.flows.application.builder_client_error_retention_task import (
    BUILDER_CLIENT_ERROR_TASK,
    BuilderClientErrorRetentionTask,
)
from eneo.flows.application.flow_housekeeping_task import (
    FLOWS_HOUSEKEEPING_TASK,
    FlowHousekeepingTask,
)
from eneo.flows.application.flow_run_history_retention_task import (
    FlowRunHistoryRetentionTask,
)
from eneo.flows.domain.flow_run_retention_policy import FLOWS_HISTORY_TASK


class _Runner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    async def run(self, task: Any) -> RetentionRunReport:
        self.calls.append(("run", task))
        return RetentionRunReport(
            task=task.name, job_run_id=None, outcome=RetentionJobOutcome.SUCCEEDED
        )

    async def skip(self, task: str) -> RetentionRunReport:
        self.calls.append(("skip", task))
        return RetentionRunReport(
            task=task, job_run_id=None, outcome=RetentionJobOutcome.SKIPPED
        )


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.asyncio
async def test_nightly_run_executes_an_enabled_task_and_records_a_disabled_one(
    monkeypatch: pytest.MonkeyPatch, enabled: bool, test_settings
) -> None:
    runner = _Runner()
    settings = test_settings.model_copy(
        update={
            "retention_flows_housekeeping_enabled": enabled,
            "retention_flows_history_enabled": not enabled,
            "retention_chats_history_enabled": enabled,
            "retention_builder_client_errors_enabled": not enabled,
            "retention_chats_max_unit_rows": 100_001,
            "retention_max_family_rows": 4096,
        }
    )
    monkeypatch.setattr(retention_worker, "get_settings", lambda: settings)
    budgets: list[RetentionBudget] = []

    def build_runner(*, session, container, settings, budget: RetentionBudget):
        budgets.append(budget)
        return runner

    monkeypatch.setattr(retention_worker, "retention_runner", build_runner)
    async with AsyncSession() as session:
        container = SimpleNamespace(session=lambda: session)
        reports = await inspect.unwrap(retention_worker.run_retention)(
            container=container
        )

    # Kills a global-budget handoff: the chat builder also rejects its smaller cap.
    assert [budget.rows for budget in budgets] == [50_000, 50_000, 250_000, 50_000]
    from eneo.worker.arq import WorkerSettings

    # Kills retaining either legacy scheduler beside the shared engine.
    scheduled = [job.coroutine.__name__ for job in WorkerSettings["cron_jobs"]]
    assert scheduled.count("run_retention") == 1
    assert not {"cleanup_old_data", "purge_old_conversations"}.intersection(scheduled)

    assert [report.task for report in reports] == [
        FLOWS_HOUSEKEEPING_TASK,
        FLOWS_HISTORY_TASK,
        CONVERSATION_HISTORY_TASK,
        BUILDER_CLIENT_ERROR_TASK,
    ]
    [(first, housekeeping), (second, history), (third, chats), (fourth, errors)] = (
        runner.calls
    )
    if enabled:
        assert first == "run" and isinstance(housekeeping, FlowHousekeepingTask)
        # Kills Q01: ignore the worker's resolved operator snapshot for admission.
        assert housekeeping.steps()[0].max_batch == 4096
        # The emergency switch never stops gallring silently.
        assert (second, history) == ("skip", FLOWS_HISTORY_TASK)
        assert third == "run" and isinstance(chats, ConversationHistoryRetentionTask)
        assert (fourth, errors) == ("skip", BUILDER_CLIENT_ERROR_TASK)
    else:
        assert (first, housekeeping) == ("skip", FLOWS_HOUSEKEEPING_TASK)
        assert second == "run" and isinstance(history, FlowRunHistoryRetentionTask)
        assert history.steps()[0].max_batch == 4096
        assert (third, chats) == ("skip", CONVERSATION_HISTORY_TASK)
        assert fourth == "run" and isinstance(errors, BuilderClientErrorRetentionTask)
    # Kills G1b-H01: omit reporting metadata or include a disabled reporter.
    assert retention_tasks.overdue_retention_tasks(settings) == (
        (FLOWS_HISTORY_TASK,) if not enabled else (CONVERSATION_HISTORY_TASK,)
    )


@pytest.mark.parametrize(("family_rows", "accepted"), [(10_000, True), (10_001, False)])
def test_the_family_cap_never_exceeds_one_executions_budget(
    test_settings, family_rows, accepted
) -> None:
    # Default budgets: 50 000 rows and 10 000 files per execution.
    values = {**test_settings.model_dump(), "retention_max_family_rows": family_rows}
    if accepted:
        assert type(test_settings).model_validate(values).retention_max_family_rows == (
            family_rows
        )
    else:
        with pytest.raises(ValueError, match="RETENTION_MAX_FAMILY_ROWS"):
            type(test_settings).model_validate(values)


@pytest.mark.parametrize(
    "execution_rows,unit_rows,resolved_rows,accepted,allocation_accepted",
    [
        pytest.param(250_000, 5000, 250_000, True, True, id="default"),
        pytest.param(5002, 5000, 5002, True, True, id="exact-fit"),
        pytest.param(5001, 5000, 5001, False, False, id="missing-proof-row"),
        pytest.param(250_000, 100_001, 250_000, True, True, id="larger-operator-unit"),
        pytest.param(250_000, 100_001, 50_000, True, False, id="wrong-resolved-budget"),
    ],
)
def test_conversation_unit_cap_reserves_discovery_and_proof(
    test_settings,
    execution_rows: int,
    unit_rows: int,
    resolved_rows: int,
    accepted: bool,
    allocation_accepted: bool,
) -> None:
    """Kills C01 missing proof allowance and C15 using a smaller resolved budget."""
    values = {
        **test_settings.model_dump(),
        "retention_chats_max_rows_per_run": execution_rows,
        "retention_chats_max_unit_rows": unit_rows,
    }
    if accepted:
        type(test_settings).model_validate(values)
    else:
        with pytest.raises(ValueError, match="RETENTION_CHATS_MAX_UNIT_ROWS"):
            type(test_settings).model_validate(values)
    if allocation_accepted:
        conversation_page_allocation(
            unit_rows=unit_rows, chunk_rows=500, execution_rows=resolved_rows
        )
    else:
        with pytest.raises(ValueError, match="RETENTION_CHATS_MAX_UNIT_ROWS"):
            conversation_page_allocation(
                unit_rows=unit_rows, chunk_rows=500, execution_rows=resolved_rows
            )
