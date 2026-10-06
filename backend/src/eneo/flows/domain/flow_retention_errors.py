"""Typed failures of Flow retention diagnostics and explicit deletion."""


class FlowRetentionStatusUnavailableError(Exception):
    """Status reads failed; a partial count must never look healthy."""

    code = "retention_status_unavailable"

    def __init__(self) -> None:
        super().__init__("Retention status is temporarily unavailable. Retry shortly.")


class FlowRetentionPurgeUnavailableError(Exception):
    """A bounded purge timed out; its request transaction has rolled back."""

    code = "retention_purge_unavailable"

    def __init__(self) -> None:
        super().__init__("Retention purge timed out. Retry shortly.")
