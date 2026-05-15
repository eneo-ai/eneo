from datetime import datetime, timedelta, timezone
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
    consecutive_failures: int,
    next_retry_at: datetime | None,
    name: str | None = "Circuit reset website",
) -> Websites:
    website = Websites(
        name=name,
        url=f"https://reset-{uuid4()}.example.com",
        download_files=True,
        crawl_type=CrawlType.CRAWL,
        update_interval=update_interval,
        size=0,
        tenant_id=tenant_id,
        user_id=user_id,
        embedding_model_id=embedding_model_id,
        consecutive_failures=consecutive_failures,
        next_retry_at=next_retry_at,
    )
    session.add(website)
    await session.flush()
    return website


async def _create_tenant_user(session) -> Users:
    tenant = Tenants(
        name=f"reset-tenant-{uuid4().hex}",
        display_name="Reset tenant isolation",
        slug=f"reset-tenant-{uuid4().hex[:20]}",
        quota_limit=1_000_000,
    )
    session.add(tenant)
    await session.flush()

    user = Users(
        email=f"reset-tenant-{uuid4().hex}@example.com",
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


def _reset_audit_calls(
    audit_calls: list[dict[str, object]],
) -> list[dict[str, object]]:
    return [
        audit_call
        for audit_call in audit_calls
        if audit_call.get("action") == ActionType.WEBSITE_CRAWL_CIRCUIT_RESET
    ]


def _assert_reset_audit_call(
    audit_calls: list[dict[str, object]],
    *,
    tenant_id: UUID,
    user_id: UUID,
    website_id: UUID,
    website_name: str,
    prev_consecutive_failures: int,
    prev_state: str,
) -> None:
    reset_calls = _reset_audit_calls(audit_calls)
    assert len(reset_calls) == 1
    audit_call = reset_calls[0]
    assert audit_call["tenant_id"] == tenant_id
    assert audit_call["actor_id"] == user_id
    assert audit_call["action"] == ActionType.WEBSITE_CRAWL_CIRCUIT_RESET
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
    assert extra["prev_consecutive_failures"] == prev_consecutive_failures
    assert extra["prev_state"] == prev_state


@pytest.mark.asyncio
@pytest.mark.integration
async def test_reset_circuit_breaker_clears_backed_off_state_and_writes_audit(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
    monkeypatch,
):
    audit_calls = _install_audit_recorder(monkeypatch)
    next_retry = datetime.now(timezone.utc) + timedelta(hours=4)

    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        website = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            update_interval=UpdateInterval.DAILY,
            consecutive_failures=3,
            next_retry_at=next_retry,
            name="Backed-off website",
        )
        website_id = website.id
        await session.commit()

    response = await client.post(
        f"/api/v1/admin/crawler/websites/{website_id}/reset-circuit-breaker",
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 204

    async with db_session() as session:
        row = (
            await session.execute(
                sa.select(
                    Websites.consecutive_failures,
                    Websites.next_retry_at,
                    Websites.update_interval,
                ).where(Websites.id == website_id)
            )
        ).one()

    assert row.consecutive_failures == 0
    assert row.next_retry_at is None
    assert row.update_interval == UpdateInterval.DAILY.value
    _assert_reset_audit_call(
        audit_calls,
        tenant_id=admin_user.tenant_id,
        user_id=admin_user.id,
        website_id=website_id,
        website_name="Backed-off website",
        prev_consecutive_failures=3,
        prev_state="BACKED_OFF",
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_reset_circuit_breaker_clears_auto_disabled_state_without_changing_schedule(
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
            update_interval=UpdateInterval.NEVER,
            consecutive_failures=WEBSITE_AUTO_DISABLE_FAILURE_THRESHOLD,
            next_retry_at=None,
            name="Auto-disabled website",
        )
        website_id = website.id
        await session.commit()

    response = await client.post(
        f"/api/v1/admin/crawler/websites/{website_id}/reset-circuit-breaker",
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 204

    async with db_session() as session:
        row = (
            await session.execute(
                sa.select(
                    Websites.consecutive_failures,
                    Websites.next_retry_at,
                    Websites.update_interval,
                ).where(Websites.id == website_id)
            )
        ).one()

    assert row.consecutive_failures == 0
    assert row.next_retry_at is None
    assert row.update_interval == UpdateInterval.NEVER.value
    _assert_reset_audit_call(
        audit_calls,
        tenant_id=admin_user.tenant_id,
        user_id=admin_user.id,
        website_id=website_id,
        website_name="Auto-disabled website",
        prev_consecutive_failures=WEBSITE_AUTO_DISABLE_FAILURE_THRESHOLD,
        prev_state="AUTO_DISABLED",
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_reset_circuit_breaker_is_idempotent_for_clean_website(
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
            consecutive_failures=0,
            next_retry_at=None,
            name="Healthy website",
        )
        website_id = website.id
        await session.commit()

    response = await client.post(
        f"/api/v1/admin/crawler/websites/{website_id}/reset-circuit-breaker",
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 204

    async with db_session() as session:
        row = (
            await session.execute(
                sa.select(
                    Websites.consecutive_failures,
                    Websites.next_retry_at,
                    Websites.update_interval,
                ).where(Websites.id == website_id)
            )
        ).one()

    assert row.consecutive_failures == 0
    assert row.next_retry_at is None
    assert row.update_interval == UpdateInterval.DAILY.value
    _assert_reset_audit_call(
        audit_calls,
        tenant_id=admin_user.tenant_id,
        user_id=admin_user.id,
        website_id=website_id,
        website_name="Healthy website",
        prev_consecutive_failures=0,
        prev_state="HEALTHY",
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_reset_circuit_breaker_returns_not_found_for_unknown_website(
    client,
    admin_user_api_key,
    monkeypatch,
):
    audit_calls = _install_audit_recorder(monkeypatch)

    response = await client.post(
        f"/api/v1/admin/crawler/websites/{uuid4()}/reset-circuit-breaker",
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 404
    assert _reset_audit_calls(audit_calls) == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_reset_circuit_breaker_does_not_touch_other_tenant_website(
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
            consecutive_failures=5,
            next_retry_at=datetime.now(timezone.utc) + timedelta(hours=8),
            name="Other tenant website",
        )
        website_id = website.id
        await session.commit()

    response = await client.post(
        f"/api/v1/admin/crawler/websites/{website_id}/reset-circuit-breaker",
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 404
    assert _reset_audit_calls(audit_calls) == []

    async with db_session() as session:
        row = (
            await session.execute(
                sa.select(
                    Websites.consecutive_failures,
                    Websites.next_retry_at,
                ).where(Websites.id == website_id)
            )
        ).one()

    assert row.consecutive_failures == 5
    assert row.next_retry_at is not None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_reset_circuit_breaker_rejects_non_admin_user(
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
            consecutive_failures=2,
            next_retry_at=datetime.now(timezone.utc) + timedelta(hours=2),
        )
        website_id = website.id
        regular_user = await user_factory(
            session,
            tenant_id=admin_user.tenant_id,
            email=f"regular-reset-{uuid4()}@example.com",
        )
        regular_user_id = regular_user.id
        await session.commit()

    async with db_container() as container:
        api_key = await container.auth_service().create_user_api_key(
            prefix="test", user_id=regular_user_id, delete_old=True
        )

    response = await client.post(
        f"/api/v1/admin/crawler/websites/{website_id}/reset-circuit-breaker",
        headers={"X-API-Key": api_key.key},
    )

    assert response.status_code == 403
    assert _reset_audit_calls(audit_calls) == []
