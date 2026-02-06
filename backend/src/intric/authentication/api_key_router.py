from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status

from intric.authentication.api_key_lifecycle import ApiKeyLifecycleService
from intric.authentication.api_key_policy import ApiKeyPolicyService
from intric.authentication.api_key_resolver import ApiKeyValidationError
from intric.authentication.api_key_router_helpers import (
    error_responses,
    extract_audit_context,
    paginate_keys,
    raise_api_key_http_error,
)
from intric.authentication.api_key_v2_repo import ApiKeysV2Repository
from intric.authentication.auth_models import (
    ApiKeyCreateRequest,
    ApiKeyCreatedResponse,
    ApiKeyCreationConstraints,
    ApiKeyListResponse,
    ApiKeyScopeType,
    ApiKeyState,
    ApiKeyStateChangeRequest,
    ApiKeyType,
    ApiKeyUpdateRequest,
    ApiKeyV2,
    ApiKeyV2InDB,
)
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
