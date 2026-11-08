"""Constants for data retention policies."""

# The days any retention period may be set to: a technical sanity bound, not a
# legal one. Every retention field validates against it.
MIN_RETENTION_DAYS = 1
MAX_RETENTION_DAYS = 2555


def validate_retention_days(days: int, context: str = "retention") -> int:
    """Return days when they are within the bound, else raise ValueError."""
    if days < MIN_RETENTION_DAYS:
        raise ValueError(
            f"Minimum {context} retention period is {MIN_RETENTION_DAYS} day"
        )
    if days > MAX_RETENTION_DAYS:
        raise ValueError(
            f"Maximum {context} retention period is {MAX_RETENTION_DAYS} days"
        )
    return days


# The least a conversation root costs: its discovery row and its own DELETE.
# Child rows, examined by the bounded proof, and Files work come on top.
CONVERSATION_UNIT_OVERHEAD_ROWS = 2


def validate_conversation_unit_budget(*, unit_rows: int, execution_rows: int) -> None:
    if unit_rows + CONVERSATION_UNIT_OVERHEAD_ROWS > execution_rows:
        raise ValueError(
            "RETENTION_CONVERSATIONS_MAX_UNIT_ROWS plus the discovery and root rows must fit "
            "RETENTION_CONVERSATIONS_MAX_ROWS_PER_RUN."
        )
