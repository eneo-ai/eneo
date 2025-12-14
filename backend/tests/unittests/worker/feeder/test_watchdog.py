"""Unit tests for the OrphanWatchdog module.

Tests the 5-phase orphan job cleanup with transaction-safe slot release.
Following TDD approach - tests define expected behavior before implementation.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


class TestWatchdogPhase0ZombieReconciliation:
    """Tests for Phase 0: Zombie counter reconciliation."""

    @pytest.mark.asyncio
    async def test_reconciles_inflated_redis_counter(self):
        """Should reset Redis counter when it exceeds actual DB active jobs."""
        from intric.worker.feeder.watchdog import OrphanWatchdog

        tenant_id = uuid4()
        redis_mock = MagicMock()
        # Redis says 5 active, but DB only has 2
        redis_mock.scan_iter = AsyncMock(
            return_value=[f"tenant:{tenant_id}:active_jobs".encode()]
        )
        redis_mock.get = AsyncMock(return_value=b"5")

        settings_mock = MagicMock()
        settings_mock.tenant_worker_semaphore_ttl_seconds = 300

        with patch(
            "intric.worker.feeder.watchdog.LuaScripts.reconcile_counter",
            new_callable=AsyncMock,
            return_value="ok:5->2",
        ) as mock_reconcile:
            watchdog = OrphanWatchdog(redis_mock, settings_mock)
            # Mock the DB query to return 2 active jobs
            result = await watchdog._reconcile_zombie_counters(
                session=MagicMock(), db_active_count=2, tenant_id=tenant_id
            )

            assert result["reconciled"] is True
            mock_reconcile.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_reconciliation_when_counts_match(self):
        """Should not reconcile when Redis counter matches DB."""
        from intric.worker.feeder.watchdog import OrphanWatchdog

        redis_mock = MagicMock()
        settings_mock = MagicMock()

        watchdog = OrphanWatchdog(redis_mock, settings_mock)
        # Redis count matches DB count
        result = await watchdog._reconcile_zombie_counters(
            session=MagicMock(), db_active_count=3, tenant_id=uuid4(), redis_count=3
        )

        assert result["reconciled"] is False

    @pytest.mark.asyncio
    async def test_handles_cas_mismatch_gracefully(self):
        """Should handle CAS mismatch (concurrent modification) gracefully."""
        from intric.worker.feeder.watchdog import OrphanWatchdog

        redis_mock = MagicMock()
        settings_mock = MagicMock()
        settings_mock.tenant_worker_semaphore_ttl_seconds = 300

        with patch(
            "intric.worker.feeder.watchdog.LuaScripts.reconcile_counter",
            new_callable=AsyncMock,
            return_value="mismatch:5->3",
        ):
            watchdog = OrphanWatchdog(redis_mock, settings_mock)
            result = await watchdog._reconcile_zombie_counters(
                session=MagicMock(),
                db_active_count=2,
                tenant_id=uuid4(),
                redis_count=5,
            )

            # Should not crash, just skip
            assert result["reconciled"] is False
            assert result.get("skipped_reason") == "cas_mismatch"


class TestWatchdogPhase1KillExpired:
    """Tests for Phase 1: Kill expired QUEUED jobs."""

    @pytest.mark.asyncio
    async def test_identifies_expired_jobs_by_created_at(self):
        """Should identify jobs where created_at exceeds max_age."""
        from intric.worker.feeder.watchdog import OrphanWatchdog

        redis_mock = MagicMock()
        settings_mock = MagicMock()
        settings_mock.crawl_job_max_age_seconds = 7200  # 2 hours

        watchdog = OrphanWatchdog(redis_mock, settings_mock)

        # Create mock expired job (created 3 hours ago)
        now = datetime.now(timezone.utc)
        expired_job = MagicMock()
        expired_job.job_id = uuid4()
        expired_job.tenant_id = uuid4()
        expired_job.created_at = now - timedelta(hours=3)

        session_mock = MagicMock()
        session_mock.execute = AsyncMock(
            return_value=MagicMock(fetchall=lambda: [expired_job])
        )

        result = await watchdog._kill_expired_jobs(session_mock, now=now)

        assert len(result.expired_job_ids) == 1
        assert expired_job.job_id in result.expired_job_ids

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_expired_jobs(self):
        """Should return empty list when no jobs exceed max_age."""
        from intric.worker.feeder.watchdog import OrphanWatchdog

        redis_mock = MagicMock()
        settings_mock = MagicMock()
        settings_mock.crawl_job_max_age_seconds = 7200

        watchdog = OrphanWatchdog(redis_mock, settings_mock)

        session_mock = MagicMock()
        session_mock.execute = AsyncMock(
            return_value=MagicMock(fetchall=lambda: [])
        )

        now = datetime.now(timezone.utc)
        result = await watchdog._kill_expired_jobs(session_mock, now=now)

        assert len(result.expired_job_ids) == 0

    @pytest.mark.asyncio
    async def test_tracks_jobs_for_slot_release(self):
        """Should track expired jobs with tenant_id for post-commit slot release."""
        from intric.worker.feeder.watchdog import OrphanWatchdog

        redis_mock = MagicMock()
        settings_mock = MagicMock()
        settings_mock.crawl_job_max_age_seconds = 7200

        watchdog = OrphanWatchdog(redis_mock, settings_mock)

        tenant_id = uuid4()
        expired_job = MagicMock()
        expired_job.job_id = uuid4()
        expired_job.tenant_id = tenant_id

        session_mock = MagicMock()
        session_mock.execute = AsyncMock(
            return_value=MagicMock(fetchall=lambda: [expired_job])
        )

        now = datetime.now(timezone.utc)
        result = await watchdog._kill_expired_jobs(session_mock, now=now)

        # Should have tenant_id for slot release
        assert len(result.slots_to_release) == 1
        assert result.slots_to_release[0].tenant_id == tenant_id


class TestWatchdogPhase2RescueStuck:
    """Tests for Phase 2: Rescue stuck QUEUED jobs."""

    @pytest.mark.asyncio
    async def test_identifies_stuck_jobs_by_stale_updated_at(self):
        """Should identify jobs with stale updated_at but fresh created_at."""
        from intric.worker.feeder.watchdog import OrphanWatchdog

        redis_mock = MagicMock()
        settings_mock = MagicMock()
        settings_mock.crawl_job_max_age_seconds = 7200

        watchdog = OrphanWatchdog(redis_mock, settings_mock)

        now = datetime.now(timezone.utc)
        # Stuck job: created 30 min ago (fresh), updated 10 min ago (stale)
        stuck_job = MagicMock()
        stuck_job.job_id = uuid4()
        stuck_job.tenant_id = uuid4()
        stuck_job.user_id = uuid4()
        stuck_job.run_id = uuid4()
        stuck_job.website_id = uuid4()
        stuck_job.url = "https://example.com"
        stuck_job.download_files = False
        stuck_job.crawl_type = "full"
        stuck_job.created_at = now - timedelta(minutes=30)
        stuck_job.updated_at = now - timedelta(minutes=10)

        session_mock = MagicMock()
        session_mock.execute = AsyncMock(
            return_value=MagicMock(fetchall=lambda: [stuck_job])
        )

        # Mock _requeue_job to isolate the test from ARQ/job_manager
        watchdog._requeue_job = AsyncMock(return_value=True)

        result = await watchdog._rescue_stuck_jobs(
            session_mock, now=now, stale_threshold_minutes=5
        )

        assert len(result.jobs_to_requeue) == 1
        watchdog._requeue_job.assert_called_once()

    @pytest.mark.asyncio
    async def test_excludes_expired_jobs_from_rescue(self):
        """Should NOT rescue jobs that are already expired (created_at > max_age)."""
        from intric.worker.feeder.watchdog import OrphanWatchdog

        redis_mock = MagicMock()
        settings_mock = MagicMock()
        settings_mock.crawl_job_max_age_seconds = 7200

        watchdog = OrphanWatchdog(redis_mock, settings_mock)

        now = datetime.now(timezone.utc)
        # This job is expired (created 3 hours ago) - should NOT be rescued
        expired_stuck_job = MagicMock()
        expired_stuck_job.job_id = uuid4()
        expired_stuck_job.created_at = now - timedelta(hours=3)
        expired_stuck_job.updated_at = now - timedelta(minutes=10)

        session_mock = MagicMock()
        # Query should filter these out, returning empty
        session_mock.execute = AsyncMock(
            return_value=MagicMock(fetchall=lambda: [])
        )

        result = await watchdog._rescue_stuck_jobs(
            session_mock, now=now, stale_threshold_minutes=5
        )

        assert len(result.jobs_to_requeue) == 0


class TestWatchdogPhase3FailLongRunning:
    """Tests for Phase 3: Fail long-running IN_PROGRESS jobs."""

    @pytest.mark.asyncio
    async def test_identifies_long_running_in_progress_jobs(self):
        """Should identify IN_PROGRESS jobs exceeding timeout."""
        from intric.worker.feeder.watchdog import OrphanWatchdog

        redis_mock = MagicMock()
        settings_mock = MagicMock()
        settings_mock.orphan_crawl_run_timeout_hours = 24

        watchdog = OrphanWatchdog(redis_mock, settings_mock)

        now = datetime.now(timezone.utc)
        # Long-running job: in progress for 30 hours
        long_running_job = MagicMock()
        long_running_job.job_id = uuid4()
        long_running_job.tenant_id = uuid4()
        long_running_job.updated_at = now - timedelta(hours=30)

        session_mock = MagicMock()
        session_mock.execute = AsyncMock(
            return_value=MagicMock(fetchall=lambda: [long_running_job])
        )

        result = await watchdog._fail_long_running_jobs(session_mock, now=now)

        assert len(result.failed_job_ids) == 1
        assert len(result.slots_to_release) == 1


class TestWatchdogSlotRelease:
    """Tests for post-transaction slot release."""

    @pytest.mark.asyncio
    async def test_releases_slots_after_transaction_commit(self):
        """Should release slots OUTSIDE the DB transaction."""
        from intric.worker.feeder.watchdog import OrphanWatchdog, SlotReleaseJob

        tenant_id = uuid4()
        job_id = uuid4()

        redis_mock = MagicMock()
        redis_mock.get = AsyncMock(return_value=str(tenant_id).encode())
        redis_mock.delete = AsyncMock()

        settings_mock = MagicMock()
        settings_mock.tenant_worker_semaphore_ttl_seconds = 300

        with patch(
            "intric.worker.feeder.watchdog.LuaScripts.release_slot",
            new_callable=AsyncMock,
        ) as mock_release:
            watchdog = OrphanWatchdog(redis_mock, settings_mock)

            slots = [SlotReleaseJob(job_id=job_id, tenant_id=tenant_id)]
            released = await watchdog._release_slots_safe(slots)

            assert released == 1
            mock_release.assert_called_once()

    @pytest.mark.asyncio
    async def test_slot_release_is_best_effort(self):
        """Should not raise on Redis errors (best effort)."""
        from intric.worker.feeder.watchdog import OrphanWatchdog, SlotReleaseJob

        redis_mock = MagicMock()
        settings_mock = MagicMock()
        settings_mock.tenant_worker_semaphore_ttl_seconds = 300

        with patch(
            "intric.worker.feeder.watchdog.LuaScripts.release_slot",
            new_callable=AsyncMock,
            side_effect=Exception("Redis connection lost"),
        ):
            watchdog = OrphanWatchdog(redis_mock, settings_mock)

            slots = [SlotReleaseJob(job_id=uuid4(), tenant_id=uuid4())]
            # Should not raise
            released = await watchdog._release_slots_safe(slots)

            assert released == 0  # Failed but didn't crash


class TestWatchdogOrchestration:
    """Tests for the main run_cleanup orchestration."""

    @pytest.mark.asyncio
    async def test_runs_all_phases_in_order(self):
        """Should execute phases 0, 1, 2, 3.5, 3 in order within transaction."""
        from intric.worker.feeder.watchdog import OrphanWatchdog

        redis_mock = MagicMock()
        redis_mock.scan_iter = AsyncMock(return_value=[])

        settings_mock = MagicMock()
        settings_mock.crawl_job_max_age_seconds = 7200
        settings_mock.orphan_crawl_run_timeout_hours = 24
        settings_mock.tenant_worker_semaphore_ttl_seconds = 300

        watchdog = OrphanWatchdog(redis_mock, settings_mock)

        # Track phase execution order
        execution_order = []

        async def mock_phase0(*args, **kwargs):
            execution_order.append("phase0")
            return {"reconciled_count": 0}

        async def mock_phase1(*args, **kwargs):
            execution_order.append("phase1")
            from intric.worker.feeder.watchdog import Phase1Result
            return Phase1Result(expired_job_ids=[], slots_to_release=[], orphaned_job_ids=[])

        async def mock_phase2(*args, **kwargs):
            execution_order.append("phase2")
            from intric.worker.feeder.watchdog import Phase2Result
            return Phase2Result(jobs_to_requeue=[], rescued_count=0)

        async def mock_phase3_5(*args, **kwargs):
            execution_order.append("phase3.5")
            from intric.worker.feeder.watchdog import Phase3_5Result
            return Phase3_5Result(failed_job_ids=[], slots_to_release=[])

        async def mock_phase3(*args, **kwargs):
            execution_order.append("phase3")
            from intric.worker.feeder.watchdog import Phase3Result
            return Phase3Result(failed_job_ids=[], slots_to_release=[])

        watchdog._run_phase0_reconciliation = mock_phase0
        watchdog._kill_expired_jobs = mock_phase1
        watchdog._rescue_stuck_jobs = mock_phase2
        watchdog._fail_stalled_startup_jobs = mock_phase3_5
        watchdog._fail_long_running_jobs = mock_phase3
        watchdog._release_slots_safe = AsyncMock(return_value=0)

        with patch("intric.database.database.sessionmanager") as mock_sm:
            mock_session = MagicMock()
            mock_session.execute = AsyncMock(return_value=MagicMock(rowcount=0))
            mock_session.begin = MagicMock(return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=None),
                __aexit__=AsyncMock(return_value=None),
            ))
            mock_sm.session = MagicMock(return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_session),
                __aexit__=AsyncMock(return_value=None),
            ))

            await watchdog.run_cleanup()

        assert execution_order == ["phase0", "phase1", "phase2", "phase3.5", "phase3"]

    @pytest.mark.asyncio
    async def test_slot_release_happens_after_db_commit(self):
        """Should release slots only AFTER transaction commits."""
        from intric.worker.feeder.watchdog import (
            OrphanWatchdog,
            Phase1Result,
            Phase2Result,
            Phase3_5Result,
            Phase3Result,
            SlotReleaseJob,
        )

        redis_mock = MagicMock()
        redis_mock.scan_iter = AsyncMock(return_value=[])

        settings_mock = MagicMock()
        settings_mock.crawl_job_max_age_seconds = 7200
        settings_mock.orphan_crawl_run_timeout_hours = 24
        settings_mock.tenant_worker_semaphore_ttl_seconds = 300

        watchdog = OrphanWatchdog(redis_mock, settings_mock)

        commit_happened = False
        slot_release_after_commit = None

        async def track_commit(*args, **kwargs):
            nonlocal commit_happened
            commit_happened = True

        async def track_slot_release(slots):
            nonlocal slot_release_after_commit
            slot_release_after_commit = commit_happened
            return len(slots)

        # Mock phases to return slots so _release_slots_safe gets called
        async def mock_phase0(*args, **kwargs):
            return {"reconciled_count": 0}

        async def mock_phase1(*args, **kwargs):
            # Return a slot to ensure slot release is triggered
            return Phase1Result(
                expired_job_ids=[uuid4()],
                slots_to_release=[SlotReleaseJob(job_id=uuid4(), tenant_id=uuid4())],
                orphaned_job_ids=[],
            )

        async def mock_phase2(*args, **kwargs):
            return Phase2Result(jobs_to_requeue=[], rescued_count=0)

        async def mock_phase3_5(*args, **kwargs):
            return Phase3_5Result(failed_job_ids=[], slots_to_release=[])

        async def mock_phase3(*args, **kwargs):
            return Phase3Result(failed_job_ids=[], slots_to_release=[])

        watchdog._run_phase0_reconciliation = mock_phase0
        watchdog._kill_expired_jobs = mock_phase1
        watchdog._rescue_stuck_jobs = mock_phase2
        watchdog._fail_stalled_startup_jobs = mock_phase3_5
        watchdog._fail_long_running_jobs = mock_phase3
        watchdog._release_slots_safe = track_slot_release

        with patch("intric.database.database.sessionmanager") as mock_sm:
            mock_session = MagicMock()
            mock_session.execute = AsyncMock(
                return_value=MagicMock(fetchall=lambda: [], rowcount=0)
            )

            # Track when commit happens via __aexit__
            mock_begin = MagicMock()
            mock_begin.__aenter__ = AsyncMock(return_value=None)
            mock_begin.__aexit__ = track_commit
            mock_session.begin = MagicMock(return_value=mock_begin)

            mock_sm.session = MagicMock(return_value=AsyncMock(
                __aenter__=AsyncMock(return_value=mock_session),
                __aexit__=AsyncMock(return_value=None),
            ))

            await watchdog.run_cleanup()

        # Slot release should have happened after commit
        assert slot_release_after_commit is True
