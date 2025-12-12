"""Integration tests for stale job preemption (commit a8f9969).

Tests the safe preemption system for stale crawl jobs:
- crawl_stale_threshold_minutes setting (5-1440 min, default from env)
- Settings flow from API through database to worker retrieval
- Stale threshold configuration for different tenants
- Multi-tenant isolation of stale detection settings

The stale job preemption system provides:
- Automatic detection of jobs stuck without progress
- Safe preemption without data loss
- Configurable threshold per tenant
- Prevention of infinite blocking from stuck jobs

Note: Full E2E testing of actual stale job detection and preemption would
require running live crawler jobs and simulating staleness conditions.
These tests verify the configuration layer that enables stale detection.
"""

import pytest
from httpx import AsyncClient

from intric.tenants.crawler_settings_helper import (
    get_crawler_setting,
)


@pytest.mark.asyncio
@pytest.mark.integration
class TestStaleThresholdConfiguration:
    """Tests that stale threshold setting configures correctly."""

    async def test_stale_threshold_setting_configured(
        self, client: AsyncClient, test_tenant, super_admin_token, db_container
    ):
        """crawl_stale_threshold_minutes flows from API to worker retrieval.

        This verifies the critical path for stale job detection:
        1. Admin sets stale threshold via API
        2. Worker retrieves threshold from database
        3. Worker uses threshold for stale job detection
        """
        # Set custom stale threshold (30 minutes)
        threshold_minutes = 30
        response = await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"crawl_stale_threshold_minutes": threshold_minutes},
            headers={"X-API-Key": super_admin_token},
        )
        assert response.status_code == 200

        # Verify worker can retrieve it
        async with db_container() as container:
            tenant_repo = container.tenant_repo()
            tenant = await tenant_repo.get(test_tenant.id)

            configured_threshold = get_crawler_setting(
                "crawl_stale_threshold_minutes",
                tenant.crawler_settings,
            )

            assert configured_threshold == threshold_minutes
            assert isinstance(configured_threshold, int)

    async def test_stale_threshold_default_value(
        self, client: AsyncClient, test_tenant, super_admin_token, db_container
    ):
        """When not set, stale threshold should use environment default."""
        # Reset settings to defaults
        await client.delete(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            headers={"X-API-Key": super_admin_token},
        )

        async with db_container() as container:
            tenant_repo = container.tenant_repo()
            tenant = await tenant_repo.get(test_tenant.id)

            # Should return environment default
            default_threshold = get_crawler_setting(
                "crawl_stale_threshold_minutes",
                tenant.crawler_settings,
            )

            # Verify it's a reasonable stale threshold
            assert isinstance(default_threshold, int)
            assert 5 <= default_threshold <= 1440, "Default should be within valid range"


@pytest.mark.asyncio
@pytest.mark.integration
class TestStaleThresholdRangeValidation:
    """Tests that stale threshold enforces its 5-1440 minute range."""

    async def test_stale_threshold_rejects_below_minimum(
        self, client: AsyncClient, test_tenant, super_admin_token
    ):
        """Stale threshold must be >= 5 minutes."""
        response = await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"crawl_stale_threshold_minutes": 2},  # Below minimum
            headers={"X-API-Key": super_admin_token},
        )
        assert response.status_code == 422, "Should reject threshold below 5 minutes"

    async def test_stale_threshold_rejects_above_maximum(
        self, client: AsyncClient, test_tenant, super_admin_token
    ):
        """Stale threshold must be <= 1440 minutes (24 hours)."""
        response = await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"crawl_stale_threshold_minutes": 2000},  # Above maximum
            headers={"X-API-Key": super_admin_token},
        )
        assert response.status_code == 422, "Should reject threshold above 1440 minutes"

    async def test_stale_threshold_accepts_valid_range(
        self, client: AsyncClient, test_tenant, super_admin_token
    ):
        """Stale threshold accepts values within 5-1440 minute range."""
        # Test minimum boundary (5 minutes)
        response = await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"crawl_stale_threshold_minutes": 5},
            headers={"X-API-Key": super_admin_token},
        )
        assert response.status_code == 200

        # Test maximum boundary (24 hours)
        response = await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"crawl_stale_threshold_minutes": 1440},
            headers={"X-API-Key": super_admin_token},
        )
        assert response.status_code == 200

        # Test common value (15 minutes)
        response = await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"crawl_stale_threshold_minutes": 15},
            headers={"X-API-Key": super_admin_token},
        )
        assert response.status_code == 200


