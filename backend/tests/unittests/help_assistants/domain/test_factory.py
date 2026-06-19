from datetime import datetime, timezone
from uuid import uuid4

from intric.help_assistants.domain.assignment_history import AssignmentHistory
from intric.help_assistants.domain.assignment_history_reason import (
    AssignmentHistoryReason,
)
from intric.help_assistants.domain.factory import HelperAssistantsFactory
from intric.help_assistants.domain.helper_kind import HelperKind
from intric.help_assistants.domain.helper_run import HelperRun
from intric.help_assistants.domain.helper_run_status import HelperRunStatus
from intric.help_assistants.domain.role_assignment import RoleAssignment


def test_create_role_assignment_returns_entity_with_db_defaults_blank():
    factory = HelperAssistantsFactory()
    org_space_id = uuid4()
    assistant_id = uuid4()
    user_id = uuid4()

    role = factory.create_role_assignment(
        org_space_id=org_space_id,
        kind=HelperKind.PROMPT_GUIDE,
        assistant_id=assistant_id,
        created_by_user_id=user_id,
    )

    assert isinstance(role, RoleAssignment)
    assert role.org_space_id == org_space_id
    assert role.kind == HelperKind.PROMPT_GUIDE
    assert role.assistant_id == assistant_id
    assert role.is_enabled is True
    assert role.is_visible_to_users is True
    assert role.created_by_user_id == user_id
    assert role.updated_by_user_id is None
    assert role.created_at is None
    assert role.updated_at is None


def test_create_role_assignment_round_trips_db_columns():
    factory = HelperAssistantsFactory()
    row_id = uuid4()
    now = datetime(2026, 5, 21, 12, 0, tzinfo=timezone.utc)

    role = factory.create_role_assignment(
        id=row_id,
        org_space_id=uuid4(),
        kind=HelperKind.PROMPT_GUIDE,
        assistant_id=uuid4(),
        is_enabled=False,
        is_visible_to_users=False,
        created_at=now,
        updated_at=now,
    )

    assert role.id == row_id
    assert role.is_enabled is False
    assert role.is_visible_to_users is False
    assert role.created_at == now
    assert role.updated_at == now


def test_create_assignment_history_entry_returns_entity():
    factory = HelperAssistantsFactory()
    org_space_id = uuid4()
    old_assistant_id = uuid4()
    new_assistant_id = uuid4()
    actor_id = uuid4()

    entry = factory.create_assignment_history_entry(
        org_space_id=org_space_id,
        kind=HelperKind.PROMPT_GUIDE,
        assistant_id=old_assistant_id,
        assistant_name_snapshot="Prompt Guide",
        replaced_by_assistant_id=new_assistant_id,
        reason=AssignmentHistoryReason.REASSIGNED,
        actor_user_id=actor_id,
    )

    assert isinstance(entry, AssignmentHistory)
    assert entry.org_space_id == org_space_id
    assert entry.kind == HelperKind.PROMPT_GUIDE
    assert entry.assistant_id == old_assistant_id
    assert entry.assistant_name_snapshot == "Prompt Guide"
    assert entry.replaced_by_assistant_id == new_assistant_id
    assert entry.reason == AssignmentHistoryReason.REASSIGNED
    assert entry.actor_user_id == actor_id
    assert entry.replaced_at is None


def test_create_helper_run_defaults_to_in_progress_and_no_completed_at():
    factory = HelperAssistantsFactory()
    tenant_id = uuid4()
    org_space_id = uuid4()
    helper_id = uuid4()
    target_id = uuid4()
    session_id = uuid4()
    actor_id = uuid4()

    run = factory.create_helper_run(
        tenant_id=tenant_id,
        org_space_id=org_space_id,
        kind=HelperKind.PROMPT_GUIDE,
        assistant_id=helper_id,
        target_type="assistant",
        target_id=target_id,
        session_id=session_id,
        actor_user_id=actor_id,
    )

    assert isinstance(run, HelperRun)
    assert run.tenant_id == tenant_id
    assert run.org_space_id == org_space_id
    assert run.kind == HelperKind.PROMPT_GUIDE
    assert run.assistant_id == helper_id
    assert run.target_type == "assistant"
    assert run.target_id == target_id
    assert run.session_id == session_id
    assert run.actor_user_id == actor_id
    assert run.status == HelperRunStatus.IN_PROGRESS
    assert run.completed_at is None


def test_create_helper_run_round_trips_db_columns():
    factory = HelperAssistantsFactory()
    row_id = uuid4()
    completed = datetime(2026, 5, 21, 12, 0, tzinfo=timezone.utc)

    run = factory.create_helper_run(
        id=row_id,
        tenant_id=uuid4(),
        org_space_id=uuid4(),
        kind=HelperKind.PROMPT_GUIDE,
        assistant_id=None,
        target_type="assistant",
        target_id=uuid4(),
        session_id=uuid4(),
        actor_user_id=None,
        status=HelperRunStatus.COMPLETED,
        completed_at=completed,
        created_at=completed,
        updated_at=completed,
    )

    assert run.id == row_id
    assert run.assistant_id is None
    assert run.actor_user_id is None
    assert run.status == HelperRunStatus.COMPLETED
    assert run.completed_at == completed
