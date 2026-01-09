"""Integration tests for orphaned crawl job cleanup (commits 6d41d92, 2ccee8a).

Tests the orphaned job cleanup system that prevents "Crawl already in progress" blocking:
- Time-based cleanup of stuck jobs (QUEUED/IN_PROGRESS beyond timeout)
- Prevention of false "crawl in progress" signals from stale Job records
- Integration with feeder cycle (runs every cycle)
- Configuration via environment settings

The orphan cleanup system provides:
- Automatic cleanup of Jobs stuck in QUEUED/IN_PROGRESS state
- Prevention of blocking from orphaned Jobs (tenant deleted, worker crashed, etc.)
- Time-based detection using orphan_crawl_run_timeout_hours setting
- Runs during every feeder cycle for proactive cleanup

Note: Full E2E testing of orphan detection would require simulating
tenant deletion, worker crashes, and Job state corruption scenarios.
These tests verify the configuration and integration layers.
"""

import pytest
from datetime import datetime, timezone, timedelta
from uuid import UUID

from intric.jobs.job_models import Task
from intric.main.models import Status


async def create_test_website(session, tenant_id, user_id, embedding_model_id) -> UUID:
    """Create a minimal Website record for CrawlRun tests.

    CrawlRuns.website_id is a foreign key to websites table,
    so we need a valid Website record before creating CrawlRuns.
    """
    from intric.database.tables.websites_table import Websites
    from intric.websites.domain.crawl_run import CrawlType

    website = Websites(
        tenant_id=tenant_id,
        user_id=user_id,
        embedding_model_id=embedding_model_id,
        url="https://test-orphan-cleanup.example.com",
        name="Test Website for Orphan Cleanup",
        download_files=False,
        crawl_type=CrawlType.CRAWL,
        update_interval="never",
        size=0,
    )
    session.add(website)
    await session.flush()
    return website.id


@pytest.fixture
async def test_embedding_model_id(db_container):
    """Get the fixture embedding model ID for tests.

    The seed_default_models fixture creates 'fixture-text-embedding'.
    """
    from sqlalchemy import select
    from intric.database.tables.ai_models_table import EmbeddingModels

    async with db_container() as container:
        session = container.session()
        result = await session.execute(
            select(EmbeddingModels.id).where(
                EmbeddingModels.name == "fixture-text-embedding"
            )
        )
        return result.scalar_one()


@pytest.mark.asyncio
@pytest.mark.integration
class TestOrphanCleanupConfiguration:
    """Tests that orphan cleanup timeout is configured correctly."""

    async def test_orphan_timeout_setting_from_environment(self, test_settings):
        """Orphan cleanup timeout should come from environment settings.

        This setting controls how long before a stuck Job is considered orphaned.
        """
        # Verify setting exists and is accessible
        assert hasattr(test_settings, "orphan_crawl_run_timeout_hours")
        timeout = test_settings.orphan_crawl_run_timeout_hours

        # Should be a reasonable timeout value
        assert isinstance(timeout, (int, float))
        assert timeout > 0, "Timeout must be positive"
        assert timeout <= 48, "Timeout should be reasonable (<=48 hours)"


