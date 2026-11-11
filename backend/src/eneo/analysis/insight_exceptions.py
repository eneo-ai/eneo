"""Domain errors of the insights chat.

Registered in ``eneo.server.exception_handlers.DOMAIN_EXCEPTION_MAP``; the
``code`` attribute is what the client branches on.
"""


class InsightsModelUnavailableError(Exception):
    """No accessible, tool-capable completion model that meets the security
    classification of the target's space."""

    code = "insights_model_unavailable"

    def __init__(self) -> None:
        super().__init__(
            "No completion model that supports tool calling and meets this "
            "space's security classification is available in this space."
        )


class InvalidTimezoneError(Exception):
    """The request named a timezone that is not an IANA zone."""

    code = "invalid_timezone"

    def __init__(self, timezone: str) -> None:
        super().__init__(f"Unknown timezone '{timezone}'.")