@pytest.mark.asyncio
@pytest.mark.integration
class TestStaleThresholdMultiTenantIsolation:
    """Tests that stale thresholds are isolated between tenants."""

    async def test_different_tenants_different_stale_thresholds(
        self, client: AsyncClient, super_admin_token, db_container
    ):
        """Each tenant can have independent stale threshold configuration.

        CRITICAL: Threshold leakage would cause incorrect stale detection.
        One tenant's jobs shouldn't be preempted using another's threshold.
        """
        from uuid import uuid4

        # Create two test tenants
        tenant_1_response = await client.post(
            "/api/v1/sysadmin/tenants/",
            json={
                "name": f"tenant-stale-1-{uuid4().hex[:6]}",
                "display_name": "Aggressive Preemption Tenant",
                "state": "active",
            },
            headers={"X-API-Key": super_admin_token},
        )
        assert tenant_1_response.status_code == 200
        tenant_1 = tenant_1_response.json()

        tenant_2_response = await client.post(
            "/api/v1/sysadmin/tenants/",
            json={
                "name": f"tenant-stale-2-{uuid4().hex[:6]}",
                "display_name": "Lenient Preemption Tenant",
                "state": "active",
            },
            headers={"X-API-Key": super_admin_token},
        )
        assert tenant_2_response.status_code == 200
        tenant_2 = tenant_2_response.json()

        # Configure aggressive stale detection for tenant 1 (10 minutes)
        await client.put(
            f"/api/v1/sysadmin/tenants/{tenant_1['id']}/crawler-settings",
            json={"crawl_stale_threshold_minutes": 10},
            headers={"X-API-Key": super_admin_token},
        )

        # Configure lenient stale detection for tenant 2 (2 hours)
        await client.put(
            f"/api/v1/sysadmin/tenants/{tenant_2['id']}/crawler-settings",
            json={"crawl_stale_threshold_minutes": 120},
            headers={"X-API-Key": super_admin_token},
        )

        # Verify isolation
        async with db_container() as container:
            tenant_repo = container.tenant_repo()

            # Get tenant 1
            t1 = await tenant_repo.get(tenant_1["id"])
            t1_threshold = get_crawler_setting(
                "crawl_stale_threshold_minutes", t1.crawler_settings
            )

            # Get tenant 2
            t2 = await tenant_repo.get(tenant_2["id"])
            t2_threshold = get_crawler_setting(
                "crawl_stale_threshold_minutes", t2.crawler_settings
            )

            # Verify complete isolation
            assert t1_threshold == 10, "Tenant 1 should have aggressive threshold"
            assert t2_threshold == 120, "Tenant 2 should have lenient threshold"


@pytest.mark.asyncio
@pytest.mark.integration
class TestStaleThresholdUpdatePropagation:
    """Tests that stale threshold changes propagate immediately."""

    async def test_stale_threshold_change_visible_immediately(
        self, client: AsyncClient, test_tenant, super_admin_token, db_container
    ):
        """Stale threshold changes should apply to next job evaluation.

        This ensures updated threshold is used for stale detection without restart.
        """
        # Initial threshold (30 minutes)
        await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={"crawl_stale_threshold_minutes": 30},
            headers={"X-API-Key": super_admin_token},
        )

        async with db_container() as container:
            tenant_repo = container.tenant_repo()

            # First read
            tenant = await tenant_repo.get(test_tenant.id)
            threshold_1 = get_crawler_setting(
                "crawl_stale_threshold_minutes", tenant.crawler_settings
            )
            assert threshold_1 == 30

            # Update threshold (15 minutes for faster preemption)
            await client.put(
                f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
                json={"crawl_stale_threshold_minutes": 15},
                headers={"X-API-Key": super_admin_token},
            )

            # Second read (simulating next stale check)
            tenant = await tenant_repo.get(test_tenant.id)
            threshold_2 = get_crawler_setting(
                "crawl_stale_threshold_minutes", tenant.crawler_settings
            )
            assert threshold_2 == 15, "Updated threshold should be visible immediately"


