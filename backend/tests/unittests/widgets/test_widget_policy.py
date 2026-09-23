from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from eneo.widgets.domain.widget import (
    BotProtection,
    Widget,
    WidgetLimits,
    WidgetPrivacy,
)
from eneo.widgets.domain.widget_policy import WidgetPolicy
from eneo.widgets.infrastructure.widget_repo_impl import WidgetRepoImpl
from eneo.widgets.presentation.widget_models import WidgetPolicyUpdate


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


def test_violations_introduced_are_the_ones_on_changed_settings():
    policy = WidgetPolicy(max_daily_token_budget=100_000)
    saved = _widget()
    saved.limits = WidgetLimits(daily_token_budget=500_000)

    # Tightened after the save: an unrelated edit, even to another limit,
    # is not held to the budget it did not touch.
    edited = saved.model_copy(deep=True)
    edited.name = "Ny"
    edited.limits = WidgetLimits(daily_token_budget=500_000, max_session_turns=5)
    assert policy.violations(edited) == ["daily_token_budget_exceeds_policy"]
    assert policy.violations_introduced(saved, edited) == []

    # Setting the budget answers for it, even when it moves toward the cap.
    edited.limits = WidgetLimits(daily_token_budget=400_000)
    assert policy.violations_introduced(saved, edited) == [
        "daily_token_budget_exceeds_policy"
    ]
    edited.limits = WidgetLimits(daily_token_budget=100_000)
    assert policy.violations_introduced(saved, edited) == []


def test_serving_holds_a_widget_saved_before_the_policy_to_it():
    policy = WidgetPolicy(
        max_daily_token_budget=100_000,
        allow_bot_protection_none=False,
        min_retention_days=30,
        max_retention_days=60,
    )
    widget = _widget()
    widget.limits = WidgetLimits(daily_token_budget=500_000)
    widget.privacy = WidgetPrivacy(retention_days=365)
    widget.bot_protection = BotProtection.NONE

    served = policy.serving(widget)
    assert served.limits.daily_token_budget == 100_000
    assert served.privacy.retention_days == 60
    assert served.bot_protection == BotProtection.ALTCHA
    # The configuration itself is untouched.
    assert widget.limits.daily_token_budget == 500_000
    assert widget.privacy.retention_days == 365
    assert widget.bot_protection == BotProtection.NONE

    # The minimum never makes a widget store what it was set not to store;
    # it only stops the retention job from deleting early.
    widget.privacy = WidgetPrivacy(retention_days=0)
    assert policy.serving(widget).privacy.never_persists
    assert policy.retention_days_for(0) == 30
    assert policy.retention_days_for(45) == 45
    assert policy.retention_days_for(365) == 60

    permissive = WidgetPolicy(allow_bot_protection_none=True)
    assert permissive.serving(widget).bot_protection == BotProtection.NONE
    assert permissive.serving(widget).limits.daily_token_budget == 500_000


async def test_the_serving_view_is_never_written_back():
    widget = _widget()
    widget.id = uuid4()
    served = WidgetPolicy(max_daily_token_budget=1_000).serving(widget)
    assert served.is_serving_view
    assert served.model_copy().is_serving_view
    assert not widget.is_serving_view

    session = AsyncMock()
    with pytest.raises(ValueError, match="never written back"):
        await WidgetRepoImpl(session).update(served)
    session.scalar.assert_not_called()


def test_token_budgets_stay_within_the_usage_counters():
    """The daily usage counters are int4: a larger budget would fail every
    admission with a 503 instead of being refused when it is saved."""
    WidgetLimits(daily_token_budget=2_000_000_000)
    WidgetPolicy(max_daily_token_budget=2_000_000_000)
    for build in (
        lambda: WidgetLimits(daily_token_budget=2_000_000_001),
        lambda: WidgetPolicy(max_daily_token_budget=2_000_000_001),
        lambda: WidgetPolicyUpdate(max_daily_token_budget=2_000_000_001),
    ):
        with pytest.raises(ValidationError):
            build()
