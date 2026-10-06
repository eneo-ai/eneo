from __future__ import annotations

import inspect
from types import SimpleNamespace
from typing import Any

import pytest

from eneo.data_retention.application.conversation_retention import (
    conversation_page_allocation,
)
from eneo.data_retention.application.retention_runner import RetentionRunReport
from eneo.data_retention.domain.retention import RetentionJobOutcome
from eneo.data_retention.infrastructure import retention_tasks, retention_worker
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
            "gallring_flows_housekeeping_enabled": enabled,
            "retention_flows_history_enabled": not enabled,
        }
    )
    monkeypatch.setattr(retention_worker, "get_settings", lambda: settings)
    monkeypatch.setattr(retention_worker, "retention_runner", lambda **_: runner)
    container = SimpleNamespace(session=lambda: object())

    reports = await inspect.unwrap(retention_worker.run_retention)(container=container)

    [(first, housekeeping), (second, history)] = runner.calls
    if enabled:
        assert first == "run" and isinstance(housekeeping, FlowHousekeepingTask)
        # The emergency switch never stops gallring silently.
        assert (second, history) == ("skip", FLOWS_HISTORY_TASK)
    else:
        assert (first, housekeeping) == ("skip", FLOWS_HOUSEKEEPING_TASK)
        assert second == "run" and isinstance(history, FlowRunHistoryRetentionTask)
    # Kills G1b-H01: omit reporting metadata or include a disabled reporter.
    assert retention_tasks.overdue_retention_tasks(settings) == (
        (FLOWS_HISTORY_TASK,) if not enabled else ()
    )
    # Registration order: staging data first, then run history.
    assert [report.task for report in reports] == [
        FLOWS_HOUSEKEEPING_TASK,
        FLOWS_HISTORY_TASK,
    ]


@pytest.mark.parametrize(("family_rows", "accepted"), [(10_000, True), (10_001, False)])
def test_the_family_cap_never_exceeds_one_executions_budget(
    test_settings, family_rows, accepted
) -> None:
    # Default budgets: 50 000 rows and 10 000 files per execution.
    values = {**test_settings.model_dump(), "gallring_max_family_rows": family_rows}
    if accepted:
        assert type(test_settings).model_validate(values).gallring_max_family_rows == (
            family_rows
        )
    else:
        with pytest.raises(ValueError, match="GALLRING_MAX_FAMILY_ROWS"):
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
