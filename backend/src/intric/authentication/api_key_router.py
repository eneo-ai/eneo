from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from intric.authentication.api_key_lifecycle import ApiKeyLifecycleService
from intric.authentication.api_key_policy import ApiKeyPolicyService
from intric.authentication.api_key_resolver import ApiKeyValidationError
from intric.authentication.api_key_router_helpers import (
    build_api_key_usage_page,
    build_api_key_usage_summary,
    error_responses,
    extract_audit_context,
    paginate_keys,
    raise_api_key_http_error,
)
from intric.authentication.api_key_v2_repo import ApiKeysV2Repository
from intric.authentication.auth_dependencies import require_api_key_permission
from intric.authentication.auth_models import (
    ApiKeyCreateRequest,
    ApiKeyCreatedResponse,
    ApiKeyCreationConstraints,
    ApiKeyListResponse,
    ApiKeyNotificationPolicyResponse,
    ApiKeyNotificationPreferencesResponse,
    ApiKeyNotificationPreferencesUpdate,
    ApiKeyNotificationSubscription,
    ApiKeyNotificationSubscriptionListResponse,
    ApiKeyNotificationTargetType,
    ApiKeyPermission,
    ApiKeyScopeType,
    ApiKeyState,
    ApiKeyStateChangeRequest,
    ApiKeyType,
    ApiKeyUpdateRequest,
    ApiKeyUsageResponse,
    ApiKeyV2,
    ApiKeyV2InDB,
    ExpiringKeySummaryItem,
    ExpiringKeysSummary,
)
from intric.database.tables.settings_table import Settings
from intric.main.container.container import Container
from intric.server.dependencies.container import get_container
from intric.roles.permissions import Permission
from intric.users.user import UserInDB

router = APIRouter(tags=["API Keys"])

_API_KEY_EXAMPLE = {
    "id": "3cbf5fde-7288-4f03-bf06-f71c14f76854",
    "name": "Production Backend",
    "description": "Used by backend workers",
    "key_type": "sk_",
    "permission": "write",
    "scope_type": "space",
    "scope_id": "11111111-1111-1111-1111-111111111111",
    "allowed_origins": None,
    "allowed_ips": ["203.0.113.0/24"],
    "rate_limit": 5000,
    "state": "active",
    "key_prefix": "sk_",
    "key_suffix": "ab12cd34",
    "resource_permissions": None,
    "expires_at": "2030-01-01T00:00:00Z",
    "last_used_at": None,
    "created_at": "2026-02-05T12:00:00Z",
    "updated_at": "2026-02-05T12:00:00Z",
    "revoked_at": None,
    "suspended_at": None,
}

_API_KEY_LIST_EXAMPLE = {
    "items": [_API_KEY_EXAMPLE],
    "limit": 50,
    "next_cursor": "2026-02-05T12:00:00Z",
    "previous_cursor": None,
    "total_count": 1,
}

_API_KEY_CREATED_EXAMPLE = {
    "api_key": _API_KEY_EXAMPLE,
    "secret": "sk_4d2a56d4207a...",
}

_CREATE_API_KEY_EXAMPLE = {
    "name": "Production Backend",
    "key_type": "sk_",
    "permission": "write",
    "scope_type": "space",
    "scope_id": "11111111-1111-1111-1111-111111111111",
    "allowed_ips": ["203.0.113.0/24"],
    "rate_limit": 5000,
}

_STATE_CHANGE_EXAMPLE = {
    "reason_code": "security_concern",
    "reason_text": "Suspicious traffic detected from blocked IP range.",
}

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


