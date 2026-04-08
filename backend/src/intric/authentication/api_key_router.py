from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Literal, cast
from uuid import UUID

from fastapi import (
    APIRouter,
    Body,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from intric.authentication.api_key_lifecycle import ApiKeyLifecycleService
from intric.authentication.api_key_notification_repo import (
    ApiKeyNotificationRepository,
)
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
    ApiKeyCreatedResponse,
    ApiKeyCreateRequest,
    ApiKeyCreationConstraints,
    ApiKeyListResponse,
    ApiKeyNotificationPolicyResponse,
    ApiKeyNotificationPreferencesResponse,
    ApiKeyNotificationPreferencesUpdate,
    ApiKeyNotificationSubscription,
    ApiKeyNotificationSubscriptionListResponse,
    ApiKeyNotificationSubscriptionSource,
    ApiKeyNotificationTargetType,
    ApiKeyOwnership,
    ApiKeyPermission,
    ApiKeyScopeType,
    ApiKeyState,
    ApiKeyStateChangeRequest,
    ApiKeyType,
    ApiKeyUpdateRequest,
    ApiKeyUsageResponse,
    ApiKeyV2,
    ApiKeyV2InDB,
    ExpiringKeysSummary,
    ExpiringKeySummaryItem,
    normalize_notification_day_value,
    normalize_notification_policy_payload,
)
from intric.main.container.container import Container
from intric.roles.permissions import Permission
from intric.server.dependencies.container import get_container
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


def _apply_notification_policy(
    preferences: ApiKeyNotificationPreferencesResponse,
    policy: ApiKeyNotificationPolicyResponse,
) -> ApiKeyNotificationPreferencesResponse:
    return ApiKeyNotificationPreferencesResponse(
        enabled=preferences.enabled and policy.enabled,
        days_before_expiry=_normalize_days_against_policy(
            preferences.days_before_expiry,
            policy,
        ),
        auto_follow_published_assistants=(
            preferences.auto_follow_published_assistants
            and policy.allow_auto_follow_published_assistants
        ),
        auto_follow_published_apps=(
            preferences.auto_follow_published_apps
            and policy.allow_auto_follow_published_apps
        ),
    )


async def _load_api_key_notification_settings(
    *,
    repo: ApiKeyNotificationRepository,
    user_id: UUID,
    policy: ApiKeyNotificationPolicyResponse,
) -> tuple[ApiKeyNotificationPreferencesResponse, list[ApiKeyNotificationSubscription]]:
    preferences = await repo.get_preferences(user_id)
    if preferences is None:
        preferences = _default_preferences_from_policy(policy)
    else:
        preferences = _apply_notification_policy(preferences, policy)
    subscriptions = await repo.list_subscriptions(user_id)
    return preferences, subscriptions


async def _save_notification_preferences(
    *,
    repo: ApiKeyNotificationRepository,
    user_id: UUID,
    preferences: ApiKeyNotificationPreferencesResponse,
) -> ApiKeyNotificationPreferencesResponse:
    return await repo.upsert_preferences(user_id=user_id, preferences=preferences)


