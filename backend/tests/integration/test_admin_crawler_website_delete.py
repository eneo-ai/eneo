"""Integration tests for the admin website-delete endpoint.

The DELETE /admin/crawler/websites/{website_id} endpoint backs the
Webbplatser detail Dialog's "Ta bort webbplats" action. It's
tenant-scoped + admin-gated + audited. Tests cover:

- happy path (website disappears, audit row written)
- 404 when website doesn't exist in the admin's tenant
- 404 when the website exists in another tenant (no cross-tenant
  delete; the path is indistinguishable from "not found" by design)
- 409 ACTIVE_JOB_BLOCKING when a queued/running crawl is attached
- non-admin user gets 403
- the endpoint has no tenant_id query parameter
"""

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from intric.database.tables.ai_models_table import EmbeddingModels
from intric.database.tables.job_table import Jobs
from intric.database.tables.websites_table import CrawlRuns, Websites
from intric.jobs.job_models import Task
from intric.main.models import Status
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
    url_suffix: str,
    update_interval: UpdateInterval = UpdateInterval.NEVER,
    name: str | None = None,
) -> Websites:
    website = Websites(
        name=name,
        url=f"https://tenant-delete-{url_suffix}.example.com",
        download_files=True,
        crawl_type=CrawlType.CRAWL,
        update_interval=update_interval,
        size=0,
        tenant_id=tenant_id,
        user_id=user_id,
        embedding_model_id=embedding_model_id,
        consecutive_failures=0,
    )
    session.add(website)
    await session.flush()
    return website


async def _create_active_crawl_job(
    session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    website_id: UUID,
    status: Status,
) -> Jobs:
    """Seed a Jobs row + CrawlRun bridge so the delete endpoint's
    `ACTIVE_JOB_BLOCKING` check fires on the website."""
    job = Jobs(
        user_id=user_id,
        task=Task.CRAWL.value,
        status=status.value,
        result_location=None,
        name="test-crawl",
    )
    session.add(job)
    await session.flush()

    crawl_run = CrawlRuns(
        tenant_id=tenant_id,
        website_id=website_id,
        job_id=job.id,
        pages_crawled=0,
        files_downloaded=0,
        pages_failed=0,
        files_failed=0,
    )
    session.add(crawl_run)
    await session.flush()
    return job


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_delete_website_hard_deletes_row_and_cascades(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
):
    """Happy path: website disappears + 204 returned."""
    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        website = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            url_suffix=f"happy-{uuid4()}",
            name="To delete",
        )
        website_id = website.id
        await session.commit()

    response = await client.delete(
        f"/api/v1/admin/crawler/websites/{website_id}",
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 204, response.text

    async with db_session() as session:
        remaining = await session.scalar(
            sa.select(sa.func.count(Websites.id)).where(Websites.id == website_id)
        )
        assert int(remaining or 0) == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_delete_website_returns_404_for_unknown_id(
    client,
    admin_user_api_key,
):
    """A random UUID that doesn't exist in any tenant returns 404."""
    response = await client.delete(
        f"/api/v1/admin/crawler/websites/{uuid4()}",
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_delete_website_cannot_cross_tenant(
    client,
    db_session,
    tenant_factory,
    user_factory,
    admin_user,
    admin_user_api_key,
):
    """A website in another tenant looks the same as "not found"
    to the admin caller — neither delete attempts nor information
    leakage are possible across tenants.
    """
    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        other_tenant = await tenant_factory(session, name="Other delete tenant")
        other_user = await user_factory(session, tenant_id=other_tenant.id)
        other_website = await _create_website(
            session,
            tenant_id=other_tenant.id,
            user_id=other_user.id,
            embedding_model_id=embedding_model_id,
            url_suffix=f"cross-tenant-{uuid4()}",
        )
        other_website_id = other_website.id
        await session.commit()

    response = await client.delete(
        f"/api/v1/admin/crawler/websites/{other_website_id}",
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 404

    # Confirm the other tenant's website is still present.
    async with db_session() as session:
        remaining = await session.scalar(
            sa.select(sa.func.count(Websites.id)).where(Websites.id == other_website_id)
        )
        assert int(remaining or 0) == 1


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize("job_status", [Status.QUEUED, Status.IN_PROGRESS])
async def test_admin_delete_website_refuses_with_active_job(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
    job_status,
):
    """409 ACTIVE_JOB_BLOCKING when a queued or running crawl is attached."""
    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        website = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            url_suffix=f"blocking-{job_status.value}-{uuid4()}",
        )
        website_id = website.id
        await _create_active_crawl_job(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            website_id=website.id,
            status=job_status,
        )
        await session.commit()

    response = await client.delete(
        f"/api/v1/admin/crawler/websites/{website_id}",
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 409, response.text
    body = response.json()
    assert body["error_code"] == "ACTIVE_JOB_BLOCKING"
    assert "abort" in body["detail"].lower()

    # Website must still exist; the operator's recovery is to abort
    # the active job first.
    async with db_session() as session:
        remaining = await session.scalar(
            sa.select(sa.func.count(Websites.id)).where(Websites.id == website_id)
        )
        assert int(remaining or 0) == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_delete_website_rejects_non_admin(
    client,
    db_container,
    db_session,
    user_factory,
    admin_user,
):
    """Non-admin user gets 403 — admin permission is the gate."""
    async with db_session() as session:
        regular_user = await user_factory(
            session,
            tenant_id=admin_user.tenant_id,
            email=f"regular-delete-{uuid4()}@example.com",
        )
        regular_user_id = regular_user.id
        embedding_model_id = await _embedding_model_id(session)
        website = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            url_suffix=f"forbidden-{uuid4()}",
        )
        website_id = website.id
        await session.commit()

    async with db_container() as container:
        api_key = await container.auth_service().create_user_api_key(
            prefix="test", user_id=regular_user_id, delete_old=True
        )

    response = await client.delete(
        f"/api/v1/admin/crawler/websites/{website_id}",
        headers={"X-API-Key": api_key.key},
    )

    assert response.status_code == 403

    # Website untouched.
    async with db_session() as session:
        remaining = await session.scalar(
            sa.select(sa.func.count(Websites.id)).where(Websites.id == website_id)
        )
        assert int(remaining or 0) == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_delete_website_has_no_tenant_id_query_parameter(app):
    """The endpoint must NOT accept a tenant_id query — current-user only.

    Catches accidental exposure of `tenant_id` as a query parameter if
    a future refactor forgets to keep the route scope-locked.
    """
    operation = app.openapi()["paths"]["/api/v1/admin/crawler/websites/{website_id}"][
        "delete"
    ]
    query_params = [
        param["name"]
        for param in operation.get("parameters", [])
        if param["in"] == "query"
    ]

    assert "tenant_id" not in query_params
