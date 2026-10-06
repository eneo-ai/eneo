"""Constants for data retention policies."""

# Retention period limits (in days)
MIN_RETENTION_DAYS = 1
MAX_RETENTION_DAYS = 2555  # ~7 years, Swedish statute of limitations
DEFAULT_AUDIT_RETENTION_DAYS = 365  # Swedish Arkivlagen default
DEFAULT_CONVERSATION_RETENTION_DAYS = 90  # Default for conversation data

# Session cleanup
ORPHANED_SESSION_CLEANUP_DAYS = 1  # Delete sessions without questions after 1 day

# One selected root and one aggregate cascade-proof row, before deletion.
CONVERSATION_UNIT_OVERHEAD_ROWS = 2

# Recommended minimum retention for compliance
RECOMMENDED_MIN_AUDIT_DAYS = 90
RECOMMENDED_MIN_CONVERSATION_DAYS = 30


def validate_conversation_unit_budget(*, unit_rows: int, execution_rows: int) -> None:
    if unit_rows + CONVERSATION_UNIT_OVERHEAD_ROWS > execution_rows:
        raise ValueError(
            "RETENTION_CHATS_MAX_UNIT_ROWS plus discovery/proof rows must not "
            "exceed the resolved conversation execution row budget."
        )


def validate_retention_days(days: int, context: str = "retention") -> int:
    """
    Validate retention period is within allowed range.

    Args:
        days: Number of days to retain data
        context: Context for error message (e.g., "audit", "conversation")

    Returns:
        Validated retention days

    Raises:
        ValueError: If days is outside valid range
    """
    if days < MIN_RETENTION_DAYS:
        raise ValueError(
            f"Minimum {context} retention period is {MIN_RETENTION_DAYS} day"
        )

    if days > MAX_RETENTION_DAYS:
        raise ValueError(
            f"Maximum {context} retention period is {MAX_RETENTION_DAYS} days "
            f"(~7 years, Swedish statute of limitations)"
        )

    return days
