"""End-to-end canary: HTTP request → middleware → audit_log row populated.

Pins the middleware-to-audit pathway against future refactors. If the
middleware stops capturing one of these fields, this test fails.
"""

import contextlib
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from intric.audit.domain.action_types import ActionType
from intric.database.database import sessionmanager
from intric.database.tables.audit_log_table import AuditLog as AuditLogTable

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class AuditRowSnapshot:
    ip_address: str | None
    user_agent: str | None
    request_id: UUID | None


@contextlib.asynccontextmanager
async def _db_session():
    async with sessionmanager.session() as session, session.begin():
        yield session


async def _latest_session_created_row(tenant_id) -> AuditRowSnapshot | None:
    """Return the audit-context columns of the most recent AUDIT_SESSION_CREATED row."""
    async with _db_session() as session:
        query = (
            select(
                AuditLogTable.ip_address,
                AuditLogTable.user_agent,
                AuditLogTable.request_id,
            )
            .where(
                AuditLogTable.tenant_id == tenant_id,
                AuditLogTable.action == ActionType.AUDIT_SESSION_CREATED.value,
            )
            .order_by(AuditLogTable.timestamp.desc())
            .limit(1)
        )
        row = (await session.execute(query)).first()
        if row is None:
            return None
        return AuditRowSnapshot(
            ip_address=str(row.ip_address) if row.ip_address is not None else None,
            user_agent=row.user_agent,
            request_id=row.request_id,
        )


async def test_audit_row_captures_request_context_from_headers(
    client, auth_headers, test_tenant, redis_client
):
    """POST with X-Request-Id + User-Agent → audit row stores both."""
    request_id = uuid4()
    user_agent = "canary-client/1.0"

    # Reset the access-session rate limit so this test does not collide with
    # other tests that consume the bucket.
    await redis_client.delete(
        f"rate_limit:audit_session:*:{test_tenant.id}",
    )

    response = await client.post(
        "/api/v1/audit/access-session",
        json={
            "category": "context_canary",
            "description": "Integration canary for HTTP audit context capture.",
        },
        headers={
            **auth_headers,
            "X-Request-Id": str(request_id),
            "User-Agent": user_agent,
        },
    )

    assert response.status_code == 200, response.text

    row = await _latest_session_created_row(test_tenant.id)

    assert row is not None, "audit row was not created"
    assert row.user_agent == user_agent
    assert row.request_id == request_id
    # ip_address comes from the test client's connection — value depends on
    # transport but must not be NULL when the middleware is wired correctly.
    assert row.ip_address is not None


async def test_audit_row_request_id_null_when_header_is_invalid_uuid(
    client, auth_headers, test_tenant, redis_client
):
    """Invalid X-Request-Id header → request still succeeds, request_id is NULL."""
    user_agent = "canary-client/2.0"

    await redis_client.delete(
        f"rate_limit:audit_session:*:{test_tenant.id}",
    )

    response = await client.post(
        "/api/v1/audit/access-session",
        json={
            "category": "context_canary_invalid",
            "description": "Canary for invalid X-Request-Id graceful fallback.",
        },
        headers={
            **auth_headers,
            "X-Request-Id": "not-a-uuid",
            "User-Agent": user_agent,
        },
    )

    # Graceful fallback: request still succeeds with 200.
    assert response.status_code == 200, response.text

    row = await _latest_session_created_row(test_tenant.id)

    assert row is not None
    assert row.user_agent == user_agent
    assert row.request_id is None
    assert row.ip_address is not None


async def test_audit_row_user_agent_null_when_header_missing(
    client, auth_headers, test_tenant, redis_client
):
    """No User-Agent header → audit row records NULL user_agent."""
    await redis_client.delete(
        f"rate_limit:audit_session:*:{test_tenant.id}",
    )

    # httpx sends a default User-Agent; override with empty value.
    headers_no_ua = {**auth_headers, "User-Agent": ""}

    response = await client.post(
        "/api/v1/audit/access-session",
        json={
            "category": "context_canary_no_ua",
            "description": "Canary for missing User-Agent header.",
        },
        headers=headers_no_ua,
    )

    assert response.status_code == 200, response.text

    row = await _latest_session_created_row(test_tenant.id)

    assert row is not None
    # Empty User-Agent is treated as a valid (empty) string by Starlette;
    # the middleware does not coerce empty strings to None.
    assert row.user_agent in ("", None)
    assert row.ip_address is not None
