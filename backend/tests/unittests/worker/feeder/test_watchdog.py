"""Unit tests for the OrphanWatchdog module.

Tests the 5-phase orphan job cleanup with transaction-safe slot release.
Following TDD approach - tests define expected behavior before implementation.
"""

import ast
import json
import re
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


def _compiled_params(stmt: object) -> dict[str, object]:
    compile_stmt = getattr(stmt, "compile", None)
    assert callable(compile_stmt)
    params = compile_stmt().params
    assert isinstance(params, Mapping)
    return dict(params)


def _compiled_where_clause(stmt: object) -> str:
    compile_stmt = getattr(stmt, "compile", None)
    assert callable(compile_stmt)
    sql = str(compile_stmt())
    _, where_clause = sql.split("WHERE", maxsplit=1)
    return where_clause


def _executed_statement_params_containing(
    session_mock: MagicMock,
    param_name: str,
) -> dict[str, object]:
    """Return the first executed SQL statement carrying the expected parameter."""
    for call in session_mock.execute.call_args_list:
        params = _compiled_params(call.args[0])
        if param_name in params:
            return params

    raise AssertionError(f"No executed statement contained parameter {param_name!r}")


def _source_tree(relative_path: str) -> ast.Module:
    source_path = Path(__file__).parents[4] / relative_path
    return ast.parse(source_path.read_text())


def _imports_name(tree: ast.AST, *, module: str, name: str) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == module:
            if any(alias.name == name for alias in node.names):
                return True
    return False


def _calls_attribute(tree: ast.AST, attribute_name: str) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == attribute_name:
                return True
    return False


