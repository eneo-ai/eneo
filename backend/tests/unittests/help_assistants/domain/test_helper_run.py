from datetime import datetime, timezone
from uuid import uuid4

import pytest

from intric.help_assistants.domain.helper_kind import HelperKind
from intric.help_assistants.domain.helper_run import HelperRun
from intric.help_assistants.domain.helper_run_status import HelperRunStatus


def _make_run(**overrides: object) -> HelperRun:
    defaults: dict[str, object] = {
        "id": None,
        "tenant_id": uuid4(),
        "org_space_id": uuid4(),
        "kind": HelperKind.PROMPT_GUIDE,
        "assistant_id": uuid4(),
        "target_type": "assistant",
        "target_id": uuid4(),
        "session_id": uuid4(),
        "actor_user_id": uuid4(),
    }
    defaults.update(overrides)
    return HelperRun(**defaults)  # type: ignore[arg-type]


def test_new_run_defaults_to_in_progress_with_no_completed_at():
    run = _make_run()

    assert run.status == HelperRunStatus.IN_PROGRESS
    assert run.completed_at is None


@pytest.mark.parametrize(
    "transition, expected_status",
    [
        ("mark_completed", HelperRunStatus.COMPLETED),
        ("mark_abandoned", HelperRunStatus.ABANDONED),
        ("mark_failed", HelperRunStatus.FAILED),
    ],
)
def test_terminal_transitions_set_status_and_stamp_completed_at(
    transition: str, expected_status: HelperRunStatus
) -> None:
    run = _make_run()
    fixed = datetime(2026, 5, 21, 12, 0, tzinfo=timezone.utc)

    getattr(run, transition)(completed_at=fixed)

    assert run.status == expected_status
    assert run.completed_at == fixed


def test_terminal_transition_defaults_completed_at_to_now_utc():
    run = _make_run()
    before = datetime.now(timezone.utc)

    run.mark_completed()

    assert run.status == HelperRunStatus.COMPLETED
    assert run.completed_at is not None
    assert run.completed_at >= before
    assert run.completed_at.tzinfo is not None


def test_status_value_matches_db_string():
    assert HelperRunStatus.IN_PROGRESS.value == "in_progress"
    assert HelperRunStatus.COMPLETED.value == "completed"
    assert HelperRunStatus.ABANDONED.value == "abandoned"
    assert HelperRunStatus.FAILED.value == "failed"
