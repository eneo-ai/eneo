from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from intric.database.tables.ai_models_table import EmbeddingModels
from intric.database.tables.collections_table import CollectionsTable
from intric.database.tables.job_table import Jobs
from intric.database.tables.spaces_table import Spaces
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
    name: str | None,
    update_interval: UpdateInterval = UpdateInterval.NEVER,
    size: int = 0,
    space_id: UUID | None = None,
    group_id: UUID | None = None,
) -> Websites:
    website = Websites(
        id=uuid4(),
        name=name,
        url=f"https://tenant-processing-{uuid4()}.example.com",
        download_files=True,
        crawl_type=CrawlType.CRAWL,
        update_interval=update_interval,
        size=size,
        tenant_id=tenant_id,
        user_id=user_id,
        embedding_model_id=embedding_model_id,
        space_id=space_id,
        group_id=group_id,
    )
    session.add(website)
    await session.flush()
    return website


async def _create_job(
    session,
    *,
    user_id: UUID,
    status: Status,
    created_at: datetime,
    finished_at: datetime | None,
) -> Jobs:
    job = Jobs(
        id=uuid4(),
        user_id=user_id,
        task=Task.CRAWL.value,
        status=status.value,
        result_location=None,
        name="Tenant crawler processing aggregate test",
        finished_at=finished_at,
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(job)
    await session.flush()
    return job


async def _create_crawl_run(
    session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    website_id: UUID,
    created_at: datetime,
    status: Status,
    pages_crawled: int = 0,
    files_downloaded: int = 0,
    pages_failed: int = 0,
    files_failed: int = 0,
    pages_source_retained: int = 0,
    pages_hash_retained: int = 0,
    files_hash_retained: int = 0,
    files_too_large_skipped: int = 0,
    embedding_model_name_snapshot: str | None = None,
    embedding_model_litellm_name_snapshot: str | None = None,
    embedding_model_provider_snapshot: str | None = None,
    embedding_input_tokens: int | None = None,
    embedding_total_cost_usd: Decimal | None = None,
    embedding_usage_source: str | None = None,
) -> CrawlRuns:
    finished_at = created_at + timedelta(seconds=10)
    job = await _create_job(
        session,
        user_id=user_id,
        status=status,
        created_at=created_at,
        finished_at=finished_at,
    )
    crawl_run = CrawlRuns(
        id=uuid4(),
        created_at=created_at,
        updated_at=created_at,
        tenant_id=tenant_id,
        website_id=website_id,
        job_id=job.id,
        pages_crawled=pages_crawled,
        files_downloaded=files_downloaded,
        pages_failed=pages_failed,
        files_failed=files_failed,
        pages_source_retained=pages_source_retained,
        pages_hash_retained=pages_hash_retained,
        files_hash_retained=files_hash_retained,
        files_too_large_skipped=files_too_large_skipped,
        embedding_model_name_snapshot=embedding_model_name_snapshot,
        embedding_model_litellm_name_snapshot=embedding_model_litellm_name_snapshot,
        embedding_model_provider_snapshot=embedding_model_provider_snapshot,
        embedding_input_tokens=embedding_input_tokens,
        embedding_total_cost_usd=embedding_total_cost_usd,
        embedding_usage_source=embedding_usage_source,
    )
    session.add(crawl_run)
    await session.flush()
    return crawl_run


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_crawler_website_processing_aggregate_is_tenant_scoped(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
    tenant_factory,
    user_factory,
):
    now = datetime.now(timezone.utc)

    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        org_space_id = await session.scalar(
            sa.select(Spaces.id).where(
                Spaces.tenant_id == admin_user.tenant_id,
                Spaces.user_id.is_(None),
                Spaces.tenant_space_id.is_(None),
            )
        )
        assert org_space_id is not None
        space = Spaces(
            name="Crawler governance space",
            description="Crawler governance test space",
            tenant_id=admin_user.tenant_id,
            tenant_space_id=org_space_id,
        )
        session.add(space)
        await session.flush()
        collection = CollectionsTable(
            name="Crawler governance collection",
            size=0,
            user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            embedding_model_id=embedding_model_id,
            space_id=space.id,
        )
        session.add(collection)
        await session.flush()
        website = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            name="Expensive crawler website",
            update_interval=UpdateInterval.DAILY,
            size=123_456,
            space_id=space.id,
            group_id=collection.id,
        )
        other_website = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            name=None,
        )
        outside_tenant = await tenant_factory(session, name="Outside crawler tenant")
        outside_user = await user_factory(session, tenant_id=outside_tenant.id)
        outside_website = await _create_website(
            session,
            tenant_id=outside_tenant.id,
            user_id=outside_user.id,
            embedding_model_id=embedding_model_id,
            name="Outside tenant website",
        )

        await _create_crawl_run(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            website_id=website.id,
            created_at=now - timedelta(hours=2),
            status=Status.COMPLETE,
            pages_crawled=10,
            files_downloaded=2,
            pages_hash_retained=8,
            files_hash_retained=1,
            files_too_large_skipped=3,
            embedding_model_name_snapshot="Old embedding model",
            embedding_model_litellm_name_snapshot="openai/old-embedding",
            embedding_model_provider_snapshot="openai",
            embedding_input_tokens=100,
            embedding_total_cost_usd=Decimal("0.000010000000"),
            embedding_usage_source="provider_reported",
        )
        await _create_crawl_run(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            website_id=website.id,
            created_at=now - timedelta(hours=1),
            status=Status.FAILED,
            pages_crawled=1,
            pages_failed=1,
            files_failed=2,
            embedding_model_name_snapshot="Latest embedding model",
            embedding_model_litellm_name_snapshot="openai/latest-embedding",
            embedding_model_provider_snapshot="openai",
            embedding_input_tokens=25,
            embedding_total_cost_usd=Decimal("0.000002500000"),
            embedding_usage_source="provider_reported",
        )
        await _create_crawl_run(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            website_id=other_website.id,
            created_at=now - timedelta(minutes=30),
            status=Status.COMPLETE,
            pages_source_retained=4,
            embedding_input_tokens=None,
            embedding_total_cost_usd=None,
        )
        await _create_crawl_run(
            session,
            tenant_id=outside_tenant.id,
            user_id=outside_user.id,
            website_id=outside_website.id,
            created_at=now - timedelta(minutes=15),
            status=Status.COMPLETE,
            pages_crawled=99,
        )
        website_id = website.id
        website_url = website.url
        space_id = space.id
        collection_id = collection.id
        other_website_id = other_website.id
        await session.commit()

    response = await client.get(
        "/api/v1/admin/crawler/website-processing",
        params={"days": 7, "limit": 10, "offset": 0},
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert data["limit"] == 10
    assert data["offset"] == 0
    assert data["days"] == 7
    assert data["low_retention_threshold"] == 0.5
    assert data["source_skip_drift_min_indexed"] == 50
    assert "tenant_id" not in data
    assert data["summary"] == {
        "website_count": 2,
        "total_runs": 3,
        "terminal_runs": 3,
        "failed_runs": 1,
        "pages_crawled": 11,
        "files_downloaded": 2,
        "retained_content_count": 13,
        "files_too_large_skipped": 3,
        "failed_item_count": 3,
        "indexed_size_bytes": 123_456,
        "embedding_input_tokens": 125,
        "embedding_total_cost_usd": "0.000012500000",
        "action_required_count": 1,
    }
    assert len(data["space_rollup"]) == 2
    primary_space = data["space_rollup"][0]
    assert primary_space["space_id"] == str(space_id)
    assert primary_space["space_name"] == "Crawler governance space"
    assert primary_space["website_count"] == 1
    assert primary_space["total_runs"] == 2
    assert primary_space["pages_crawled"] == 11
    assert primary_space["files_downloaded"] == 2
    assert primary_space["indexed_size_bytes"] == 123_456
    assert primary_space["embedding_input_tokens"] == 125
    assert primary_space["embedding_total_cost_usd"] == "0.000012500000"
    assert primary_space["action_required_count"] == 1
    assert primary_space["latest_run_at"] is not None
    assert data["space_rollup"][1]["space_id"] is None
    assert [item["website_id"] for item in data["items"]] == [
        str(website_id),
        str(other_website_id),
    ]

    primary = data["items"][0]
    assert primary["website_name"] == "Expensive crawler website"
    assert primary["website_url"] == website_url
    assert primary["space_id"] == str(space_id)
    assert primary["space_name"] == "Crawler governance space"
    assert primary["collection_id"] == str(collection_id)
    assert primary["collection_name"] == "Crawler governance collection"
    assert primary["owner_user_id"] == str(admin_user.id)
    assert primary["owner_email"] == admin_user.email
    assert primary["indexed_size_bytes"] == 123_456
    assert primary["latest_run_at"] is not None
    assert "tenant_id" not in primary
    assert primary["total_runs"] == 2
    assert primary["terminal_runs"] == 2
    assert primary["failed_runs"] == 1
    assert primary["pages_crawled"] == 11
    assert primary["files_downloaded"] == 2
    assert primary["pages_hash_retained"] == 8
    assert primary["files_hash_retained"] == 1
    assert primary["files_too_large_skipped"] == 3
    assert primary["pages_failed"] == 1
    assert primary["files_failed"] == 2
    assert primary["update_interval"] == UpdateInterval.DAILY.value
    assert primary["schedule_frequency_weight"] == 7.0
    assert primary["indexed_content_count"] == 22
    assert primary["retention_rate"] == pytest.approx(9 / 22)
    assert primary["cost_pressure_score"] == pytest.approx(91.0)
    assert primary["embedding_input_tokens"] == 125
    assert primary["embedding_total_cost_usd"] == "0.000012500000"
    assert primary["latest_embedding_model_name_snapshot"] == "Latest embedding model"
    assert primary["latest_embedding_model_litellm_name_snapshot"] == (
        "openai/latest-embedding"
    )
    assert primary["latest_embedding_model_provider_snapshot"] == "openai"
    assert primary["latest_embedding_input_tokens"] == 25
    assert primary["latest_embedding_total_cost_usd"] == "0.000002500000"
    assert primary["latest_embedding_usage_source"] == "provider_reported"

    secondary = data["items"][1]
    assert secondary["website_name"] is None
    assert secondary["space_id"] is None
    assert secondary["collection_id"] is None
    assert secondary["owner_user_id"] == str(admin_user.id)
    assert secondary["owner_email"] == admin_user.email
    assert secondary["indexed_size_bytes"] == 0
    assert secondary["pages_source_retained"] == 4
    assert secondary["embedding_input_tokens"] is None
    assert secondary["embedding_total_cost_usd"] is None
    assert secondary["latest_embedding_model_name_snapshot"] is None
    assert secondary["latest_embedding_usage_source"] is None

    filtered_response = await client.get(
        "/api/v1/admin/crawler/website-processing",
        params={"days": 7, "limit": 10, "offset": 0, "space_id": str(space_id)},
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert filtered_response.status_code == 200
    filtered_data = filtered_response.json()
    assert filtered_data["total"] == 1
    assert filtered_data["summary"]["website_count"] == 1
    assert filtered_data["summary"]["indexed_size_bytes"] == 123_456
    assert [item["website_id"] for item in filtered_data["items"]] == [str(website_id)]
    assert filtered_data["space_rollup"][0]["space_id"] == str(space_id)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_crawler_website_processing_aggregate_rejects_invalid_bounds(
    client,
    admin_user_api_key,
):
    invalid_days_response = await client.get(
        "/api/v1/admin/crawler/website-processing",
        params={"days": 31},
        headers={"X-API-Key": admin_user_api_key.key},
    )
    invalid_limit_response = await client.get(
        "/api/v1/admin/crawler/website-processing",
        params={"limit": 201},
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert invalid_days_response.status_code == 422
    assert invalid_limit_response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_crawler_website_processing_aggregate_filters_by_website_id(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
):
    """`?website_id=` narrows the per-website 7-day aggregate.

    Seeds two websites in the same tenant, each with one finished
    crawl run. The filter must return exactly the requested website's
    bucket; the other website's stats must not bleed in. Combined
    with the existing tenant predicate the filter never widens the
    visibility scope. Uses real time so the seeded `created_at`
    stays inside the rolling 7-day window.
    """
    now = datetime.now(timezone.utc)

    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        website_a = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            name="Website A",
        )
        website_b = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            name="Website B",
        )
        await _create_crawl_run(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            website_id=website_a.id,
            created_at=now - timedelta(hours=4),
            status=Status.COMPLETE,
            pages_crawled=10,
        )
        await _create_crawl_run(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            website_id=website_b.id,
            created_at=now - timedelta(hours=3),
            status=Status.COMPLETE,
            pages_crawled=5,
        )
        website_a_id = website_a.id
        website_b_id = website_b.id
        await session.commit()

    response = await client.get(
        "/api/v1/admin/crawler/website-processing",
        params={"days": 7, "limit": 50, "website_id": str(website_a_id)},
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 200, response.text
    data = response.json()
    returned = {item["website_id"] for item in data["items"]}
    assert str(website_a_id) in returned
    assert str(website_b_id) not in returned


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_crawler_website_processing_aggregate_sort_options(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
):
    """Each sort enum value lands on the expected primary row.

    Three websites in the same tenant:
    - failure_heavy: 3 failed runs, latest 6h ago
    - busy: 5 successful runs, latest 4h ago
    - recent: 1 successful run, latest 30 min ago
    The default LOAD_PRESSURE sort uses cost-pressure × throughput, so
    busy (high throughput, DAILY interval) wins. FAILURES sort flips
    failure_heavy to the top. RUNS sort flips busy. RECENT sort flips
    recent. Asserting only the primary row keeps the test robust to
    ranking ties on the tail.
    """
    now = datetime.now(timezone.utc)

    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        failure_heavy = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            name="Failure heavy",
            update_interval=UpdateInterval.NEVER,
            size=50,
        )
        busy = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            name="Busy daily crawler",
            update_interval=UpdateInterval.DAILY,
            size=200,
        )
        recent = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            name="Recently active",
            update_interval=UpdateInterval.NEVER,
            size=100,
        )

        for offset_hours in (5, 4, 3):
            await _create_crawl_run(
                session,
                tenant_id=admin_user.tenant_id,
                user_id=admin_user.id,
                website_id=failure_heavy.id,
                created_at=now - timedelta(hours=offset_hours),
                status=Status.FAILED,
                pages_failed=2,
            )
        for offset_hours in (12, 11, 10, 9, 8):
            await _create_crawl_run(
                session,
                tenant_id=admin_user.tenant_id,
                user_id=admin_user.id,
                website_id=busy.id,
                created_at=now - timedelta(hours=offset_hours),
                status=Status.COMPLETE,
                pages_crawled=20,
                files_downloaded=5,
                embedding_input_tokens=10,
            )
        await _create_crawl_run(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            website_id=recent.id,
            created_at=now - timedelta(minutes=30),
            status=Status.COMPLETE,
            pages_crawled=1,
            embedding_input_tokens=500,
        )
        failure_heavy_id = str(failure_heavy.id)
        busy_id = str(busy.id)
        recent_id = str(recent.id)
        await session.commit()

    async def fetch(sort: str) -> dict:
        response = await client.get(
            "/api/v1/admin/crawler/website-processing",
            params={"days": 7, "limit": 10, "sort": sort},
            headers={"X-API-Key": admin_user_api_key.key},
        )
        assert response.status_code == 200, response.text
        return response.json()

    load_pressure = await fetch("load_pressure")
    failures = await fetch("failures")
    runs = await fetch("runs")
    tokens = await fetch("tokens")
    indexed_size = await fetch("indexed_size")
    low_retention = await fetch("low_retention")
    recent_sort = await fetch("recent")

    assert load_pressure["items"][0]["website_id"] == busy_id
    assert failures["items"][0]["website_id"] == failure_heavy_id
    assert runs["items"][0]["website_id"] == busy_id
    assert tokens["items"][0]["website_id"] == recent_id
    assert indexed_size["items"][0]["website_id"] == busy_id
    assert low_retention["items"][0]["website_id"] == busy_id
    assert recent_sort["items"][0]["website_id"] == recent_id


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_crawler_website_processing_aggregate_failures_only_filter(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
):
    """`failures_only=true` returns only websites with failure signals.

    Seeds one healthy + one failure-heavy website. The healthy site
    must be excluded from items and from the total count so pagination
    matches what the operator sees.
    """
    now = datetime.now(timezone.utc)

    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        healthy = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            name="Healthy site",
        )
        failing = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            name="Failing site",
        )
        await _create_crawl_run(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            website_id=healthy.id,
            created_at=now - timedelta(hours=2),
            status=Status.COMPLETE,
            pages_crawled=10,
        )
        await _create_crawl_run(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            website_id=failing.id,
            created_at=now - timedelta(hours=1),
            status=Status.FAILED,
            pages_failed=3,
        )
        failing_id = str(failing.id)
        await session.commit()

    response = await client.get(
        "/api/v1/admin/crawler/website-processing",
        params={"days": 7, "limit": 10, "failures_only": True},
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert [item["website_id"] for item in data["items"]] == [failing_id]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_admin_crawler_website_processing_aggregate_search(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
):
    """`search=` does a case-insensitive substring match on name + URL.

    A literal `%` in the query must not widen the match (escape_like
    guard). When the search term matches no rows the response is empty
    with total=0.
    """
    now = datetime.now(timezone.utc)

    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        alpha = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            name="Alpha service",
        )
        beta = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            name="Beta service",
        )
        await _create_crawl_run(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            website_id=alpha.id,
            created_at=now - timedelta(hours=2),
            status=Status.COMPLETE,
            pages_crawled=10,
        )
        await _create_crawl_run(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            website_id=beta.id,
            created_at=now - timedelta(hours=1),
            status=Status.COMPLETE,
            pages_crawled=5,
        )
        alpha_id = str(alpha.id)
        await session.commit()

    name_hit = await client.get(
        "/api/v1/admin/crawler/website-processing",
        params={"days": 7, "search": "alpha"},
        headers={"X-API-Key": admin_user_api_key.key},
    )
    no_hit = await client.get(
        "/api/v1/admin/crawler/website-processing",
        params={"days": 7, "search": "100%"},
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert name_hit.status_code == 200
    name_data = name_hit.json()
    assert name_data["total"] == 1
    assert [item["website_id"] for item in name_data["items"]] == [alpha_id]

    assert no_hit.status_code == 200
    no_hit_data = no_hit.json()
    assert no_hit_data["total"] == 0
    assert no_hit_data["summary"]["website_count"] == 0
    assert no_hit_data["summary"]["embedding_input_tokens"] is None
    assert no_hit_data["summary"]["embedding_total_cost_usd"] is None