@pytest.mark.asyncio
@pytest.mark.integration
class TestStaleThresholdUseCases:
    """Tests for different stale threshold use cases."""

    async def test_short_crawls_use_short_stale_threshold(
        self, client: AsyncClient, test_tenant, super_admin_token, db_container
    ):
        """Short crawls should use short stale threshold for quick preemption."""
        # Set short crawl duration with short stale threshold
        await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={
                "crawl_max_length": 600,  # 10 minute crawl
                "crawl_stale_threshold_minutes": 5,  # 5 minute stale threshold
            },
            headers={"X-API-Key": super_admin_token},
        )

        async with db_container() as container:
            tenant_repo = container.tenant_repo()
            tenant = await tenant_repo.get(test_tenant.id)

            max_length = get_crawler_setting("crawl_max_length", tenant.crawler_settings)
            stale_threshold = get_crawler_setting(
                "crawl_stale_threshold_minutes", tenant.crawler_settings
            )

            # Verify configuration makes sense
            assert max_length == 600
            assert stale_threshold == 5
            stale_threshold_seconds = stale_threshold * 60
            assert stale_threshold_seconds < max_length, (
                "Stale threshold should be shorter than max crawl length"
            )

    async def test_long_crawls_use_long_stale_threshold(
        self, client: AsyncClient, test_tenant, super_admin_token, db_container
    ):
        """Long crawls can use longer stale threshold to avoid false positives."""
        # Set long crawl duration with longer stale threshold
        await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={
                "crawl_max_length": 21600,  # 6 hour crawl
                "crawl_stale_threshold_minutes": 60,  # 1 hour stale threshold
            },
            headers={"X-API-Key": super_admin_token},
        )

        async with db_container() as container:
            tenant_repo = container.tenant_repo()
            tenant = await tenant_repo.get(test_tenant.id)

            max_length = get_crawler_setting("crawl_max_length", tenant.crawler_settings)
            stale_threshold = get_crawler_setting(
                "crawl_stale_threshold_minutes", tenant.crawler_settings
            )

            # Verify configuration makes sense
            assert max_length == 21600
            assert stale_threshold == 60
            stale_threshold_seconds = stale_threshold * 60
            assert stale_threshold_seconds < max_length, (
                "Stale threshold should be shorter than max crawl length"
            )


