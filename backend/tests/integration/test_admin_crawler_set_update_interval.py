"""Tenant admin interval change for a crawler website.

This is the canonical pause/resume surface — pausing is setting
`update_interval=never`; resuming is setting it to any recurring value.
A single endpoint covers both directions because the underlying operation
is the same. Resuming an auto-disabled website (previous=NEVER + counters
≥ threshold + new=recurring) additionally clears `consecutive_failures`
and `next_retry_at` so the next crawl failure does not immediately re-trip
the auto-disable; pause and arbitrary recurring-to-recurring changes keep
the existing counters intact so "change schedule" stays distinct from
"reset circuit breaker".
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from intric.audit.application.audit_service import AuditService
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.database.tables.ai_models_table import EmbeddingModels
from intric.database.tables.tenant_table import Tenants
from intric.database.tables.users_table import Users
from intric.database.tables.websites_table import Websites
from intric.websites.domain.crawl_run import CrawlType
from intric.websites.domain.website import (
    WEBSITE_AUTO_DISABLE_FAILURE_THRESHOLD,
    UpdateInterval,
)


async def _embedding_model_id(session) -> UUID:
    embedding_model_id = await session.scalar(sa.select(EmbeddingModels.id).limit(1))
    assert embedding_model_id is not None
    return embedding_model_id


async def _create_website(
    session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    embedding_model_id: UUID,
    update_interval: UpdateInterval,
    name: str | None = "Interval target website",
    consecutive_failures: int = 0,
) -> Websites:
    website = Websites(
        name=name,
        url=f"https://interval-{uuid4()}.example.com",
        download_files=True,
        crawl_type=CrawlType.CRAWL,
        update_interval=update_interval,
        size=0,
        tenant_id=tenant_id,
        user_id=user_id,
        embedding_model_id=embedding_model_id,
        consecutive_failures=consecutive_failures,
    )
    session.add(website)
    await session.flush()
    return website


async def _create_tenant_user(session) -> Users:
    tenant = Tenants(
        name=f"interval-tenant-{uuid4().hex}",
        display_name="Interval tenant isolation",
        slug=f"interval-tenant-{uuid4().hex[:20]}",
        quota_limit=1_000_000,
    )
    session.add(tenant)
    await session.flush()

    user = Users(
        email=f"interval-tenant-{uuid4().hex}@example.com",
        tenant_id=tenant.id,
        state="active",
    )
    session.add(user)
    await session.flush()
    return user


def _install_audit_recorder(
    monkeypatch: pytest.MonkeyPatch,
) -> list[dict[str, object]]:
    audit_calls: list[dict[str, object]] = []

    async def record_audit(
        self: AuditService,
        **kwargs: object,
    ) -> UUID | None:
        audit_calls.append(kwargs)
        return uuid4()

    monkeypatch.setattr(AuditService, "log_async", record_audit)
    return audit_calls


def _interval_audit_calls(
    audit_calls: list[dict[str, object]],
) -> list[dict[str, object]]:
    return [
        audit_call
        for audit_call in audit_calls
        if audit_call.get("action") == ActionType.WEBSITE_CRAWL_INTERVAL_CHANGED
    ]


def _assert_interval_audit(
    audit_calls: list[dict[str, object]],
    *,
    tenant_id: UUID,
    user_id: UUID,
    website_id: UUID,
    website_name: str,
    previous: UpdateInterval,
    new: UpdateInterval,
    expected_failure_state_cleared: bool = False,
    expected_previous_consecutive_failures: int = 0,
) -> None:
    interval_calls = _interval_audit_calls(audit_calls)
    assert len(interval_calls) == 1
    audit_call = interval_calls[0]
    assert audit_call["tenant_id"] == tenant_id
    assert audit_call["actor_id"] == user_id
    assert audit_call["action"] == ActionType.WEBSITE_CRAWL_INTERVAL_CHANGED
    assert audit_call["entity_type"] == EntityType.WEBSITE
    assert audit_call["entity_id"] == website_id

    metadata = audit_call["metadata"]
    assert isinstance(metadata, dict)
    target = metadata["target"]
    assert isinstance(target, dict)
    assert target["id"] == str(website_id)
    assert target["name"] == website_name
    extra = metadata["extra"]
    assert isinstance(extra, dict)
    assert extra["previous_update_interval"] == previous.value
    assert extra["new_update_interval"] == new.value
    assert extra["failure_state_cleared"] == expected_failure_state_cleared
    assert (
        extra["previous_consecutive_failures"] == expected_previous_consecutive_failures
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_set_update_interval_pauses_scheduled_crawl(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
    monkeypatch,
):
    audit_calls = _install_audit_recorder(monkeypatch)

    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        website = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            update_interval=UpdateInterval.DAILY,
            name="Daily website",
        )
        website_id = website.id
        await session.commit()

    response = await client.patch(
        f"/api/v1/admin/crawler/websites/{website_id}/update-interval",
        headers={"X-API-Key": admin_user_api_key.key},
        json={"update_interval": UpdateInterval.NEVER.value},
    )

    assert response.status_code == 204

    async with db_session() as session:
        new_interval = await session.scalar(
            sa.select(Websites.update_interval).where(Websites.id == website_id)
        )

    assert new_interval == UpdateInterval.NEVER.value
    _assert_interval_audit(
        audit_calls,
        tenant_id=admin_user.tenant_id,
        user_id=admin_user.id,
        website_id=website_id,
        website_name="Daily website",
        previous=UpdateInterval.DAILY,
        new=UpdateInterval.NEVER,
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_set_update_interval_resumes_paused_crawl(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
    monkeypatch,
):
    """A user-paused (manual NEVER, no failures) website resumes without
    touching the circuit breaker counters."""
    audit_calls = _install_audit_recorder(monkeypatch)

    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        website = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            update_interval=UpdateInterval.NEVER,
            name="Paused website",
        )
        website_id = website.id
        await session.commit()

    response = await client.patch(
        f"/api/v1/admin/crawler/websites/{website_id}/update-interval",
        headers={"X-API-Key": admin_user_api_key.key},
        json={"update_interval": UpdateInterval.WEEKLY.value},
    )

    assert response.status_code == 204

    async with db_session() as session:
        new_interval = await session.scalar(
            sa.select(Websites.update_interval).where(Websites.id == website_id)
        )

    assert new_interval == UpdateInterval.WEEKLY.value
    _assert_interval_audit(
        audit_calls,
        tenant_id=admin_user.tenant_id,
        user_id=admin_user.id,
        website_id=website_id,
        website_name="Paused website",
        previous=UpdateInterval.NEVER,
        new=UpdateInterval.WEEKLY,
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_set_update_interval_resume_from_auto_disable_clears_failure_state(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
    monkeypatch,
):
    """An auto-disabled website (NEVER + counters ≥ threshold) resumed to a
    recurring schedule must also reset `consecutive_failures` and
    `next_retry_at`. Otherwise the next crawl failure trips auto-disable
    again immediately and operators have no recovery path short of also
    calling `/reset-circuit-breaker`. Regression test against codex AB
    finding for the interval-change tranche."""
    audit_calls = _install_audit_recorder(monkeypatch)

    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        website = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            update_interval=UpdateInterval.NEVER,
            consecutive_failures=WEBSITE_AUTO_DISABLE_FAILURE_THRESHOLD,
            name="Auto-disabled website",
        )
        website_id = website.id
        await session.commit()

    response = await client.patch(
        f"/api/v1/admin/crawler/websites/{website_id}/update-interval",
        headers={"X-API-Key": admin_user_api_key.key},
        json={"update_interval": UpdateInterval.DAILY.value},
    )

    assert response.status_code == 204

    async with db_session() as session:
        row = (
            await session.execute(
                sa.select(
                    Websites.update_interval,
                    Websites.consecutive_failures,
                    Websites.next_retry_at,
                ).where(Websites.id == website_id)
            )
        ).one()

    assert row.update_interval == UpdateInterval.DAILY.value
    assert row.consecutive_failures == 0
    assert row.next_retry_at is None
    _assert_interval_audit(
        audit_calls,
        tenant_id=admin_user.tenant_id,
        user_id=admin_user.id,
        website_id=website_id,
        website_name="Auto-disabled website",
        previous=UpdateInterval.NEVER,
        new=UpdateInterval.DAILY,
        expected_failure_state_cleared=True,
        expected_previous_consecutive_failures=WEBSITE_AUTO_DISABLE_FAILURE_THRESHOLD,
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_set_update_interval_pause_preserves_failure_state(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
    monkeypatch,
):
    """Pausing a backed-off website must NOT clear its counters — that's
    a different operator action handled by `/reset-circuit-breaker`. Drift
    here would conflate "change schedule" with "reset state"."""
    audit_calls = _install_audit_recorder(monkeypatch)

    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        website = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            update_interval=UpdateInterval.DAILY,
            consecutive_failures=3,
            name="Backed-off website",
        )
        website_id = website.id
        await session.commit()

    response = await client.patch(
        f"/api/v1/admin/crawler/websites/{website_id}/update-interval",
        headers={"X-API-Key": admin_user_api_key.key},
        json={"update_interval": UpdateInterval.NEVER.value},
    )

    assert response.status_code == 204

    async with db_session() as session:
        row = (
            await session.execute(
                sa.select(
                    Websites.update_interval,
                    Websites.consecutive_failures,
                ).where(Websites.id == website_id)
            )
        ).one()

    assert row.update_interval == UpdateInterval.NEVER.value
    assert row.consecutive_failures == 3
    _assert_interval_audit(
        audit_calls,
        tenant_id=admin_user.tenant_id,
        user_id=admin_user.id,
        website_id=website_id,
        website_name="Backed-off website",
        previous=UpdateInterval.DAILY,
        new=UpdateInterval.NEVER,
        expected_failure_state_cleared=False,
        expected_previous_consecutive_failures=3,
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_set_update_interval_is_noop_when_unchanged(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
    monkeypatch,
):
    audit_calls = _install_audit_recorder(monkeypatch)

    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        website = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            update_interval=UpdateInterval.DAILY,
        )
        website_id = website.id
        await session.commit()

    response = await client.patch(
        f"/api/v1/admin/crawler/websites/{website_id}/update-interval",
        headers={"X-API-Key": admin_user_api_key.key},
        json={"update_interval": UpdateInterval.DAILY.value},
    )

    # No-op change still returns 204 (idempotent operator action) but writes
    # NO audit row because nothing actually changed. This keeps the audit
    # trail signal-to-noise high.
    assert response.status_code == 204
    assert _interval_audit_calls(audit_calls) == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_set_update_interval_rejects_unknown_website(
    client,
    admin_user_api_key,
    monkeypatch,
):
    audit_calls = _install_audit_recorder(monkeypatch)

    response = await client.patch(
        f"/api/v1/admin/crawler/websites/{uuid4()}/update-interval",
        headers={"X-API-Key": admin_user_api_key.key},
        json={"update_interval": UpdateInterval.DAILY.value},
    )

    assert response.status_code == 404
    assert _interval_audit_calls(audit_calls) == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_set_update_interval_does_not_touch_other_tenant_website(
    client,
    db_session,
    admin_user_api_key,
    monkeypatch,
):
    audit_calls = _install_audit_recorder(monkeypatch)

    async with db_session() as session:
        other_user = await _create_tenant_user(session)
        embedding_model_id = await _embedding_model_id(session)
        website = await _create_website(
            session,
            tenant_id=other_user.tenant_id,
            user_id=other_user.id,
            embedding_model_id=embedding_model_id,
            update_interval=UpdateInterval.DAILY,
        )
        website_id = website.id
        await session.commit()

    response = await client.patch(
        f"/api/v1/admin/crawler/websites/{website_id}/update-interval",
        headers={"X-API-Key": admin_user_api_key.key},
        json={"update_interval": UpdateInterval.NEVER.value},
    )

    assert response.status_code == 404
    assert _interval_audit_calls(audit_calls) == []

    async with db_session() as session:
        unchanged_interval = await session.scalar(
            sa.select(Websites.update_interval).where(Websites.id == website_id)
        )

    assert unchanged_interval == UpdateInterval.DAILY.value


@pytest.mark.asyncio
@pytest.mark.integration
async def test_set_update_interval_rejects_non_admin_user(
    client,
    db_container,
    db_session,
    user_factory,
    admin_user,
    monkeypatch,
):
    audit_calls = _install_audit_recorder(monkeypatch)

    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        website = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            update_interval=UpdateInterval.DAILY,
        )
        website_id = website.id
        regular_user = await user_factory(
            session,
            tenant_id=admin_user.tenant_id,
            email=f"regular-interval-{uuid4()}@example.com",
        )
        regular_user_id = regular_user.id
        await session.commit()

    async with db_container() as container:
        api_key = await container.auth_service().create_user_api_key(
            prefix="test", user_id=regular_user_id, delete_old=True
        )

    response = await client.patch(
        f"/api/v1/admin/crawler/websites/{website_id}/update-interval",
        headers={"X-API-Key": api_key.key},
        json={"update_interval": UpdateInterval.NEVER.value},
    )

    assert response.status_code == 403
    assert _interval_audit_calls(audit_calls) == []