def _normalize_notification_preferences(
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


def _normalize_notification_subscriptions(
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


async def _load_api_key_notification_settings(
    *,
    session: AsyncSession,
    user_id: UUID,
    policy: ApiKeyNotificationPolicyResponse,
) -> tuple[ApiKeyNotificationPreferencesResponse, list[ApiKeyNotificationSubscription]]:
    query = (
        sa.select(_SETTINGS_CHATBOT_WIDGET_COL)
        .where(_SETTINGS_USER_ID_COL == user_id)
        .order_by(Settings.updated_at.desc())
        .limit(1)
    )
    raw_widget = await session.scalar(query)
    chatbot_widget = _as_json_object(raw_widget)

    bucket = _as_json_object(chatbot_widget.get(_API_KEY_NOTIFICATIONS_BUCKET))
    preferences = _normalize_notification_preferences(bucket.get("preferences"), policy)
    subscriptions = _normalize_notification_subscriptions(bucket.get("subscriptions"))
    return preferences, subscriptions


async def _save_api_key_notification_settings(
    *,
    session: AsyncSession,
    user_id: UUID,
    preferences: ApiKeyNotificationPreferencesResponse,
    subscriptions: list[ApiKeyNotificationSubscription],
) -> None:
    bucket_payload = {
        "preferences": preferences.model_dump(mode="json"),
        "subscriptions": [
            subscription.model_dump(mode="json") for subscription in subscriptions
        ],
    }

    row_query = (
        sa.select(_SETTINGS_ID_COL, _SETTINGS_CHATBOT_WIDGET_COL)
        .where(_SETTINGS_USER_ID_COL == user_id)
        .order_by(Settings.updated_at.desc())
        .limit(1)
    )
    row = (await session.execute(row_query)).first()
    if row is None:
        await session.execute(
            sa.insert(Settings).values(
                user_id=user_id,
                chatbot_widget={_API_KEY_NOTIFICATIONS_BUCKET: bucket_payload},
            )
        )
        return

    settings_id = cast(UUID, row[0])
    existing_widget = _as_json_object(row[1])
    updated_widget: dict[str, Any] = dict(existing_widget)
    updated_widget[_API_KEY_NOTIFICATIONS_BUCKET] = bucket_payload

    await session.execute(
        sa.update(Settings)
        .where(_SETTINGS_ID_COL == settings_id)
        .values(chatbot_widget=updated_widget)
    )


async def _validate_notification_follow_target(
    *,
    target_type: ApiKeyNotificationTargetType,
    target_id: UUID,
    tenant_id: UUID,
    repo: ApiKeysV2Repository,
    policy: ApiKeyPolicyService,
) -> None:
    if target_type == ApiKeyNotificationTargetType.KEY:
        key = await repo.get(key_id=target_id, tenant_id=tenant_id)
        if key is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "resource_not_found", "message": "API key not found."},
            )
        try:
            await policy.ensure_manage_authorized(key=key)
        except ApiKeyValidationError as exc:
            raise_api_key_http_error(exc)
        return

    scope_type_mapping: dict[ApiKeyNotificationTargetType, ApiKeyScopeType] = {
        ApiKeyNotificationTargetType.ASSISTANT: ApiKeyScopeType.ASSISTANT,
        ApiKeyNotificationTargetType.APP: ApiKeyScopeType.APP,
        ApiKeyNotificationTargetType.SPACE: ApiKeyScopeType.SPACE,
    }
    try:
        await policy.ensure_creator_authorized(
            scope_type=scope_type_mapping[target_type],
            scope_id=target_id,
        )
    except ApiKeyValidationError as exc:
        raise_api_key_http_error(exc)


async def _filter_manageable_keys(
    *,
    keys: list[ApiKeyV2InDB],
    policy: ApiKeyPolicyService,
    cache: dict[tuple[str, UUID | None], bool] | None = None,
) -> tuple[list[ApiKeyV2InDB], dict[tuple[str, UUID | None], bool]]:
    auth_cache = cache or {}
    filtered_keys: list[ApiKeyV2InDB] = []
    for key in keys:
        cache_key = (key.scope_type, key.scope_id)
        allowed = auth_cache.get(cache_key)
        if allowed is None:
            try:
                await policy.ensure_manage_authorized(key=key)
            except ApiKeyValidationError:
                allowed = False
            else:
                allowed = True
            auth_cache[cache_key] = allowed
        if allowed:
            filtered_keys.append(key)
    return filtered_keys, auth_cache