@pytest.mark.asyncio
@pytest.mark.integration
class TestStaleThresholdWithHeartbeat:
    """Tests stale threshold interaction with heartbeat settings."""

    async def test_stale_threshold_longer_than_heartbeat(
        self, client: AsyncClient, test_tenant, super_admin_token, db_container
    ):
        """Stale threshold should be longer than heartbeat interval.

        If heartbeat fires before stale threshold, job won't be falsely marked stale.
        """
        # Configure with sensible relationship
        await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={
                "crawl_heartbeat_interval_seconds": 300,  # 5 minutes
                "crawl_stale_threshold_minutes": 15,  # 15 minutes
            },
            headers={"X-API-Key": super_admin_token},
        )

        async with db_container() as container:
            tenant_repo = container.tenant_repo()
            tenant = await tenant_repo.get(test_tenant.id)

            heartbeat_seconds = get_crawler_setting(
                "crawl_heartbeat_interval_seconds", tenant.crawler_settings
            )
            stale_minutes = get_crawler_setting(
                "crawl_stale_threshold_minutes", tenant.crawler_settings
            )

            # Verify sensible relationship
            stale_seconds = stale_minutes * 60
            assert stale_seconds > heartbeat_seconds, (
                "Stale threshold should be longer than heartbeat to allow heartbeats to fire"
            )

            # Verify there's enough buffer for multiple heartbeats
            heartbeats_before_stale = stale_seconds / heartbeat_seconds
            assert heartbeats_before_stale >= 2, (
                "Should allow at least 2 heartbeats before marking stale"
            )

    async def test_conservative_stale_detection_configuration(
        self, client: AsyncClient, test_tenant, super_admin_token, db_container
    ):
        """Conservative configuration allows multiple heartbeats before stale detection."""
        # Conservative: stale threshold much longer than heartbeat
        await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={
                "crawl_heartbeat_interval_seconds": 120,  # 2 minutes
                "crawl_stale_threshold_minutes": 20,  # 20 minutes
            },
            headers={"X-API-Key": super_admin_token},
        )

        async with db_container() as container:
            tenant_repo = container.tenant_repo()
            tenant = await tenant_repo.get(test_tenant.id)

            heartbeat_seconds = get_crawler_setting(
                "crawl_heartbeat_interval_seconds", tenant.crawler_settings
            )
            stale_minutes = get_crawler_setting(
                "crawl_stale_threshold_minutes", tenant.crawler_settings
            )

            stale_seconds = stale_minutes * 60
            expected_heartbeats = stale_seconds / heartbeat_seconds

            # Should allow 10 heartbeats before stale detection
            assert expected_heartbeats == 10, (
                "Conservative config should allow many heartbeats before stale detection"
            )


@pytest.mark.asyncio
@pytest.mark.integration
class TestStaleThresholdWithJobMaxAge:
    """Tests stale threshold interaction with job max age settings."""

    async def test_stale_threshold_vs_job_max_age(
        self, client: AsyncClient, test_tenant, super_admin_token, db_container
    ):
        """Stale threshold and job max age serve different purposes.

        - Stale threshold: No activity/progress for N minutes → preempt
        - Job max age: Job has been retrying for N seconds → fail permanently

        Both can be configured independently for different failure modes.
        """
        await client.put(
            f"/api/v1/sysadmin/tenants/{test_tenant.id}/crawler-settings",
            json={
                "crawl_stale_threshold_minutes": 10,  # No progress for 10 min
                "crawl_job_max_age_seconds": 3600,  # Retrying for 1 hour
            },
            headers={"X-API-Key": super_admin_token},
        )

        async with db_container() as container:
            tenant_repo = container.tenant_repo()
            tenant = await tenant_repo.get(test_tenant.id)

            stale_minutes = get_crawler_setting(
                "crawl_stale_threshold_minutes", tenant.crawler_settings
            )
            max_age_seconds = get_crawler_setting(
                "crawl_job_max_age_seconds", tenant.crawler_settings
            )

            # Both settings configured independently
            assert stale_minutes == 10
            assert max_age_seconds == 3600

            # Stale threshold is for lack of progress
            # Max age is for total retry duration
            # They serve complementary purposes


