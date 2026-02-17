from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from intric.authentication.auth_models import (
    ApiKeyNotificationPolicyResponse,
    ApiKeyNotificationPreferencesResponse,
    ApiKeyNotificationSubscription,
    ApiKeyNotificationTargetType,
)
from intric.database.tables.settings_table import Settings
from intric.users.user import UserInDB

_API_KEY_NOTIFICATIONS_BUCKET = "api_key_notifications"
_SETTINGS_ID_COL: Any = getattr(Settings, "id")
_SETTINGS_USER_ID_COL: Any = getattr(Settings, "user_id")
_SETTINGS_CHATBOT_WIDGET_COL: Any = getattr(Settings, "chatbot_widget")


def _as_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return cast(dict[str, Any], value)
    return {}


def _as_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return cast(list[Any], value)
    return []


def _notification_policy_for_user(user: UserInDB) -> ApiKeyNotificationPolicyResponse:
    tenant = getattr(user, "tenant", None)
    tenant_api_key_policy = getattr(tenant, "api_key_policy", None)
    tenant_policy = _as_json_object(tenant_api_key_policy)
    raw_policy = _as_json_object(tenant_policy.get("notification_policy"))
    return ApiKeyNotificationPolicyResponse.model_validate(raw_policy)


def _normalize_days_against_policy(
    days: list[int], policy: ApiKeyNotificationPolicyResponse
) -> list[int]:
    max_days = policy.max_days_before_expiry
    normalized = sorted(set(days), reverse=True)
    if max_days is not None:
        normalized = [day for day in normalized if day <= max_days]

    if normalized:
        return normalized

    fallback = sorted(set(policy.default_days_before_expiry), reverse=True)
    if max_days is not None:
        fallback = [day for day in fallback if day <= max_days]
    return fallback or [1]


def _default_preferences_from_policy(
    policy: ApiKeyNotificationPolicyResponse,
) -> ApiKeyNotificationPreferencesResponse:
    return ApiKeyNotificationPreferencesResponse(
        enabled=False,
        days_before_expiry=_normalize_days_against_policy(
            policy.default_days_before_expiry,
            policy,
        ),
        auto_follow_published_assistants=False,
        auto_follow_published_apps=False,
    )


def _normalize_preferences(
    raw_preferences: Any,
    policy: ApiKeyNotificationPolicyResponse,
) -> ApiKeyNotificationPreferencesResponse:
    fallback = _default_preferences_from_policy(policy)
    if not isinstance(raw_preferences, dict):
        return fallback

    try:
        parsed = ApiKeyNotificationPreferencesResponse.model_validate(raw_preferences)
    except ValueError:
        return fallback

    return ApiKeyNotificationPreferencesResponse(
        enabled=parsed.enabled and policy.enabled,
        days_before_expiry=_normalize_days_against_policy(
            parsed.days_before_expiry,
            policy,
        ),
        auto_follow_published_assistants=(
            parsed.auto_follow_published_assistants
            and policy.allow_auto_follow_published_assistants
        ),
        auto_follow_published_apps=(
            parsed.auto_follow_published_apps
            and policy.allow_auto_follow_published_apps
        ),
    )


def _normalize_subscriptions(
    raw_subscriptions: Any,
) -> list[ApiKeyNotificationSubscription]:
    raw_items = _as_json_list(raw_subscriptions)
    if not raw_items:
        return []

    deduped: dict[tuple[str, UUID], ApiKeyNotificationSubscription] = {}
    for raw_item in raw_items:
        item = _as_json_object(raw_item)
        if not item:
            continue
        raw_target_type = item.get("target_type")
        raw_target_id = item.get("target_id")
        if not isinstance(raw_target_type, str):
            continue

        if isinstance(raw_target_id, UUID):
            target_id = raw_target_id
        elif isinstance(raw_target_id, str):
            try:
                target_id = UUID(raw_target_id)
            except ValueError:
                continue
        else:
            continue

        try:
            target_type = ApiKeyNotificationTargetType(raw_target_type)
        except ValueError:
            continue
        subscription = ApiKeyNotificationSubscription(
            target_type=target_type,
            target_id=target_id,
        )
        deduped[(subscription.target_type.value, subscription.target_id)] = subscription

    return sorted(
        deduped.values(),
        key=lambda subscription: (
            subscription.target_type.value,
            str(subscription.target_id),
        ),
    )


def _should_auto_follow(
    *,
    preferences: ApiKeyNotificationPreferencesResponse,
    policy: ApiKeyNotificationPolicyResponse,
    target_type: ApiKeyNotificationTargetType,
) -> bool:
    if not preferences.enabled or not policy.enabled:
        return False
    if target_type == ApiKeyNotificationTargetType.ASSISTANT:
        return (
            policy.allow_auto_follow_published_assistants
            and preferences.auto_follow_published_assistants
        )
    if target_type == ApiKeyNotificationTargetType.APP:
        return (
            policy.allow_auto_follow_published_apps
            and preferences.auto_follow_published_apps
        )
    return False


async def auto_follow_on_publish(
    *,
    session: AsyncSession,
    user: UserInDB,
    target_type: ApiKeyNotificationTargetType,
    target_id: UUID,
) -> bool:
    """Auto-follow published assistant/app when tenant policy and user prefs allow it."""
    if target_type not in (
        ApiKeyNotificationTargetType.ASSISTANT,
        ApiKeyNotificationTargetType.APP,
    ):
        return False

    policy = _notification_policy_for_user(user)
    user_id = user.id
    row_query = (
        sa.select(_SETTINGS_ID_COL, _SETTINGS_CHATBOT_WIDGET_COL)
        .where(_SETTINGS_USER_ID_COL == user_id)
        .order_by(Settings.updated_at.desc())
        .limit(1)
    )
    row = (await session.execute(row_query)).first()
    if row is None:
        return False

    settings_id = cast(UUID, row[0])
    existing_widget = _as_json_object(row[1])
    bucket = _as_json_object(existing_widget.get(_API_KEY_NOTIFICATIONS_BUCKET))

    preferences = _normalize_preferences(bucket.get("preferences"), policy)
    if not _should_auto_follow(
        preferences=preferences,
        policy=policy,
        target_type=target_type,
    ):
        return False

    subscriptions = _normalize_subscriptions(bucket.get("subscriptions"))
    key = (target_type.value, target_id)
    existing_keys = {
        (subscription.target_type.value, subscription.target_id)
        for subscription in subscriptions
    }
    if key in existing_keys:
        return False

    subscriptions.append(
        ApiKeyNotificationSubscription(target_type=target_type, target_id=target_id)
    )
    subscriptions = sorted(
        subscriptions,
        key=lambda subscription: (
            subscription.target_type.value,
            str(subscription.target_id),
        ),
    )

    updated_widget: dict[str, Any] = dict(existing_widget)
    updated_widget[_API_KEY_NOTIFICATIONS_BUCKET] = {
        "preferences": preferences.model_dump(mode="json"),
        "subscriptions": [
            subscription.model_dump(mode="json") for subscription in subscriptions
        ],
        "auto_followed_at": datetime.now(timezone.utc).isoformat(),
    }

    await session.execute(
        sa.update(Settings)
        .where(_SETTINGS_ID_COL == settings_id)
        .values(chatbot_widget=updated_widget)
    )

    return True
