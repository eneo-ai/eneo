from eneo.data_retention.domain.retention import RetentionBudget, RetentionUsage


def test_budget_is_spent_by_any_limit() -> None:
    """Kills ignoring a row, file or elapsed-time execution limit."""
    budget = RetentionBudget(rows=10, files=5, seconds=60)

    assert budget.left(RetentionUsage(rows=4, files=1), elapsed_seconds=1) == (
        RetentionUsage(rows=6, files=4)
    )
    for used, elapsed in ((RetentionUsage(rows=10), 1), (RetentionUsage(files=5), 1)):
        assert budget.left(used, elapsed_seconds=elapsed) == RetentionUsage()
    assert budget.left(RetentionUsage(), elapsed_seconds=60) == RetentionUsage()
