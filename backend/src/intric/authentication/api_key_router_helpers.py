from __future__ import annotations

from datetime import datetime
from typing import Any, NoReturn, cast
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel
from starlette.requests import Request

from intric.authentication.api_key_request_context import resolve_client_ip
from intric.authentication.api_key_resolver import ApiKeyValidationError
from intric.authentication.auth_models import ApiKeyV2, ApiKeyV2InDB
from intric.main.config import get_settings
from intric.main.models import CursorPaginatedResponse


class ApiKeyErrorResponse(BaseModel):
    code: str
    message: str


def raise_api_key_http_error(exc: ApiKeyValidationError) -> NoReturn:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
    ) from exc


def error_responses(codes: list[int]) -> dict[int | str, dict[str, Any]]:
    return cast(
        dict[int | str, dict[str, Any]],
        {code: {"model": ApiKeyErrorResponse} for code in codes},
    )


def paginate_keys(
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


def extract_audit_context(
    request: Request | None,
) -> tuple[str | None, UUID | None, str | None]:
    if request is None:
        return None, None, None

    settings = get_settings()
    ip_address = resolve_client_ip(
        request,
        trusted_proxy_count=settings.trusted_proxy_count,
        trusted_proxy_headers=settings.trusted_proxy_headers,
    )
    user_agent = request.headers.get("user-agent")
    request_id_raw = request.headers.get("x-request-id") or request.headers.get(
        "x-correlation-id"
    )
    request_id: UUID | None = None
    if request_id_raw:
        try:
            request_id = UUID(request_id_raw)
        except ValueError:
            request_id = None
    return ip_address, request_id, user_agent