def _sorted_subscriptions(
    subscriptions: list[ApiKeyNotificationSubscription],
) -> list[ApiKeyNotificationSubscription]:
    return sorted(
        subscriptions,
        key=lambda subscription: (
            subscription.target_type.value,
            str(subscription.target_id),
        ),
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
    ownership: str | None = None,
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
            ownership=ownership,
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
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> ApiKeyCreationConstraints:
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
    responses={
        200: {"description": "Notification preferences."},
        **error_responses([401, 429]),
    },
)
async def get_notification_preferences(
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> ApiKeyNotificationPreferencesResponse:
    user: UserInDB = container.user()
    repo: ApiKeyNotificationRepository = container.api_key_notification_repo()
    policy = _notification_policy_for_user(user)
    preferences, _subscriptions = await _load_api_key_notification_settings(
        repo=repo,
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
    request: Annotated[
        ApiKeyNotificationPreferencesUpdate,
        Body(examples=[{"enabled": True, "days_before_expiry": 30}]),
    ],
    container: Annotated[Container, Depends(get_container(with_user=True))],
    _guard: None = Depends(require_api_key_permission(ApiKeyPermission.WRITE)),
) -> ApiKeyNotificationPreferencesResponse:
    user: UserInDB = container.user()
    repo: ApiKeyNotificationRepository = container.api_key_notification_repo()
    policy = _notification_policy_for_user(user)
    current_preferences, _subscriptions = await _load_api_key_notification_settings(
        repo=repo,
        user_id=user.id,
        policy=policy,
    )

    merged_preferences = current_preferences.model_dump(mode="python")
    merged_preferences.update(request.model_dump(exclude_unset=True))
    validated_preferences = ApiKeyNotificationPreferencesResponse.model_validate(
        merged_preferences
    )
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

    await _save_notification_preferences(
        repo=repo,
        user_id=user.id,
        preferences=updated_preferences,
    )
    return updated_preferences


@router.get(
    "/api-keys/notification-subscriptions",
    response_model=ApiKeyNotificationSubscriptionListResponse,
    tags=["API Keys"],
    summary="List API key notification subscriptions",
    description="List followed targets used for subscribed expiry notification mode.",
    responses={
        200: {"description": "Notification subscriptions."},
        **error_responses([401, 429]),
    },
)
async def list_notification_subscriptions(
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> ApiKeyNotificationSubscriptionListResponse:
    user: UserInDB = container.user()
    repo: ApiKeyNotificationRepository = container.api_key_notification_repo()
    policy = _notification_policy_for_user(user)
    _preferences, subscriptions = await _load_api_key_notification_settings(
        repo=repo,
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
    container: Annotated[Container, Depends(get_container(with_user=True))],
    _guard: None = Depends(require_api_key_permission(ApiKeyPermission.WRITE)),
) -> ApiKeyNotificationSubscriptionListResponse:
    user: UserInDB = container.user()
    repo: ApiKeysV2Repository = container.api_key_v2_repo()
    notification_repo: ApiKeyNotificationRepository = (
        container.api_key_notification_repo()
    )
    policy: ApiKeyPolicyService = container.api_key_policy_service()

    await _validate_notification_follow_target(
        target_type=target_type,
        target_id=target_id,
        tenant_id=user.tenant_id,
        repo=repo,
        policy=policy,
    )

    new_subscription = ApiKeyNotificationSubscription(
        target_type=target_type,
        target_id=target_id,
    )
    await notification_repo.add_subscription(
        user_id=user.id,
        subscription=new_subscription,
        source=ApiKeyNotificationSubscriptionSource.MANUAL,
    )
    subscriptions = _sorted_subscriptions(
        await notification_repo.list_subscriptions(user.id)
    )
    return ApiKeyNotificationSubscriptionListResponse(items=subscriptions)


@router.delete(
    "/api-keys/notification-subscriptions/{target_type}/{target_id}",
    response_model=ApiKeyNotificationSubscriptionListResponse,
    tags=["API Keys"],
    summary="Unfollow target for API key expiry notifications",
    description="Remove a followed API key/assistant/app/space target from subscribed notifications.",
    responses={
        200: {"description": "Updated notification subscriptions."},
        **error_responses([401, 429]),
    },
)
async def delete_notification_subscription(
    target_type: ApiKeyNotificationTargetType,
    target_id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
    _guard: None = Depends(require_api_key_permission(ApiKeyPermission.WRITE)),
) -> ApiKeyNotificationSubscriptionListResponse:
    user: UserInDB = container.user()
    repo: ApiKeyNotificationRepository = container.api_key_notification_repo()
    await repo.delete_subscription(
        user_id=user.id,
        target_type=target_type.value,
        target_id=target_id,
    )
    subscriptions = _sorted_subscriptions(await repo.list_subscriptions(user.id))
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
    container: Annotated[Container, Depends(get_container(with_user=True))],
    days: Annotated[
        int, Query(ge=1, le=90, description="Look-ahead window in days")
    ] = 30,
    mode: Annotated[
        Literal["all", "subscribed"],
        Query(
            description="all: tenant-visible expiring keys, subscribed: only followed targets.",
        ),
    ] = "all",
) -> ExpiringKeysSummary:
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
        notification_repo: ApiKeyNotificationRepository = (
            container.api_key_notification_repo()
        )
        preferences, subscriptions = await _load_api_key_notification_settings(
            repo=notification_repo,
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
    container: Annotated[Container, Depends(get_container(with_user=True))],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[datetime | None, Query()] = None,
) -> ApiKeyUsageResponse:
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
        session=session,
        tenant_id=user.tenant_id,
        key_id=id,
    )
    usage_events, next_cursor = await build_api_key_usage_page(
        session=session,
        tenant_id=user.tenant_id,
        key_id=id,
        limit=limit,
        cursor=cursor,
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
    payload: Annotated[ApiKeyCreateRequest, Body(examples=[_CREATE_API_KEY_EXAMPLE])],
    container: Annotated[Container, Depends(get_container(with_user=True))],
    _guard: None = Depends(require_api_key_permission(ApiKeyPermission.ADMIN)),
) -> ApiKeyCreatedResponse:
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
    container: Annotated[Container, Depends(get_container(with_user=True))],
    limit: Annotated[int | None, Query(ge=1, description="Keys per page")] = None,
    cursor: Annotated[datetime | None, Query(description="Current cursor")] = None,
    previous: Annotated[bool, Query(description="Show previous page")] = False,
    scope_type: Annotated[
        ApiKeyScopeType | None, Query(description="Scope type filter")
    ] = None,
    scope_id: Annotated[UUID | None, Query(description="Scope id filter")] = None,
    state: Annotated[ApiKeyState | None, Query(description="State filter")] = None,
    key_type: Annotated[ApiKeyType | None, Query(description="Key type filter")] = None,
    ownership: Annotated[
        ApiKeyOwnership | None, Query(description="Ownership filter")
    ] = None,
) -> ApiKeyListResponse:
    user: UserInDB = container.user()
    repo: ApiKeysV2Repository = container.api_key_v2_repo()
    policy: ApiKeyPolicyService = container.api_key_policy_service()

    ownership_value = ownership.value if ownership else None
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
            ownership=ownership_value,
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
            ownership=ownership_value,
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
            ownership=ownership_value,
        )

    return ApiKeyListResponse.model_validate(
        paginate_keys(
            filtered_keys,
            total_count=total_count,
            limit=limit,
            cursor=cursor,
            previous=previous,
        )
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
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> ApiKeyV2:
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
    payload: Annotated[
        ApiKeyUpdateRequest,
        Body(
            examples=[
                {"name": "Backend Key - Rotated", "expires_at": "2030-01-01T00:00:00Z"}
            ],
        ),
    ],
    container: Annotated[Container, Depends(get_container(with_user=True))],
    _guard: None = Depends(require_api_key_permission(ApiKeyPermission.ADMIN)),
) -> ApiKeyV2:
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
    response_class=Response,
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
    container: Annotated[Container, Depends(get_container(with_user=True))],
    _guard: None = Depends(require_api_key_permission(ApiKeyPermission.ADMIN)),
) -> Response:
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
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
    container: Annotated[Container, Depends(get_container(with_user=True))],
    _guard: None = Depends(require_api_key_permission(ApiKeyPermission.ADMIN)),
    payload: Annotated[
        ApiKeyStateChangeRequest | None,
        Body(examples=[_STATE_CHANGE_EXAMPLE]),
    ] = None,
) -> ApiKeyV2:
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
    container: Annotated[Container, Depends(get_container(with_user=True))],
    _guard: None = Depends(require_api_key_permission(ApiKeyPermission.ADMIN)),
) -> ApiKeyCreatedResponse:
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
    container: Annotated[Container, Depends(get_container(with_user=True))],
    _guard: None = Depends(require_api_key_permission(ApiKeyPermission.ADMIN)),
    payload: Annotated[
        ApiKeyStateChangeRequest | None,
        Body(examples=[_STATE_CHANGE_EXAMPLE]),
    ] = None,
) -> ApiKeyV2:
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
    container: Annotated[Container, Depends(get_container(with_user=True))],
    _guard: None = Depends(require_api_key_permission(ApiKeyPermission.ADMIN)),
) -> ApiKeyV2:
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
