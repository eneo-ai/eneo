"""The readback after a restore: when retention may be called complete.

Every step of every required task must finish a pass that started, in this
readback, after the newest removal anywhere: a removal can make other work due
(a removed question can leave its session empty).
"""

from collections.abc import Mapping
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from eneo.data_retention.application.retention_readback import (
    RetentionReadback,
    RetentionReadbackFailed,
)
from eneo.data_retention.application.retention_runner import (
    RetentionRunReport,
    RetentionStepPass,
)
from eneo.data_retention.domain.retention import (
    RetentionErrorCode,
    RetentionJobOutcome,
    RetentionKeyset,
)

SUCCEEDED = RetentionJobOutcome.SUCCEEDED
PARTIAL = RetentionJobOutcome.PARTIAL
HISTORY = "conversations.history"
SESSIONS = "sessions.empty"
STEPS = {HISTORY: ("questions", "app_runs"), SESSIONS: ("sessions",)}
NOT_DUE = {
    HISTORY: frozenset({"no_longer_due"}),
    SESSIONS: frozenset({"no_longer_due"}),
}

FINISHED = RetentionStepPass(started_at=None, ended_at=None, finished=True)
NOT_REACHED = None


def at(day: int) -> RetentionKeyset:
    return RetentionKeyset(at=datetime(2026, 1, day, tzinfo=timezone.utc), id=uuid4())


def begun(position: RetentionKeyset) -> RetentionStepPass:
    return RetentionStepPass(started_at=None, ended_at=position, finished=False)


def resumed(
    start: RetentionKeyset, end: RetentionKeyset | None = None
) -> RetentionStepPass:
    return RetentionStepPass(started_at=start, ended_at=end, finished=end is None)


def run(
    task: str = HISTORY,
    outcome: RetentionJobOutcome | None = SUCCEEDED,
    *,
    disposed: int = 0,
    blocked: Mapping[str, int] | None = None,
    error_code: RetentionErrorCode | None = None,
    **steps: RetentionStepPass | None,
) -> RetentionRunReport:
    passes = {name: steps.get(name, FINISHED) for name in STEPS[task]}
    return RetentionRunReport(
        task=task,
        job_run_id=uuid4() if outcome is not None else None,
        outcome=outcome,
        blocked=blocked or {},
        error_code=error_code,
        disposed={f"{STEPS[task][0]}.deleted": disposed} if disposed else {},
        steps=passes if outcome is not None else {},
        not_due=NOT_DUE[task],
    )


def test_a_fresh_finished_pass_of_every_step_completes() -> None:
    readback = RetentionReadback([HISTORY, SESSIONS])

    assert readback.add_round([run(HISTORY), run(SESSIONS)]) is True


def test_a_removal_needs_another_pass_of_every_step() -> None:
    readback = RetentionReadback([HISTORY, SESSIONS])

    assert readback.add_round([run(HISTORY, disposed=2), run(SESSIONS)]) is False
    assert readback.add_round([run(HISTORY), run(SESSIONS)]) is True


def test_a_removal_late_in_a_round_restarts_the_earlier_tasks() -> None:
    readback = RetentionReadback([HISTORY, SESSIONS])

    assert readback.add_round([run(HISTORY), run(SESSIONS, disposed=1)]) is False
    assert readback.add_round([run(HISTORY), run(SESSIONS)]) is True


def test_a_pass_resumed_from_the_restored_cursor_does_not_count() -> None:
    readback = RetentionReadback([HISTORY])

    # Rows before the restored cursor were not read in this readback.
    assert readback.add_round([run(questions=resumed(at(3)))]) is False
    assert readback.add_round([run()]) is True


def test_a_step_that_was_never_reached_keeps_the_readback_open() -> None:
    readback = RetentionReadback([HISTORY])

    assert readback.add_round([run(outcome=PARTIAL, app_runs=NOT_REACHED)]) is False
    assert readback.add_round([run()]) is True


def test_a_population_larger_than_one_execution_completes_over_several_runs() -> None:
    readback = RetentionReadback([HISTORY])
    first, second = at(1), at(2)

    assert (
        readback.add_round(
            [run(outcome=PARTIAL, questions=begun(first), app_runs=NOT_REACHED)]
        )
        is False
    )
    assert (
        readback.add_round(
            [
                run(
                    outcome=PARTIAL,
                    questions=resumed(first, second),
                    app_runs=NOT_REACHED,
                )
            ]
        )
        is False
    )
    assert readback.add_round([run(questions=resumed(second))]) is True


def test_a_removal_within_a_pass_spoils_that_pass() -> None:
    readback = RetentionReadback([HISTORY])
    first = at(1)

    assert readback.add_round([run(outcome=PARTIAL, questions=begun(first))]) is False
    assert readback.add_round([run(questions=resumed(first), disposed=1)]) is False
    assert readback.add_round([run()]) is True


def test_a_round_in_which_nothing_moves_fails() -> None:
    readback = RetentionReadback([HISTORY])
    first = at(1)

    assert readback.add_round([run(outcome=PARTIAL, questions=begun(first))]) is False
    with pytest.raises(RetentionReadbackFailed, match="no progress"):
        readback.add_round(
            [
                run(
                    outcome=PARTIAL,
                    questions=resumed(first, first),
                    app_runs=RetentionStepPass(
                        started_at=None, ended_at=None, finished=False
                    ),
                )
            ]
        )


