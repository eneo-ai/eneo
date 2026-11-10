"""When retention may be called complete: the readback after a restore.

The readback runs every registered task, round after round, with the workers
stopped. It is complete when every step of every required task has finished a
pass that began, in this readback, after the newest removal anywhere. A
removal can make other work due (a removed question can leave its session
empty), and a pass that resumed a cursor from before the readback never read
the rows before it, so neither counts.

Anything that leaves due work in place fails it at once: a task without a
report (it raised), a claim another execution holds, an execution that did not
end as succeeded or partial, an error, or blocked work. A blocked reason the
task declares as not due (any longer, or yet) does not.

Every round runs against the time the readback started, with traffic and
workers stopped, so nothing falls due under it and every pass ends, and a
round without progress fails: no removal, no unfinished step moved, and either
nothing moved at all or a finished step ran another whole pass meanwhile
(the budget then never reaches the steps after it).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from eneo.data_retention.application.retention_runner import RetentionRunReport
from eneo.data_retention.domain.retention import RetentionJobOutcome

_ENDED = frozenset({RetentionJobOutcome.SUCCEEDED, RetentionJobOutcome.PARTIAL})


class RetentionReadbackFailed(Exception):
    def __init__(self, reasons: Sequence[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = tuple(reasons)


@dataclass(slots=True)
class _StepPasses:
    # The run in which the current pass began; None for one resumed from
    # before the readback.
    begun: int | None = None
    # The run in which the newest finished pass began.
    finished_from: int | None = None


class RetentionReadback:
    def __init__(self, required: Iterable[str]) -> None:
        self._required = tuple(required)
        self._steps: dict[str, tuple[str, ...]] = {}
        self._passes: dict[tuple[str, str], _StepPasses] = {}
        self._runs = 0
        self._last_removal = 0

    def add_round(self, reports: Sequence[RetentionRunReport]) -> bool:
        """Take one round of reports; True once retention is complete."""
        reasons = self._failures(reports)
        if reasons:
            raise RetentionReadbackFailed(reasons)
        covered_before = {key for key in self._passes if self._covered(key)}
        removed = advanced = moved = repeated = False
        for report in reports:
            self._runs += 1
            if any(report.disposed.values()):
                self._last_removal = self._runs
                removed = True
            self._steps[report.task] = tuple(report.steps)
            for step, done in report.steps.items():
                if done is None:
                    continue
                passes = self._passes.setdefault((report.task, step), _StepPasses())
                if done.started_at is None:
                    passes.begun = self._runs
                if done.finished:
                    passes.finished_from, passes.begun = passes.begun, None
                if not done.finished and done.ended_at == done.started_at:
                    continue
                if (report.task, step) in covered_before:
                    moved = True
                    repeated = repeated or done.finished
                else:
                    advanced = True

        open_steps = [
            f"{task}.{step}"
            for task in self._required
            for step in self._steps.get(task, ())
            if not self._covered((task, step))
        ]
        if not open_steps:
            return True
        if not removed and not advanced and (repeated or not moved):
            raise RetentionReadbackFailed(
                [f"{step}: no progress" for step in open_steps]
            )
        return False

    def _covered(self, key: tuple[str, str]) -> bool:
        passes = self._passes.get(key)
        return (
            passes is not None
            and passes.finished_from is not None
            and passes.finished_from > self._last_removal
        )

    def _failures(self, reports: Sequence[RetentionRunReport]) -> list[str]:
        by_task = {report.task: report for report in reports}
        reasons: list[str] = []
        for name in self._required:
            report = by_task.get(name)
            if report is None:
                reasons.append(f"{name}: no report; the task raised, see the log")
                continue
            if report.outcome is None:
                reasons.append(f"{name}: held by another execution; stop the workers")
                continue
            if report.outcome not in _ENDED or report.error_code is not None:
                ending = report.outcome.value
                if report.error_code is not None:
                    ending += f" ({report.error_code.value})"
                reasons.append(f"{name}: {ending}")
            blocked = sorted(
                f"{key} {count}"
                for key, count in report.blocked.items()
                if count and key.rpartition(".")[2] not in report.not_due
            )
            if blocked:
                reasons.append(f"{name}: blocked {', '.join(blocked)}")
        return reasons