def test_worker_runtime_arq_jobs_imports_stay_behind_typed_boundaries() -> None:
    worker_root = Path(__file__).parents[4] / "src/intric/worker"
    offenders: list[str] = []
    for source_path in worker_root.rglob("*.py"):
        tree = ast.parse(source_path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "arq.jobs":
                offenders.append(str(source_path.relative_to(worker_root)))
            elif isinstance(node, ast.ImportFrom) and node.module == "arq":
                if any(alias.name == "jobs" for alias in node.names):
                    offenders.append(str(source_path.relative_to(worker_root)))
            elif isinstance(node, ast.Import):
                if any(alias.name == "arq.jobs" for alias in node.names):
                    offenders.append(str(source_path.relative_to(worker_root)))

    assert offenders == []


class TestWatchdogRequeue:
    """Tests for watchdog requeue idempotency boundaries."""

    def test_watchdog_requeue_does_not_construct_arq_job_directly(self):
        source_path = Path(__file__).parents[4] / "src/intric/worker/feeder/watchdog.py"
        source = source_path.read_text()

        assert not re.search(r"from arq\.jobs import .*\bJob\b", source)
        assert not re.search(r"\bJob\(job_id=str\(", source)

    @pytest.mark.asyncio
    async def test_requeue_uses_typed_status_and_enqueue_owners(self):
        from intric.worker.feeder.crawl_enqueue import (
            CrawlEnqueued,
        )
        from intric.worker.feeder.crawl_status import (
            CrawlJobStatus,
            CrawlJobStatusKnown,
        )
        from intric.worker.feeder.watchdog import OrphanWatchdog

        redis_mock = MagicMock()
        settings_mock = MagicMock()
        watchdog = OrphanWatchdog(redis_mock, settings_mock)
        job_id = uuid4()
        user_id = uuid4()
        run_id = uuid4()
        website_id = uuid4()

        with (
            patch(
                "intric.worker.feeder.watchdog.get_crawl_job_status",
                new=AsyncMock(
                    return_value=CrawlJobStatusKnown(
                        job_id=job_id,
                        status=CrawlJobStatus.NOT_FOUND,
                    )
                ),
            ) as get_crawl_job_status,
            patch(
                "intric.worker.feeder.watchdog.enqueue_crawl_job",
                new=AsyncMock(return_value=CrawlEnqueued(job_id=job_id)),
            ) as enqueue_crawl_job,
        ):
            requeued = await watchdog._requeue_job(
                job_id=job_id,
                user_id=user_id,
                run_id=run_id,
                tenant_id=uuid4(),
                website_id=website_id,
                url="https://example.com",
                download_files=False,
                crawl_type="crawl",
            )

        assert requeued is True
        get_crawl_job_status.assert_awaited_once_with(job_id)
        enqueue_crawl_job.assert_awaited_once()
        call_kwargs = enqueue_crawl_job.await_args.kwargs
        assert call_kwargs["job_id"] == job_id
        assert call_kwargs["user_id"] == user_id
        assert call_kwargs["run_id"] == run_id
        assert call_kwargs["website_id"] == website_id

    @pytest.mark.asyncio
    async def test_requeue_skips_when_typed_status_owner_sees_existing_arq_job(self):
        from intric.worker.feeder.crawl_status import (
            CrawlJobStatus,
            CrawlJobStatusKnown,
        )
        from intric.worker.feeder.watchdog import OrphanWatchdog

        redis_mock = MagicMock()
        settings_mock = MagicMock()
        watchdog = OrphanWatchdog(redis_mock, settings_mock)
        job_id = uuid4()

        with (
            patch(
                "intric.worker.feeder.watchdog.get_crawl_job_status",
                new=AsyncMock(
                    return_value=CrawlJobStatusKnown(
                        job_id=job_id,
                        status=CrawlJobStatus.QUEUED,
                    )
                ),
            ),
            patch(
                "intric.worker.feeder.watchdog.enqueue_crawl_job",
                new=AsyncMock(),
            ) as enqueue_crawl_job,
        ):
            requeued = await watchdog._requeue_job(
                job_id=job_id,
                user_id=uuid4(),
                run_id=uuid4(),
                tenant_id=uuid4(),
                website_id=uuid4(),
                url="https://example.com",
                download_files=False,
                crawl_type="crawl",
            )

        assert requeued is False
        enqueue_crawl_job.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_requeue_does_not_parse_duplicate_exception_text(self):
        """ARQ duplicates are represented by enqueue(False), not exception text."""
        from intric.worker.feeder.crawl_enqueue import (
            CrawlEnqueueFailed,
        )
        from intric.worker.feeder.crawl_status import (
            CrawlJobStatus,
            CrawlJobStatusKnown,
        )
        from intric.worker.feeder.watchdog import OrphanWatchdog

        redis_mock = MagicMock()
        settings_mock = MagicMock()
        watchdog = OrphanWatchdog(redis_mock, settings_mock)
        expected_error = Exception("Job already exists")

        with (
            patch(
                "intric.worker.feeder.watchdog.get_crawl_job_status",
                new=AsyncMock(
                    return_value=CrawlJobStatusKnown(
                        job_id=uuid4(),
                        status=CrawlJobStatus.NOT_FOUND,
                    )
                ),
            ),
            patch(
                "intric.worker.feeder.watchdog.enqueue_crawl_job",
                new=AsyncMock(
                    return_value=CrawlEnqueueFailed(
                        job_id=uuid4(),
                        error=expected_error,
                    )
                ),
            ),
        ):
            with pytest.raises(Exception) as exc_info:
                await watchdog._requeue_job(
                    job_id=uuid4(),
                    user_id=uuid4(),
                    run_id=uuid4(),
                    tenant_id=uuid4(),
                    website_id=uuid4(),
                    url="https://example.com",
                    download_files=False,
                    crawl_type="crawl",
                )

        assert exc_info.value is expected_error


class TestWatchdogPhase0ZombieReconciliation:
    """Tests for Phase 0: Zombie counter reconciliation."""

    def test_phase0_redis_boundary_is_canonical(self):
        tree = _source_tree("src/intric/worker/feeder/watchdog.py")

        assert not _imports_name(tree, module="typing", name="Any")
        assert not _calls_attribute(tree, "scan_iter")
        assert _imports_name(
            tree,
            module="intric.worker.redis.client",
            name="redis_scan_match_bytes",
        )

    @pytest.mark.asyncio
    async def test_phase0_uses_typed_scan_boundary(self):
        from intric.worker.feeder import watchdog as watchdog_module
        from intric.worker.feeder.watchdog import OrphanWatchdog

        tenant_a = uuid4()
        tenant_b = uuid4()
        keys = [
            f"tenant:{tenant_a}:active_jobs".encode(),
            f"tenant:{tenant_b}:active_jobs".encode(),
        ]
        scanned_patterns: list[tuple[object, str, int]] = []

        async def scan_keys(redis: object, *, pattern: str, count: int):
            scanned_patterns.append((redis, pattern, count))
            for key in keys:
                yield key

        redis_mock = MagicMock()
        settings_mock = MagicMock()
        session_mock = MagicMock()
        watchdog = OrphanWatchdog(redis_mock, settings_mock)
        reconcile_results = iter(
            [
                {"reconciled": True},
                {"reconciled": False},
            ]
        )
        reconciled_keys: list[bytes] = []

        async def reconcile_counter(session: object, key: bytes):
            assert session is session_mock
            reconciled_keys.append(key)
            return next(reconcile_results)

        watchdog._reconcile_single_counter = reconcile_counter

        with patch.object(
            watchdog_module,
            "redis_scan_match_bytes",
            scan_keys,
        ):
            result = await watchdog._run_phase0_reconciliation(session_mock)

        assert result == {"reconciled_count": 1}
        assert scanned_patterns == [(redis_mock, "tenant:*:active_jobs", 100)]
        assert reconciled_keys == keys

    @pytest.mark.asyncio
    async def test_reconciles_inflated_redis_counter(self):
        """Should reset Redis counter when it exceeds actual DB active jobs."""
        from intric.worker.feeder.watchdog import OrphanWatchdog

        tenant_id = uuid4()
        redis_mock = MagicMock()
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
        session_mock.execute = AsyncMock(return_value=MagicMock(fetchall=lambda: []))

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
        stuck_job.crawl_type = "crawl"
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
    async def test_rescue_does_not_count_job_already_present_in_arq(self):
        """Should not bump rescued count when ARQ already has the queued job."""
        from intric.worker.feeder.watchdog import OrphanWatchdog

        redis_mock = MagicMock()
        settings_mock = MagicMock()
        settings_mock.crawl_job_max_age_seconds = 7200

        watchdog = OrphanWatchdog(redis_mock, settings_mock)

        now = datetime.now(timezone.utc)
        stuck_job = MagicMock()
        stuck_job.job_id = uuid4()
        stuck_job.tenant_id = uuid4()
        stuck_job.user_id = uuid4()
        stuck_job.run_id = uuid4()
        stuck_job.website_id = uuid4()
        stuck_job.url = "https://example.com"
        stuck_job.download_files = False
        stuck_job.crawl_type = "crawl"
        stuck_job.created_at = now - timedelta(minutes=30)
        stuck_job.updated_at = now - timedelta(minutes=10)
        stuck_job.crawler_settings = {}

        session_mock = MagicMock()
        session_mock.execute = AsyncMock(
            return_value=MagicMock(fetchall=lambda: [stuck_job])
        )

        watchdog._requeue_job = AsyncMock(return_value=False)

        result = await watchdog._rescue_stuck_jobs(
            session_mock, now=now, stale_threshold_minutes=5
        )

        assert result.jobs_to_requeue == []
        assert result.rescued_count == 0
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
        session_mock.execute = AsyncMock(return_value=MagicMock(fetchall=lambda: []))

        result = await watchdog._rescue_stuck_jobs(
            session_mock, now=now, stale_threshold_minutes=5
        )

        assert len(result.jobs_to_requeue) == 0


class TestWatchdogPhase3FailLongRunning:
    """Tests for Phase 3: Fail long-running IN_PROGRESS jobs."""

    @pytest.mark.asyncio
    async def test_identifies_long_running_in_progress_jobs(self):
        """Should identify IN_PROGRESS jobs exceeding timeout."""
        from intric.websites.domain.crawl_outcome import CrawlOutcomeCode
        from intric.worker.feeder.watchdog import OrphanWatchdog

        redis_mock = MagicMock()
        settings_mock = MagicMock()
        settings_mock.orphan_crawl_run_timeout_hours = 24

        watchdog = OrphanWatchdog(redis_mock, settings_mock)

        now = datetime.now(timezone.utc)
        # Long-running job: in progress for 30 hours
        long_running_job = MagicMock()
        long_running_job.job_id = uuid4()
        long_running_job.status = "in progress"
        long_running_job.crawl_run_id = uuid4()
        long_running_job.website_id = uuid4()
        long_running_job.tenant_id = uuid4()
        long_running_job.finished_at = None
        long_running_job.pages_crawled = 1
        long_running_job.files_downloaded = 0
        long_running_job.pages_failed = 0
        long_running_job.files_failed = 0
        long_running_job.pages_source_retained = 0
        long_running_job.pages_hash_retained = 0
        long_running_job.files_hash_retained = 0
        long_running_job.files_too_large_skipped = 0
        long_running_job.updated_at = now - timedelta(hours=30)

        session_mock = MagicMock()
        session_mock.execute = AsyncMock(
            return_value=MagicMock(fetchall=lambda: [long_running_job])
        )

        result = await watchdog._fail_long_running_jobs(session_mock, now=now)

        assert len(result.failed_job_ids) == 1
        assert len(result.slots_to_release) == 1
        emitted_sql = "\n".join(
            str(call.args[0]) for call in session_mock.execute.call_args_list
        )
        assert "finished_at" in emitted_sql
        assert "result_location" in emitted_sql
        crawl_run_update_params = _executed_statement_params_containing(
            session_mock, "outcome_code"
        )
        assert (
            crawl_run_update_params["outcome_code"]
            == CrawlOutcomeCode.CRAWL_RUNTIME_TIMEOUT.value
        )

    @pytest.mark.asyncio
    async def test_records_lifecycle_observation_without_changing_selection(self):
        from intric.worker.feeder.watchdog import OrphanWatchdog

        redis_mock = MagicMock()
        settings_mock = MagicMock()
        settings_mock.orphan_crawl_run_timeout_hours = 24

        watchdog = OrphanWatchdog(redis_mock, settings_mock)

        now = datetime.now(timezone.utc)
        long_running_job = MagicMock()
        long_running_job.job_id = uuid4()
        long_running_job.status = "in progress"
        long_running_job.crawl_run_id = uuid4()
        long_running_job.website_id = uuid4()
        long_running_job.tenant_id = uuid4()
        long_running_job.finished_at = None
        long_running_job.pages_crawled = 7
        long_running_job.files_downloaded = 0
        long_running_job.pages_failed = 0
        long_running_job.files_failed = 0
        long_running_job.pages_source_retained = 0
        long_running_job.pages_hash_retained = 0
        long_running_job.files_hash_retained = 0
        long_running_job.files_too_large_skipped = 0

        session_mock = MagicMock()
        session_mock.execute = AsyncMock(
            return_value=MagicMock(fetchall=lambda: [long_running_job])
        )

        result = await watchdog._fail_long_running_jobs(session_mock, now=now)

        assert result.failed_job_ids == [long_running_job.job_id]
        assert result.lifecycle_observed.running_with_progress == 1
        where_clause = _compiled_where_clause(
            session_mock.execute.call_args_list[0].args[0]
        )
        assert "crawl_runs.pages_crawled IS NULL" not in where_clause
        assert "crawl_runs.pages_crawled =" not in where_clause

    @pytest.mark.asyncio
    async def test_records_terminal_lifecycle_observation_for_finished_row(self):
        from intric.worker.feeder.watchdog import OrphanWatchdog

        redis_mock = MagicMock()
        settings_mock = MagicMock()
        settings_mock.orphan_crawl_run_timeout_hours = 24

        watchdog = OrphanWatchdog(redis_mock, settings_mock)

        now = datetime.now(timezone.utc)
        long_running_job = MagicMock()
        long_running_job.job_id = uuid4()
        long_running_job.status = "in progress"
        long_running_job.crawl_run_id = uuid4()
        long_running_job.website_id = uuid4()
        long_running_job.tenant_id = uuid4()
        long_running_job.finished_at = now
        long_running_job.pages_crawled = 7
        long_running_job.files_downloaded = 0
        long_running_job.pages_failed = 0
        long_running_job.files_failed = 0
        long_running_job.pages_source_retained = 0
        long_running_job.pages_hash_retained = 0
        long_running_job.files_hash_retained = 0
        long_running_job.files_too_large_skipped = 0

        session_mock = MagicMock()
        session_mock.execute = AsyncMock(
            return_value=MagicMock(fetchall=lambda: [long_running_job])
        )

        result = await watchdog._fail_long_running_jobs(session_mock, now=now)

        assert result.lifecycle_observed.terminal == 1


class TestWatchdogPhase35FailStalledStartup:
    """Tests for Phase 3.5: fail IN_PROGRESS crawls that never made progress."""

    @pytest.mark.asyncio
    async def test_marks_stalled_startup_job_with_failure_detail_and_outcome(self):
        from intric.websites.domain.crawl_outcome import CrawlOutcomeCode
        from intric.worker.feeder.watchdog import OrphanWatchdog

        redis_mock = MagicMock()
        settings_mock = MagicMock()
        settings_mock.crawl_heartbeat_interval_seconds = 300
        settings_mock.crawl_heartbeat_max_failures = 3

        watchdog = OrphanWatchdog(redis_mock, settings_mock)

        stalled_job = MagicMock()
        stalled_job.job_id = uuid4()
        stalled_job.status = "in progress"
        stalled_job.tenant_id = uuid4()
        stalled_job.crawl_run_id = uuid4()
        stalled_job.website_id = uuid4()
        stalled_job.finished_at = None
        stalled_job.pages_crawled = 0
        stalled_job.files_downloaded = 0
        stalled_job.pages_failed = 0
        stalled_job.files_failed = 0
        stalled_job.pages_source_retained = 0
        stalled_job.pages_hash_retained = 0
        stalled_job.files_hash_retained = 0
        stalled_job.files_too_large_skipped = 0

        session_mock = MagicMock()
        session_mock.execute = AsyncMock(
            return_value=MagicMock(fetchall=lambda: [stalled_job])
        )

        result = await watchdog._fail_stalled_startup_jobs(
            session_mock, now=datetime.now(timezone.utc)
        )

        assert result.failed_job_ids == [stalled_job.job_id]
        assert len(result.slots_to_release) == 1
        emitted_sql = "\n".join(
            str(call.args[0]) for call in session_mock.execute.call_args_list
        )
        assert "finished_at" in emitted_sql
        assert "result_location" in emitted_sql
        crawl_run_update_params = _executed_statement_params_containing(
            session_mock, "outcome_code"
        )
        assert (
            crawl_run_update_params["outcome_code"]
            == CrawlOutcomeCode.CRAWL_TIMEOUT_NO_PAGES.value
        )

    @pytest.mark.asyncio
    async def test_records_lifecycle_observation_without_changing_selection(self):
        from intric.worker.feeder.watchdog import OrphanWatchdog

        redis_mock = MagicMock()
        settings_mock = MagicMock()
        settings_mock.crawl_heartbeat_interval_seconds = 300
        settings_mock.crawl_heartbeat_max_failures = 3

        watchdog = OrphanWatchdog(redis_mock, settings_mock)

        stalled_job = MagicMock()
        stalled_job.job_id = uuid4()
        stalled_job.status = "in progress"
        stalled_job.crawl_run_id = uuid4()
        stalled_job.website_id = uuid4()
        stalled_job.tenant_id = uuid4()
        stalled_job.finished_at = None
        stalled_job.pages_crawled = 0
        stalled_job.files_downloaded = 1
        stalled_job.pages_failed = 0
        stalled_job.files_failed = 0
        stalled_job.pages_source_retained = 0
        stalled_job.pages_hash_retained = 0
        stalled_job.files_hash_retained = 0
        stalled_job.files_too_large_skipped = 0

        session_mock = MagicMock()
        session_mock.execute = AsyncMock(
            return_value=MagicMock(fetchall=lambda: [stalled_job])
        )

        result = await watchdog._fail_stalled_startup_jobs(
            session_mock, now=datetime.now(timezone.utc)
        )

        assert result.failed_job_ids == [stalled_job.job_id]
        assert result.lifecycle_observed.running_with_progress == 1
        where_clause = _compiled_where_clause(
            session_mock.execute.call_args_list[0].args[0]
        )
        assert "crawl_runs.pages_crawled IS NULL" in where_clause
        assert "crawl_runs.pages_crawled =" in where_clause
        assert "crawl_runs.files_" not in where_clause

    @pytest.mark.asyncio
    async def test_records_no_progress_lifecycle_observation(self):
        from intric.worker.feeder.watchdog import OrphanWatchdog

        redis_mock = MagicMock()
        settings_mock = MagicMock()
        settings_mock.crawl_heartbeat_interval_seconds = 300
        settings_mock.crawl_heartbeat_max_failures = 3

        watchdog = OrphanWatchdog(redis_mock, settings_mock)

        stalled_job = MagicMock()
        stalled_job.job_id = uuid4()
        stalled_job.status = "in progress"
        stalled_job.crawl_run_id = uuid4()
        stalled_job.website_id = uuid4()
        stalled_job.tenant_id = uuid4()
        stalled_job.finished_at = None
        stalled_job.pages_crawled = 0
        stalled_job.files_downloaded = 0
        stalled_job.pages_failed = 0
        stalled_job.files_failed = 0
        stalled_job.pages_source_retained = 0
        stalled_job.pages_hash_retained = 0
        stalled_job.files_hash_retained = 0
        stalled_job.files_too_large_skipped = 0

        session_mock = MagicMock()
        session_mock.execute = AsyncMock(
            return_value=MagicMock(fetchall=lambda: [stalled_job])
        )

        result = await watchdog._fail_stalled_startup_jobs(
            session_mock, now=datetime.now(timezone.utc)
        )

        assert result.lifecycle_observed.running_no_progress == 1


class TestWatchdogSlotRelease:
    """Tests for post-transaction slot release."""

    def test_watchdog_delegates_slot_release_storage_to_capacity_manager(self):
        source_path = Path(__file__).parents[4] / "src/intric/worker/feeder/watchdog.py"
        source = source_path.read_text()

        assert "LuaScripts.preacquired_slot_key" not in source
        assert "LuaScripts.release_slot" not in source

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
            "intric.worker.feeder.capacity.LuaScripts.release_slot",
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
            "intric.worker.feeder.capacity.LuaScripts.release_slot",
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

            return Phase1Result(
                expired_job_ids=[], slots_to_release=[], orphaned_job_ids=[]
            )

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
            mock_session.begin = MagicMock(
                return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=None),
                    __aexit__=AsyncMock(return_value=None),
                )
            )
            mock_sm.session = MagicMock(
                return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=mock_session),
                    __aexit__=AsyncMock(return_value=None),
                )
            )

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

            mock_sm.session = MagicMock(
                return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=mock_session),
                    __aexit__=AsyncMock(return_value=None),
                )
            )

            await watchdog.run_cleanup()

        # Slot release should have happened after commit
        assert slot_release_after_commit is True

    @pytest.mark.asyncio
    async def test_run_cleanup_merges_watchdog_lifecycle_observations(self):
        from intric.worker.feeder.watchdog import (
            OrphanWatchdog,
            Phase1Result,
            Phase2Result,
            Phase3_5Result,
            Phase3Result,
            WatchdogLifecycleCounts,
        )

        redis_mock = MagicMock()
        redis_mock.scan_iter = AsyncMock(return_value=[])
        redis_mock.set = AsyncMock()

        settings_mock = MagicMock()
        settings_mock.crawl_job_max_age_seconds = 7200
        settings_mock.orphan_crawl_run_timeout_hours = 24
        settings_mock.tenant_worker_semaphore_ttl_seconds = 300
        settings_mock.crawl_feeder_interval_seconds = 10

        watchdog = OrphanWatchdog(redis_mock, settings_mock)
        watchdog._run_phase0_reconciliation = AsyncMock(
            return_value={"reconciled_count": 0}
        )
        watchdog._kill_expired_jobs = AsyncMock(return_value=Phase1Result())
        watchdog._rescue_stuck_jobs = AsyncMock(return_value=Phase2Result())
        watchdog._fail_stalled_startup_jobs = AsyncMock(
            return_value=Phase3_5Result(
                lifecycle_observed=WatchdogLifecycleCounts(running_no_progress=2)
            )
        )
        watchdog._fail_long_running_jobs = AsyncMock(
            return_value=Phase3Result(
                lifecycle_observed=WatchdogLifecycleCounts(running_with_progress=3)
            )
        )
        watchdog._release_slots_safe = AsyncMock(return_value=0)

        with patch("intric.database.database.sessionmanager") as mock_sm:
            mock_session = MagicMock()
            mock_session.begin = MagicMock(
                return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=None),
                    __aexit__=AsyncMock(return_value=None),
                )
            )
            mock_sm.session = MagicMock(
                return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=mock_session),
                    __aexit__=AsyncMock(return_value=None),
                )
            )

            metrics = await watchdog.run_cleanup()

        assert metrics.lifecycle_observed.running_no_progress == 2
        assert metrics.lifecycle_observed.running_with_progress == 3

    @pytest.mark.asyncio
    async def test_metrics_snapshot_includes_lifecycle_observations(self):
        from intric.worker.feeder.watchdog import (
            CleanupMetrics,
            OrphanWatchdog,
            WatchdogLifecycleCounts,
        )

        redis_mock = MagicMock()
        redis_mock.set = AsyncMock()

        settings_mock = MagicMock()
        settings_mock.crawl_feeder_interval_seconds = 10

        watchdog = OrphanWatchdog(redis_mock, settings_mock)
        metrics = CleanupMetrics(
            lifecycle_observed=WatchdogLifecycleCounts(
                running_no_progress=2,
                running_with_progress=3,
            )
        )

        await watchdog._write_metrics_snapshot(metrics)

        payload = json.loads(redis_mock.set.call_args.args[1])
        assert payload["lifecycle_observed"] == {
            "queued": 0,
            "running_no_progress": 2,
            "running_with_progress": 3,
            "terminal": 0,
        }
