from __future__ import annotations

from datetime import datetime
from typing import Any, NoReturn, cast
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from intric.authentication.api_key_request_context import resolve_client_ip
from intric.authentication.api_key_resolver import ApiKeyValidationError
from intric.authentication.auth_models import ApiKeyUsageEvent, ApiKeyUsageSummary, ApiKeyV2, ApiKeyV2InDB
from intric.main.config import get_settings
from intric.main.logging import get_logger
from intric.main.request_context import get_request_context

logger = get_logger(__name__)


class ApiKeyErrorResponse(BaseModel):
    code: str
    message: str


_SAFE_CONTEXT_KEYS: frozenset[str] = frozenset(
    {
        "resource_type",
        "required_level",
        "scope_type",
        "action",
        "auth_layer",
        "required_capability",
    }
)
_GUARDRAIL_CODES: frozenset[str] = frozenset(
    {
        "origin_not_allowed",
        "ip_not_allowed",
        "rate_limited",
        "rate_limit_exceeded",
        "api_key_expired",
        "api_key_revoked",
        "api_key_inactive",
    }
)


def _resolve_request_id(request: Request | None = None) -> str | None:
    if request is not None:
        request_id = request.headers.get("x-correlation-id") or request.headers.get(
            "x-request-id"
        )
        if request_id:
            return request_id
    context = get_request_context()
    return cast(str | None, context.get("correlation_id"))


def _infer_auth_layer(exc: ApiKeyValidationError) -> str | None:
    if exc.status_code == 401:
        return "identity"
    if exc.status_code != 403:
        return None

    if exc.code in {"insufficient_scope"}:
        return "api_key_scope"
    if exc.code in {"insufficient_resource_permission"}:
        return "api_key_resource"
    if exc.code in {"insufficient_permission"}:
        return "api_key_method"
    if exc.code in _GUARDRAIL_CODES:
        return "guardrail"

    return None


def _sanitize_context(
    context: dict[str, object] | None,
    *,
    auth_layer: str | None,
) -> dict[str, object] | None:
    if context is None:
        sanitized: dict[str, object] = {}
    else:
        sanitized = {
            key: value
            for key, value in context.items()
            if key in _SAFE_CONTEXT_KEYS and key != "granted_level"
        }

    if auth_layer is not None:
        sanitized["auth_layer"] = auth_layer
    elif "auth_layer" in sanitized:
        # 400/500 style errors should not carry auth-layer tags.
        sanitized.pop("auth_layer", None)

    return sanitized or None


def raise_api_key_http_error(
    exc: ApiKeyValidationError,
    *,
    request: Request | None = None,
) -> NoReturn:
    auth_layer = _infer_auth_layer(exc)
    context = _sanitize_context(
        dict(exc.context) if exc.context is not None else None,
        auth_layer=auth_layer,
    )
    request_id = _resolve_request_id(request)

    logger.warning(
        "API key authentication failed",
        extra={
            "code": exc.code,
            "error_message": exc.message,
            "status_code": exc.status_code,
            "auth_layer": auth_layer,
        },
    )

    detail: dict[str, object] = {"code": exc.code, "message": exc.message}
    if context is not None:
        detail["context"] = context
    if request_id:
        detail["request_id"] = request_id

    raise HTTPException(
        status_code=exc.status_code,
        detail=detail,
        headers=exc.headers,
    ) from exc


def error_responses(codes: list[int]) -> dict[int | str, dict[str, Any]]:
    return cast(
        dict[int | str, dict[str, Any]],
        {code: {"model": ApiKeyErrorResponse} for code in codes},
    )


def paginate_keys(
    keys: list[ApiKeyV2InDB],
    *,
    total_count: int | None,
    limit: int | None,
    cursor: datetime | None,
    previous: bool,
) -> dict[str, object]:
    if limit is None:
        return {
            "items": [ApiKeyV2.model_validate(key) for key in keys],
            "total_count": total_count,
            "limit": limit,
        }

    if not previous:
        if len(keys) > limit:
            next_cursor = keys[limit].created_at
            page = keys[:limit]
        else:
            next_cursor = None
            page = keys
        return {
            "items": [ApiKeyV2.model_validate(key) for key in page],
            "total_count": total_count,
            "limit": limit,
            "next_cursor": next_cursor,
            "previous_cursor": cursor,
        }

    if len(keys) > limit:
        page = keys[1:]
        previous_cursor = keys[0].created_at
    else:
        page = keys
        previous_cursor = None

    return {
        "items": [ApiKeyV2.model_validate(key) for key in page],
        "total_count": total_count,
        "limit": limit,
        "next_cursor": cursor,
        "previous_cursor": previous_cursor,
    }


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


