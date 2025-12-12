"""Crawl Feeder Service - Pull-based queueing to prevent burst overload.

Why: When schedulers trigger, they may queue dozens of websites simultaneously.
This overwhelms per-tenant concurrency limits, causing retry storms and queue congestion.

How: Feeder observes existing TenantConcurrencyLimiter state and meters enqueue rate:
- Scheduler adds jobs to pending Redis list (not directly to ARQ)
- Feeder checks active_jobs count every 10s
- Enqueues to ARQ only when capacity exists (active < max_concurrent)
- Worker uses existing limiter.acquire/release (unchanged)

Result: Smooth, predictable enqueue rate instead of burst spikes.
Reuses existing concurrency infrastructure, no parallel permit system needed.
"""

import asyncio
import json
import socket
from datetime import datetime, timedelta, timezone
from uuid import UUID

import redis.asyncio as aioredis

from intric.jobs.job_manager import job_manager
from intric.main.config import get_settings
from intric.main.logging import get_logger
from intric.tenants.crawler_settings_helper import get_crawler_setting

logger = get_logger(__name__)


class CrawlFeeder:
    """Meters crawl job enqueue rate based on available concurrency capacity.

    Why: Prevents burst overload by only enqueueing when capacity exists.
    Observes the existing TenantConcurrencyLimiter state (active_jobs counter).

    Note: This service is long-running and manages its own DB sessions and Redis client.
    It does NOT depend on a request-scoped Container to avoid session lifecycle issues.
    """

    def __init__(self):
        self.settings = get_settings()
        self._running = False
        self._redis_client: aioredis.Redis | None = None
        # Cache worker_id at init to avoid blocking I/O in async loop
        # Why: socket.gethostname() is sync and may trigger DNS lookup
        self._worker_id = socket.gethostname()
        # Heartbeat tracking - log idle status every 5 minutes instead of every cycle
        self._last_heartbeat: datetime | None = None
        self._heartbeat_interval = 300  # 5 minutes

    async def _try_acquire_leader_lock(
        self, redis_client: aioredis.Redis
    ) -> bool:
        """Try to acquire leader lock for feeder singleton.

        Why: Ensures only ONE feeder runs even with multiple worker processes.
        Uses Redis SET NX with TTL for automatic failover if leader crashes.

        Returns:
            True if lock acquired (this instance is leader), False otherwise
        """
        key = "crawl_feeder:leader"
        ttl = 30  # Lock expires after 30 seconds for automatic failover

        try:
            # Atomic SET with NX (only if not exists) and EX (expiry)
            # Why: If another feeder holds the lock, this returns False
            acquired = await redis_client.set(key, self._worker_id, nx=True, ex=ttl)
            return bool(acquired)
        except Exception as exc:
            logger.warning(
                "Failed to acquire feeder leader lock",
                extra={"error": str(exc)},
            )
            return False

    # Lua script for ownership-safe leader lock refresh
    # Why: Prevents any process from extending another process's lock
    # Only the actual lock owner (verified by value match) can extend TTL
    # Returns: 1 if refreshed successfully, 0 if not owner or lock doesn't exist
    _refresh_lock_lua: str = (
        "local key = KEYS[1]\n"
        "local expected_owner = ARGV[1]\n"
        "local ttl = tonumber(ARGV[2])\n"
        "local current_owner = redis.call('GET', key)\n"
        "if current_owner == expected_owner then\n"
        "    redis.call('EXPIRE', key, ttl)\n"
        "    return 1\n"
        "end\n"
        "return 0\n"
    )

    async def _refresh_leader_lock(
        self, redis_client: aioredis.Redis
    ) -> bool:
        """Refresh leader lock TTL while running (ownership-safe).

        Why: Keeps lock alive while we're the active leader.
        Only refreshes if we still own the lock (verified atomically via Lua).

        Returns:
            True if lock was refreshed (we're still leader), False otherwise
        """
        key = "crawl_feeder:leader"
        ttl = 30
        try:
            # NOTE: This is Redis EVAL command for Lua scripts, not Python eval()
            # Redis EVAL is the standard way to run atomic operations
            result = await redis_client.eval(
                self._refresh_lock_lua,
                1,
                key,
                self._worker_id,
                str(ttl),
            )
            return result == 1
        except Exception as exc:
            logger.debug("Failed to refresh feeder leader lock", extra={"error": str(exc)})
            return False  # Assume we lost leadership on error

    # Lua script for atomic slot acquisition (same logic as TenantConcurrencyLimiter)
    # FIX: Only refresh TTL on SUCCESS path - prevents zombie counters when acquire fails
    # Bug: Previous version refreshed TTL on both success AND failure, keeping counter alive forever
    _acquire_slot_lua: str = (
        "local key = KEYS[1]\n"
        "local limit = tonumber(ARGV[1])\n"
        "local ttl = tonumber(ARGV[2])\n"
        "if limit <= 0 then\n"
        "  return 1\n"
        "end\n"
        "local current = redis.call('INCR', key)\n"
        "if current > limit then\n"
        "  local after_decr = redis.call('DECR', key)\n"
        "  if after_decr <= 0 then\n"
        "    redis.call('DEL', key)\n"
        "  end\n"
        "  -- DO NOT refresh TTL on failure - let counter expire naturally if unused\n"
        "  return 0\n"
        "end\n"
        "-- Success: refresh TTL only after confirming slot acquired\n"
        "redis.call('EXPIRE', key, ttl)\n"
        "return current\n"
    )

    # Lua script for safe slot release (same logic as TenantConcurrencyLimiter)
    _release_slot_lua: str = (
        "local key = KEYS[1]\n"
        "local ttl = tonumber(ARGV[1])\n"
        "local current = redis.call('GET', key)\n"
        "if not current then\n"
        "  return 0\n"
        "end\n"
        "current = redis.call('DECR', key)\n"
        "if not current or current <= 0 then\n"
        "  redis.call('DEL', key)\n"
        "  return 0\n"
        "end\n"
        "redis.call('EXPIRE', key, ttl)\n"
        "return current\n"
    )

    # CAS Lua script for atomic zombie counter reconciliation (Phase 0)
    # Why: Prevents TOCTOU race where counter changes between GET and SET
    # Returns: "ok:set", "ok:del", "mismatch:X", "deleted", "invalid"
    _reconcile_cas_lua: str = (
        "local key = KEYS[1]\n"
        "local observed = tonumber(ARGV[1])\n"
        "local new_value = tonumber(ARGV[2])\n"
        "local ttl = tonumber(ARGV[3])\n"
        "-- Key deleted between GET and CAS\n"
        "local current = redis.call('GET', key)\n"
        "if not current then return 'deleted' end\n"
        "-- Non-numeric value (data corruption)\n"
        "current = tonumber(current)\n"
        "if current == nil then return 'invalid' end\n"
        "-- CAS check: abort if counter changed\n"
        "if current ~= observed then return 'mismatch:' .. tostring(current) end\n"
        "-- Apply correction atomically\n"
        "if new_value <= 0 then\n"
        "  redis.call('DEL', key)\n"
        "  return 'ok:del'\n"
        "end\n"
        "-- Guard: reject invalid TTL (should never happen, config validates)\n"
        "if ttl <= 0 then return 'invalid_ttl' end\n"
        "redis.call('SET', key, tostring(new_value), 'EX', ttl)\n"
        "return 'ok:set'\n"
    )

    async def _get_tenant_crawler_settings(
        self, tenant_id: UUID
    ) -> dict | None:
        """Fetch tenant's crawler_settings from the database.

        Why: Feeder needs per-tenant settings for concurrency limits and batch sizes.
        Uses own session (not container) since feeder is a long-running service.

        Args:
            tenant_id: Tenant identifier

        Returns:
            Dict of crawler_settings or None if tenant not found
        """
        from sqlalchemy import select

        from intric.database.database import sessionmanager
        from intric.database.tables.tenant_table import Tenants

        try:
            async with sessionmanager.session() as session, session.begin():
                stmt = select(Tenants.crawler_settings).where(Tenants.id == tenant_id)
                result = await session.execute(stmt)
                row = result.scalar_one_or_none()
                return row if row else {}
        except Exception as exc:
            logger.warning(
                "Failed to fetch tenant crawler settings",
                extra={"tenant_id": str(tenant_id), "error": str(exc)},
            )
            return None

    async def _get_minimum_feeder_interval(
        self, redis_client: aioredis.Redis
    ) -> int:
        """Get minimum feeder interval across all active tenants.

        Why: Singleton feeder serves all tenants with one loop. To respect
        per-tenant intervals, we use the shortest interval configured by
        any tenant with pending jobs. This ensures responsive scheduling
        for tenants who need faster polling.

        Args:
            redis_client: Redis connection for scanning tenant queues

        Returns:
            Minimum interval in seconds across active tenants.
            Falls back to global default if no tenant overrides exist.
        """
        # Get all tenant IDs with pending jobs
        pattern = "tenant:*:crawl_pending"
        tenant_ids: list[UUID] = []

        try:
            cursor = 0
            while True:
                cursor, keys = await redis_client.scan(
                    cursor=cursor, match=pattern, count=100
                )
                for key_bytes in keys:
                    key = key_bytes.decode() if isinstance(key_bytes, bytes) else key_bytes
                    # Extract tenant_id from key: tenant:{uuid}:crawl_pending
                    parts = key.split(":")
                    if len(parts) >= 2:
                        try:
                            tenant_ids.append(UUID(parts[1]))
                        except ValueError:
                            continue
                if cursor == 0:
                    break
        except Exception as exc:
            logger.warning(
                "Failed to scan tenant queues for interval calculation",
                extra={"error": str(exc)},
            )
            return self.settings.crawl_feeder_interval_seconds

        if not tenant_ids:
            return self.settings.crawl_feeder_interval_seconds

        # Get minimum interval across all active tenants
        min_interval = self.settings.crawl_feeder_interval_seconds

        for tenant_id in tenant_ids:
            try:
                tenant_settings = await self._get_tenant_crawler_settings(tenant_id)
                interval = get_crawler_setting(
                    "crawl_feeder_interval_seconds",
                    tenant_settings,
                    default=self.settings.crawl_feeder_interval_seconds,
                )
                min_interval = min(min_interval, interval)
            except Exception:
                # Skip tenant on error, use current min
                continue

        logger.debug(
            "Calculated minimum feeder interval",
            extra={
                "min_interval": min_interval,
                "active_tenants": len(tenant_ids),
                "global_default": self.settings.crawl_feeder_interval_seconds,
            },
        )

        return min_interval

    async def _try_acquire_slot(
        self,
        tenant_id: UUID,
        redis_client: aioredis.Redis,
        tenant_crawler_settings: dict | None = None,
    ) -> bool:
        """Atomically try to acquire a concurrency slot for this tenant.

        Why: Eliminates race condition between feeder capacity check and worker acquire.
        Uses same Lua script as TenantConcurrencyLimiter for atomic INCR-then-check.

        Args:
            tenant_id: Tenant identifier
            redis_client: Redis connection
            tenant_crawler_settings: Optional tenant-specific settings for concurrency limit

        Returns:
            True if slot acquired, False if at capacity
        """
        key = f"tenant:{tenant_id}:active_jobs"
        max_concurrent = get_crawler_setting(
            "tenant_worker_concurrency_limit",
            tenant_crawler_settings,
            default=self.settings.tenant_worker_concurrency_limit,
        )
        ttl = self.settings.tenant_worker_semaphore_ttl_seconds

        try:
            result = await redis_client.eval(
                self._acquire_slot_lua,
                1,
                key,
                str(max_concurrent),
                str(ttl),
            )

            if isinstance(result, bytes):
                result = int(result)

            acquired = bool(result and int(result) > 0)

            if not acquired:
                logger.debug(
                    "Feeder slot acquisition failed (at capacity)",
                    extra={
                        "tenant_id": str(tenant_id),
                        "max_concurrent": max_concurrent,
                    },
                )

            return acquired

        except Exception as exc:
            logger.warning(
                "Failed to acquire slot in feeder",
                extra={"tenant_id": str(tenant_id), "error": str(exc)},
            )
            return False

    async def _mark_slot_preacquired(
        self,
        job_id: UUID,
        tenant_id: UUID,
        redis_client: aioredis.Redis,
        tenant_crawler_settings: dict | None = None,
    ) -> None:
        """Mark that the feeder pre-acquired a slot for this job.

        Why: Worker checks this flag to skip limiter.acquire() (slot already held).
        TTL ensures cleanup if job is never picked up.

        Args:
            job_id: The job identifier
            tenant_id: The tenant identifier - stored in the value so worker can
                       release the slot even if tenant injection fails
            redis_client: Redis connection
            tenant_crawler_settings: Optional tenant-specific settings for TTL

        Raises:
            Exception: If Redis operation fails - caller MUST handle and release slot.
        """
        key = f"job:{job_id}:slot_preacquired"
        # Get per-tenant TTL if available, otherwise use global default
        ttl = get_crawler_setting(
            "tenant_worker_semaphore_ttl_seconds",
            tenant_crawler_settings,
            default=self.settings.tenant_worker_semaphore_ttl_seconds,
        )
        # Store tenant_id so worker can release slot even if tenant lookup fails
        # Use semaphore TTL for consistency - ensures flag and slot expire together
        await redis_client.set(key, str(tenant_id), ex=ttl)

    async def _release_slot(
        self, tenant_id: UUID, redis_client: aioredis.Redis
    ) -> None:
        """Release a previously acquired slot (used when ARQ enqueue fails).

        Why: If feeder acquires slot but fails to enqueue, must release to prevent leak.
        """
        key = f"tenant:{tenant_id}:active_jobs"
        ttl = self.settings.tenant_worker_semaphore_ttl_seconds

        try:
            # Use class constant for consistency and maintainability
            await redis_client.eval(self._release_slot_lua, 1, key, str(ttl))
        except Exception as exc:
            logger.warning(
                "Failed to release slot in feeder",
                extra={"tenant_id": str(tenant_id), "error": str(exc)},
            )

    async def _get_available_capacity(
        self,
        tenant_id: UUID,
        redis_client: aioredis.Redis,
        tenant_crawler_settings: dict | None = None,
    ) -> int:
        """Check available crawl capacity for this tenant (read-only).

        Why: Used to decide how many pending jobs to consider.
        Actual slot acquisition is done atomically per-job via _try_acquire_slot().

        Args:
            tenant_id: Tenant identifier
            redis_client: Redis connection
            tenant_crawler_settings: Optional tenant-specific settings for concurrency limit

        Returns:
            Number of jobs that can be enqueued (0 if at capacity)
        """
        # Use same Redis key as TenantConcurrencyLimiter
        # Why: Ensures feeder and worker coordinate on same state
        key = f"tenant:{tenant_id}:active_jobs"

        try:
            active_jobs_bytes = await redis_client.get(key)
            max_concurrent = get_crawler_setting(
                "tenant_worker_concurrency_limit",
                tenant_crawler_settings,
                default=self.settings.tenant_worker_concurrency_limit,
            )

            # Allow capacity check even if key doesn't exist (will be 0 active)
            # Why: _try_acquire_slot() handles actual atomic acquisition
            if not active_jobs_bytes:
                return max_concurrent  # No active jobs, full capacity available

            # Decode bytes to int, with safety clamping
            # Why: Prevents crashes and ensures value is within valid range
            active_jobs = int(active_jobs_bytes.decode())
            active_jobs = max(0, min(active_jobs, max_concurrent))

            # Calculate available capacity
            available = max_concurrent - active_jobs
            return max(0, available)

        except Exception as exc:
            logger.warning(
                "Failed to check available capacity",
                extra={"tenant_id": str(tenant_id), "error": str(exc)},
            )
            # Conservative: assume no capacity
            return 0

    async def _get_pending_crawls(
        self, tenant_id: UUID, redis_client: aioredis.Redis, limit: int
    ) -> list[tuple[bytes, dict]]:
        """Get pending crawl jobs from the queue.

        Args:
            tenant_id: Tenant identifier
            redis_client: Redis connection
            limit: Maximum number of jobs to retrieve

        Returns:
            List of tuples: (raw_bytes, parsed_job_data)
            Raw bytes are preserved for exact LREM matching to avoid serialization mismatch.
        """
        key = f"tenant:{tenant_id}:crawl_pending"

        try:
            # Get first N items from list (FIFO queue)
            pending_bytes = await redis_client.lrange(key, 0, limit - 1)

            if not pending_bytes:
                return []

            # Parse JSON job data, keeping raw bytes for LREM
            # Why: Re-serializing with sort_keys=True may not match original, causing LREM to fail
            pending_jobs = []
            for raw_bytes in pending_bytes:
                try:
                    job_data = json.loads(raw_bytes.decode())
                    pending_jobs.append((raw_bytes, job_data))
                except json.JSONDecodeError as parse_exc:
                    # Remove poison message to prevent infinite retry loop
                    # Why: Invalid JSON will never parse successfully
                    logger.warning(
                        "Removing invalid JSON from pending queue (poison message)",
                        extra={"tenant_id": str(tenant_id), "error": str(parse_exc)},
                    )
                    try:
                        await redis_client.lrem(key, 1, raw_bytes)
                    except Exception:
                        pass  # Best effort removal
                    continue

            return pending_jobs

        except Exception as exc:
            logger.warning(
                "Failed to get pending crawls",
                extra={"tenant_id": str(tenant_id), "error": str(exc)},
            )
            return []

    async def _enqueue_crawl_job(
        self, job_data: dict, tenant_id: UUID
    ) -> tuple[bool, UUID]:
        """Enqueue a crawl job to ARQ using pre-created job record.

        Why: Job and CrawlRun records already created by scheduler.
        Feeder only handles ARQ enqueueing with deterministic job_id for idempotency.

        Args:
            job_data: Job parameters from pending queue (includes job_id from DB)
            tenant_id: Tenant identifier

        Returns:
            Tuple of (success: bool, job_id: UUID)
        """
        # Parse job_id early to avoid re-parsing in exception handler
        # Why: If this fails, we want a clean error, not a masked one
        try:
            job_id = UUID(job_data["job_id"])
        except (KeyError, ValueError, TypeError) as exc:
            logger.error(
                "Invalid job_id in pending job data",
                extra={"tenant_id": str(tenant_id), "job_data": job_data, "error": str(exc)},
            )
            # Return a nil UUID to indicate failure - caller should handle
            return False, UUID("00000000-0000-0000-0000-000000000000")

        try:
            from intric.websites.crawl_dependencies.crawl_models import CrawlTask, CrawlType
            from intric.jobs.job_models import Task

            # Reconstruct CrawlTask parameters
            params = CrawlTask(
                user_id=UUID(job_data["user_id"]),
                website_id=UUID(job_data["website_id"]),
                run_id=UUID(job_data["run_id"]),
                url=job_data["url"],
                download_files=job_data["download_files"],
                crawl_type=CrawlType(job_data["crawl_type"]),
            )

            # Enqueue to ARQ with deterministic job_id
            # Why: If feeder crashes and retries, ARQ rejects duplicate IDs
            await job_manager.enqueue(
                task=Task.CRAWL,
                job_id=job_id,  # Use pre-created ID for idempotency
                params=params,
            )

            logger.debug(
                "Enqueued crawl job from feeder",
                extra={
                    "tenant_id": str(tenant_id),
                    "job_id": str(job_id),
                    "website_id": job_data["website_id"],
                    "url": job_data["url"],
                },
            )
            return True, job_id

        except Exception as exc:
            # Handle "job already exists" as success for idempotency
            # Why: If feeder crashes after enqueue but before LREM, job stays in pending.
            # On retry, ARQ returns "already exists" error. We treat this as SUCCESS
            # so LREM proceeds and clears the job from pending (prevents infinite loop).

            error_msg = str(exc).lower()

            # Check for duplicate job error - use specific patterns to avoid false positives
            # Why: Broad matching like "job_id" could match "invalid job_id" validation errors
            is_duplicate = (
                "already exists" in error_msg
                or "duplicate" in error_msg
                or "job exists" in error_msg
            )

            if is_duplicate:
                logger.info(
                    "Job already in ARQ queue (idempotent), treating as success",
                    extra={
                        "tenant_id": str(tenant_id),
                        "job_id": str(job_id),
                        "url": job_data.get("url"),
                        "reason": "duplicate_job_id",
                    },
                )
                # Return TRUE so LREM proceeds and removes from pending
                return True, job_id

            # Real error - return false, job stays in pending for retry
            logger.error(
                "Failed to enqueue crawl job from feeder",
                extra={
                    "tenant_id": str(tenant_id),
                    "job_data": job_data,
                    "error": str(exc),
                },
            )
            return False, job_id

    async def _remove_from_pending(
        self, tenant_id: UUID, raw_bytes: bytes, redis_client: aioredis.Redis
    ) -> None:
        """Remove job from pending queue after successful enqueue.

        Args:
            tenant_id: Tenant identifier
            raw_bytes: Original raw bytes from lrange (NOT re-serialized)
            redis_client: Redis connection

        Note: Using exact raw bytes from lrange ensures LREM matches.
        Re-serializing with sort_keys=True could produce different string than original push.
        """
        key = f"tenant:{tenant_id}:crawl_pending"

        try:
            # Remove first occurrence (LREM count=1) using exact original bytes
            # Why: Avoids serialization mismatch that could cause LREM to fail
            await redis_client.lrem(key, 1, raw_bytes)
        except Exception as exc:
            logger.warning(
                "Failed to remove from pending queue",
                extra={"tenant_id": str(tenant_id), "error": str(exc)},
            )

    async def _cleanup_orphaned_crawl_jobs(self) -> None:
        """Clean up orphaned crawl Jobs with Safe Watchdog pattern.

        Why: CrawlRun.status comes from Job.status (via relationship). If a crawl Job gets
        stuck in QUEUED/IN_PROGRESS, the CrawlRun appears as "in progress" and blocks new crawls.

        Safe Watchdog Pattern (prevents infinite re-queue loops):
        0. RECONCILE: Detect zombie counters (Redis active_jobs > actual DB active jobs)
           → Reset Redis counter to actual DB count (self-healing for slot leaks)
        1. KILL expired: Jobs where created_at > max_age → Mark FAILED permanently
           (Uses created_at which is immutable - prevents infinite loops)
        2. RESCUE stuck: Jobs where updated_at is stale but created_at is fresh
           → Re-queue to Redis pending queue, bump updated_at (visibility timeout)
        3. FAIL long-running: IN_PROGRESS jobs older than conservative timeout → FAILED

        Note: CrawlRuns table does NOT have a status column. Status is derived from Job.status.
        """
        from sqlalchemy import update, and_, select

        from intric.database.database import sessionmanager
        from intric.database.tables.job_table import Jobs
        from intric.database.tables.websites_table import CrawlRuns, Websites
        from intric.main.models import Status

        # Thresholds (using tenant defaults - could be made per-tenant later)
        # Stale threshold: 5 minutes - if updated_at hasn't changed, job is likely stuck
        stale_threshold_minutes = 5
        # Max age: Hard TTL to prevent infinite re-queue loops (default 2 hours)
        max_age_seconds = self.settings.crawl_job_max_age_seconds or 7200
        # IN_PROGRESS timeout: Conservative - long crawls may legitimately run for hours
        in_progress_timeout_hours = self.settings.orphan_crawl_run_timeout_hours

        now = datetime.now(timezone.utc)
        stale_cutoff = now - timedelta(minutes=stale_threshold_minutes)
        max_age_cutoff = now - timedelta(seconds=max_age_seconds)
        in_progress_cutoff = now - timedelta(hours=in_progress_timeout_hours)

        session = None  # Initialize to prevent UnboundLocalError in except block
        expired_jobs = []  # Track expired jobs for slot release after transaction
        orphaned_job_ids = []  # Track orphaned jobs (no CrawlRun) for flag-based slot release
        try:
            async with sessionmanager.session() as session, session.begin():
                # ============================================================
                # Phase 0: Zombie Counter Reconciliation
                # ============================================================
                # Detect and fix cases where Redis active_jobs counter is higher
                # than actual QUEUED/IN_PROGRESS jobs in DB (zombie counters).
                # This can happen if:
                # - Worker crashed after slot acquire but before job completion
                # - Safe Watchdog marked job FAILED but flag had expired (no slot release)
                # - Manual DB interventions
                # ============================================================
                redis_client = self._redis_client
                if redis_client:
                    from sqlalchemy import func
                    try:
                        reconciled_count = 0
                        # SCAN for all tenant active_jobs counters
                        # NOTE: SCAN is O(N) but safe for large Redis (cursor-based)
                        async for key in redis_client.scan_iter(match="tenant:*:active_jobs"):
                            try:
                                key_str = key.decode('utf-8') if isinstance(key, bytes) else key
                                parts = key_str.split(':')
                                if len(parts) != 3:
                                    continue
                                tenant_id_str = parts[1]

                                # Get Redis counter value
                                redis_val = await redis_client.get(key)
                                if not redis_val:
                                    continue
                                redis_count = int(redis_val.decode() if isinstance(redis_val, bytes) else redis_val)

                                if redis_count <= 0:
                                    # Counter already at or below zero, skip
                                    continue

                                # Query DB for actual active jobs (QUEUED or IN_PROGRESS)
                                # NOTE: Convert tenant_id_str to UUID for proper column comparison
                                # SQLAlchemy doesn't auto-coerce string to UUID in WHERE clause
                                try:
                                    tenant_uuid = UUID(tenant_id_str)
                                except ValueError:
                                    # Invalid UUID format in key, skip
                                    continue
                                actual_active = await session.scalar(
                                    select(func.count())
                                    .select_from(Jobs)
                                    .join(CrawlRuns, CrawlRuns.job_id == Jobs.id)
                                    .where(
                                        Jobs.task == "CRAWL",
                                        Jobs.status.in_([Status.QUEUED, Status.IN_PROGRESS]),
                                        CrawlRuns.tenant_id == tenant_uuid,
                                    )
                                )

                                # Reconcile if Redis is inflated (zombie slots)
                                # Uses CAS (Compare-And-Swap) to prevent TOCTOU race
                                if redis_count > actual_active:
                                    ttl = self.settings.tenant_worker_semaphore_ttl_seconds
                                    # Atomic CAS: only modify if counter hasn't changed
                                    # Uses execute_command for Lua script execution
                                    cas_result = await redis_client.execute_command(
                                        "EVAL",
                                        self._reconcile_cas_lua,
                                        1,
                                        key,
                                        str(redis_count),      # observed value
                                        str(actual_active),    # new value from DB
                                        str(ttl),              # TTL for SET
                                    )
                                    result_str = (
                                        cas_result.decode()
                                        if isinstance(cas_result, bytes)
                                        else str(cas_result)
                                    )

                                    if result_str.startswith("ok:"):
                                        logger.warning(
                                            "Zombie counter reconciled",
                                            extra={
                                                "tenant_id": tenant_id_str,
                                                "redis_count": redis_count,
                                                "actual_active": actual_active,
                                                "released": redis_count - actual_active,
                                                "cas_result": result_str,
                                            },
                                        )
                                        reconciled_count += 1
                                    elif result_str.startswith("mismatch:"):
                                        # Counter changed during DB query - skip, next cycle catches
                                        logger.debug(
                                            "Phase 0 CAS skipped - concurrent modification",
                                            extra={
                                                "tenant_id": tenant_id_str,
                                                "observed": redis_count,
                                                "cas_result": result_str,
                                            },
                                        )
                                    elif result_str == "deleted":
                                        logger.debug(
                                            "Phase 0 key already deleted",
                                            extra={"tenant_id": tenant_id_str},
                                        )
                                    elif result_str == "invalid":
                                        logger.warning(
                                            "Phase 0 found invalid counter value",
                                            extra={
                                                "tenant_id": tenant_id_str,
                                                "key": key_str,
                                            },
                                        )
                                    elif result_str == "invalid_ttl":
                                        logger.error(
                                            "Phase 0 CAS rejected - invalid TTL passed",
                                            extra={
                                                "tenant_id": tenant_id_str,
                                                "ttl": ttl,
                                            },
                                        )

                            except Exception as key_exc:
                                logger.debug(
                                    "Phase 0 reconciliation error for key",
                                    extra={"key": str(key), "error": str(key_exc)},
                                )
                                continue  # Don't crash watchdog on individual key errors

                        if reconciled_count > 0:
                            logger.info(
                                f"Phase 0: Reconciled {reconciled_count} zombie counters",
                                extra={"reconciled_count": reconciled_count},
                            )
                    except Exception as phase0_exc:
                        logger.warning(
                            "Phase 0 reconciliation failed",
                            extra={"error": str(phase0_exc)},
                        )
                        # Continue to other phases - reconciliation is best-effort

                # ============================================================
                # Phase 1: KILL expired jobs (created_at > max_age)
                # ============================================================
                # Why: Prevents infinite re-queue loops. created_at is immutable.

                # Step 1a: SELECT ALL expired job IDs (including orphaned jobs without CrawlRun)
                all_expired_query = (
                    select(Jobs.id)
                    .where(
                        and_(
                            Jobs.task == "CRAWL",
                            Jobs.status == Status.QUEUED,
                            Jobs.created_at < max_age_cutoff,
                        )
                    )
                )
                all_expired_result = await session.execute(all_expired_query)
                all_expired_ids = {row.id for row in all_expired_result.fetchall()}

                # Step 1b: SELECT jobs WITH CrawlRuns (need tenant_id for slot release)
                expired_query = (
                    select(Jobs.id.label("job_id"), CrawlRuns.tenant_id)
                    .select_from(Jobs)
                    .join(CrawlRuns, CrawlRuns.job_id == Jobs.id)
                    .where(
                        and_(
                            Jobs.task == "CRAWL",
                            Jobs.status == Status.QUEUED,
                            Jobs.created_at < max_age_cutoff,
                        )
                    )
                )
                expired_result = await session.execute(expired_query)
                expired_jobs = expired_result.fetchall()

                # Step 1c: Identify orphaned jobs (expired but no CrawlRun)
                # These still need slot release if they have a pre-acquired flag
                jobs_with_crawlrun = {row.job_id for row in expired_jobs}
                orphaned_job_ids = list(all_expired_ids - jobs_with_crawlrun)

                # Step 1b: UPDATE - mark expired jobs as FAILED
                kill_expired_stmt = (
                    update(Jobs)
                    .where(
                        and_(
                            Jobs.task == "CRAWL",
                            Jobs.status == Status.QUEUED,
                            Jobs.created_at < max_age_cutoff,
                        )
                    )
                    .values(
                        status=Status.FAILED,
                        updated_at=now,
                    )
                    .execution_options(synchronize_session=False)
                )
                kill_result = await session.execute(kill_expired_stmt)
                killed_count = kill_result.rowcount

                # Phase 2: RESCUE stuck jobs (stale updated_at but fresh created_at)
                # Query to get stuck jobs with their crawl data for re-queuing
                rescue_query = (
                    select(
                        Jobs.id.label("job_id"),
                        Jobs.user_id,
                        CrawlRuns.id.label("run_id"),
                        CrawlRuns.tenant_id,
                        CrawlRuns.website_id,
                        Websites.url,
                        Websites.download_files,
                        Websites.crawl_type,
                    )
                    .select_from(Jobs)
                    .join(CrawlRuns, CrawlRuns.job_id == Jobs.id)
                    .join(Websites, Websites.id == CrawlRuns.website_id)
                    .where(
                        and_(
                            Jobs.task == "CRAWL",
                            Jobs.status == Status.QUEUED,
                            Jobs.updated_at < stale_cutoff,  # Stale (stuck)
                            Jobs.created_at >= max_age_cutoff,  # Not expired (can rescue)
                        )
                    )
                )
                rescue_result = await session.execute(rescue_query)
                stuck_jobs = rescue_result.fetchall()

                # Re-queue stuck jobs to Redis pending queue
                rescued_count = 0
                for row in stuck_jobs:
                    try:
                        await self._requeue_stuck_job(
                            job_id=row.job_id,
                            user_id=row.user_id,
                            run_id=row.run_id,
                            tenant_id=row.tenant_id,
                            website_id=row.website_id,
                            url=row.url,
                            download_files=row.download_files,
                            crawl_type=row.crawl_type,
                        )
                        rescued_count += 1
                    except Exception as requeue_exc:
                        logger.warning(
                            "Failed to re-queue stuck job",
                            extra={"job_id": str(row.job_id), "error": str(requeue_exc)},
                        )

                # Bump updated_at for rescued jobs (visibility timeout)
                # Why: Prevents immediate re-pickup in next cycle
                if stuck_jobs:
                    rescued_job_ids = [row.job_id for row in stuck_jobs]
                    bump_stmt = (
                        update(Jobs)
                        .where(Jobs.id.in_(rescued_job_ids))
                        .values(updated_at=now)
                        .execution_options(synchronize_session=False)
                    )
                    await session.execute(bump_stmt)

                # Phase 3: FAIL long-running IN_PROGRESS jobs (conservative timeout)
                # Why: Long crawls may legitimately run for hours, but not forever
                # CRITICAL: We must release Redis slots for these jobs, not just update DB
                # Otherwise we get "zombie slots" that permanently block new jobs
                fail_in_progress_query = (
                    select(
                        Jobs.id.label("job_id"),
                        CrawlRuns.tenant_id,
                    )
                    .select_from(Jobs)
                    .join(CrawlRuns, CrawlRuns.job_id == Jobs.id)
                    .where(
                        and_(
                            Jobs.task == "CRAWL",
                            Jobs.status == Status.IN_PROGRESS,
                            Jobs.updated_at < in_progress_cutoff,
                        )
                    )
                )
                fail_in_progress_result = await session.execute(fail_in_progress_query)
                stale_in_progress_jobs = fail_in_progress_result.fetchall()

                # Mark jobs as FAILED in database
                failed_in_progress = 0
                if stale_in_progress_jobs:
                    stale_job_ids = [row.job_id for row in stale_in_progress_jobs]
                    fail_stmt = (
                        update(Jobs)
                        .where(Jobs.id.in_(stale_job_ids))
                        .values(status=Status.FAILED, updated_at=now)
                        .execution_options(synchronize_session=False)
                    )
                    fail_result = await session.execute(fail_stmt)
                    failed_in_progress = fail_result.rowcount
                # Transaction auto-commits on exit of session.begin() context

            # Release Redis slots OUTSIDE the DB transaction
            # Why: Redis operations shouldn't block DB commit, and we want to
            # release even if there are Redis errors (best effort)
            redis_client = self._redis_client

            # Phase 1 slot release: Release slots for expired QUEUED jobs
            # Only release if flag exists (job had pre-acquired slot from optimistic acquire)
            if expired_jobs and redis_client:
                expired_released = 0
                for row in expired_jobs:
                    flag_key = f"job:{row.job_id}:slot_preacquired"
                    try:
                        # Only release if flag exists (job had pre-acquired slot)
                        if await redis_client.get(flag_key):
                            await self._release_slot(row.tenant_id, redis_client)
                            await redis_client.delete(flag_key)
                            expired_released += 1
                            logger.debug(
                                "Released slot for expired QUEUED job",
                                extra={"job_id": str(row.job_id), "tenant_id": str(row.tenant_id)},
                            )
                    except Exception as exc:
                        logger.warning(
                            "Failed to release slot for expired job",
                            extra={"job_id": str(row.job_id), "error": str(exc)},
                        )
                if expired_released > 0:
                    logger.info(
                        f"Safe Watchdog released {expired_released} slots for expired QUEUED jobs",
                        extra={"expired_released": expired_released},
                    )

            # Phase 1b: Release slots for orphaned jobs (no CrawlRun, e.g., Website deleted)
            # These jobs are marked FAILED by the bulk UPDATE but weren't in expired_jobs
            # because they don't have a CrawlRun to JOIN with. We read tenant_id from the flag.
            if orphaned_job_ids and redis_client:
                orphaned_released = 0
                # Use pipelining for batch performance
                pipeline = redis_client.pipeline()
                for job_id in orphaned_job_ids:
                    pipeline.get(f"job:{job_id}:slot_preacquired")
                # Track whether we had a pipeline failure (unknown state) vs confirmed missing flags
                pipeline_failed = False
                try:
                    flag_values = await pipeline.execute()
                except Exception as exc:
                    logger.warning(
                        "Redis pipeline failed - cannot determine flag state for orphaned jobs",
                        extra={"error": str(exc), "job_count": len(orphaned_job_ids)},
                    )
                    pipeline_failed = True
                    flag_values = [None] * len(orphaned_job_ids)

                for job_id, flag_value in zip(orphaned_job_ids, flag_values):
                    # Use explicit None check - flag_value is bytes if exists, None if missing
                    # This avoids confusion with empty bytes (unlikely but possible with Redis)
                    if flag_value is None:
                        if pipeline_failed:
                            # Pipeline error - flag state unknown, will retry next cycle
                            # Phase 0 reconciliation will eventually fix any actual leaks
                            logger.debug(
                                "Skipping orphaned job due to pipeline failure - will retry next cycle",
                                extra={"job_id": str(job_id)},
                            )
                        else:
                            # Confirmed missing flag - permanent leak requiring manual intervention
                            logger.error(
                                "Slot leak detected: Orphaned job has no Redis flag (expired or missing)",
                                extra={"job_id": str(job_id)},
                            )
                        continue

                    try:
                        tenant_id = UUID(flag_value.decode())
                        await self._release_slot(tenant_id, redis_client)
                        await redis_client.delete(f"job:{job_id}:slot_preacquired")
                        orphaned_released += 1
                        logger.info(
                            "Released slot for orphaned job (Website likely deleted)",
                            extra={"job_id": str(job_id), "tenant_id": str(tenant_id)},
                        )
                    except Exception as exc:
                        logger.warning(
                            "Failed to release slot for orphaned job",
                            extra={"job_id": str(job_id), "error": str(exc)},
                        )
                if orphaned_released > 0:
                    logger.info(
                        f"Safe Watchdog released {orphaned_released} slots for orphaned jobs",
                        extra={"orphaned_released": orphaned_released},
                    )

            # Phase 3 slot release: Release slots for long-running IN_PROGRESS jobs
            if stale_in_progress_jobs and redis_client:
                released_slots = 0
                for row in stale_in_progress_jobs:
                    try:
                        await self._release_slot(row.tenant_id, redis_client)
                        # Also clean up pre-acquired flag if it exists (prevents zombie flags)
                        flag_key = f"job:{row.job_id}:slot_preacquired"
                        await redis_client.delete(flag_key)
                        released_slots += 1
                    except Exception as slot_exc:
                        logger.warning(
                            "Failed to release slot for failed job",
                            extra={
                                "job_id": str(row.job_id),
                                "tenant_id": str(row.tenant_id),
                                "error": str(slot_exc),
                            },
                        )
                if released_slots > 0:
                    logger.info(
                        f"Safe Watchdog released {released_slots} zombie slots",
                        extra={"released_slots": released_slots},
                    )

            # Log only if we did something (avoid log spam)
            if killed_count > 0 or rescued_count > 0 or failed_in_progress > 0:
                logger.info(
                    f"Safe Watchdog: killed={killed_count} (expired), "
                    f"rescued={rescued_count} (re-queued), "
                    f"failed_in_progress={failed_in_progress}",
                    extra={
                        "killed_expired": killed_count,
                        "rescued_stuck": rescued_count,
                        "failed_in_progress": failed_in_progress,
                        "max_age_seconds": max_age_seconds,
                        "stale_threshold_minutes": stale_threshold_minutes,
                    },
                )

        except Exception as exc:
            # Rollback on failure to prevent partial state
            if session is not None:
                try:
                    await session.rollback()
                except Exception:
                    pass  # Best effort rollback
            logger.warning(
                "Failed to run Safe Watchdog cleanup",
                extra={"error": str(exc)},
            )

    async def _requeue_stuck_job(
        self,
        job_id: UUID,
        user_id: UUID,
        run_id: UUID,
        tenant_id: UUID,
        website_id: UUID,
        url: str,
        download_files: bool,
        crawl_type: str,
    ) -> bool:
        """Re-queue a stuck job directly to ARQ with Job.status() check.

        Uses ARQ's native enqueue_job() with _job_id for atomic deduplication.
        Checks Job.status() first to avoid duplicates when DB is out of sync.

        Returns:
            True if job was re-queued, False if skipped (already in ARQ)
        """
        if not self._redis_client:
            raise RuntimeError("Redis client not initialized")

        # Check ARQ status before re-queuing to prevent duplicates
        from arq.jobs import Job, JobStatus

        arq_job = Job(job_id=str(job_id), redis=self._redis_client)
        try:
            status = await arq_job.status()
        except Exception as status_exc:
            logger.warning(
                "Failed to check ARQ job status, proceeding with re-queue",
                extra={"job_id": str(job_id), "error": str(status_exc)},
            )
            status = JobStatus.not_found  # Assume not found on error

        if status != JobStatus.not_found:
            # Job is already in ARQ (queued, in_progress, or complete)
            # Don't re-queue - this would create duplicates
            logger.info(
                "Job already in ARQ, skipping re-queue",
                extra={
                    "job_id": str(job_id),
                    "arq_status": status.value,
                    "tenant_id": str(tenant_id),
                },
            )
            return False

        # FIX: Use ARQ native enqueue instead of redis.rpush()
        # Why: ARQ's enqueue_job() uses atomic SETNX with _job_id for deduplication.
        # Manual rpush() bypasses this safety mechanism.
        from intric.jobs.job_manager import job_manager
        from intric.jobs.job_models import Task
        from intric.websites.crawl_dependencies.crawl_models import CrawlTask, CrawlType

        params = CrawlTask(
            user_id=user_id,
            website_id=website_id,
            run_id=run_id,
            url=url,
            download_files=download_files,
            crawl_type=CrawlType(crawl_type) if isinstance(crawl_type, str) else crawl_type,
        )

        try:
            await job_manager.enqueue(
                task=Task.CRAWL,
                job_id=job_id,  # Use existing job_id for idempotency
                params=params,
            )

            logger.info(
                "Re-queued stuck job directly to ARQ",
                extra={
                    "job_id": str(job_id),
                    "tenant_id": str(tenant_id),
                    "website_id": str(website_id),
                    "url": url,
                },
            )
            return True

        except Exception as enqueue_exc:
            # Handle "job already exists" as success (idempotency)
            error_msg = str(enqueue_exc).lower()
            if "already exists" in error_msg or "duplicate" in error_msg:
                logger.info(
                    "Job already in ARQ (duplicate error), treating as success",
                    extra={"job_id": str(job_id), "tenant_id": str(tenant_id)},
                )
                return True

            logger.error(
                "Failed to re-queue stuck job to ARQ",
                extra={
                    "job_id": str(job_id),
                    "tenant_id": str(tenant_id),
                    "error": str(enqueue_exc),
                },
            )
            raise

    # NOTE: _hydrate_pending_queues_from_db() removed - Safe Watchdog handles orphan recovery

    async def _cleanup_orphaned_crawl_runs(self) -> None:
        """Clean up CrawlRuns with NULL job_id older than timeout threshold.

        Why: These orphaned records occur when:
        - Jobs are deleted (CASCADE sets job_id to NULL)
        - CrawlRun creation fails after insert but before job_id is set

        CrawlRun.status is derived from Job.status. With NULL job_id, status
        defaults to QUEUED but these are ghost records that accumulate.
        Uses same timeout threshold as job cleanup for consistency.
        """
        from sqlalchemy import delete, and_

        from intric.database.database import sessionmanager
        from intric.database.tables.websites_table import CrawlRuns

        timeout_hours = self.settings.orphan_crawl_run_timeout_hours
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=timeout_hours)

        try:
            async with sessionmanager.session() as session, session.begin():
                cleanup_stmt = (
                    delete(CrawlRuns)
                    .where(
                        and_(
                            CrawlRuns.job_id == None,
                            CrawlRuns.updated_at < cutoff_time,
                        )
                    )
                    .execution_options(synchronize_session=False)
                )
                result = await session.execute(cleanup_stmt)
                if result.rowcount > 0:
                    logger.info(
                        "Cleaned up orphaned CrawlRuns with NULL job_id",
                        extra={"cleaned_count": result.rowcount},
                    )
        except Exception as exc:
            logger.warning(
                "Failed to cleanup orphaned CrawlRuns",
                extra={"error": str(exc)},
            )

    async def _process_tenant_queue(
        self, tenant_id: UUID, redis_client: aioredis.Redis
    ) -> None:
        """Process pending crawls for one tenant.

        Why: Atomically acquires slots and enqueues jobs when capacity exists.
        FIX: Eliminates race condition by acquiring slot BEFORE enqueueing.

        Args:
            tenant_id: Tenant identifier
            redis_client: Redis connection
        """
        # Fetch tenant-specific crawler settings (supports per-tenant overrides)
        # Why: Different tenants may have different concurrency limits and batch sizes
        tenant_crawler_settings = await self._get_tenant_crawler_settings(tenant_id)

        # Check available capacity (read-only hint for batch sizing)
        available = await self._get_available_capacity(
            tenant_id, redis_client, tenant_crawler_settings
        )

        if available <= 0:
            return  # No capacity, skip this tenant

        # Get pending jobs (limit to available capacity and batch size)
        # Why: Batch size prevents enqueueing too many at once
        batch_size = get_crawler_setting(
            "crawl_feeder_batch_size",
            tenant_crawler_settings,
            default=self.settings.crawl_feeder_batch_size,
        )
        limit = min(available, batch_size)
        pending_jobs = await self._get_pending_crawls(tenant_id, redis_client, limit)

        if not pending_jobs:
            return  # No pending jobs for this tenant

        logger.info(
            f"Processing {len(pending_jobs)} pending crawls",
            extra={
                "tenant_id": str(tenant_id),
                "available_capacity": available,
                "pending_count": len(pending_jobs),
            },
        )

        # Enqueue each pending job with atomic slot acquisition
        enqueued_count = 0
        failed_count = 0
        skipped_capacity = 0

        # pending_jobs is list of (raw_bytes, job_data) tuples
        # raw_bytes preserved for exact LREM matching
        for raw_bytes, job_data in pending_jobs:
            # Extract job_id early for flag operations
            # Why: Need job_id before enqueue to mark flag first
            try:
                job_id = UUID(job_data["job_id"])
            except (KeyError, ValueError, TypeError):
                logger.warning(
                    "Invalid job_id in pending job, skipping",
                    extra={"tenant_id": str(tenant_id), "job_data": job_data},
                )
                failed_count += 1
                continue

            # FIX: Atomically acquire slot BEFORE enqueueing
            # Why: Eliminates race condition between feeder GET and worker INCR
            slot_acquired = await self._try_acquire_slot(
                tenant_id, redis_client, tenant_crawler_settings
            )

            if not slot_acquired:
                # At capacity - stop processing this tenant
                # Remaining jobs stay in pending queue for next cycle
                skipped_capacity = len(pending_jobs) - enqueued_count - failed_count
                logger.debug(
                    "Stopping tenant processing: at capacity",
                    extra={
                        "tenant_id": str(tenant_id),
                        "enqueued": enqueued_count,
                        "skipped": skipped_capacity,
                    },
                )
                break

            # FIX: Mark flag BEFORE enqueueing (safe hand-off)
            # Why: If enqueue succeeds but mark fails, worker would double-acquire
            # By marking first, we ensure flag exists before job enters ARQ queue
            try:
                await self._mark_slot_preacquired(
                    job_id, tenant_id, redis_client, tenant_crawler_settings
                )
            except Exception as mark_exc:
                # Mark failed - MUST release slot and skip enqueue to prevent double-acquire
                logger.error(
                    "Failed to mark slot pre-acquired, rolling back slot",
                    extra={"job_id": str(job_id), "tenant_id": str(tenant_id), "error": str(mark_exc)},
                )
                await self._release_slot(tenant_id, redis_client)
                failed_count += 1
                continue

            # Now enqueue to ARQ
            success, returned_job_id = await self._enqueue_crawl_job(job_data, tenant_id)

            if success:
                # Remove from pending queue using exact raw bytes (avoids serialization mismatch)
                await self._remove_from_pending(tenant_id, raw_bytes, redis_client)
                enqueued_count += 1
            else:
                # Enqueue failed - rollback: delete flag and release slot
                # Why: Prevents slot leak and stale flag when ARQ enqueue fails
                try:
                    await redis_client.delete(f"job:{job_id}:slot_preacquired")
                except Exception:
                    pass  # Best effort cleanup
                await self._release_slot(tenant_id, redis_client)
                failed_count += 1

        if enqueued_count > 0 or failed_count > 0 or skipped_capacity > 0:
            logger.info(
                f"Feeder cycle complete: {enqueued_count} enqueued, {failed_count} failed, {skipped_capacity} skipped (capacity)",
                extra={"tenant_id": str(tenant_id)},
            )

    async def run_forever(self) -> None:
        """Run the feeder loop with leader election.

        Why: Only ONE feeder runs across all worker processes using Redis leader lock.
        This prevents N workers from spawning N feeders (which would recreate burst problem).

        Leader Lock Pattern:
        - Each worker tries to acquire lock on startup
        - Only one succeeds (becomes leader)
        - Others sleep and retry (become leader if current leader crashes)
        - Lock TTL=30s for automatic failover

        Note: This service manages its own Redis client lifecycle.
        It does NOT depend on a Container to avoid session scope issues.
        """
        if not self.settings.crawl_feeder_enabled:
            logger.info("Crawl feeder disabled, not starting")
            return

        logger.info(
            "Starting crawl feeder service with leader election",
            extra={
                "interval_seconds": self.settings.crawl_feeder_interval_seconds,
                "batch_size": self.settings.crawl_feeder_batch_size,
            },
        )
        self._running = True

        # Create own Redis client (not from container which may have stale session)
        # Why: Long-running service must manage its own client lifecycle
        try:
            # Build Redis URL with optional DB selection (same as Container)
            # Why: Ensures feeder sees same keys as producers/consumers
            redis_url = f"redis://{self.settings.redis_host}:{self.settings.redis_port}"
            redis_kwargs = {"decode_responses": False}  # Keep raw bytes for LREM matching

            # Respect redis_db setting if present (multi-db deployments)
            redis_db = getattr(self.settings, "redis_db", None)
            if redis_db is not None:
                redis_kwargs["db"] = redis_db

            self._redis_client = aioredis.Redis.from_url(redis_url, **redis_kwargs)
            redis_client = self._redis_client
        except Exception as exc:
            logger.error(f"Failed to create Redis client: {exc}")
            return

        try:
            while self._running:
                try:
                    # CRITICAL: Try to become leader
                    # Why: Prevents multiple feeders from running simultaneously
                    if not await self._try_acquire_leader_lock(redis_client):
                        # Not leader, sleep and retry
                        # Why: Another worker is already running the feeder
                        await asyncio.sleep(5)
                        continue

                    # We are the leader, run one feeder cycle
                    # Run orphan cleanup every cycle (lightweight - only updates stuck jobs)
                    # Why: Prevents "Crawl already in progress" blocking from stale records
                    await self._cleanup_orphaned_crawl_jobs()
                    await self._cleanup_orphaned_crawl_runs()

                    # DB hydration removed - Safe Watchdog handles orphan recovery

                    # Find all tenants with pending crawls
                    # Why: Use SCAN instead of KEYS for production safety
                    pattern = "tenant:*:crawl_pending"
                    tenant_ids = set()

                    cursor = 0
                    while True:
                        cursor, keys = await redis_client.scan(
                            cursor=cursor, match=pattern, count=100
                        )

                        for key_bytes in keys:
                            key = key_bytes.decode()
                            # Extract tenant_id from key: tenant:{uuid}:crawl_pending
                            parts = key.split(":")
                            if len(parts) >= 2:
                                try:
                                    tenant_ids.add(UUID(parts[1]))
                                except ValueError:
                                    continue

                        if cursor == 0:
                            break

                    # Process each tenant's pending queue
                    # Why: Single feeder processes ALL tenants efficiently
                    processed_any = False
                    for tenant_id in tenant_ids:
                        try:
                            await self._process_tenant_queue(tenant_id, redis_client)
                            processed_any = True
                        except Exception as exc:
                            logger.error(
                                f"Error processing tenant queue: {exc}",
                                extra={"tenant_id": str(tenant_id)},
                            )
                            continue  # Don't let one tenant's error stop others

                    # Heartbeat pattern: Only log when idle every 5 minutes
                    # Why: Reduces log spam while confirming feeder is alive
                    now = datetime.now(timezone.utc)
                    if not processed_any:
                        if (
                            self._last_heartbeat is None
                            or (now - self._last_heartbeat).total_seconds() >= self._heartbeat_interval
                        ):
                            logger.info("Feeder heartbeat: idle, no pending crawls")
                            self._last_heartbeat = now
                    else:
                        # Reset heartbeat timer after actual work
                        self._last_heartbeat = now

                    # Refresh leader lock before sleeping
                    # Why: Keeps us as leader for next cycle
                    await self._refresh_leader_lock(redis_client)

                    # Sleep until next cycle using tenant-aware interval
                    # Why: Use shortest interval among active tenants for responsive scheduling
                    sleep_interval = await self._get_minimum_feeder_interval(redis_client)
                    await asyncio.sleep(sleep_interval)

                except Exception as exc:
                    logger.error(f"Error in feeder loop: {exc}")
                    # Continue running even on errors
                    # Why: Feeder should be resilient, not crash the worker
                    # Use tenant-aware interval even in error recovery
                    sleep_interval = await self._get_minimum_feeder_interval(redis_client)
                    await asyncio.sleep(sleep_interval)
        finally:
            # Always close Redis client on exit
            # Why: Prevents connection leaks on worker shutdown/reload
            await self._close_redis()

    async def _close_redis(self) -> None:
        """Close Redis client if it exists."""
        if self._redis_client:
            try:
                await self._redis_client.aclose()
                self._redis_client = None
                logger.debug("Feeder Redis client closed")
            except Exception as exc:
                logger.warning(f"Error closing Redis client: {exc}")

    async def stop(self) -> None:
        """Stop the feeder loop gracefully."""
        logger.info("Stopping crawl feeder service")
        self._running = False
        await self._close_redis()
