# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from collections.abc import Callable
from typing import Any, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from eneo.widgets.domain.widget import BotProtection, Widget

# The widget setting each violation is about.
_VIOLATION_SETTINGS: dict[str, Callable[[Widget], Any]] = {
    "daily_token_budget_exceeds_policy": lambda widget: (
        widget.limits.daily_token_budget
    ),
    "retention_below_policy_minimum": lambda widget: widget.privacy.retention_days,
    "retention_above_policy_maximum": lambda widget: widget.privacy.retention_days,
    "bot_protection_none_not_allowed": lambda widget: widget.bot_protection,
}


class WidgetPolicy(BaseModel):
    """Tenant-wide guardrails for widgets, stored in ``tenants.widget_policy``.

    Missing keys fall back to these defaults so a tenant without an explicit
    policy still gets safe limits. The policy holds at runtime too: a widget
    saved before the policy was tightened is served within it (``serving``,
    the budget reservation and the retention job), never outside it.
    """

    model_config = ConfigDict(extra="ignore")

    max_daily_token_budget: int = Field(default=2_000_000, ge=1_000)
    allow_bot_protection_none: bool = False
    min_retention_days: int = Field(default=0, ge=0, le=3650)
    max_retention_days: int = Field(default=365, ge=0, le=3650)

    @model_validator(mode="after")
    def _retention_window(self) -> "WidgetPolicy":
        if self.min_retention_days > self.max_retention_days:
            raise ValueError("min_retention_days cannot exceed max_retention_days.")
        return self

    @classmethod
    def from_tenant(cls, raw: Optional[Mapping[str, Any]]) -> "WidgetPolicy":
        return cls.model_validate(dict(raw or {}))

    def violations(self, widget: Widget) -> list[str]:
        problems: list[str] = []
        if widget.limits.daily_token_budget > self.max_daily_token_budget:
            problems.append("daily_token_budget_exceeds_policy")
        if widget.privacy.retention_days < self.min_retention_days:
            problems.append("retention_below_policy_minimum")
        if widget.privacy.retention_days > self.max_retention_days:
            problems.append("retention_above_policy_maximum")
        if (
            widget.bot_protection == BotProtection.NONE
            and not self.allow_bot_protection_none
        ):
            problems.append("bot_protection_none_not_allowed")
        return problems

    def violations_introduced(self, before: Widget, after: Widget) -> list[str]:
        """Violations on settings that changed between ``before`` and ``after``.

        An edit is answerable for the values it sets. A violation left
        standing on a setting it did not change (the policy was tightened
        after the widget was saved) does not block it; the widget is served
        within the policy regardless.
        """
        return [
            code
            for code in self.violations(after)
            if _VIOLATION_SETTINGS[code](after) != _VIOLATION_SETTINGS[code](before)
        ]

    def daily_token_budget_for(self, widget: Widget) -> int:
        return min(widget.limits.daily_token_budget, self.max_daily_token_budget)

    def retention_days_for(self, retention_days: int) -> int:
        """How long the retention job keeps a widget's conversations."""
        return min(
            max(retention_days, self.min_retention_days), self.max_retention_days
        )

    def bot_protection_for(self, widget: Widget) -> BotProtection:
        if (
            widget.bot_protection == BotProtection.NONE
            and not self.allow_bot_protection_none
        ):
            return BotProtection.ALTCHA
        return widget.bot_protection

    def serving(self, widget: Widget) -> Widget:
        """The widget as the visitor surface serves it.

        A copy with the budget capped, a challenge required where the policy
        forbids ``none``, and retention cut to the policy maximum. The
        minimum is left to the retention job: the policy can make a widget
        keep less, never start storing conversations it was set not to store.
        """
        return widget.model_copy(
            update={
                "limits": widget.limits.model_copy(
                    update={"daily_token_budget": self.daily_token_budget_for(widget)}
                ),
                "privacy": widget.privacy.model_copy(
                    update={
                        "retention_days": min(
                            widget.privacy.retention_days, self.max_retention_days
                        )
                    }
                ),
                "bot_protection": self.bot_protection_for(widget),
            },
            deep=True,
        )
