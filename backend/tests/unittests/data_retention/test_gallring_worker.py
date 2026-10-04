from __future__ import annotations

import inspect
from types import SimpleNamespace
from typing import Any

import pytest

from eneo.data_retention.application.gallring_runner import GallringRunReport
from eneo.data_retention.domain.gallring import GallringJobOutcome
from eneo.data_retention.infrastructure import gallring_worker
from eneo.flows.application.flow_housekeeping_task import (
    FLOWS_HOUSEKEEPING_TASK,
    FlowHousekeepingTask,
)


class _Runner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    async def run(self, task: Any) -> GallringRunReport:
        self.calls.append(("run", task))
        return GallringRunReport(
            task=task.name, job_run_id=None, outcome=GallringJobOutcome.SUCCEEDED
        )

    async def skip(self, task: str) -> GallringRunReport:
        self.calls.append(("skip", task))
        return GallringRunReport(
            task=task, job_run_id=None, outcome=GallringJobOutcome.SKIPPED
        )


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.asyncio
async def test_nightly_run_executes_an_enabled_task_and_records_a_disabled_one(
    monkeypatch: pytest.MonkeyPatch, enabled: bool
) -> None:
    runner = _Runner()
    settings = SimpleNamespace(gallring_flows_housekeeping_enabled=enabled)
    monkeypatch.setattr(gallring_worker, "get_settings", lambda: settings)
    monkeypatch.setattr(gallring_worker, "gallring_runner", lambda **_: runner)
    container = SimpleNamespace(session=lambda: object())

    reports = await inspect.unwrap(gallring_worker.run_gallring)(container=container)

    [(kind, target)] = runner.calls
    if enabled:
        assert kind == "run" and isinstance(target, FlowHousekeepingTask)
    else:
        # The emergency switch never stops gallring silently.
        assert (kind, target) == ("skip", FLOWS_HOUSEKEEPING_TASK)
    assert [report.task for report in reports] == [FLOWS_HOUSEKEEPING_TASK]


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
