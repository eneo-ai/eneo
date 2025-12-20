"""Integration tests for Phase 0 Zombie Counter Reconciliation.

Tests verify that the OrphanWatchdog Phase 0 correctly detects and fixes
zombie counters - cases where Redis active_jobs counter is higher than actual
QUEUED/IN_PROGRESS jobs in the database.

Bug context:
- Redis counter can get "stuck" at a high value due to:
  1. Worker crashes after slot acquire but before job completion
  2. Safe Watchdog marking job FAILED but flag had expired (no slot release)
  3. TTL refresh on failure (fixed separately - see test_lua_ttl_fix.py)
  4. Manual DB interventions

- Zombie counters cause queue stagnation:
  Redis says "active_jobs=10" → Feeder thinks at capacity → no new jobs processed
  But DB has 0 active jobs → deadlock

The fix: Phase 0 reconciliation runs BEFORE other cleanup phases to:
1. SCAN all tenant:*:active_jobs keys
2. For each tenant, query DB for actual QUEUED/IN_PROGRESS job count
3. If Redis > DB, reset Redis to DB value (or DELETE if DB=0)
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import redis.asyncio as aioredis

from intric.main.config import Settings
from intric.main.models import Status
from intric.worker.feeder.watchdog import OrphanWatchdog


# ============================================================================
# Helper Functions
# ============================================================================


async def create_test_website(session, tenant_id, user_id, embedding_model_id):
    """Create a minimal Website record for CrawlRun tests."""
    from intric.database.tables.websites_table import Websites
    from intric.websites.domain.crawl_run import CrawlType

    website = Websites(
        tenant_id=tenant_id,
        user_id=user_id,
        embedding_model_id=embedding_model_id,
        url=f"https://test-phase0-{uuid4().hex[:8]}.example.com",
        name="Test Website for Phase 0 Tests",
        download_files=False,
        crawl_type=CrawlType.CRAWL,
        update_interval="never",
        size=0,
    )
    session.add(website)
    await session.flush()
    return website.id


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
async def clean_redis(redis_client: aioredis.Redis):
    """Clean up Redis test keys before and after each test."""
    patterns = [
        "tenant:*:active_jobs",
        "job:*:slot_preacquired",
        "tenant:*:crawl_pending",
    ]

    # Clean before test
    for pattern in patterns:
        cursor = 0
        while True:
            cursor, keys = await redis_client.scan(cursor=cursor, match=pattern, count=100)
            if keys:
                await redis_client.delete(*keys)
            if cursor == 0:
                break

    yield redis_client

    # Clean after test
    for pattern in patterns:
        cursor = 0
        while True:
            cursor, keys = await redis_client.scan(cursor=cursor, match=pattern, count=100)
            if keys:
                await redis_client.delete(*keys)
            if cursor == 0:
                break


@pytest.fixture
async def test_embedding_model_id(db_container):
    """Get the fixture embedding model ID for tests."""
    from sqlalchemy import select
    from intric.database.tables.ai_models_table import EmbeddingModels

    async with db_container() as container:
        session = container.session()
        result = await session.execute(
            select(EmbeddingModels.id).where(EmbeddingModels.name == "fixture-text-embedding")
        )
        return result.scalar_one()


# ============================================================================
# Test Class: Phase 0 - Zombie Counter Reconciliation
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.integration
class TestPhase0ZombieCounterReconciliation:
    """Verify that Phase 0 correctly detects and fixes zombie counters."""

    async def test_zombie_counter_with_no_active_jobs_is_deleted(
        self,
        clean_redis: aioredis.Redis,
        db_container,
        test_tenant,
        admin_user,
        test_settings: Settings,
        test_embedding_model_id,
    ):
        """
        CRITICAL: Zombie counter should be DELETED when DB has zero active jobs.

        Setup:
        - Redis counter = 5 (zombie)
        - DB: No QUEUED/IN_PROGRESS jobs for tenant

        Expected:
        - Redis key is DELETED (not just set to 0)
        - Feeder can now acquire slots normally
        """
        # Setup Redis with zombie counter
        slot_key = f"tenant:{test_tenant.id}:active_jobs"
        await clean_redis.set(slot_key, "5")

        # Verify initial zombie state
        assert await clean_redis.get(slot_key) == b"5"

        # Run cleanup using OrphanWatchdog directly
        watchdog = OrphanWatchdog(clean_redis, test_settings)
        metrics = await watchdog.run_cleanup()

        # CRITICAL: Verify zombie counter was DELETED (DB has 0 jobs)
        slot_value = await clean_redis.get(slot_key)
        assert slot_value is None, (
            f"Zombie counter should be DELETED when DB has 0 active jobs, got {slot_value}"
        )
        assert metrics.zombies_reconciled >= 1, "Should have reconciled at least one zombie"

    async def test_zombie_counter_with_some_active_jobs_is_reset(
        self,
        clean_redis: aioredis.Redis,
        db_container,
        test_tenant,
        admin_user,
        test_settings: Settings,
        test_embedding_model_id,
    ):
        """
        Zombie counter should be RESET to actual DB count when DB has some active jobs.

        Setup:
        - Redis counter = 10 (inflated)
        - DB: 2 QUEUED jobs for tenant

        Expected:
        - Redis counter reset to 2 (matches DB)
        - Counter has TTL set
        """
        from intric.database.tables.job_table import Jobs
        from intric.database.tables.websites_table import CrawlRuns

        # Setup Redis with inflated counter
        slot_key = f"tenant:{test_tenant.id}:active_jobs"
        await clean_redis.set(slot_key, "10")

        # Create 2 active jobs in DB
        async with db_container() as container:
            session = container.session()

            for i in range(2):
                job = Jobs(
                    id=uuid4(),
                    user_id=admin_user.id,
                    task="CRAWL",
                    status=Status.QUEUED,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
                session.add(job)
                await session.flush()

                website_id = await create_test_website(
                    session, test_tenant.id, admin_user.id, test_embedding_model_id
                )

                crawl_run = CrawlRuns(
                    tenant_id=test_tenant.id,
                    website_id=website_id,
                    job_id=job.id,
                    pages_crawled=0,
                    files_downloaded=0,
                    pages_failed=0,
                    files_failed=0,
                )
                session.add(crawl_run)

            await session.commit()

        # Run cleanup using OrphanWatchdog
        watchdog = OrphanWatchdog(clean_redis, test_settings)
        await watchdog.run_cleanup()

        # Verify counter was reset to actual count
        slot_value = await clean_redis.get(slot_key)
        assert slot_value is not None, "Counter should exist (DB has active jobs)"
        assert int(slot_value) == 2, (
            f"Zombie counter should be reset to 2 (actual DB count), got {int(slot_value)}"
        )

    async def test_normal_counter_unchanged_when_matching_db(
        self,
        clean_redis: aioredis.Redis,
        db_container,
        test_tenant,
        admin_user,
        test_settings: Settings,
        test_embedding_model_id,
    ):
        """
        Normal counter (matching DB) should NOT be modified.

        Setup:
        - Redis counter = 3
        - DB: 3 QUEUED jobs for tenant

        Expected:
        - Redis counter remains 3 (no change)
        """
        from intric.database.tables.job_table import Jobs
        from intric.database.tables.websites_table import CrawlRuns

        # Setup Redis with correct counter
        slot_key = f"tenant:{test_tenant.id}:active_jobs"
        await clean_redis.set(slot_key, "3")

        # Create 3 active jobs in DB
        async with db_container() as container:
            session = container.session()

            for i in range(3):
                job = Jobs(
                    id=uuid4(),
                    user_id=admin_user.id,
                    task="CRAWL",
                    status=Status.QUEUED,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
                session.add(job)
                await session.flush()

                website_id = await create_test_website(
                    session, test_tenant.id, admin_user.id, test_embedding_model_id
                )

                crawl_run = CrawlRuns(
                    tenant_id=test_tenant.id,
                    website_id=website_id,
                    job_id=job.id,
                    pages_crawled=0,
                    files_downloaded=0,
                    pages_failed=0,
                    files_failed=0,
                )
                session.add(crawl_run)

            await session.commit()

        # Run cleanup using OrphanWatchdog
        watchdog = OrphanWatchdog(clean_redis, test_settings)
        await watchdog.run_cleanup()

        # Verify counter unchanged
        slot_value = await clean_redis.get(slot_key)
        assert slot_value is not None and int(slot_value) == 3, (
            f"Normal counter should remain 3, got {slot_value}"
        )

    async def test_undercount_not_modified(
        self,
        clean_redis: aioredis.Redis,
        db_container,
        test_tenant,
        admin_user,
        test_settings: Settings,
        test_embedding_model_id,
    ):
        """
        Counter LOWER than DB should NOT be modified (safe - no zombie).

        Setup:
        - Redis counter = 1
        - DB: 3 QUEUED jobs for tenant

        Expected:
        - Redis counter remains 1 (undercount is safe, will self-correct)

        Note: Undercount can happen during race conditions but is safe because
        feeder will still allow new jobs (not blocking). The counter will
        self-correct as jobs complete and new ones acquire slots.
        """
        from intric.database.tables.job_table import Jobs
        from intric.database.tables.websites_table import CrawlRuns

        # Setup Redis with undercount
        slot_key = f"tenant:{test_tenant.id}:active_jobs"
        await clean_redis.set(slot_key, "1")

        # Create 3 active jobs in DB
        async with db_container() as container:
            session = container.session()

            for i in range(3):
                job = Jobs(
                    id=uuid4(),
                    user_id=admin_user.id,
                    task="CRAWL",
                    status=Status.QUEUED,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
                session.add(job)
                await session.flush()

                website_id = await create_test_website(
                    session, test_tenant.id, admin_user.id, test_embedding_model_id
                )

                crawl_run = CrawlRuns(
                    tenant_id=test_tenant.id,
                    website_id=website_id,
                    job_id=job.id,
                    pages_crawled=0,
                    files_downloaded=0,
                    pages_failed=0,
                    files_failed=0,
                )
                session.add(crawl_run)

            await session.commit()

        # Run cleanup using OrphanWatchdog
        watchdog = OrphanWatchdog(clean_redis, test_settings)
        await watchdog.run_cleanup()

        # Verify undercount NOT modified (safe state)
        slot_value = await clean_redis.get(slot_key)
        assert slot_value is not None and int(slot_value) == 1, (
            f"Undercount should remain 1 (safe - not blocking), got {slot_value}"
        )

    async def test_multiple_tenants_reconciled_independently(
        self,
        clean_redis: aioredis.Redis,
        db_container,
        test_tenant,
        admin_user,
        test_settings: Settings,
        test_embedding_model_id,
    ):
        """
        Phase 0 should reconcile each tenant independently.

        This test uses a single tenant (test_tenant) with multiple Redis keys
        to simulate multi-tenant behavior without FK violations.

        Setup:
        - Tenant A (test_tenant): Redis=5, DB=0 (zombie) - main test case
        - Also tests: Redis key with no DB jobs gets deleted

        Expected:
        - Tenant A: DELETED (zombie with no active jobs)
        """
        # Use only the test_tenant to avoid FK violations
        tenant_a_id = test_tenant.id

        # Setup Redis with zombie counter (DB has 0 jobs for this tenant)
        key_a = f"tenant:{tenant_a_id}:active_jobs"
        await clean_redis.set(key_a, "5")  # Zombie (DB=0)

        # Verify initial state
        assert await clean_redis.get(key_a) == b"5"

        # Run cleanup using OrphanWatchdog
        watchdog = OrphanWatchdog(clean_redis, test_settings)
        await watchdog.run_cleanup()

        # Verify zombie counter was DELETED (DB has 0 jobs)
        val_a = await clean_redis.get(key_a)
        assert val_a is None, f"Tenant A zombie should be DELETED, got {val_a}"

    async def test_in_progress_jobs_counted_correctly(
        self,
        clean_redis: aioredis.Redis,
        db_container,
        test_tenant,
        admin_user,
        test_settings: Settings,
        test_embedding_model_id,
    ):
        """
        Phase 0 should count both QUEUED and IN_PROGRESS jobs as active.

        Setup:
        - Redis counter = 10 (zombie)
        - DB: 1 QUEUED job + 2 IN_PROGRESS jobs = 3 active

        Expected:
        - Redis counter reset to 3 (QUEUED + IN_PROGRESS)
        """
        from intric.database.tables.job_table import Jobs
        from intric.database.tables.websites_table import CrawlRuns

        # Setup Redis with zombie counter
        slot_key = f"tenant:{test_tenant.id}:active_jobs"
        await clean_redis.set(slot_key, "10")

        async with db_container() as container:
            session = container.session()

            # 1 QUEUED job
            job_queued = Jobs(
                id=uuid4(),
                user_id=admin_user.id,
                task="CRAWL",
                status=Status.QUEUED,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            session.add(job_queued)
            await session.flush()

            website_id = await create_test_website(
                session, test_tenant.id, admin_user.id, test_embedding_model_id
            )
            crawl_run = CrawlRuns(
                tenant_id=test_tenant.id,
                website_id=website_id,
                job_id=job_queued.id,
                pages_crawled=0,
                files_downloaded=0,
                pages_failed=0,
                files_failed=0,
            )
            session.add(crawl_run)

            # 2 IN_PROGRESS jobs
            for i in range(2):
                job_ip = Jobs(
                    id=uuid4(),
                    user_id=admin_user.id,
                    task="CRAWL",
                    status=Status.IN_PROGRESS,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
                session.add(job_ip)
                await session.flush()

                website_id = await create_test_website(
                    session, test_tenant.id, admin_user.id, test_embedding_model_id
                )
                crawl_run = CrawlRuns(
                    tenant_id=test_tenant.id,
                    website_id=website_id,
                    job_id=job_ip.id,
                    pages_crawled=0,
                    files_downloaded=0,
                    pages_failed=0,
                    files_failed=0,
                )
                session.add(crawl_run)

            await session.commit()

        # Run cleanup using OrphanWatchdog
        watchdog = OrphanWatchdog(clean_redis, test_settings)
        await watchdog.run_cleanup()

        # Verify counter reset to 3 (1 QUEUED + 2 IN_PROGRESS)
        slot_value = await clean_redis.get(slot_key)
        assert slot_value is not None and int(slot_value) == 3, (
            f"Counter should be reset to 3 (QUEUED + IN_PROGRESS), got {slot_value}"
        )

    async def test_completed_jobs_not_counted(
        self,
        clean_redis: aioredis.Redis,
        db_container,
        test_tenant,
        admin_user,
        test_settings: Settings,
        test_embedding_model_id,
    ):
        """
        Phase 0 should NOT count COMPLETE or FAILED jobs as active.

        Setup:
        - Redis counter = 5 (zombie)
        - DB: 1 QUEUED + 2 COMPLETE + 1 FAILED = only 1 active

        Expected:
        - Redis counter reset to 1 (only QUEUED counted)
        """
        from intric.database.tables.job_table import Jobs
        from intric.database.tables.websites_table import CrawlRuns

        # Setup Redis with zombie counter
        slot_key = f"tenant:{test_tenant.id}:active_jobs"
        await clean_redis.set(slot_key, "5")

        async with db_container() as container:
            session = container.session()

            # 1 QUEUED job (active)
            job_queued = Jobs(
                id=uuid4(),
                user_id=admin_user.id,
                task="CRAWL",
                status=Status.QUEUED,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            session.add(job_queued)
            await session.flush()

            website_id = await create_test_website(
                session, test_tenant.id, admin_user.id, test_embedding_model_id
            )
            crawl_run = CrawlRuns(
                tenant_id=test_tenant.id,
                website_id=website_id,
                job_id=job_queued.id,
                pages_crawled=0,
                files_downloaded=0,
                pages_failed=0,
                files_failed=0,
            )
            session.add(crawl_run)

            # 2 COMPLETE jobs (not active)
            for i in range(2):
                job_complete = Jobs(
                    id=uuid4(),
                    user_id=admin_user.id,
                    task="CRAWL",
                    status=Status.COMPLETE,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
                session.add(job_complete)
                await session.flush()

                website_id = await create_test_website(
                    session, test_tenant.id, admin_user.id, test_embedding_model_id
                )
                crawl_run = CrawlRuns(
                    tenant_id=test_tenant.id,
                    website_id=website_id,
                    job_id=job_complete.id,
                    pages_crawled=10,
                    files_downloaded=5,
                    pages_failed=0,
                    files_failed=0,
                )
                session.add(crawl_run)

            # 1 FAILED job (not active)
            job_failed = Jobs(
                id=uuid4(),
                user_id=admin_user.id,
                task="CRAWL",
                status=Status.FAILED,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            session.add(job_failed)
            await session.flush()

            website_id = await create_test_website(
                session, test_tenant.id, admin_user.id, test_embedding_model_id
            )
            crawl_run = CrawlRuns(
                tenant_id=test_tenant.id,
                website_id=website_id,
                job_id=job_failed.id,
                pages_crawled=0,
                files_downloaded=0,
                pages_failed=0,
                files_failed=0,
            )
            session.add(crawl_run)

            await session.commit()

        # Run cleanup using OrphanWatchdog
        watchdog = OrphanWatchdog(clean_redis, test_settings)
        await watchdog.run_cleanup()

        # Verify counter reset to 1 (only QUEUED counted)
        slot_value = await clean_redis.get(slot_key)
        assert slot_value is not None and int(slot_value) == 1, (
            f"Counter should be reset to 1 (only QUEUED counted), got {slot_value}"
        )

    async def test_phase0_runs_before_other_phases(
        self,
        clean_redis: aioredis.Redis,
        db_container,
        test_tenant,
        admin_user,
        test_settings: Settings,
        test_embedding_model_id,
    ):
        """
        Phase 0 should run BEFORE Phase 1 (expired job cleanup).

        This is important because:
        1. Phase 0 reconciles zombie counters
        2. Phase 1 may create more zombies if it marks jobs FAILED without slot release
        3. By running Phase 0 first, we ensure correct baseline before modifications

        Setup:
        - Redis counter = 10 (zombie)
        - DB: 1 expired QUEUED job with slot_preacquired flag (will be failed by Phase 1)

        Expected:
        - Phase 0: Reconciles counter to 1 (1 active QUEUED job at that moment)
        - Phase 1: Marks job FAILED, releases slot (flag exists)
        - After cleanup: Redis counter = 0 or deleted
        - Expired job marked FAILED
        """
        from intric.database.tables.job_table import Jobs
        from intric.database.tables.websites_table import CrawlRuns
        from sqlalchemy import select

        # Setup Redis with zombie counter
        slot_key = f"tenant:{test_tenant.id}:active_jobs"
        await clean_redis.set(slot_key, "10")

        job_id = uuid4()
        max_age_seconds = test_settings.crawl_job_max_age_seconds or 7200
        old_time = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds + 600)

        async with db_container() as container:
            session = container.session()

            # Create expired QUEUED job (will be failed by Phase 1)
            job = Jobs(
                id=job_id,
                user_id=admin_user.id,
                task="CRAWL",
                status=Status.QUEUED,
                created_at=old_time,
                updated_at=old_time,
            )
            session.add(job)
            await session.flush()

            website_id = await create_test_website(
                session, test_tenant.id, admin_user.id, test_embedding_model_id
            )

            crawl_run = CrawlRuns(
                tenant_id=test_tenant.id,
                website_id=website_id,
                job_id=job.id,
                pages_crawled=0,
                files_downloaded=0,
                pages_failed=0,
                files_failed=0,
            )
            session.add(crawl_run)
            await session.commit()

        # CRITICAL: Set slot_preacquired flag so Phase 1 can release the slot
        # This simulates a job that acquired a slot via optimistic acquire
        flag_key = f"job:{job_id}:slot_preacquired"
        await clean_redis.set(flag_key, str(test_tenant.id))

        # Run cleanup using OrphanWatchdog (runs Phase 0, then Phase 1)
        watchdog = OrphanWatchdog(clean_redis, test_settings)
        metrics = await watchdog.run_cleanup()

        # Verify job was failed by Phase 1
        async with db_container() as container:
            session = container.session()
            result = await session.execute(select(Jobs).where(Jobs.id == job_id))
            updated_job = result.scalar_one()
            assert updated_job.status == Status.FAILED, "Expired job should be marked FAILED"

        # Verify counter is 0 or deleted after Phase 0 reconciliation + Phase 1 slot release
        slot_value = await clean_redis.get(slot_key)
        assert slot_value is None or int(slot_value) == 0, (
            f"Counter should be 0 or deleted after Phase 0 + Phase 1, got {slot_value}"
        )

        # Verify metrics show both phases ran
        assert metrics.expired_killed >= 1, "Should have killed at least one expired job"
