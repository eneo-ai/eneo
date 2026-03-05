from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from fastapi import HTTPException, Request, status

from intric.authentication.auth_dependencies import ScopeFilter, get_scope_filter
from intric.main.container.container import Container
from intric.main.exceptions import ErrorCodes
from intric.main.models import GeneralError


def error_response(
    *,
    description: str,
    message: str,
    intric_error_code: ErrorCodes,
    code: str | None = None,
    context: dict[str, object] | None = None,
) -> dict[str, Any]:
    example: dict[str, Any] = {
        "message": message,
        "intric_error_code": int(intric_error_code),
    }
    if code is not None:
        example["code"] = code
    if context is not None:
        example["context"] = context
    return {
        "model": GeneralError,
        "description": description,
        "content": {"application/json": {"example": example}},
    }


def raise_scope_mismatch() -> None:
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "insufficient_scope",
            "message": "API key space scope does not match requested flow.",
            "context": {"auth_layer": "api_key_scope"},
        },
    )


async def enforce_flow_scope(
    request: Request,
    container: Container,
    *,
    flow_id: UUID,
    require_flow_lookup_without_scope: bool = False,
    scope_filter_getter: Callable[[Request], ScopeFilter] | None = None,
) -> Any | None:
    getter = scope_filter_getter or get_scope_filter
    scope_filter = getter(request)
    if scope_filter.space_id is None and not require_flow_lookup_without_scope:
        return None

    flow = await container.flow_service().get_flow(flow_id)
    if scope_filter.space_id is not None and scope_filter.space_id != flow.space_id:
        raise_scope_mismatch()
    return flow
