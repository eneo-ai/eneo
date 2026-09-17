# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from typing import Optional


class WidgetPublicError(Exception):
    """Error on the anonymous widget surface.

    Rendered as ``{"detail": {"code", "message"}}`` with the given status and
    headers so the embed page can branch on ``code`` (re-mint, re-solve,
    show paused state, back off) without parsing prose.
    """

    status_code: int = 400
    code: str = "bad_request"

    def __init__(
        self,
        message: str,
        *,
        code: Optional[str] = None,
        status_code: Optional[int] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.headers = headers


class WidgetNotActiveError(WidgetPublicError):
    status_code = 404
    code = "widget_not_active"

    def __init__(self, message: str = "Widget is not available.") -> None:
        super().__init__(message)


class ChallengeInvalidError(WidgetPublicError):
    status_code = 400
    code = "challenge_invalid"


class VisitorTokenInvalidError(WidgetPublicError):
    status_code = 401
    code = "visitor_token_invalid"

    def __init__(self, message: str = "Visitor token is invalid.") -> None:
        super().__init__(message)


class VisitorTokenStaleError(WidgetPublicError):
    """The token was valid for an earlier configuration generation."""

    status_code = 401
    code = "visitor_token_stale"

    def __init__(self, message: str = "Visitor token is no longer valid.") -> None:
        super().__init__(message)


class WidgetRateLimitedError(WidgetPublicError):
    status_code = 429

    def __init__(self, code: str, *, retry_after: int, message: str) -> None:
        super().__init__(
            message, code=code, headers={"Retry-After": str(max(1, retry_after))}
        )
        self.retry_after = retry_after


class WidgetBudgetExhaustedError(WidgetPublicError):
    status_code = 429
    code = "budget_exhausted"

    def __init__(self, *, retry_after: int) -> None:
        super().__init__(
            "The widget's daily budget is exhausted.",
            headers={"Retry-After": str(max(1, retry_after))},
        )
        self.retry_after = retry_after


class WidgetProtectionUnavailableError(WidgetPublicError):
    status_code = 503
    code = "rate_limit_unavailable"

    def __init__(self) -> None:
        super().__init__(
            "Widget protection is temporarily unavailable.",
            headers={"Retry-After": "30"},
        )
