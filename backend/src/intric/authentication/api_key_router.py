from __future__ import annotations

from datetime import datetime
from typing import Any, NoReturn, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from intric.authentication.api_key_lifecycle import ApiKeyLifecycleService
from intric.authentication.api_key_policy import ApiKeyPolicyService
from intric.authentication.api_key_resolver import ApiKeyValidationError
from intric.authentication.api_key_v2_repo import ApiKeysV2Repository
from intric.authentication.auth_models import (
    ApiKeyCreateRequest,
    ApiKeyCreatedResponse,
    ApiKeyScopeType,
    ApiKeyState,
    ApiKeyStateChangeRequest,
    ApiKeyType,
    ApiKeyUpdateRequest,
    ApiKeyV2,
    ApiKeyV2InDB,
)
from intric.main.container.container import Container
from intric.main.models import CursorPaginatedResponse
from intric.server.dependencies.container import get_container
from intric.server.protocol import responses
from intric.roles.permissions import Permission
from intric.users.user import UserInDB

router = APIRouter()


def _raise_api_key_http_error(exc: ApiKeyValidationError) -> NoReturn:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
    ) from exc


def _error_responses(codes: list[int]) -> dict[int | str, dict[str, Any]]:
    return cast(dict[int | str, dict[str, Any]], responses.get_responses(codes))


def _paginate_keys(
    keys: list[ApiKeyV2InDB],
    *,
    total_count: int,
    limit: int | None,
    cursor: datetime | None,
    previous: bool,
) -> CursorPaginatedResponse[ApiKeyV2]:
    if limit is None:
        return CursorPaginatedResponse(
            items=[ApiKeyV2.model_validate(key) for key in keys],
            total_count=total_count,
            limit=limit,
        )

    if not previous:
        if len(keys) > limit:
            next_cursor = keys[limit].created_at
            page = keys[:limit]
        else:
            next_cursor = None
            page = keys
        return CursorPaginatedResponse(
            items=[ApiKeyV2.model_validate(key) for key in page],
            total_count=total_count,
            limit=limit,
            next_cursor=next_cursor,
            previous_cursor=cursor,
        )

    if len(keys) > limit:
        page = keys[1:]
        previous_cursor = keys[0].created_at
    else:
        page = keys
        previous_cursor = None

    return CursorPaginatedResponse(
        items=[ApiKeyV2.model_validate(key) for key in page],
        total_count=total_count,
        limit=limit,
        next_cursor=cursor,
        previous_cursor=previous_cursor,
    )


@router.post(
    "/api-keys",
    response_model=ApiKeyCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_error_responses([400, 401, 403, 429]),
)
async def create_api_key(
    request: ApiKeyCreateRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    lifecycle = container.api_key_lifecycle_service()
    try:
        return await lifecycle.create_key(request=request)
    except ApiKeyValidationError as exc:
        _raise_api_key_http_error(exc)


@router.get(
    "/api-keys",
    response_model=CursorPaginatedResponse[ApiKeyV2],
    responses=_error_responses([401, 429]),
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

    filtered_keys: list[ApiKeyV2InDB] = []
    for key in raw_keys:
        try:
            await policy.ensure_manage_authorized(key=key)
        except ApiKeyValidationError:
            continue
        filtered_keys.append(key)

    total_count = len(filtered_keys)
    if Permission.ADMIN in user.permissions:
        total_count = await repo.count(
            tenant_id=user.tenant_id,
            scope_type=scope_type,
            scope_id=scope_id,
            state=state,
            key_type=key_type.value if key_type else None,
        )

    return _paginate_keys(
        filtered_keys,
        total_count=total_count,
        limit=limit,
        cursor=cursor,
        previous=previous,
    )


@router.get(
    "/api-keys/{id}",
    response_model=ApiKeyV2,
    responses=_error_responses([401, 403, 404, 429]),
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
        _raise_api_key_http_error(exc)

    return ApiKeyV2.model_validate(key)


@router.patch(
    "/api-keys/{id}",
    response_model=ApiKeyV2,
    responses=_error_responses([400, 401, 403, 404, 429]),
)
async def update_api_key(
    id: UUID,
    request: ApiKeyUpdateRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    lifecycle: ApiKeyLifecycleService = container.api_key_lifecycle_service()
    try:
        return await lifecycle.update_key(key_id=id, request=request)
    except ApiKeyValidationError as exc:
        _raise_api_key_http_error(exc)


@router.delete(
    "/api-keys/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_error_responses([401, 403, 404, 429]),
    deprecated=True,
    description="Deprecated. Use POST /api/v1/api-keys/{id}/revoke with reason body.",
)
async def revoke_api_key_deprecated(
    id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    lifecycle: ApiKeyLifecycleService = container.api_key_lifecycle_service()
    try:
        await lifecycle.revoke_key(key_id=id)
    except ApiKeyValidationError as exc:
        _raise_api_key_http_error(exc)
    return None


@router.post(
    "/api-keys/{id}/revoke",
    response_model=ApiKeyV2,
    responses=_error_responses([400, 401, 403, 404, 429]),
)
async def revoke_api_key(
    id: UUID,
    request: ApiKeyStateChangeRequest | None = None,
    container: Container = Depends(get_container(with_user=True)),
):
    lifecycle: ApiKeyLifecycleService = container.api_key_lifecycle_service()
    try:
        return await lifecycle.revoke_key(key_id=id, request=request)
    except ApiKeyValidationError as exc:
        _raise_api_key_http_error(exc)


@router.post(
    "/api-keys/{id}/rotate",
    response_model=ApiKeyCreatedResponse,
    responses=_error_responses([400, 401, 403, 404, 429]),
)
async def rotate_api_key(
    id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    lifecycle: ApiKeyLifecycleService = container.api_key_lifecycle_service()
    try:
        return await lifecycle.rotate_key(key_id=id)
    except ApiKeyValidationError as exc:
        _raise_api_key_http_error(exc)


@router.post(
    "/api-keys/{id}/suspend",
    response_model=ApiKeyV2,
    responses=_error_responses([400, 401, 403, 404, 429]),
)
async def suspend_api_key(
    id: UUID,
    request: ApiKeyStateChangeRequest | None = None,
    container: Container = Depends(get_container(with_user=True)),
):
    lifecycle: ApiKeyLifecycleService = container.api_key_lifecycle_service()
    try:
        return await lifecycle.suspend_key(key_id=id, request=request)
    except ApiKeyValidationError as exc:
        _raise_api_key_http_error(exc)


@router.post(
    "/api-keys/{id}/reactivate",
    response_model=ApiKeyV2,
    responses=_error_responses([400, 401, 403, 404, 429]),
)
async def reactivate_api_key(
    id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    lifecycle: ApiKeyLifecycleService = container.api_key_lifecycle_service()
    try:
        return await lifecycle.reactivate_key(key_id=id)
    except ApiKeyValidationError as exc:
        _raise_api_key_http_error(exc)
