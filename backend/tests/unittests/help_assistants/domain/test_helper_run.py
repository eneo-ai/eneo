from uuid import uuid4

from eneo.help_assistants.domain.helper_kind import HelperKind
from eneo.help_assistants.domain.helper_run import HelperRun
from eneo.help_assistants.domain.helper_run_status import HelperRunStatus


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


def test_status_value_matches_db_string():
    # Terminal transitions are owned by HelperRunService.set_status (a
    # conditional UPDATE) so they stay atomic; the entity only holds state.
    assert HelperRunStatus.IN_PROGRESS.value == "in_progress"
    assert HelperRunStatus.COMPLETED.value == "completed"
    assert HelperRunStatus.ABANDONED.value == "abandoned"
    assert HelperRunStatus.FAILED.value == "failed"
