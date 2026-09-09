"""Domain errors of the insights chat.

Registered in ``eneo.server.exception_handlers.DOMAIN_EXCEPTION_MAP``; the
``code`` attribute is what the client branches on.
"""


class InsightsModelUnavailableError(Exception):
    """No accessible, tool-capable completion model for the target's space."""

    code = "insights_model_unavailable"

    def __init__(self) -> None:
        super().__init__(
            "No completion model with tool calling is available in this space. "
            "Add one to the space or enable tool calling on the assistant's model."
        )


class InvalidTimezoneError(Exception):
    """The request named a timezone that is not an IANA zone."""

    code = "invalid_timezone"

    def __init__(self, timezone: str) -> None:
        super().__init__(f"Unknown timezone '{timezone}'.")