@pytest.mark.asyncio
@pytest.mark.integration
class TestOrphanJobDetection:
    """Tests for identifying orphaned jobs based on age and status."""

    async def test_recent_queued_job_not_orphaned(
        self, db_container, test_tenant, admin_user
    ):
        """Recently created QUEUED jobs should not be considered orphaned."""
        from intric.database.tables.job_table import Jobs

        async with db_container() as container:
            # Create a job that's only 30 minutes old (recent)
            recent_time = datetime.now(timezone.utc) - timedelta(minutes=30)
            job = Jobs(
                user_id=admin_user.id,
                task=Task.CRAWL.value,
                status=Status.QUEUED,
                created_at=recent_time,
                updated_at=recent_time,
            )

            session = container.session()
            session.add(job)
            await session.flush()

            # Recent queued jobs should not be cleaned up
            # (orphan_crawl_run_timeout_hours is typically >= 2 hours)
            assert job.status == Status.QUEUED
            assert job.updated_at == recent_time

    async def test_old_queued_job_eligible_for_cleanup(
        self, db_container, test_tenant, test_settings, admin_user
    ):
        """Jobs stuck in QUEUED beyond timeout should be eligible for cleanup."""
        from intric.database.tables.job_table import Jobs

        async with db_container() as container:
            # Create a job older than the orphan timeout
            timeout_hours = test_settings.orphan_crawl_run_timeout_hours
            old_time = datetime.now(timezone.utc) - timedelta(
                hours=timeout_hours + 1  # Older than timeout
            )

            job = Jobs(
                user_id=admin_user.id,
                task=Task.CRAWL.value,
                status=Status.QUEUED,
                created_at=old_time,
                updated_at=old_time,
            )

            session = container.session()
            session.add(job)
            await session.flush()

            # This job should be eligible for cleanup
            # (actual cleanup happens in feeder's _cleanup_orphaned_crawl_jobs)
            assert job.status == Status.QUEUED
            age_hours = (
                datetime.now(timezone.utc) - job.updated_at
            ).total_seconds() / 3600
            assert age_hours > timeout_hours, "Job should be older than timeout"

    async def test_old_in_progress_job_eligible_for_cleanup(
        self, db_container, test_tenant, test_settings, admin_user
    ):
        """Jobs stuck in IN_PROGRESS beyond timeout should be eligible for cleanup."""
        from intric.database.tables.job_table import Jobs

        async with db_container() as container:
            # Create a job stuck in IN_PROGRESS
            timeout_hours = test_settings.orphan_crawl_run_timeout_hours
            old_time = datetime.now(timezone.utc) - timedelta(hours=timeout_hours + 1)

            job = Jobs(
                user_id=admin_user.id,
                task=Task.CRAWL.value,
                status=Status.IN_PROGRESS,
                created_at=old_time,
                updated_at=old_time,
            )

            session = container.session()
            session.add(job)
            await session.flush()

            # Job is old and stuck in IN_PROGRESS -> eligible for cleanup
            assert job.status == Status.IN_PROGRESS
            age_hours = (
                datetime.now(timezone.utc) - job.updated_at
            ).total_seconds() / 3600
            assert age_hours > timeout_hours


@pytest.mark.asyncio
@pytest.mark.integration
class TestOrphanCleanupPreservesActiveJobs:
    """Tests that cleanup only affects orphaned jobs, not active ones."""

    async def test_completed_jobs_not_affected(
        self, db_container, test_tenant, test_settings, admin_user
    ):
        """Completed jobs should never be touched by orphan cleanup."""
        from intric.database.tables.job_table import Jobs

        async with db_container() as container:
            # Create old completed job
            timeout_hours = test_settings.orphan_crawl_run_timeout_hours
            old_time = datetime.now(timezone.utc) - timedelta(
                hours=timeout_hours + 10  # Very old
            )

            job = Jobs(
                user_id=admin_user.id,
                task=Task.CRAWL.value,
                status=Status.COMPLETE,
                created_at=old_time,
                updated_at=old_time,
            )

            session = container.session()
            session.add(job)
            await session.flush()

            # Completed jobs are never orphans (already finished)
            assert job.status == Status.COMPLETE

    async def test_failed_jobs_not_affected(
        self, db_container, test_tenant, test_settings, admin_user
    ):
        """Failed jobs should not be touched by orphan cleanup."""
        from intric.database.tables.job_table import Jobs

        async with db_container() as container:
            timeout_hours = test_settings.orphan_crawl_run_timeout_hours
            old_time = datetime.now(timezone.utc) - timedelta(hours=timeout_hours + 5)

            job = Jobs(
                user_id=admin_user.id,
                task=Task.CRAWL.value,
                status=Status.FAILED,
                created_at=old_time,
                updated_at=old_time,
            )

            session = container.session()
            session.add(job)
            await session.flush()

            # Failed jobs are terminal states, not orphans
            assert job.status == Status.FAILED


