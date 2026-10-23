from eneo.data_retention.domain.retention import (
    RetentionBudget,
    RetentionUsage,
    retention_summary,
)


def test_budget_is_spent_by_any_limit() -> None:
    """Kills ignoring a row, file or elapsed-time execution limit."""
    budget = RetentionBudget(rows=10, files=5, seconds=60)

    assert budget.left(RetentionUsage(rows=4, files=1), elapsed_seconds=1) == (
        RetentionUsage(rows=6, files=4)
    )
    for used, elapsed in ((RetentionUsage(rows=10), 1), (RetentionUsage(files=5), 1)):
        assert budget.left(used, elapsed_seconds=elapsed) == RetentionUsage()
    assert budget.left(RetentionUsage(), elapsed_seconds=60) == RetentionUsage()


def test_the_audit_summary_names_every_nonzero_count() -> None:
    """Kills a summary that lists zero counts, drops a count or a blocked
    reason, puts a number before a plural noun ("deleted 1 questions"), shows
    a raw key, or omits the empty case."""
    assert retention_summary(
        {"questions_deleted": 1, "app_runs_deleted": 0, "by_space_rule": 12},
        {"root_locked": 1, "files_locked": 2, "unit_exceeds_budget": 0},
    ) == ("questions deleted 1, by space rule 12; kept 1 root locked, 2 files locked")
    # A run's blocked keys carry their step.
    assert retention_summary({}, {"questions.cascade_locked": 1}) == (
        "kept 1 questions cascade locked"
    )
    assert retention_summary({}, {}) == "nothing deleted"
