# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from typing import Any, Optional


class WidgetPublicError(Exception):
    """A widget error the client branches on by ``code``.

    Rendered as ``{"detail": {"code", "message", **details()}}`` with the
    given status and headers so the embed page and the admin page can act on
    it (re-mint, re-solve, show paused state, back off, mark a field) without
    parsing prose.
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

    def details(self) -> dict[str, Any]:
        """Machine-readable fields rendered next to ``code`` and ``message``."""
        return {}


class AssistantPublishedAsWidgetError(Exception):
    """An active or paused widget serves the assistant from its space."""


class WidgetNotActiveError(WidgetPublicError):
    status_code = 404
    code = "widget_not_active"

    def __init__(self, message: str = "Widget is not available.") -> None:
        super().__init__(message)


class WidgetRevisionConflictError(WidgetPublicError):
    status_code = 409
    code = "widget_revision_conflict"

    def __init__(self) -> None:
        super().__init__("Widget changed. Reload it before saving your changes.")


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


class WidgetFieldLockedError(WidgetPublicError):
    """An update touched a part of the widget its template governs."""

    status_code = 400
    code = "field_locked_by_template"

    def __init__(self, fields: list[str]) -> None:
        super().__init__(
            "These parts are governed by the widget's template: "
            + ", ".join(fields)
            + ". Detach the template to change them."
        )
        self.fields = fields


class WidgetTemplateInUseError(WidgetPublicError):
    status_code = 409
    code = "template_in_use"

    def __init__(self, linked_widgets: int) -> None:
        super().__init__(
            f"The template is followed by {linked_widgets} widget(s)."
            " Detach them before deleting it."
        )
        self.linked_widgets = linked_widgets


class WidgetTemplateNotPublishedError(WidgetPublicError):
    status_code = 400
    code = "template_not_published"

    def __init__(self) -> None:
        super().__init__(
            "The template has not been published yet; publish it before"
            " widgets can follow it."
        )


class WidgetTemplateLocksUnenforceableError(WidgetPublicError):
    """The template's locks could not be written onto its followers as saved."""

    status_code = 400
    code = "template_locks_unenforceable"

    def __init__(self, violations: list[str]) -> None:
        super().__init__(
            "Template locks cannot be enforced: " + ", ".join(violations) + "."
        )
        self.violations = violations

    def details(self) -> dict[str, Any]:
        return {"violations": list(self.violations)}


class WidgetPolicyViolationError(WidgetPublicError):
    """The widget's settings are outside the organisation's widget policy."""

    status_code = 400
    code = "widget_policy_violation"

    def __init__(self, violations: list[str]) -> None:
        super().__init__(
            "The widget's settings are outside the organisation's widget policy: "
            + ", ".join(violations)
            + "."
        )
        self.violations = violations

    def details(self) -> dict[str, Any]:
        return {"violations": list(self.violations)}


class WidgetServingBlockedError(WidgetPublicError):
    """The widget cannot serve visitors as configured: activation was refused,
    or an edit would leave an active widget unable to serve."""

    status_code = 400
    code = "widget_serving_blocked"

    def __init__(self, blockers: list[str]) -> None:
        super().__init__(
            "The widget cannot serve visitors like this: " + ", ".join(blockers) + "."
        )
        self.blockers = blockers

    def details(self) -> dict[str, Any]:
        return {"blockers": list(self.blockers)}