@pytest.mark.asyncio
@pytest.mark.integration
class TestJobRepoTouchJob:
    """Tests for JobRepository.touch_job() heartbeat method.

    touch_job() updates a job's updated_at timestamp to signal "still alive".
    This prevents safe preemption from marking the job as stale during long crawls.
    """

    async def test_touch_job_updates_timestamp(
        self, db_container, admin_user
    ):
        """touch_job() should update the job's updated_at timestamp."""
        from datetime import datetime, timezone, timedelta
        from intric.database.tables.job_table import Jobs
        from intric.jobs.job_repo import JobRepository
        from intric.main.models import Status

        async with db_container() as container:
            session = container.session()

            # Create a job with old updated_at
            old_time = datetime.now(timezone.utc) - timedelta(hours=1)
            job = Jobs(
                user_id=admin_user.id,
                task="CRAWL",
                status=Status.IN_PROGRESS,
                created_at=old_time,
                updated_at=old_time,
            )
            session.add(job)
            await session.flush()

            job_id = job.id
            original_updated_at = job.updated_at

            # Touch the job
            job_repo = JobRepository(session)
            await job_repo.touch_job(job_id)
            await session.flush()

            # Refresh to get updated value
            await session.refresh(job)

            # Verify timestamp was updated
            assert job.updated_at > original_updated_at, "touch_job should update timestamp"
            # Should be recent (within last minute)
            time_diff = datetime.now(timezone.utc) - job.updated_at.replace(tzinfo=timezone.utc)
            assert time_diff.total_seconds() < 60, "Timestamp should be recent"

    async def test_touch_job_prevents_stale_detection(
        self, db_container, admin_user, test_settings
    ):
        """Regular touch_job() calls should keep job under stale threshold."""
        from datetime import datetime, timezone
        from intric.database.tables.job_table import Jobs
        from intric.jobs.job_repo import JobRepository
        from intric.main.models import Status

        async with db_container() as container:
            session = container.session()

            # Create a job
            job = Jobs(
                user_id=admin_user.id,
                task="CRAWL",
                status=Status.IN_PROGRESS,
            )
            session.add(job)
            await session.flush()

            job_id = job.id
            job_repo = JobRepository(session)

            # Touch the job
            await job_repo.touch_job(job_id)
            await session.flush()
            await session.refresh(job)

            # Calculate age
            job_updated = job.updated_at.replace(tzinfo=timezone.utc)
            age_minutes = (datetime.now(timezone.utc) - job_updated).total_seconds() / 60
            threshold_minutes = test_settings.crawl_stale_threshold_minutes

            # Should be well under stale threshold
            assert age_minutes < threshold_minutes, (
                "Touched job should be under stale threshold"
            )

    async def test_touch_job_nonexistent_job_no_error(
        self, db_container
    ):
        """touch_job() on non-existent job should not raise error."""
        from uuid import uuid4
        from intric.jobs.job_repo import JobRepository

        async with db_container() as container:
            session = container.session()
            job_repo = JobRepository(session)

            # Touch non-existent job - should not raise
            await job_repo.touch_job(uuid4())
            # No assertion needed - just verifying no exception