async def _collect_manageable_keys_for_page(
    *,
    repo: ApiKeysV2Repository,
    policy: ApiKeyPolicyService,
    tenant_id: UUID,
    limit: int,
    cursor: datetime | None,
    scope_type: ApiKeyScopeType | None,
    scope_id: UUID | None,
    state: ApiKeyState | None,
    key_type: ApiKeyType | None,
) -> list[ApiKeyV2InDB]:
    """Collect enough manageable keys to produce one filtered page.

    Filtering happens after retrieval because manageability is actor-dependent.
    This collector fetches multiple forward batches when needed so low-permission
    users still receive full pages where possible.
    """
    collected: list[ApiKeyV2InDB] = []
    auth_cache: dict[tuple[str, UUID | None], bool] = {}
    next_cursor = cursor
    max_batches = 20

    for _ in range(max_batches):
        raw_keys = await repo.list_paginated(
            tenant_id=tenant_id,
            limit=limit,
            cursor=next_cursor,
            previous=False,
            scope_type=scope_type,
            scope_id=scope_id,
            state=state,
            key_type=key_type.value if key_type else None,
        )
        if not raw_keys:
            break

        filtered_keys, auth_cache = await _filter_manageable_keys(
            keys=raw_keys,
            policy=policy,
            cache=auth_cache,
        )
        collected.extend(filtered_keys)

        if len(collected) > limit:
            break

        # The repository returns at most limit+1 rows. If we got <= limit,
        # there are no further rows to scan.
        if len(raw_keys) <= limit:
            break

        next_cursor = raw_keys[-1].created_at

    return collected


@router.get(
    "/api-keys/creation-constraints",
    response_model=ApiKeyCreationConstraints,
    tags=["API Keys"],
    summary="Get API key creation constraints",
    description="Returns tenant policy limits relevant to key creation UX (expiration, rate limit).",
    responses={
        200: {"description": "Creation constraints from tenant policy."},
        **error_responses([401, 429]),
    },
)
async def get_creation_constraints(
    container: Container = Depends(get_container(with_user=True)),
):
    user: UserInDB = container.user()
    policy: dict[str, Any] = getattr(user.tenant, "api_key_policy", None) or {}
    return ApiKeyCreationConstraints(
        require_expiration=bool(policy.get("require_expiration")),
        max_expiration_days=policy.get("max_expiration_days"),
        max_rate_limit=policy.get("max_rate_limit_override"),
    )


@router.get(
    "/api-keys/notification-preferences",
    response_model=ApiKeyNotificationPreferencesResponse,
    tags=["API Keys"],
    summary="Get API key notification preferences",
    description="Get the caller's API key expiry notification preferences.",
    responses={200: {"description": "Notification preferences."}, **error_responses([401, 429])},
)
async def get_notification_preferences(
    container: Container = Depends(get_container(with_user=True)),
):
    user: UserInDB = container.user()
    session = cast(AsyncSession, container.session())
    policy = _notification_policy_for_user(user)
    preferences, _subscriptions = await _load_api_key_notification_settings(
        session=session,
        user_id=user.id,
        policy=policy,
    )
    return preferences


@router.put(
    "/api-keys/notification-preferences",
    response_model=ApiKeyNotificationPreferencesResponse,
    tags=["API Keys"],
    summary="Update API key notification preferences",
    description="Update the caller's API key expiry notification preferences.",
    responses={
        200: {"description": "Updated notification preferences."},
        **error_responses([400, 401, 429]),
    },
)
async def update_notification_preferences(
    request: ApiKeyNotificationPreferencesUpdate = Body(
        ...,
        examples=[{"enabled": True, "days_before_expiry": [30, 14, 7, 3, 1]}],
    ),
    container: Container = Depends(get_container(with_user=True)),
):
    user: UserInDB = container.user()
    session = cast(AsyncSession, container.session())
    policy = _notification_policy_for_user(user)
    current_preferences, subscriptions = await _load_api_key_notification_settings(
        session=session,
        user_id=user.id,
        policy=policy,
    )

    merged_preferences = current_preferences.model_dump(mode="python")
    merged_preferences.update(request.model_dump(exclude_unset=True))
    validated_preferences = ApiKeyNotificationPreferencesResponse.model_validate(merged_preferences)
    updated_preferences = ApiKeyNotificationPreferencesResponse(
        enabled=validated_preferences.enabled and policy.enabled,
        days_before_expiry=_normalize_days_against_policy(
            validated_preferences.days_before_expiry,
            policy,
        ),
        auto_follow_published_assistants=(
            validated_preferences.auto_follow_published_assistants
            and policy.allow_auto_follow_published_assistants
        ),
        auto_follow_published_apps=(
            validated_preferences.auto_follow_published_apps
            and policy.allow_auto_follow_published_apps
        ),
    )

    await _save_api_key_notification_settings(
        session=session,
        user_id=user.id,
        preferences=updated_preferences,
        subscriptions=subscriptions,
    )
    return updated_preferences


