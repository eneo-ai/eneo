from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

from eneo.authentication.api_key_rate_limiter import (
    ApiKeyRateCapacity,
    ApiKeyRateLimitSource,
)
from eneo.authentication.api_key_resolver import ApiKeyValidationError
from eneo.authentication.api_key_router_helpers import (
    error_responses,
    raise_api_key_http_error,
)
from eneo.authentication.auth_models import ApiKeyPermission, ApiKeyScopeType
from eneo.main.container.container import Container
from eneo.server.dependencies.container import get_container
from eneo.users.user import UserInDB

router = APIRouter()

_DESCRIPTION = """
Return how much request budget the calling API key has left in the current
rate-limit window.

Use this before submitting a large batch, so a client knows its own ceiling up
front instead of discovering it as a `429` partway through. Reading this
endpoint is itself one request against the same window, so `remaining` is
already net of this call.

`limit_source` is the discriminator. An unlimited key keeps no counter at all,
so `limit`, `current_count` and `remaining` are `null` rather than zero.

`fail_open` reports whether the deployment lets requests through when the
rate-limit store is unreachable. A client that needs a trustworthy budget
should refuse to rely on `remaining` while it is true.

This endpoint describes the authenticated key only. Session-authenticated
callers have no API key and receive `403`.
"""


class ApiKeyCapacityPublic(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "key_id": "00000000-0000-0000-0000-000000000030",
                "scope_type": "space",
                "scope_id": "00000000-0000-0000-0000-000000000020",
                "permission": "write",
                "limit_source": "explicit",
                "limit": 20000,
                "window_seconds": 3600,
                "current_count": 412,
                "remaining": 19588,
                "fail_open": False,
            }
        },
    )

    key_id: UUID = Field(description="Id of the authenticated API key.")
    scope_type: Literal["tenant", "space", "assistant", "app"] = Field(
        description="Scope kind the key authenticates as."
    )
    scope_id: UUID | None = Field(
        description=(
            "Scoped resource the key is bound to. Null for a tenant-scoped key."
        )
    )
    permission: ApiKeyPermission = Field(
        description="Method level the key may use: read, write or admin."
    )
    limit_source: ApiKeyRateLimitSource = Field(
        description=(
            "How the effective limit was decided: `unlimited` for a key set to "
            "`-1`, `explicit` for a per-key limit, `scope_default` for the "
            "configured default for this scope kind."
        )
    )
    window_seconds: int = Field(
        description=(
            "Length of the fixed rate-limit window. The count resets when the "
            "current window ends."
        )
    )
    fail_open: bool = Field(
        description=(
            "True when the deployment allows requests while the rate-limit store "
            "is unreachable, which makes any remaining-budget claim unreliable."
        )
    )
    limit: int | None = Field(
        description="Requests allowed per window. Null only when unlimited."
    )
    current_count: int | None = Field(
        description=(
            "Requests already counted in the current window, including this one. "
            "Null only when unlimited."
        )
    )
    remaining: int | None = Field(
        description=(
            "`limit` minus `current_count`, never negative. Null only when "
            "unlimited. A snapshot, not a reservation."
        )
    )

    @model_validator(mode="after")
    def _check_limit_source_invariants(self) -> "ApiKeyCapacityPublic":
        finite_fields = (self.limit, self.current_count, self.remaining)
        if self.limit_source == "unlimited":
            if any(value is not None for value in finite_fields):
                raise ValueError("an unlimited key reports no limit or counter")
            return self
        if any(value is None for value in finite_fields):
            raise ValueError("a limited key reports limit, count and remaining")
        return self


@router.get(
    "/api-key-capacity/",
    response_model=ApiKeyCapacityPublic,
    status_code=status.HTTP_200_OK,
    tags=["API Keys"],
    operation_id="get_api_key_capacity",
    summary="Get API key request capacity",
    description=_DESCRIPTION,
    responses={
        200: {"description": "Request capacity for the authenticated API key."},
        **error_responses([401, 403, 429, 503]),
    },
)
async def get_api_key_capacity(
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> ApiKeyCapacityPublic:
    user: UserInDB = container.user()
    key = user.active_api_key
    if key is None:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "api_key_required",
                "message": "This endpoint describes the calling API key.",
            },
        )
    try:
        capacity: ApiKeyRateCapacity = await container.api_key_rate_limiter().snapshot(
            key
        )
    except ApiKeyValidationError as exc:
        raise_api_key_http_error(exc)
    return ApiKeyCapacityPublic(
        key_id=capacity.key_id,
        scope_type=ApiKeyScopeType(capacity.scope_type).value,
        scope_id=capacity.scope_id,
        permission=key.permission,
        limit_source=capacity.limit_source,
        window_seconds=capacity.window_seconds,
        fail_open=capacity.fail_open,
        limit=capacity.limit,
        current_count=capacity.current_count,
        remaining=capacity.remaining,
    )