@pytest.mark.asyncio
@pytest.mark.integration
class TestJobRepoMarkJobFailedIfRunning:
    """Tests for JobRepository.mark_job_failed_if_running() atomic preemption.

    This method uses Compare-and-Swap pattern to atomically mark a job as FAILED
    only if it's currently IN_PROGRESS or QUEUED. This prevents race conditions
    when multiple users try to preempt the same stale job.
    """

    async def test_marks_queued_job_as_failed(
        self, db_container, admin_user
    ):
        """mark_job_failed_if_running() should fail QUEUED jobs."""
        from intric.database.tables.job_table import Jobs
        from intric.jobs.job_repo import JobRepository
        from intric.main.models import Status

        async with db_container() as container:
            session = container.session()

            # Create a QUEUED job
            job = Jobs(
                user_id=admin_user.id,
                task="CRAWL",
                status=Status.QUEUED,
            )
            session.add(job)
            await session.flush()

            job_id = job.id
            job_repo = JobRepository(session)

            # Mark as failed
            rows_affected = await job_repo.mark_job_failed_if_running(
                job_id, "Preempted: stale job"
            )
            await session.flush()
            await session.refresh(job)

            assert rows_affected == 1, "Should affect 1 row"
            assert job.status == Status.FAILED, "Job should be FAILED"

    async def test_marks_in_progress_job_as_failed(
        self, db_container, admin_user
    ):
        """mark_job_failed_if_running() should fail IN_PROGRESS jobs."""
        from intric.database.tables.job_table import Jobs
        from intric.jobs.job_repo import JobRepository
        from intric.main.models import Status

        async with db_container() as container:
            session = container.session()

            # Create an IN_PROGRESS job
            job = Jobs(
                user_id=admin_user.id,
                task="CRAWL",
                status=Status.IN_PROGRESS,
            )
            session.add(job)
            await session.flush()

            job_id = job.id
            job_repo = JobRepository(session)

            # Mark as failed
            rows_affected = await job_repo.mark_job_failed_if_running(
                job_id, "Worker crashed"
            )
            await session.flush()
            await session.refresh(job)

            assert rows_affected == 1, "Should affect 1 row"
            assert job.status == Status.FAILED, "Job should be FAILED"

    async def test_does_not_affect_completed_job(
        self, db_container, admin_user
    ):
        """mark_job_failed_if_running() should not touch COMPLETE jobs."""
        from intric.database.tables.job_table import Jobs
        from intric.jobs.job_repo import JobRepository
        from intric.main.models import Status

        async with db_container() as container:
            session = container.session()

            # Create a COMPLETE job
            job = Jobs(
                user_id=admin_user.id,
                task="CRAWL",
                status=Status.COMPLETE,
            )
            session.add(job)
            await session.flush()

            job_id = job.id
            job_repo = JobRepository(session)

            # Try to mark as failed
            rows_affected = await job_repo.mark_job_failed_if_running(
                job_id, "This should not apply"
            )
            await session.flush()
            await session.refresh(job)

            assert rows_affected == 0, "Should not affect completed job"
            assert job.status == Status.COMPLETE, "Status should remain COMPLETE"

    async def test_does_not_affect_already_failed_job(
        self, db_container, admin_user
    ):
        """mark_job_failed_if_running() should not touch already FAILED jobs."""
        from intric.database.tables.job_table import Jobs
        from intric.jobs.job_repo import JobRepository
        from intric.main.models import Status

        async with db_container() as container:
            session = container.session()

            # Create a FAILED job
            job = Jobs(
                user_id=admin_user.id,
                task="CRAWL",
                status=Status.FAILED,
            )
            session.add(job)
            await session.flush()

            job_id = job.id
            job_repo = JobRepository(session)

            # Try to mark as failed again
            rows_affected = await job_repo.mark_job_failed_if_running(
                job_id, "New error message"
            )
            await session.flush()
            await session.refresh(job)

            assert rows_affected == 0, "Should not affect already failed job"
            assert job.status == Status.FAILED

    async def test_compare_and_swap_race_condition_prevention(
        self, db_container, admin_user
    ):
        """Only one concurrent preemption attempt should succeed.

        This tests the Compare-and-Swap pattern: when multiple processes
        try to preempt the same job, only one should win.
        """
        from intric.database.tables.job_table import Jobs
        from intric.jobs.job_repo import JobRepository
        from intric.main.models import Status

        async with db_container() as container:
            session = container.session()

            # Create a QUEUED job
            job = Jobs(
                user_id=admin_user.id,
                task="CRAWL",
                status=Status.QUEUED,
            )
            session.add(job)
            await session.flush()

            job_id = job.id
            job_repo = JobRepository(session)

            # First preemption attempt (should succeed)
            rows_1 = await job_repo.mark_job_failed_if_running(
                job_id, "First preemption"
            )
            await session.flush()

            # Second preemption attempt (should fail - job already failed)
            rows_2 = await job_repo.mark_job_failed_if_running(
                job_id, "Second preemption"
            )
            await session.flush()

            await session.refresh(job)

            # Only first attempt should succeed
            assert rows_1 == 1, "First attempt should succeed"
            assert rows_2 == 0, "Second attempt should fail (job already failed)"
            assert job.status == Status.FAILED, "Job should be in FAILED status"

    async def test_nonexistent_job_returns_zero(
        self, db_container
    ):
        """mark_job_failed_if_running() on non-existent job returns 0."""
        from uuid import uuid4
        from intric.jobs.job_repo import JobRepository

        async with db_container() as container:
            session = container.session()
            job_repo = JobRepository(session)

            # Try to mark non-existent job
            rows_affected = await job_repo.mark_job_failed_if_running(
                uuid4(), "Non-existent job"
            )

            assert rows_affected == 0, "Should return 0 for non-existent job"