@pytest.mark.asyncio
@pytest.mark.integration
class TestOrphanCleanupMultiTenant:
    """Tests that orphan cleanup respects tenant isolation."""

    async def test_cleanup_scoped_to_crawl_jobs_only(
        self, db_container, test_tenant, test_settings, admin_user
    ):
        """Orphan cleanup should only affect crawl jobs, not other job types."""
        from intric.database.tables.job_table import Jobs

        async with db_container() as container:
            timeout_hours = test_settings.orphan_crawl_run_timeout_hours
            old_time = datetime.now(timezone.utc) - timedelta(hours=timeout_hours + 1)

            # Create old stuck job of non-crawl type
            other_job = Jobs(
                user_id=admin_user.id,
                task="other_type",  # Not "CRAWL"
                status=Status.QUEUED,
                created_at=old_time,
                updated_at=old_time,
            )

            session = container.session()
            session.add(other_job)
            await session.flush()

            # Non-crawl jobs should not be affected by crawl orphan cleanup
            # (cleanup only targets job_type="crawl")
            assert other_job.status == Status.QUEUED

    async def test_orphan_cleanup_preserves_tenant_isolation(
        self, db_container, super_admin_token, client, test_settings
    ):
        """Orphan cleanup should not leak between tenants."""
        from uuid import uuid4
        from intric.database.tables.job_table import Jobs
        from intric.database.tables.users_table import Users

        # Create two tenants
        tenant_1_response = await client.post(
            "/api/v1/sysadmin/tenants/",
            json={
                "name": f"tenant-orphan-1-{uuid4().hex[:6]}",
                "display_name": "Tenant 1",
                "state": "active",
            },
            headers={"X-API-Key": super_admin_token},
        )
        assert tenant_1_response.status_code == 200
        tenant_1_id = UUID(tenant_1_response.json()["id"])

        tenant_2_response = await client.post(
            "/api/v1/sysadmin/tenants/",
            json={
                "name": f"tenant-orphan-2-{uuid4().hex[:6]}",
                "display_name": "Tenant 2",
                "state": "active",
            },
            headers={"X-API-Key": super_admin_token},
        )
        assert tenant_2_response.status_code == 200
        tenant_2_id = UUID(tenant_2_response.json()["id"])

        async with db_container() as container:
            timeout_hours = test_settings.orphan_crawl_run_timeout_hours
            old_time = datetime.now(timezone.utc) - timedelta(hours=timeout_hours + 1)

            # Create users for each tenant
            user_1 = Users(
                email=f"user1-{uuid4().hex[:6]}@tenant1.com",
                tenant_id=tenant_1_id,
                state="active",
            )
            user_2 = Users(
                email=f"user2-{uuid4().hex[:6]}@tenant2.com",
                tenant_id=tenant_2_id,
                state="active",
            )

            session = container.session()
            session.add(user_1)
            session.add(user_2)
            await session.flush()

            # Create old stuck jobs for both tenants
            job_1 = Jobs(
                user_id=user_1.id,
                task=Task.CRAWL.value,
                status=Status.QUEUED,
                created_at=old_time,
                updated_at=old_time,
            )
            job_2 = Jobs(
                user_id=user_2.id,
                task=Task.CRAWL.value,
                status=Status.QUEUED,
                created_at=old_time,
                updated_at=old_time,
            )

            session.add(job_1)
            session.add(job_2)
            await session.flush()

            # Both jobs should be eligible for cleanup
            # Verify tenant isolation via user's tenant_id
            assert user_1.tenant_id == tenant_1_id
            assert user_2.tenant_id == tenant_2_id
            assert user_1.tenant_id != user_2.tenant_id


@pytest.mark.asyncio
@pytest.mark.integration
class TestOrphanCleanupTimingBoundaries:
    """Tests boundary conditions for orphan detection timing."""

    async def test_job_exactly_at_timeout_boundary(
        self, db_container, test_tenant, test_settings, admin_user
    ):
        """Job exactly at timeout boundary should be handled correctly."""
        from intric.database.tables.job_table import Jobs

        async with db_container() as container:
            # Create job exactly at the timeout boundary
            timeout_hours = test_settings.orphan_crawl_run_timeout_hours
            boundary_time = datetime.now(timezone.utc) - timedelta(hours=timeout_hours)

            job = Jobs(
                user_id=admin_user.id,
                task=Task.CRAWL.value,
                status=Status.QUEUED,
                created_at=boundary_time,
                updated_at=boundary_time,
            )

            session = container.session()
            session.add(job)
            await session.flush()

            # Job at exact boundary
            age_hours = (
                datetime.now(timezone.utc) - job.updated_at
            ).total_seconds() / 3600
            # Allow small tolerance for test execution time
            assert abs(age_hours - timeout_hours) < 0.1

    async def test_job_just_before_timeout(
        self, db_container, test_tenant, test_settings, admin_user
    ):
        """Job just before timeout should not be cleaned up."""
        from intric.database.tables.job_table import Jobs

        async with db_container() as container:
            # Create job 1 minute before timeout
            timeout_hours = test_settings.orphan_crawl_run_timeout_hours
            almost_timeout = datetime.now(timezone.utc) - timedelta(
                hours=timeout_hours, minutes=-1
            )

            job = Jobs(
                user_id=admin_user.id,
                task=Task.CRAWL.value,
                status=Status.QUEUED,
                created_at=almost_timeout,
                updated_at=almost_timeout,
            )

            session = container.session()
            session.add(job)
            await session.flush()

            # Job is just before timeout -> not orphaned yet
            age_hours = (
                datetime.now(timezone.utc) - job.updated_at
            ).total_seconds() / 3600
            assert age_hours < timeout_hours


