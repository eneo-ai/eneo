# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.


from typing import Any, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from eneo.widgets.domain.widget import BotProtection, Widget


class WidgetPolicy(BaseModel):
    """Tenant-wide guardrails for widgets, stored in ``tenants.widget_policy``.

    Missing keys fall back to these defaults so a tenant without an explicit
    policy still gets safe limits.
    """

    model_config = ConfigDict(extra="ignore")

    max_active_widgets: int = Field(default=5, ge=0, le=1000)
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