@router.get(
    "/api-keys/notification-subscriptions",
    response_model=ApiKeyNotificationSubscriptionListResponse,
    tags=["API Keys"],
    summary="List API key notification subscriptions",
    description="List followed targets used for subscribed expiry notification mode.",
    responses={200: {"description": "Notification subscriptions."}, **error_responses([401, 429])},
)
async def list_notification_subscriptions(
    container: Container = Depends(get_container(with_user=True)),
):
    user: UserInDB = container.user()
    session = cast(AsyncSession, container.session())
    policy = _notification_policy_for_user(user)
    _preferences, subscriptions = await _load_api_key_notification_settings(
        session=session,
        user_id=user.id,
        policy=policy,
    )
    return ApiKeyNotificationSubscriptionListResponse(items=subscriptions)


@router.put(
    "/api-keys/notification-subscriptions/{target_type}/{target_id}",
    response_model=ApiKeyNotificationSubscriptionListResponse,
    tags=["API Keys"],
    summary="Follow target for API key expiry notifications",
    description="Follow an API key, assistant, app, or space for subscribed expiry notifications.",
    responses={
        200: {"description": "Updated notification subscriptions."},
        **error_responses([400, 401, 403, 404, 429]),
    },
)
async def upsert_notification_subscription(
    target_type: ApiKeyNotificationTargetType,
    target_id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    user: UserInDB = container.user()
    repo: ApiKeysV2Repository = container.api_key_v2_repo()
    policy: ApiKeyPolicyService = container.api_key_policy_service()
    session = cast(AsyncSession, container.session())
    notification_policy = _notification_policy_for_user(user)

    await _validate_notification_follow_target(
        target_type=target_type,
        target_id=target_id,
        tenant_id=user.tenant_id,
        repo=repo,
        policy=policy,
    )

    preferences, current_subscriptions = await _load_api_key_notification_settings(
        session=session,
        user_id=user.id,
        policy=notification_policy,
    )
    updated = {
        (subscription.target_type.value, subscription.target_id): subscription
        for subscription in current_subscriptions
    }
    new_subscription = ApiKeyNotificationSubscription(
        target_type=target_type,
        target_id=target_id,
    )
    updated[(new_subscription.target_type.value, new_subscription.target_id)] = (
        new_subscription
    )
    subscriptions = sorted(
        updated.values(),
        key=lambda subscription: (
            subscription.target_type.value,
            str(subscription.target_id),
        ),
    )

    await _save_api_key_notification_settings(
        session=session,
        user_id=user.id,
        preferences=preferences,
        subscriptions=subscriptions,
    )
    return ApiKeyNotificationSubscriptionListResponse(items=subscriptions)


@router.delete(
    "/api-keys/notification-subscriptions/{target_type}/{target_id}",
    response_model=ApiKeyNotificationSubscriptionListResponse,
    tags=["API Keys"],
    summary="Unfollow target for API key expiry notifications",
    description="Remove a followed API key/assistant/app/space target from subscribed notifications.",
    responses={200: {"description": "Updated notification subscriptions."}, **error_responses([401, 429])},
)
async def delete_notification_subscription(
    target_type: ApiKeyNotificationTargetType,
    target_id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    user: UserInDB = container.user()
    session = cast(AsyncSession, container.session())
    policy = _notification_policy_for_user(user)
    preferences, current_subscriptions = await _load_api_key_notification_settings(
        session=session,
        user_id=user.id,
        policy=policy,
    )
    subscriptions = [
        subscription
        for subscription in current_subscriptions
        if not (
            subscription.target_type == target_type and subscription.target_id == target_id
        )
    ]

    await _save_api_key_notification_settings(
        session=session,
        user_id=user.id,
        preferences=preferences,
        subscriptions=subscriptions,
    )
    return ApiKeyNotificationSubscriptionListResponse(items=subscriptions)


def _classify_severity(
    expires_at: datetime, now: datetime
) -> Literal["notice", "warning", "urgent", "expired"]:
    if expires_at <= now:
        return "expired"
    days = (expires_at - now).total_seconds() / 86400
    if days <= 3:
        return "urgent"
    if days <= 14:
        return "warning"
    return "notice"


def _build_expiring_summary(
    items: list[ApiKeyV2InDB],
    total_count: int,
    now: datetime,
    cap: int = 10,
) -> ExpiringKeysSummary:
    counts: dict[str, int] = {"notice": 0, "warning": 0, "urgent": 0, "expired": 0}
    summary_items: list[ExpiringKeySummaryItem] = []

    for key in items:
        assert key.expires_at is not None  # noqa: S101 — guaranteed by query
        sev = _classify_severity(key.expires_at, now)
        counts[sev] += 1
        summary_items.append(
            ExpiringKeySummaryItem(
                id=key.id,
                name=key.name,
                key_suffix=key.key_suffix,
                scope_type=key.scope_type,
                scope_id=key.scope_id,
                expires_at=key.expires_at,
                suspended_at=key.suspended_at,
                severity=sev,
            )
        )

    # If total > cap, the items list is already truncated by the repo query.
    # But we still need accurate counts for the truncated keys — those are lost.
    # The counts above only cover materialized items. For accuracy, we report
    # counts from the materialized set and note truncation.
    earliest = min((i.expires_at for i in summary_items), default=None)

    return ExpiringKeysSummary(
        total_count=total_count,
        counts_by_severity=counts,
        earliest_expiration=earliest,
        items=summary_items,
        truncated=total_count > len(summary_items),
        generated_at=now,
    )


@router.get(
    "/api-keys/expiring-soon",
    response_model=ExpiringKeysSummary,
    tags=["API Keys"],
    summary="Get expiring API key summary",
    description="Returns keys expiring within the specified window, filtered by user visibility.",
    responses={
        200: {"description": "Expiring key summary."},
        **error_responses([401, 429]),
    },
)
async def get_expiring_keys(
    days: int = Query(30, ge=1, le=90, description="Look-ahead window in days"),
    mode: Literal["all", "subscribed"] = Query(
        "all",
        description="all: tenant-visible expiring keys, subscribed: only followed targets.",
    ),
    container: Container = Depends(get_container(with_user=True)),
):
    user: UserInDB = container.user()
    repo: ApiKeysV2Repository = container.api_key_v2_repo()
    authorization_policy: ApiKeyPolicyService = container.api_key_policy_service()
    now = datetime.now(timezone.utc)
    notification_policy = _notification_policy_for_user(user)

    followed_key_ids: list[UUID] | None = None
    followed_assistant_scope_ids: list[UUID] | None = None
    followed_app_scope_ids: list[UUID] | None = None
    followed_space_scope_ids: list[UUID] | None = None

    if mode == "subscribed":
        session = cast(AsyncSession, container.session())
        preferences, subscriptions = await _load_api_key_notification_settings(
            session=session,
            user_id=user.id,
            policy=notification_policy,
        )

        if not preferences.enabled or not subscriptions:
            return _build_expiring_summary([], 0, now)

        key_ids = [
            subscription.target_id
            for subscription in subscriptions
            if subscription.target_type == ApiKeyNotificationTargetType.KEY
        ]
        assistant_scope_ids = [
            subscription.target_id
            for subscription in subscriptions
            if subscription.target_type == ApiKeyNotificationTargetType.ASSISTANT
        ]
        app_scope_ids = [
            subscription.target_id
            for subscription in subscriptions
            if subscription.target_type == ApiKeyNotificationTargetType.APP
        ]
        space_scope_ids = [
            subscription.target_id
            for subscription in subscriptions
            if subscription.target_type == ApiKeyNotificationTargetType.SPACE
        ]
        if not (key_ids or assistant_scope_ids or app_scope_ids or space_scope_ids):
            return _build_expiring_summary([], 0, now)

        followed_key_ids = key_ids or None
        followed_assistant_scope_ids = assistant_scope_ids or None
        followed_app_scope_ids = app_scope_ids or None
        followed_space_scope_ids = space_scope_ids or None

    items, total_count = await repo.list_expiring_soon(
        tenant_id=user.tenant_id,
        now=now,
        days=days,
        followed_key_ids=followed_key_ids,
        followed_assistant_scope_ids=followed_assistant_scope_ids,
        followed_app_scope_ids=followed_app_scope_ids,
        followed_space_scope_ids=followed_space_scope_ids,
    )

    # Filter by user visibility (same as GET /api-keys)
    filtered, _cache = await _filter_manageable_keys(
        keys=items,
        policy=authorization_policy,
    )

    # Recount: total_count from repo is unfiltered. For non-admin users the
    # total may be lower but computing exact filtered total would require
    # loading all keys. We use the filtered items length as best-effort.
    filtered_total = len(filtered) if total_count <= 10 else total_count

    return _build_expiring_summary(filtered, filtered_total, now)


@router.get(
    "/api-keys/{id}/usage",
    response_model=ApiKeyUsageResponse,
    tags=["API Keys"],
    summary="Get API key usage",
    description="Returns usage and auth-failure audit events for a single API key you manage.",
    responses={
        200: {"description": "API key usage response."},
        **error_responses([401, 403, 404, 429]),
    },
)
async def get_api_key_usage(
    id: UUID,
    limit: int = Query(50, ge=1, le=200),
    cursor: datetime | None = Query(None),
    container: Container = Depends(get_container(with_user=True)),
):
    user: UserInDB = container.user()
    repo: ApiKeysV2Repository = container.api_key_v2_repo()
    policy: ApiKeyPolicyService = container.api_key_policy_service()

    key = await repo.get(key_id=id, tenant_id=user.tenant_id)
    if key is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "resource_not_found", "message": "API key not found."},
        )
    try:
        await policy.ensure_manage_authorized(key=key)
    except ApiKeyValidationError as exc:
        raise_api_key_http_error(exc)

    session = cast(AsyncSession, container.session())
    summary = await build_api_key_usage_summary(
        session=session, tenant_id=user.tenant_id, key_id=id,
    )
    usage_events, next_cursor = await build_api_key_usage_page(
        session=session, tenant_id=user.tenant_id, key_id=id, limit=limit, cursor=cursor,
    )

    return ApiKeyUsageResponse(
        summary=summary,
        items=usage_events,
        limit=limit,
        next_cursor=next_cursor,
    )


