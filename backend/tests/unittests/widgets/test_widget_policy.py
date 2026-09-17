from uuid import uuid4

import pytest

from eneo.widgets.domain.widget import (
    BotProtection,
    Widget,
    WidgetLimits,
    WidgetPrivacy,
)
from eneo.widgets.domain.widget_policy import WidgetPolicy


def _widget() -> Widget:
    return Widget.create(
        tenant_id=uuid4(), space_id=uuid4(), target_id=uuid4(), name="w"
    )


def test_defaults_apply_when_tenant_has_no_policy():
    policy = WidgetPolicy.from_tenant(None)
    assert policy.max_daily_token_budget == 2_000_000
    assert policy.allow_bot_protection_none is False
    assert (policy.min_retention_days, policy.max_retention_days) == (0, 365)


def test_unknown_keys_are_ignored_and_window_is_validated():
    # Keys from older policies (the removed active-widget ceiling) are ignored.
    policy = WidgetPolicy.from_tenant({"max_active_widgets": 2, "legacy": True})
    assert policy.max_daily_token_budget == 2_000_000
    with pytest.raises(ValueError):
        WidgetPolicy.from_tenant({"min_retention_days": 10, "max_retention_days": 5})


def test_violations_report_each_breached_guardrail():
    policy = WidgetPolicy(
        max_daily_token_budget=1_000_000, min_retention_days=7, max_retention_days=30
    )
    widget = _widget()
    assert policy.violations(widget) == []

    widget.limits = WidgetLimits(daily_token_budget=2_000_000)
    widget.privacy = WidgetPrivacy(retention_days=0)
    widget.bot_protection = BotProtection.NONE
    assert policy.violations(widget) == [
        "daily_token_budget_exceeds_policy",
        "retention_below_policy_minimum",
        "bot_protection_none_not_allowed",
    ]

    widget.privacy = WidgetPrivacy(retention_days=90)
    assert "retention_above_policy_maximum" in policy.violations(widget)