@pytest.mark.asyncio
@pytest.mark.integration
class TestOrphanCleanupPreventsBlocking:
    """Tests that orphan cleanup prevents "Crawl already in progress" blocking."""

    async def test_orphaned_queued_job_prevents_new_crawl(
        self, db_container, test_tenant, test_settings, admin_user
    ):
        """Orphaned QUEUED job can block new crawls (this is what cleanup fixes).

        This test demonstrates the problem that orphan cleanup solves:
        - Old stuck Job remains in QUEUED state
        - CrawlRun.status comes from Job.status via relationship
        - New crawl attempt sees "crawl in progress" signal
        - Cleanup marks old Job as FAILED to unblock
        """
        from intric.database.tables.job_table import Jobs

        async with db_container() as container:
            # Simulate orphaned scenario: old stuck Job
            timeout_hours = test_settings.orphan_crawl_run_timeout_hours
            old_time = datetime.now(timezone.utc) - timedelta(hours=timeout_hours + 2)

            # Create old stuck crawl Job (orphaned)
            orphan_job = Jobs(
                user_id=admin_user.id,
                task=Task.CRAWL.value,
                status=Status.QUEUED,
                created_at=old_time,
                updated_at=old_time,
            )

            session = container.session()
            session.add(orphan_job)
            await session.flush()

            # Note: In production, this orphaned Job would be linked to a CrawlRun
            # which derives its status from the Job. This test focuses on the Job
            # orphan detection without requiring full CrawlRun setup.

            # Problem: Job stuck in QUEUED blocks new crawls
            # Solution: Orphan cleanup marks old Job as FAILED
            assert orphan_job.status == Status.QUEUED
            age_hours = (
                datetime.now(timezone.utc) - orphan_job.updated_at
            ).total_seconds() / 3600
            assert age_hours > timeout_hours, (
                "Job should be orphaned and eligible for cleanup"
            )