@router.post(
    "/api-keys",
    response_model=ApiKeyCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["API Keys"],
    summary="Create API key",
    description="Create a v2 API key with scoped permission, guardrails, and optional rate limits.",
    responses={
        201: {
            "description": "API key created successfully. Secret is shown once.",
            "content": {"application/json": {"example": _API_KEY_CREATED_EXAMPLE}},
        },
        **error_responses([400, 401, 403, 429]),
    },
)
async def create_api_key(
    http_request: Request,
    payload: ApiKeyCreateRequest = Body(..., examples=[_CREATE_API_KEY_EXAMPLE]),
    container: Container = Depends(get_container(with_user=True)),
    _guard: None = Depends(require_api_key_permission(ApiKeyPermission.ADMIN)),
):
    lifecycle = container.api_key_lifecycle_service()
    ip_address, request_id, user_agent = extract_audit_context(http_request)
    try:
        return await lifecycle.create_key(
            request=payload,
            ip_address=ip_address,
            request_id=request_id,
            user_agent=user_agent,
        )
    except ApiKeyValidationError as exc:
        raise_api_key_http_error(exc)


@router.get(
    "/api-keys",
    response_model=ApiKeyListResponse,
    tags=["API Keys"],
    summary="List API keys",
    description="List manageable API keys in the current tenant with cursor pagination and filters.",
    responses={
        200: {
            "description": "Paginated API key list.",
            "content": {"application/json": {"example": _API_KEY_LIST_EXAMPLE}},
        },
        **error_responses([401, 429]),
    },
)
async def list_api_keys(
    limit: int | None = Query(None, ge=1, description="Keys per page"),
    cursor: datetime | None = Query(None, description="Current cursor"),
    previous: bool = Query(False, description="Show previous page"),
    scope_type: ApiKeyScopeType | None = Query(None, description="Scope type filter"),
    scope_id: UUID | None = Query(None, description="Scope id filter"),
    state: ApiKeyState | None = Query(None, description="State filter"),
    key_type: ApiKeyType | None = Query(None, description="Key type filter"),
    container: Container = Depends(get_container(with_user=True)),
):
    user: UserInDB = container.user()
    repo: ApiKeysV2Repository = container.api_key_v2_repo()
    policy: ApiKeyPolicyService = container.api_key_policy_service()

    if limit is not None and not previous:
        filtered_keys = await _collect_manageable_keys_for_page(
            repo=repo,
            policy=policy,
            tenant_id=user.tenant_id,
            limit=limit,
            cursor=cursor,
            scope_type=scope_type,
            scope_id=scope_id,
            state=state,
            key_type=key_type,
        )
    else:
        raw_keys = await repo.list_paginated(
            tenant_id=user.tenant_id,
            limit=limit,
            cursor=cursor,
            previous=previous,
            scope_type=scope_type,
            scope_id=scope_id,
            state=state,
            key_type=key_type.value if key_type else None,
        )

        filtered_keys, _auth_cache = await _filter_manageable_keys(
            keys=raw_keys,
            policy=policy,
        )

    total_count: int | None = None
    if Permission.ADMIN in user.permissions:
        total_count = await repo.count(
            tenant_id=user.tenant_id,
            scope_type=scope_type,
            scope_id=scope_id,
            state=state,
            key_type=key_type.value if key_type else None,
        )

    return paginate_keys(
        filtered_keys,
        total_count=total_count,
        limit=limit,
        cursor=cursor,
        previous=previous,
    )


