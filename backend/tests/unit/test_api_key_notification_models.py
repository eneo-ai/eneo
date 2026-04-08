from __future__ import annotations

import pytest

from intric.authentication.auth_models import (
    ApiKeyNotificationPolicyResponse,
    ApiKeyNotificationPolicyUpdate,
    normalize_notification_day_value,
    normalize_notification_policy_payload,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (30, 30),
        ("14", 14),
        ([30, 14, 7], 30),
        ([14, "7", 1.0], 14),
    ],
)
def test_normalize_notification_day_value_accepts_positive_values(raw, expected):
    assert normalize_notification_day_value(raw, default=21) == expected


@pytest.mark.parametrize("raw", [0, -1, "0", "abc", [], None, False, 1.5])
def test_normalize_notification_day_value_falls_back_for_invalid_values(raw):
    assert normalize_notification_day_value(raw, default=21) == 21


def test_normalize_notification_policy_payload_clamps_legacy_default_to_max():
    normalized = normalize_notification_policy_payload(
        {
            "enabled": True,
            "default_days_before_expiry": [30, 14, 7],
            "max_days_before_expiry": 14,
        }
    )

    assert normalized["default_days_before_expiry"] == 14
    assert normalized["max_days_before_expiry"] == 14


def test_notification_policy_models_reject_default_above_max():
    with pytest.raises(ValueError):
        ApiKeyNotificationPolicyResponse.model_validate(
            {
                "enabled": True,
                "default_days_before_expiry": 30,
                "max_days_before_expiry": 14,
            }
        )

    with pytest.raises(ValueError):
        ApiKeyNotificationPolicyUpdate.model_validate(
            {
                "default_days_before_expiry": 30,
                "max_days_before_expiry": 14,
            }
        )
