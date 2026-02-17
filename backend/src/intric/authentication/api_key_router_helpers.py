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


class ApiKeyErrorResponse(BaseModel):
    code: str
    message: str


def raise_api_key_http_error(exc: ApiKeyValidationError) -> NoReturn:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
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
        metadata = record.log_metadata if isinstance(record.log_metadata, dict) else {}
        extra = metadata.get("extra") if isinstance(metadata, dict) else {}
        extra = extra if isinstance(extra, dict) else {}
        usage_events.append(
            ApiKeyUsageEvent(
                id=record.id,
                timestamp=record.timestamp,
                action=record.action,
                outcome=record.outcome,
                ip_address=str(record.ip_address) if record.ip_address else None,
                user_agent=record.user_agent,
                request_id=record.request_id,
                request_path=cast(str | None, extra.get("request_path")),
                method=cast(str | None, extra.get("method")),
                origin=cast(str | None, extra.get("origin")),
                error_message=record.error_message,
            )
        )

    return usage_events, next_cursor
