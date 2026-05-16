"""Active crawler inventory attribution fields.

Tenant admins need to see — without leaving the admin crawler page —
which space and collection a running crawl belongs to and which user
started it. Without that context the operator can't decide whether to
abort a long-running crawl (is it the marketing team's bulk reindex or
a stuck zombie?), and the admin surface forces them to navigate to the
space → website view for every row.

This guards the canonical attribution wire shape against drift on the
`GET /api/v1/admin/crawler/active` response.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from intric.database.tables.ai_models_table import EmbeddingModels
from intric.database.tables.collections_table import CollectionsTable
from intric.database.tables.job_table import Jobs
from intric.database.tables.spaces_table import Spaces
from intric.database.tables.tenant_table import Tenants
from intric.database.tables.users_table import Users
from intric.database.tables.websites_table import CrawlRuns, Websites
from intric.jobs.job_models import Task
from intric.main.models import Status
from intric.websites.domain.crawl_run import CrawlType
from intric.websites.domain.website import UpdateInterval


async def _embedding_model_id(session) -> UUID:
    embedding_model_id = await session.scalar(sa.select(EmbeddingModels.id).limit(1))
    assert embedding_model_id is not None
    return embedding_model_id


@pytest.mark.asyncio
@pytest.mark.integration
async def test_active_inventory_exposes_space_collection_user_attribution(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
):
    """A crawl tied to a Space + Collection + creator User must surface
    all six attribution fields. Missing attribution (no Space, no
    Collection, deleted creator) renders as None — the wire shape uses
    nullable typed fields so the frontend can present a fallback without
    string parsing."""
    now = datetime.now(timezone.utc)

    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)

        # A regular tenant space lives under the tenant's org space (one org
        # space per tenant; the unique partial index `idx_unique_org_space_per_tenant`
        # rejects a second `user_id IS NULL AND tenant_space_id IS NULL` row).
        org_space_id = await session.scalar(
            sa.select(Spaces.id).where(
                Spaces.tenant_id == admin_user.tenant_id,
                Spaces.user_id.is_(None),
                Spaces.tenant_space_id.is_(None),
            )
        )
        assert org_space_id is not None, "Tenant must have an org space fixture"

        space = Spaces(
            name="Marketing space",
            description="Marketing team's crawler workspace",
            tenant_id=admin_user.tenant_id,
            tenant_space_id=org_space_id,
        )
        session.add(space)
        await session.flush()

        collection = CollectionsTable(
            name="Marketing knowledge",
            size=0,
            user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            embedding_model_id=embedding_model_id,
            space_id=space.id,
        )
        session.add(collection)
        await session.flush()

        website = Websites(
            name="Marketing website",
            url="https://marketing.example.com",
            download_files=True,
            crawl_type=CrawlType.CRAWL,
            update_interval=UpdateInterval.NEVER,
            size=0,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            space_id=space.id,
            group_id=collection.id,
        )
        session.add(website)
        await session.flush()

        job = Jobs(
            id=uuid4(),
            user_id=admin_user.id,
            task=Task.CRAWL.value,
            status=Status.IN_PROGRESS.value,
            result_location=None,
            name="Attribution crawl",
            finished_at=None,
            created_at=now,
            updated_at=now,
        )
        session.add(job)
        await session.flush()

        crawl_run = CrawlRuns(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            tenant_id=admin_user.tenant_id,
            website_id=website.id,
            job_id=job.id,
        )
        session.add(crawl_run)
        await session.flush()

        expected = {
            "space_id": str(space.id),
            "space_name": "Marketing space",
            "collection_id": str(collection.id),
            "collection_name": "Marketing knowledge",
            "user_started_by_id": str(admin_user.id),
            "user_started_by_email": admin_user.email,
            "job_id": str(job.id),
        }
        await session.commit()

    response = await client.get(
        "/api/v1/admin/crawler/active",
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 200
    data = response.json()
    matching = [item for item in data["items"] if item["job_id"] == expected["job_id"]]
    assert len(matching) == 1
    item = matching[0]
    assert item["space_id"] == expected["space_id"]
    assert item["space_name"] == expected["space_name"]
    assert item["collection_id"] == expected["collection_id"]
    assert item["collection_name"] == expected["collection_name"]
    assert item["user_started_by_id"] == expected["user_started_by_id"]
    assert item["user_started_by_email"] == expected["user_started_by_email"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_active_inventory_attribution_handles_missing_space_and_collection(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
):
    """Websites can exist without a Space (legacy data) or without a
    Collection (group_id is nullable). The attribution fields must
    render as null rather than dropping the row or raising — keeping
    the operator visibility intact for partially-populated tenants."""
    now = datetime.now(timezone.utc) - timedelta(minutes=1)

    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)

        website = Websites(
            name="Bare website",
            url="https://bare.example.com",
            download_files=True,
            crawl_type=CrawlType.CRAWL,
            update_interval=UpdateInterval.NEVER,
            size=0,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            space_id=None,
            group_id=None,
        )
        session.add(website)
        await session.flush()

        job = Jobs(
            id=uuid4(),
            user_id=admin_user.id,
            task=Task.CRAWL.value,
            status=Status.QUEUED.value,
            result_location=None,
            name="Bare attribution crawl",
            finished_at=None,
            created_at=now,
            updated_at=now,
        )
        session.add(job)
        await session.flush()

        crawl_run = CrawlRuns(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            tenant_id=admin_user.tenant_id,
            website_id=website.id,
            job_id=job.id,
        )
        session.add(crawl_run)
        await session.flush()

        expected_job_id = str(job.id)
        await session.commit()

    response = await client.get(
        "/api/v1/admin/crawler/active",
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 200
    data = response.json()
    matching = [item for item in data["items"] if item["job_id"] == expected_job_id]
    assert len(matching) == 1
    item = matching[0]
    assert item["space_id"] is None
    assert item["space_name"] is None
    assert item["collection_id"] is None
    assert item["collection_name"] is None
    # The job creator is still known even when website attribution is missing.
    assert item["user_started_by_id"] == str(admin_user.id)
    assert item["user_started_by_email"] == admin_user.email


@pytest.mark.asyncio
@pytest.mark.integration
async def test_active_inventory_attribution_drops_cross_tenant_references(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
):
    """Defense-in-depth: if a current-tenant CrawlRun's website/job somehow
    references another tenant's Space, Collection, or User (an admin
    import gone wrong, a future code path that doesn't re-check tenant
    ownership), the attribution fields must render as NULL so no foreign
    tenant data leaks through the JOIN. The crawl row itself stays visible
    — the operator still needs to see and abort it — but every attribution
    field renders nullably together rather than partial-leaking. Codex
    AB-tier finding from the attribution sub-tranche review."""
    now = datetime.now(timezone.utc) - timedelta(minutes=2)

    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)

        foreign_tenant = Tenants(
            name=f"foreign-{uuid4().hex}",
            display_name="Foreign tenant",
            slug=f"foreign-{uuid4().hex[:20]}",
            quota_limit=1_000_000,
        )
        session.add(foreign_tenant)
        await session.flush()

        foreign_org_space = Spaces(
            name="Foreign org",
            description=None,
            tenant_id=foreign_tenant.id,
        )
        session.add(foreign_org_space)
        await session.flush()

        foreign_space = Spaces(
            name="Foreign secret space",
            description=None,
            tenant_id=foreign_tenant.id,
            tenant_space_id=foreign_org_space.id,
        )
        session.add(foreign_space)
        await session.flush()

        foreign_user = Users(
            email=f"foreign-{uuid4().hex}@example.com",
            tenant_id=foreign_tenant.id,
            state="active",
        )
        session.add(foreign_user)
        await session.flush()

        foreign_collection = CollectionsTable(
            name="Foreign secret collection",
            size=0,
            user_id=foreign_user.id,
            tenant_id=foreign_tenant.id,
            embedding_model_id=embedding_model_id,
            space_id=foreign_space.id,
        )
        session.add(foreign_collection)
        await session.flush()

        # The poisoned website is in the admin's tenant but points at the
        # foreign tenant's space + collection. In production a tenant_id
        # mismatch like this is the symptom we're guarding against.
        poisoned_website = Websites(
            name="Poisoned website",
            url="https://poisoned.example.com",
            download_files=True,
            crawl_type=CrawlType.CRAWL,
            update_interval=UpdateInterval.NEVER,
            size=0,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            space_id=foreign_space.id,
            group_id=foreign_collection.id,
        )
        session.add(poisoned_website)
        await session.flush()

        job = Jobs(
            id=uuid4(),
            user_id=foreign_user.id,
            task=Task.CRAWL.value,
            status=Status.IN_PROGRESS.value,
            result_location=None,
            name="Poisoned crawl",
            finished_at=None,
            created_at=now,
            updated_at=now,
        )
        session.add(job)
        await session.flush()

        crawl_run = CrawlRuns(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            tenant_id=admin_user.tenant_id,
            website_id=poisoned_website.id,
            job_id=job.id,
        )
        session.add(crawl_run)
        await session.flush()

        expected_job_id = str(job.id)
        await session.commit()

    response = await client.get(
        "/api/v1/admin/crawler/active",
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 200
    data = response.json()
    matching = [item for item in data["items"] if item["job_id"] == expected_job_id]
    assert len(matching) == 1
    item = matching[0]
    # The poisoned row is visible so operators can abort, but every
    # attribution field is null — no foreign tenant data leaks through.
    assert item["space_id"] is None
    assert item["space_name"] is None
    assert item["collection_id"] is None
    assert item["collection_name"] is None
    assert item["user_started_by_id"] is None
    assert item["user_started_by_email"] is None