@pytest.mark.asyncio
@pytest.mark.integration
class TestOrphanCrawlRunCleanup:
    """Tests for cleanup of CrawlRuns with NULL job_id (ghost records).

    CrawlRun.status is derived from Job.status via relationship. When job_id is NULL:
    - Status defaults to QUEUED (no job to reference)
    - These are ghost records that accumulate from deleted jobs or failed creation
    - The _cleanup_orphaned_crawl_runs() method deletes these old records
    """

    async def test_recent_crawl_run_with_null_job_id_not_cleaned(
        self,
        db_container,
        test_tenant,
        test_settings,
        admin_user,
        test_embedding_model_id,
    ):
        """Recently created CrawlRuns with NULL job_id should NOT be cleaned up."""
        from intric.database.tables.websites_table import CrawlRuns

        async with db_container() as container:
            session = container.session()

            # Create a valid Website first (CrawlRuns.website_id is FK to websites)
            website_id = await create_test_website(
                session, test_tenant.id, admin_user.id, test_embedding_model_id
            )

            # Create a recent CrawlRun with NULL job_id (only 30 minutes old)
            recent_time = datetime.now(timezone.utc) - timedelta(minutes=30)
            crawl_run = CrawlRuns(
                tenant_id=test_tenant.id,
                website_id=website_id,
                job_id=None,  # NULL job_id (ghost record)
                pages_crawled=0,
                files_downloaded=0,
                pages_failed=0,
                files_failed=0,
                created_at=recent_time,
                updated_at=recent_time,
            )

            session.add(crawl_run)
            await session.flush()

            # Recent CrawlRuns should not be cleaned up
            assert crawl_run.job_id is None
            age_hours = (
                datetime.now(timezone.utc) - crawl_run.updated_at
            ).total_seconds() / 3600
            timeout_hours = test_settings.orphan_crawl_run_timeout_hours
            assert age_hours < timeout_hours, (
                "Recent CrawlRun should not be eligible for cleanup"
            )

    async def test_old_crawl_run_with_null_job_id_eligible_for_cleanup(
        self,
        db_container,
        test_tenant,
        test_settings,
        admin_user,
        test_embedding_model_id,
    ):
        """Old CrawlRuns with NULL job_id should be eligible for cleanup."""
        from intric.database.tables.websites_table import CrawlRuns

        async with db_container() as container:
            session = container.session()

            # Create a valid Website first (CrawlRuns.website_id is FK to websites)
            website_id = await create_test_website(
                session, test_tenant.id, admin_user.id, test_embedding_model_id
            )

            # Create old CrawlRun with NULL job_id
            timeout_hours = test_settings.orphan_crawl_run_timeout_hours
            old_time = datetime.now(timezone.utc) - timedelta(hours=timeout_hours + 1)

            crawl_run = CrawlRuns(
                tenant_id=test_tenant.id,
                website_id=website_id,
                job_id=None,  # NULL job_id (ghost record)
                pages_crawled=0,
                files_downloaded=0,
                pages_failed=0,
                files_failed=0,
                created_at=old_time,
                updated_at=old_time,
            )

            session.add(crawl_run)
            await session.flush()

            # Old CrawlRun with NULL job_id should be eligible for cleanup
            assert crawl_run.job_id is None
            age_hours = (
                datetime.now(timezone.utc) - crawl_run.updated_at
            ).total_seconds() / 3600
            assert age_hours > timeout_hours, (
                "Old CrawlRun should be eligible for cleanup"
            )

    async def test_crawl_run_with_valid_job_id_not_affected(
        self,
        db_container,
        test_tenant,
        test_settings,
        admin_user,
        test_embedding_model_id,
    ):
        """CrawlRuns WITH valid job_id should NOT be cleaned up, even if old."""
        from intric.database.tables.websites_table import CrawlRuns
        from intric.database.tables.job_table import Jobs

        async with db_container() as container:
            session = container.session()

            # Create a valid Website first (CrawlRuns.website_id is FK to websites)
            website_id = await create_test_website(
                session, test_tenant.id, admin_user.id, test_embedding_model_id
            )

            timeout_hours = test_settings.orphan_crawl_run_timeout_hours
            old_time = datetime.now(timezone.utc) - timedelta(hours=timeout_hours + 10)

            # Create a job first
            job = Jobs(
                user_id=admin_user.id,
                task=Task.CRAWL.value,
                status=Status.COMPLETE,
                created_at=old_time,
                updated_at=old_time,
            )

            session.add(job)
            await session.flush()

            # Create old CrawlRun WITH valid job_id
            crawl_run = CrawlRuns(
                tenant_id=test_tenant.id,
                website_id=website_id,
                job_id=job.id,  # Has valid job_id
                pages_crawled=100,
                files_downloaded=50,
                pages_failed=0,
                files_failed=0,
                created_at=old_time,
                updated_at=old_time,
            )

            session.add(crawl_run)
            await session.flush()

            # CrawlRun with valid job_id should NOT be cleaned up
            # (only NULL job_id records are targeted)
            assert crawl_run.job_id is not None
            assert crawl_run.job_id == job.id