def test_a_step_starved_by_a_repeating_finished_step_fails() -> None:
    readback = RetentionReadback([HISTORY])
    first = at(1)

    # The questions pass spends each execution's budget; app_runs never runs.
    assert (
        readback.add_round(
            [run(outcome=PARTIAL, questions=begun(first), app_runs=NOT_REACHED)]
        )
        is False
    )
    assert (
        readback.add_round(
            [run(outcome=PARTIAL, questions=resumed(first), app_runs=NOT_REACHED)]
        )
        is False
    )
    assert (
        readback.add_round(
            [run(outcome=PARTIAL, questions=begun(first), app_runs=NOT_REACHED)]
        )
        is False
    )
    with pytest.raises(
        RetentionReadbackFailed, match=f"{HISTORY}.app_runs: no progress"
    ):
        readback.add_round(
            [run(outcome=PARTIAL, questions=resumed(first), app_runs=NOT_REACHED)]
        )


def test_a_missing_report_fails() -> None:
    readback = RetentionReadback([HISTORY, SESSIONS])

    with pytest.raises(RetentionReadbackFailed, match=f"{SESSIONS}: no report"):
        readback.add_round([run(HISTORY)])


@pytest.mark.parametrize(
    ("outcome", "error_code", "reason"),
    [
        (None, None, "held by another execution"),
        (
            RetentionJobOutcome.SKIPPED,
            RetentionErrorCode.DISABLED_BY_DEPLOYMENT_SETTING,
            "disabled_by_deployment_setting",
        ),
        (
            RetentionJobOutcome.SKIPPED,
            RetentionErrorCode.CLAIM_TIMEOUT,
            "claim_timeout",
        ),
        (RetentionJobOutcome.FAILED, RetentionErrorCode.CHUNK_FAILED, "chunk_failed"),
        (PARTIAL, RetentionErrorCode.CHUNK_TIMEOUT, "chunk_timeout"),
        (PARTIAL, RetentionErrorCode.CHUNK_DEADLOCK, "chunk_deadlock"),
        (RetentionJobOutcome.SUPERSEDED, None, "superseded"),
        (
            RetentionJobOutcome.RUNNING,
            RetentionErrorCode.FINISH_TIMEOUT,
            "finish_timeout",
        ),
    ],
)
def test_an_execution_that_did_not_finish_cleanly_fails(
    outcome: RetentionJobOutcome | None,
    error_code: RetentionErrorCode | None,
    reason: str,
) -> None:
    readback = RetentionReadback([HISTORY])

    with pytest.raises(RetentionReadbackFailed, match=reason):
        readback.add_round([run(outcome=outcome, error_code=error_code)])


@pytest.mark.parametrize(
    "blocked",
    [
        "questions.root_locked",
        "questions.unit_exceeds_budget",
        "sessions.root_locked",
        "files.files_locked",
        "questions.a_reason_added_later",
    ],
)
def test_blocked_work_fails(blocked: str) -> None:
    readback = RetentionReadback([HISTORY])

    with pytest.raises(RetentionReadbackFailed, match=blocked):
        readback.add_round([run(blocked={blocked: 1})])


@pytest.mark.parametrize(
    "task,not_due",
    [(HISTORY, "questions.no_longer_due"), (SESSIONS, "sessions.no_longer_due")],
)
def test_work_that_is_not_due_does_not_fail(task: str, not_due: str) -> None:
    readback = RetentionReadback([task])

    assert readback.add_round([run(task, blocked={not_due: 3})]) is True


def test_a_reason_another_task_declares_as_not_due_still_fails() -> None:
    """Mutant: the readback accepts a not-due reason by name across tasks, so
    one task's declaration excuses another task's blocked work."""
    readback = RetentionReadback([HISTORY])

    with pytest.raises(RetentionReadbackFailed, match="files_not_old_enough"):
        readback.add_round([run(blocked={"questions.files_not_old_enough": 1})])


def test_every_failure_of_a_round_is_named() -> None:
    readback = RetentionReadback([HISTORY, SESSIONS])

    with pytest.raises(RetentionReadbackFailed) as failed:
        readback.add_round([run(HISTORY, blocked={"questions.root_locked": 1})])
    assert [reason.split(":")[0] for reason in failed.value.reasons] == [
        HISTORY,
        SESSIONS,
    ]


def test_each_task_keeps_its_own_not_due_reasons() -> None:
    """Which blocked reasons of each registered task the readback accepts as
    work that is not due. Pinned per task, so moving the declaration does not
    change the readback's verdict.

    Mutant: a task accepts a reason it never reports as not due, or loses one."""
    from sqlalchemy.ext.asyncio import AsyncSession

    from eneo.main.config import get_settings
    from eneo.main.retention_tasks import retention_task_registrations

    assert {
        registration.name: registration.build(AsyncSession()).not_due_keys
        for registration in retention_task_registrations(get_settings())
    } == {
        "conversations.history": {"no_longer_due"},
        "conversations.derived_copies": {"no_longer_due"},
        "sessions.empty": {"no_longer_due"},
        "files.unused": {"files_not_old_enough"},
        "retention.jobs": set(),
    }
