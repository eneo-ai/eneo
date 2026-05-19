"""Lifecycle-status filter on the tenant admin active crawler inventory.

Without a filter, the limit:8-default view forces operators to scan a
mixed bag of queued and in-progress crawls. The lifecycle_status query
parameter lets an operator narrow to one bucket (e.g. only running with
progress) without raising the page limit.

This guards the SQL-side filter shape against drift; the Python-side
classifier already lives in `crawl_lifecycle.py` and is exercised by
unit tests there. Here we assert the SQL classifier produces the same
buckets the Python derivation does, end-to-end through the HTTP layer.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from intric.database.tables.ai_models_table import EmbeddingModels
from intric.database.tables.job_table import Jobs
from intric.database.tables.websites_table import CrawlRuns, Websites
from intric.jobs.job_models import Task
from intric.main.models import Status
from intric.websites.domain.crawl_lifecycle import CrawlLifecycle
from intric.websites.domain.crawl_run import CrawlType
from intric.websites.domain.website import UpdateInterval


async def _embedding_model_id(session) -> UUID:
    embedding_model_id = await session.scalar(sa.select(EmbeddingModels.id).limit(1))
    assert embedding_model_id is not None
    return embedding_model_id


async def _seed_three_lifecycle_crawls(
    session,
    *,
    tenant_id: UUID,
    user_id: UUID,
) -> dict[CrawlLifecycle, UUID]:
    """Seed one crawl in each lifecycle bucket the active endpoint exposes.

    Returns a map from lifecycle_state -> job_id so the test can assert
    the filter response contains the right job for each filter value.
    """
    now = datetime.now(timezone.utc)
    embedding_model_id = await _embedding_model_id(session)

    job_ids: dict[CrawlLifecycle, UUID] = {}
    for bucket, (status, pages_crawled) in (
        (CrawlLifecycle.QUEUED, (Status.QUEUED, None)),
        (CrawlLifecycle.RUNNING_NO_PROGRESS, (Status.IN_PROGRESS, 0)),
        (CrawlLifecycle.RUNNING_WITH_PROGRESS, (Status.IN_PROGRESS, 5)),
    ):
        website = Websites(
            name=f"Lifecycle bucket {bucket.value}",
            url=f"https://lifecycle-{bucket.value}-{uuid4()}.example.com",
            download_files=True,
            crawl_type=CrawlType.CRAWL,
            update_interval=UpdateInterval.NEVER,
            size=0,
            tenant_id=tenant_id,
            user_id=user_id,
            embedding_model_id=embedding_model_id,
        )
        session.add(website)
        await session.flush()

        job = Jobs(
            id=uuid4(),
            user_id=user_id,
            task=Task.CRAWL.value,
            status=status.value,
            result_location=None,
            name=f"Lifecycle bucket {bucket.value}",
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
            tenant_id=tenant_id,
            website_id=website.id,
            job_id=job.id,
            pages_crawled=pages_crawled,
        )
        session.add(crawl_run)
        await session.flush()
        job_ids[bucket] = job.id
    return job_ids


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(
    "filter_value, expected_bucket",
    [
        (CrawlLifecycle.QUEUED.value, CrawlLifecycle.QUEUED),
        (
            CrawlLifecycle.RUNNING_NO_PROGRESS.value,
            CrawlLifecycle.RUNNING_NO_PROGRESS,
        ),
        (
            CrawlLifecycle.RUNNING_WITH_PROGRESS.value,
            CrawlLifecycle.RUNNING_WITH_PROGRESS,
        ),
    ],
)
async def test_active_inventory_lifecycle_filter_returns_only_matching_bucket(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
    filter_value: str,
    expected_bucket: CrawlLifecycle,
):
    async with db_session() as session:
        job_ids = await _seed_three_lifecycle_crawls(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
        )
        expected_job_id = str(job_ids[expected_bucket])
        await session.commit()

    response = await client.get(
        "/api/v1/admin/crawler/active",
        params={"lifecycle_status": filter_value},
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 200
    data = response.json()
    matching = [item for item in data["items"] if item["job_id"] == expected_job_id]
    assert len(matching) == 1
    assert matching[0]["lifecycle_state"] == expected_bucket.value
    # No other lifecycle states leak into the filtered response.
    other_lifecycles = {
        item["lifecycle_state"]
        for item in data["items"]
        if item["lifecycle_state"] != expected_bucket.value
    }
    assert other_lifecycles == set()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_active_inventory_lifecycle_filter_terminal_returns_empty(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
):
    """`TERMINAL` is a valid `CrawlLifecycle` enum value but the active
    inventory query already excludes terminal jobs (status filter +
    finished_at gate). Filtering by terminal must return an empty
    response rather than reject the request — operators may toggle
    filter values rapidly via a ToggleGroup and a 422 mid-toggle is bad
    UX. The wire shape stays the same; total == 0; items == [].
    """
    async with db_session() as session:
        await _seed_three_lifecycle_crawls(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
        )
        await session.commit()

    response = await client.get(
        "/api/v1/admin/crawler/active",
        params={"lifecycle_status": CrawlLifecycle.TERMINAL.value},
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["items"] == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_active_inventory_excludes_in_progress_jobs_with_finished_at_set(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
):
    """Defense-in-depth: a Jobs row with status=IN_PROGRESS but
    finished_at!=NULL is an inconsistent terminal state (the worker
    should have flipped status before setting finished_at). The active
    query excludes such rows so the Python lifecycle classifier and the
    SQL filter cannot disagree on whether the row is RUNNING or TERMINAL."""
    now = datetime.now(timezone.utc)

    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        website = Websites(
            name="Inconsistent terminal-state website",
            url=f"https://terminal-{uuid4()}.example.com",
            download_files=True,
            crawl_type=CrawlType.CRAWL,
            update_interval=UpdateInterval.NEVER,
            size=0,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
        )
        session.add(website)
        await session.flush()

        ghost_job = Jobs(
            id=uuid4(),
            user_id=admin_user.id,
            task=Task.CRAWL.value,
            status=Status.IN_PROGRESS.value,  # inconsistent...
            result_location=None,
            name="Ghost IN_PROGRESS with finished_at set",
            finished_at=now,  # ...with finished_at populated
            created_at=now,
            updated_at=now,
        )
        session.add(ghost_job)
        await session.flush()

        ghost_run = CrawlRuns(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            tenant_id=admin_user.tenant_id,
            website_id=website.id,
            job_id=ghost_job.id,
            pages_crawled=5,
        )
        session.add(ghost_run)
        await session.flush()
        ghost_job_id = str(ghost_job.id)
        await session.commit()

    response = await client.get(
        "/api/v1/admin/crawler/active",
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 200
    data = response.json()
    response_job_ids = {item["job_id"] for item in data["items"]}
    assert ghost_job_id not in response_job_ids, (
        "Active inventory must exclude IN_PROGRESS rows with finished_at set "
        "to keep the SQL filter and Python lifecycle classifier from "
        "disagreeing at the row level."
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_active_inventory_lifecycle_filter_unknown_value_rejected(
    client,
    admin_user_api_key,
):
    response = await client.get(
        "/api/v1/admin/crawler/active",
        params={"lifecycle_status": "not-a-real-lifecycle"},
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.integration
async def test_active_inventory_lifecycle_filter_omitted_returns_all_buckets(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
):
    """Omitting the filter preserves the prior unfiltered semantics so
    existing UI continues to work unchanged."""
    async with db_session() as session:
        job_ids = await _seed_three_lifecycle_crawls(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
        )
        expected_job_ids = {str(jid) for jid in job_ids.values()}
        await session.commit()

    response = await client.get(
        "/api/v1/admin/crawler/active",
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 200
    data = response.json()
    response_ids = {item["job_id"] for item in data["items"]}
    assert expected_job_ids.issubset(response_ids)