@router.get(
    "/api-keys/{id}",
    response_model=ApiKeyV2,
    tags=["API Keys"],
    summary="Get API key",
    description="Get a single API key by ID if the current user is authorized to manage it.",
    responses={
        200: {
            "description": "API key details.",
            "content": {"application/json": {"example": _API_KEY_EXAMPLE}},
        },
        **error_responses([401, 403, 404, 429]),
    },
)
async def get_api_key(
    id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    user: UserInDB = container.user()
    repo: ApiKeysV2Repository = container.api_key_v2_repo()
    policy: ApiKeyPolicyService = container.api_key_policy_service()

    key = await repo.get(key_id=id, tenant_id=user.tenant_id)
    if key is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "resource_not_found", "message": "API key not found."},
        )
    try:
        await policy.ensure_manage_authorized(key=key)
    except ApiKeyValidationError as exc:
        raise_api_key_http_error(exc)

    return ApiKeyV2.model_validate(key)


@router.patch(
    "/api-keys/{id}",
    response_model=ApiKeyV2,
    tags=["API Keys"],
    summary="Update API key",
    description="Update API key metadata and guardrail fields supported by policy.",
    responses={
        200: {
            "description": "Updated API key.",
            "content": {"application/json": {"example": _API_KEY_EXAMPLE}},
        },
        **error_responses([400, 401, 403, 404, 429]),
    },
)
async def update_api_key(
    id: UUID,
    http_request: Request,
    payload: ApiKeyUpdateRequest = Body(
        ...,
        examples=[
            {"name": "Backend Key - Rotated", "expires_at": "2030-01-01T00:00:00Z"}
        ],
    ),
    container: Container = Depends(get_container(with_user=True)),
    _guard: None = Depends(require_api_key_permission(ApiKeyPermission.ADMIN)),
):
    lifecycle: ApiKeyLifecycleService = container.api_key_lifecycle_service()
    ip_address, request_id, user_agent = extract_audit_context(http_request)
    try:
        return await lifecycle.update_key(
            key_id=id,
            request=payload,
            ip_address=ip_address,
            request_id=request_id,
            user_agent=user_agent,
        )
    except ApiKeyValidationError as exc:
        raise_api_key_http_error(exc)