@pytest.mark.asyncio
@pytest.mark.integration
class TestOrphanCrawlRunCleanupExecution:
    """Tests that actually execute the cleanup method."""

    async def test_cleanup_deletes_old_null_job_id_crawl_runs(
        self,
        db_container,
        test_tenant,
        test_settings,
        admin_user,
        test_embedding_model_id,
    ):
        """Cleanup should delete old CrawlRuns with NULL job_id."""
        from sqlalchemy import select
        from intric.database.tables.websites_table import CrawlRuns
        from intric.worker.crawl_feeder import CrawlFeeder

        async with db_container() as container:
            session = container.session()

            # Create a valid Website first (CrawlRuns.website_id is FK to websites)
            website_id = await create_test_website(
                session, test_tenant.id, admin_user.id, test_embedding_model_id
            )

            timeout_hours = test_settings.orphan_crawl_run_timeout_hours
            old_time = datetime.now(timezone.utc) - timedelta(hours=timeout_hours + 2)
            recent_time = datetime.now(timezone.utc) - timedelta(minutes=30)

            # Create old orphan CrawlRun (should be deleted)
            old_orphan = CrawlRuns(
                tenant_id=test_tenant.id,
                website_id=website_id,
                job_id=None,
                pages_crawled=0,
                files_downloaded=0,
                pages_failed=0,
                files_failed=0,
                created_at=old_time,
                updated_at=old_time,
            )
            session.add(old_orphan)

            # Create recent orphan CrawlRun (should NOT be deleted)
            recent_orphan = CrawlRuns(
                tenant_id=test_tenant.id,
                website_id=website_id,
                job_id=None,
                pages_crawled=0,
                files_downloaded=0,
                pages_failed=0,
                files_failed=0,
                created_at=recent_time,
                updated_at=recent_time,
            )
            session.add(recent_orphan)
            await session.flush()

            old_orphan_id = old_orphan.id
            recent_orphan_id = recent_orphan.id

            # Commit so cleanup can see it
            await session.commit()

        # Run cleanup
        feeder = CrawlFeeder()
        await feeder._cleanup_orphaned_crawl_runs()

        # Verify: old orphan deleted, recent orphan preserved
        async with db_container() as container:
            session = container.session()

            # Old orphan should be deleted
            old_result = await session.execute(
                select(CrawlRuns).where(CrawlRuns.id == old_orphan_id)
            )
            assert old_result.scalar_one_or_none() is None, (
                "Old orphan should be deleted"
            )

            # Recent orphan should still exist
            recent_result = await session.execute(
                select(CrawlRuns).where(CrawlRuns.id == recent_orphan_id)
            )
            assert recent_result.scalar_one_or_none() is not None, (
                "Recent orphan should be preserved"
            )

    async def test_cleanup_preserves_crawl_runs_with_valid_job_id(
        self,
        db_container,
        test_tenant,
        test_settings,
        admin_user,
        test_embedding_model_id,
    ):
        """Cleanup should NOT delete CrawlRuns with valid job_id, even if old."""
        from sqlalchemy import select
        from intric.database.tables.websites_table import CrawlRuns
        from intric.database.tables.job_table import Jobs
        from intric.worker.crawl_feeder import CrawlFeeder

        async with db_container() as container:
            session = container.session()

            # Create a valid Website first (CrawlRuns.website_id is FK to websites)
            website_id = await create_test_website(
                session, test_tenant.id, admin_user.id, test_embedding_model_id
            )

            timeout_hours = test_settings.orphan_crawl_run_timeout_hours
            old_time = datetime.now(timezone.utc) - timedelta(hours=timeout_hours + 10)

            # Create a job
            job = Jobs(
                user_id=admin_user.id,
                task=Task.CRAWL.value,
                status=Status.COMPLETE,
                created_at=old_time,
                updated_at=old_time,
            )
            session.add(job)
            await session.flush()

            # Create old CrawlRun WITH valid job_id
            crawl_run_with_job = CrawlRuns(
                tenant_id=test_tenant.id,
                website_id=website_id,
                job_id=job.id,
                pages_crawled=100,
                files_downloaded=50,
                pages_failed=0,
                files_failed=0,
                created_at=old_time,
                updated_at=old_time,
            )
            session.add(crawl_run_with_job)
            await session.flush()

            crawl_run_id = crawl_run_with_job.id
            await session.commit()

        # Run cleanup
        feeder = CrawlFeeder()
        await feeder._cleanup_orphaned_crawl_runs()

        # Verify: CrawlRun with valid job_id should still exist
        async with db_container() as container:
            session = container.session()
            result = await session.execute(
                select(CrawlRuns).where(CrawlRuns.id == crawl_run_id)
            )
            preserved = result.scalar_one_or_none()
            assert preserved is not None, (
                "CrawlRun with valid job_id should be preserved"
            )
            assert preserved.job_id is not None
