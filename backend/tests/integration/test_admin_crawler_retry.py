"""Tenant-admin retry-now endpoint.

The retry-now action gives a tenant admin a way to immediately
re-queue a crawl for a tenant-owned website without waiting for the
scheduler to pick it up at the next interval. Unlike abort or
circuit-reset, retry-now does NOT touch circuit-breaker counters and
does NOT change the website's update_interval — it's deliberately
lighter so an admin can use it as a "kick" without coupling it to
the recovery flow.

These tests pin the contract for
`POST /api/v1/admin/crawler/websites/{website_id}/retry`:
  * 404 when the website does not exist in the tenant.
  * 404 (NOT 403) when the website exists in ANOTHER tenant — no
    cross-tenant existence oracle leaks.
  * 204 + new CrawlRun + audit row when the website exists in the
    current tenant.
  * Audit row uses ActionType.WEBSITE_CRAWL_RETRY_REQUESTED, carries
    the new crawl_run_id in metadata.extra, and surfaces the website
    label operators saw on the admin page.
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
from intric.database.tables.websites_table import CrawlRuns, Websites
from intric.websites.domain.crawl_run import CrawlType
from intric.websites.domain.website import UpdateInterval


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
    name: str | None = "Retry website",
) -> Websites:
    website = Websites(
        name=name,
        url=f"https://retry-{uuid4()}.example.com",
        download_files=True,
        crawl_type=CrawlType.CRAWL,
        update_interval=UpdateInterval.DAILY,
        size=0,
        tenant_id=tenant_id,
        user_id=user_id,
        embedding_model_id=embedding_model_id,
        consecutive_failures=2,
        next_retry_at=None,
    )
    session.add(website)
    await session.flush()
    return website


async def _create_foreign_tenant_user(session) -> Users:
    tenant = Tenants(
        name=f"retry-foreign-{uuid4().hex}",
        display_name="Retry foreign tenant",
        slug=f"retry-foreign-{uuid4().hex[:20]}",
        quota_limit=1_000_000,
    )
    session.add(tenant)
    await session.flush()

    user = Users(
        email=f"retry-foreign-{uuid4().hex}@example.com",
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


def _install_crawl_service_stub(
    monkeypatch: pytest.MonkeyPatch,
) -> list[UUID]:
    """Replace `CrawlService.crawl` so the retry test does not require
    a Redis-backed feeder + ARQ worker. The integration test asserts
    the endpoint wired the call shape correctly; the actual enqueue
    path is covered by the crawl-service unit tests."""
    from intric.websites.domain import crawl_service as crawl_service_module
    from intric.websites.domain.crawl_run import CrawlRun

    crawled_website_ids: list[UUID] = []

    async def fake_crawl(self, website) -> CrawlRun:  # type: ignore[no-untyped-def]
        crawled_website_ids.append(website.id)
        return CrawlRun.create(website=website)

    monkeypatch.setattr(
        crawl_service_module.CrawlService, "crawl", fake_crawl, raising=True
    )
    return crawled_website_ids


@pytest.mark.asyncio
@pytest.mark.integration
async def test_retry_returns_404_when_website_does_not_exist(
    client,
    admin_user_api_key,
):
    """Bogus website_id with no DB row: 404 before any crawl/audit work."""
    response = await client.post(
        f"/api/v1/admin/crawler/websites/{uuid4()}/retry",
        headers={"X-API-Key": admin_user_api_key.key},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.integration
async def test_retry_returns_404_for_cross_tenant_website_no_existence_oracle(
    client,
    db_session,
    admin_user_api_key,
):
    """A website that exists in ANOTHER tenant must surface as 404
    rather than 403 — the response shape must not let a tenant admin
    probe foreign websites by ID."""
    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        foreign_user = await _create_foreign_tenant_user(session)
        website = await _create_website(
            session,
            tenant_id=foreign_user.tenant_id,
            user_id=foreign_user.id,
            embedding_model_id=embedding_model_id,
            name="Foreign-tenant website",
        )
        website_id = website.id
        await session.commit()

    response = await client.post(
        f"/api/v1/admin/crawler/websites/{website_id}/retry",
        headers={"X-API-Key": admin_user_api_key.key},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.integration
async def test_retry_queues_crawl_and_writes_audit_row(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
    monkeypatch,
):
    audit_calls = _install_audit_recorder(monkeypatch)
    crawled_website_ids = _install_crawl_service_stub(monkeypatch)

    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        website = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            name="Retry-now website",
        )
        website_id = website.id
        prior_runs = await session.scalar(
            sa.select(sa.func.count())
            .select_from(CrawlRuns)
            .where(CrawlRuns.website_id == website_id)
        )
        await session.commit()

    response = await client.post(
        f"/api/v1/admin/crawler/websites/{website_id}/retry",
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 204
    # Retry-now must NOT touch circuit-breaker counters — those are
    # for the explicit reset-circuit-breaker endpoint. Confirm the
    # stored consecutive_failures stays untouched.
    async with db_session() as session:
        row = (
            await session.execute(
                sa.select(
                    Websites.consecutive_failures,
                    Websites.update_interval,
                ).where(Websites.id == website_id)
            )
        ).one()
    assert row.consecutive_failures == 2
    assert row.update_interval == UpdateInterval.DAILY.value

    # The stubbed `CrawlService.crawl` was invoked exactly once with
    # the correct website ID.
    assert crawled_website_ids == [website_id]
    del prior_runs  # the stub returns an unsaved CrawlRun so DB row count is unchanged

    # Audit row was written with the canonical shape for crawler admin
    # website mutations.
    retry_calls = [
        c
        for c in audit_calls
        if c.get("action") == ActionType.WEBSITE_CRAWL_RETRY_REQUESTED
    ]
    assert len(retry_calls) == 1
    audit_call = retry_calls[0]
    assert audit_call["tenant_id"] == admin_user.tenant_id
    assert audit_call["actor_id"] == admin_user.id
    assert audit_call["entity_type"] == EntityType.WEBSITE
    assert audit_call["entity_id"] == website_id

    metadata = audit_call["metadata"]
    assert isinstance(metadata, dict)
    target = metadata["target"]
    assert isinstance(target, dict)
    assert target["id"] == str(website_id)
    assert target["name"] == "Retry-now website"
    extra = metadata["extra"]
    assert isinstance(extra, dict)
    # `crawl_run_id` records the brand-new run (not the prior failed
    # one) so the audit trail cross-references the requested retry
    # with the run that actually executed.
    assert "crawl_run_id" in extra
    crawl_run_id_str = extra["crawl_run_id"]
    assert isinstance(crawl_run_id_str, str)
    UUID(crawl_run_id_str)  # well-formed UUID
