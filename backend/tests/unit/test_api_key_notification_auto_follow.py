from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from intric.authentication.api_key_notification_auto_follow import (
    _normalize_preferences,
    _normalize_subscriptions,
    _should_auto_follow,
)
from intric.authentication.auth_models import (
    ApiKeyNotificationPolicyResponse,
    ApiKeyNotificationTargetType,
)


def _policy(
    **overrides,
) -> ApiKeyNotificationPolicyResponse:
    payload = {
        "enabled": True,
        "default_days_before_expiry": [30, 14, 7, 3, 1],
        "max_days_before_expiry": 90,
        "allow_auto_follow_published_assistants": True,
        "allow_auto_follow_published_apps": True,
    }
    payload.update(overrides)
    return ApiKeyNotificationPolicyResponse.model_validate(payload)


def test_normalize_preferences_applies_policy_bounds_and_flags():
    policy = _policy(
        max_days_before_expiry=30,
        allow_auto_follow_published_assistants=True,
        allow_auto_follow_published_apps=False,
    )
    raw = {
        "enabled": True,
        "days_before_expiry": [120, 30, 14, 1],
        "auto_follow_published_assistants": True,
        "auto_follow_published_apps": True,
    }

    normalized = _normalize_preferences(raw, policy)

    assert normalized.enabled is True
    assert normalized.days_before_expiry == [30, 14, 1]
    assert normalized.auto_follow_published_assistants is True
    assert normalized.auto_follow_published_apps is False


def test_normalize_preferences_defaults_to_opt_out_when_missing():
    policy = _policy(default_days_before_expiry=[45, 20], max_days_before_expiry=40)

    normalized = _normalize_preferences(None, policy)

    assert normalized.enabled is False
    assert normalized.days_before_expiry == [20]
    assert normalized.auto_follow_published_assistants is False
    assert normalized.auto_follow_published_apps is False


def test_normalize_subscriptions_dedupes_invalid_and_duplicate_items():
    assistant_id = uuid4()
    raw = [
        {"target_type": "assistant", "target_id": str(assistant_id)},
        {"target_type": "assistant", "target_id": str(assistant_id)},
        {"target_type": "invalid", "target_id": "not-a-uuid"},
        {"target_type": "app", "target_id": str(uuid4())},
    ]

    items = _normalize_subscriptions(raw)

    assert len(items) == 2
    assert items[0].target_type.value in {"app", "assistant"}
    assert items[1].target_type.value in {"app", "assistant"}


@pytest.mark.parametrize(
    "target_type,expected",
    [
        (ApiKeyNotificationTargetType.ASSISTANT, True),
        (ApiKeyNotificationTargetType.APP, False),
        (ApiKeyNotificationTargetType.SPACE, False),
    ],
)
def test_should_auto_follow_honors_target_specific_flags(target_type, expected):
    policy = _policy(
        allow_auto_follow_published_assistants=True,
        allow_auto_follow_published_apps=False,
    )
    preferences = SimpleNamespace(
        enabled=True,
        auto_follow_published_assistants=True,
        auto_follow_published_apps=True,
    )

    assert (
        _should_auto_follow(
            preferences=preferences,
            policy=policy,
            target_type=target_type,
        )
        is expected
    )


def test_should_auto_follow_requires_policy_and_preference_enabled():
    policy = _policy(enabled=False)
    preferences = SimpleNamespace(
        enabled=True,
        auto_follow_published_assistants=True,
        auto_follow_published_apps=True,
    )

    assert (
        _should_auto_follow(
            preferences=preferences,
            policy=policy,
            target_type=ApiKeyNotificationTargetType.ASSISTANT,
        )
        is False
    )