async def build_api_key_usage_summary(
    *,
    session: AsyncSession,
    tenant_id: UUID,
    key_id: UUID,
) -> ApiKeyUsageSummary:
    from intric.database.tables.audit_log_table import AuditLog as AuditLogTable
    from intric.audit.domain.action_types import ActionType
    from intric.audit.domain.entity_types import EntityType

    stmt = (
        sa.select(
            sa.func.count(AuditLogTable.id).label("total_events"),
            sa.func.count(AuditLogTable.id)
            .filter(AuditLogTable.action == ActionType.API_KEY_USED.value)
            .label("used_events"),
            sa.func.count(AuditLogTable.id)
            .filter(AuditLogTable.action == ActionType.API_KEY_AUTH_FAILED.value)
            .label("auth_failed_events"),
            sa.func.max(AuditLogTable.timestamp).label("last_seen_at"),
            sa.func.max(AuditLogTable.timestamp)
            .filter(AuditLogTable.action == ActionType.API_KEY_USED.value)
            .label("last_success_at"),
            sa.func.max(AuditLogTable.timestamp)
            .filter(AuditLogTable.action == ActionType.API_KEY_AUTH_FAILED.value)
            .label("last_failure_at"),
        )
        .where(AuditLogTable.tenant_id == tenant_id)
        .where(AuditLogTable.entity_type == EntityType.API_KEY.value)
        .where(AuditLogTable.entity_id == key_id)
        .where(
            AuditLogTable.action.in_(
                [ActionType.API_KEY_USED.value, ActionType.API_KEY_AUTH_FAILED.value]
            )
        )
        .where(AuditLogTable.deleted_at.is_(None))
    )
    row = (await session.execute(stmt)).one()

    return ApiKeyUsageSummary(
        total_events=int(row.total_events or 0),
        used_events=int(row.used_events or 0),
        auth_failed_events=int(row.auth_failed_events or 0),
        last_seen_at=row.last_seen_at,
        last_success_at=row.last_success_at,
        last_failure_at=row.last_failure_at,
        sampled_used_events=get_settings().api_key_used_audit_sample_rate < 1.0,
    )


async def build_api_key_usage_page(
    *,
    session: AsyncSession,
    tenant_id: UUID,
    key_id: UUID,
    limit: int,
    cursor: datetime | None,
) -> tuple[list[ApiKeyUsageEvent], datetime | None]:
    from intric.database.tables.audit_log_table import AuditLog as AuditLogTable
    from intric.audit.domain.action_types import ActionType
    from intric.audit.domain.entity_types import EntityType

    stmt = (
        sa.select(AuditLogTable)
        .where(AuditLogTable.tenant_id == tenant_id)
        .where(AuditLogTable.entity_type == EntityType.API_KEY.value)
        .where(AuditLogTable.entity_id == key_id)
        .where(
            AuditLogTable.action.in_(
                [ActionType.API_KEY_USED.value, ActionType.API_KEY_AUTH_FAILED.value]
            )
        )
        .where(AuditLogTable.deleted_at.is_(None))
    )
    if cursor is not None:
        stmt = stmt.where(AuditLogTable.timestamp < cursor)
    stmt = stmt.order_by(AuditLogTable.timestamp.desc(), AuditLogTable.id.desc()).limit(
        limit + 1
    )

    records = list(await session.scalars(stmt))
    page = records[:limit]
    next_cursor = records[limit].timestamp if len(records) > limit else None

    usage_events: list[ApiKeyUsageEvent] = []
    for record in page:
        raw_metadata = cast(dict[str, Any] | None, record.log_metadata)
        metadata: dict[str, Any] = raw_metadata if isinstance(raw_metadata, dict) else {}
        raw_extra: Any = metadata.get("extra")
        extra = cast(dict[str, Any], raw_extra if isinstance(raw_extra, dict) else {})
        ip_addr = cast(str | None, record.ip_address)
        usage_events.append(
            ApiKeyUsageEvent(
                id=cast(UUID, record.id),
                timestamp=cast(datetime, record.timestamp),
                action=cast(str, record.action),
                outcome=cast(str, record.outcome),
                ip_address=str(ip_addr) if ip_addr else None,
                user_agent=cast(str | None, record.user_agent),
                request_id=cast(UUID | None, record.request_id),
                request_path=cast(str | None, extra.get("request_path")),
                method=cast(str | None, extra.get("method")),
                origin=cast(str | None, extra.get("origin")),
                error_message=cast(str | None, record.error_message),
            )
        )

    return usage_events, cast(datetime | None, next_cursor)