@router.delete(
    "/api-keys/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["API Keys"],
    summary="Revoke API key (deprecated alias)",
    responses={
        204: {"description": "API key revoked. No response body."},
        **error_responses([401, 403, 404, 429]),
    },
    deprecated=True,
    description="Deprecated. Use POST /api/v1/api-keys/{id}/revoke with reason body.",
)
async def revoke_api_key_deprecated(
    id: UUID,
    http_request: Request,
    container: Container = Depends(get_container(with_user=True)),
    _guard: None = Depends(require_api_key_permission(ApiKeyPermission.ADMIN)),
):
    lifecycle: ApiKeyLifecycleService = container.api_key_lifecycle_service()
    ip_address, request_id, user_agent = extract_audit_context(http_request)
    try:
        await lifecycle.revoke_key(
            key_id=id,
            ip_address=ip_address,
            request_id=request_id,
            user_agent=user_agent,
        )
    except ApiKeyValidationError as exc:
        raise_api_key_http_error(exc)
    return None


@router.post(
    "/api-keys/{id}/revoke",
    response_model=ApiKeyV2,
    tags=["API Keys"],
    summary="Revoke API key",
    description="Revoke an API key and optionally include reason metadata for audit logs.",
    responses={
        200: {
            "description": "Revoked API key.",
            "content": {
                "application/json": {"example": _API_KEY_EXAMPLE | {"state": "revoked"}}
            },
        },
        **error_responses([400, 401, 403, 404, 429]),
    },
)
async def revoke_api_key(
    id: UUID,
    http_request: Request,
    payload: ApiKeyStateChangeRequest | None = Body(
        default=None, examples=[_STATE_CHANGE_EXAMPLE]
    ),
    container: Container = Depends(get_container(with_user=True)),
    _guard: None = Depends(require_api_key_permission(ApiKeyPermission.ADMIN)),
):
    lifecycle: ApiKeyLifecycleService = container.api_key_lifecycle_service()
    ip_address, request_id, user_agent = extract_audit_context(http_request)
    try:
        return await lifecycle.revoke_key(
            key_id=id,
            request=payload,
            ip_address=ip_address,
            request_id=request_id,
            user_agent=user_agent,
        )
    except ApiKeyValidationError as exc:
        raise_api_key_http_error(exc)


