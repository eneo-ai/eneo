from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from intric.authentication.api_key_notification_repo import (
    ApiKeyNotificationRepository,
)
from intric.authentication.auth_models import (
    ApiKeyNotificationPolicyResponse,
    ApiKeyNotificationPreferencesResponse,
    ApiKeyNotificationSubscription,
    ApiKeyNotificationSubscriptionSource,
    ApiKeyNotificationTargetType,
    normalize_notification_day_value,
    normalize_notification_policy_payload,
)
from intric.users.user import UserInDB


def _as_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return cast(dict[str, Any], value)
    return {}


def _notification_policy_for_user(user: UserInDB) -> ApiKeyNotificationPolicyResponse:
    tenant = getattr(user, "tenant", None)
    tenant_api_key_policy = getattr(tenant, "api_key_policy", None)
    tenant_policy = _as_json_object(tenant_api_key_policy)
    raw_policy = _as_json_object(tenant_policy.get("notification_policy"))
    return ApiKeyNotificationPolicyResponse.model_validate(
        normalize_notification_policy_payload(raw_policy)
    )


def _normalize_days_against_policy(
    days: object, policy: ApiKeyNotificationPolicyResponse
) -> int:
    normalized = normalize_notification_day_value(
        days, default=policy.default_days_before_expiry
    )
    if normalized is None:
        normalized = policy.default_days_before_expiry
    if policy.max_days_before_expiry is not None:
        normalized = min(normalized, policy.max_days_before_expiry)
    return normalized


def _default_preferences_from_policy(
    policy: ApiKeyNotificationPolicyResponse,
) -> ApiKeyNotificationPreferencesResponse:
    return ApiKeyNotificationPreferencesResponse(
        enabled=False,
        days_before_expiry=_normalize_days_against_policy(
            policy.default_days_before_expiry, policy
        ),
        auto_follow_published_assistants=False,
        auto_follow_published_apps=False,
    )


def _normalize_preferences(  # pyright: ignore[reportUnusedFunction]
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
    repo = ApiKeyNotificationRepository(session=session)
    preferences = await repo.get_preferences(user.id)
    if preferences is None:
        preferences = _default_preferences_from_policy(policy)
    if not _should_auto_follow(
        preferences=preferences,
        policy=policy,
        target_type=target_type,
    ):
        return False

    return await repo.add_subscription(
        user_id=user.id,
        subscription=ApiKeyNotificationSubscription(
            target_type=target_type,
            target_id=target_id,
        ),
        source=ApiKeyNotificationSubscriptionSource.AUTO_FOLLOW,
    )
