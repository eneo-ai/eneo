"""The count names an administrator reads, per task; frozen once released."""

from eneo.data_retention.application.conversation_history_retention_task import (
    ConversationHistoryRetentionTask,
)
from eneo.data_retention.application.empty_session_retention_task import (
    EmptySessionRetentionTask,
)
from eneo.data_retention.application.job_history_retention_task import (
    JobHistoryRetentionTask,
)
from eneo.files.unused_file_retention_task import UnusedFileRetentionTask


def test_each_adopter_declares_its_released_vocabulary() -> None:
    """The release freeze: these names are in released audit events and job
    rows, so a change to any of them must be deliberate and fail here first.

    Mutants: a File kept in its own state (in use, missing, not a root) is
    audited as blocked; a tenant mismatch blocks a conversation that was
    deleted; the same File reason gets a different name in another task; the
    conversation release reports a File age it never checks."""
    tasks = (
        ConversationHistoryRetentionTask,
        EmptySessionRetentionTask,
        UnusedFileRetentionTask,
        JobHistoryRetentionTask,
    )
    assert [
        (task.count_keys, task.observation_keys, task.blocked_keys) for task in tasks
    ] == [
        (
            {
                "questions_deleted",
                "app_runs_deleted",
                "sessions_deleted",
                "files_deleted",
                "by_assistant_or_app_rule",
                "by_space_rule",
                "by_organization_rule",
            },
            {
                "owners_examined",
                "files_in_use",
                "files_missing",
                "files_not_root",
                "files_tenant_mismatch",
            },
            {
                "unit_exceeds_budget",
                "no_longer_due",
                "root_locked",
                "cascade_locked",
                "files_locked",
                "files_family_exceeds_budget",
            },
        ),
        ({"sessions_deleted"}, {"sessions_examined"}, {"no_longer_due"}),
        (
            {"roots_deleted", "files_deleted", "file_dependencies_deleted"},
            {"files_in_use", "files_missing", "files_not_root"},
            {
                "files_not_old_enough",
                "files_tenant_mismatch",
                "files_locked",
                "files_family_exceeds_budget",
                "files_insufficient_budget",
            },
        ),
        ({"job_runs_deleted"}, {"job_runs_examined"}, set()),
    ]