@router.post(
    "/api-keys/{id}/rotate",
    response_model=ApiKeyCreatedResponse,
    tags=["API Keys"],
    summary="Rotate API key",
    description="Rotate an API key, issuing a new secret and starting the grace overlap window.",
    responses={
        200: {
            "description": "Rotated API key and one-time secret.",
            "content": {"application/json": {"example": _API_KEY_CREATED_EXAMPLE}},
        },
        **error_responses([400, 401, 403, 404, 429]),
    },
)
async def rotate_api_key(
    id: UUID,
    http_request: Request,
    container: Container = Depends(get_container(with_user=True)),
    _guard: None = Depends(require_api_key_permission(ApiKeyPermission.ADMIN)),
):
    lifecycle: ApiKeyLifecycleService = container.api_key_lifecycle_service()
    ip_address, request_id, user_agent = extract_audit_context(http_request)
    try:
        return await lifecycle.rotate_key(
            key_id=id,
            ip_address=ip_address,
            request_id=request_id,
            user_agent=user_agent,
        )
    except ApiKeyValidationError as exc:
        raise_api_key_http_error(exc)


@router.post(
    "/api-keys/{id}/suspend",
    response_model=ApiKeyV2,
    tags=["API Keys"],
    summary="Suspend API key",
    description="Suspend an API key temporarily. Suspended keys cannot authenticate.",
    responses={
        200: {
            "description": "Suspended API key.",
            "content": {
                "application/json": {
                    "example": _API_KEY_EXAMPLE | {"state": "suspended"}
                }
            },
        },
        **error_responses([400, 401, 403, 404, 429]),
    },
)
async def suspend_api_key(
    id: UUID,
    http_request: Request,
    payload: ApiKeyStateChangeRequest | None = Body(
        default=None, examples=[_STATE_CHANGE_EXAMPLE]
    ),
    container: Container = Depends(get_container(with_user=True)),
    _guard: None = Depends(require_api_key_permission(ApiKeyPermission.ADMIN)),
):
    lifecycle: ApiKeyLifecycleService = container.api_key_lifecycle_service()
    ip_address, request_id, user_agent = extract_audit_context(http_request)
    try:
        return await lifecycle.suspend_key(
            key_id=id,
            request=payload,
            ip_address=ip_address,
            request_id=request_id,
            user_agent=user_agent,
        )
    except ApiKeyValidationError as exc:
        raise_api_key_http_error(exc)


@router.post(
    "/api-keys/{id}/reactivate",
    response_model=ApiKeyV2,
    tags=["API Keys"],
    summary="Reactivate API key",
    description="Reactivate a previously suspended API key.",
    responses={
        200: {
            "description": "Reactivated API key.",
            "content": {"application/json": {"example": _API_KEY_EXAMPLE}},
        },
        **error_responses([400, 401, 403, 404, 429]),
    },
)
async def reactivate_api_key(
    id: UUID,
    http_request: Request,
    container: Container = Depends(get_container(with_user=True)),
    _guard: None = Depends(require_api_key_permission(ApiKeyPermission.ADMIN)),
):
    lifecycle: ApiKeyLifecycleService = container.api_key_lifecycle_service()
    ip_address, request_id, user_agent = extract_audit_context(http_request)
    try:
        return await lifecycle.reactivate_key(
            key_id=id,
            ip_address=ip_address,
            request_id=request_id,
            user_agent=user_agent,
        )
    except ApiKeyValidationError as exc:
        raise_api_key_http_error(exc)
