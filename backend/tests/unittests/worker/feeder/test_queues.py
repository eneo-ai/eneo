"""Unit tests for the queues module.

Tests PendingQueue and JobEnqueuer classes for feeder job management.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest


class TestPendingQueueGetPending:
    """Tests for PendingQueue.get_pending method."""

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_queue_empty(self):
        """Should return empty list when no pending jobs."""
        from intric.worker.feeder.queues import PendingQueue

        redis_mock = MagicMock()
        redis_mock.lrange = AsyncMock(return_value=[])

        queue = PendingQueue(redis_mock)
        result = await queue.get_pending(uuid4(), limit=10)

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_parsed_jobs_with_raw_bytes(self):
        """Should return tuples of (raw_bytes, parsed_data)."""
        from intric.worker.feeder.queues import PendingQueue

        tenant_id = uuid4()
        job_data = {"job_id": str(uuid4()), "url": "https://example.com"}
        raw_bytes = json.dumps(job_data).encode()

        redis_mock = MagicMock()
        redis_mock.lrange = AsyncMock(return_value=[raw_bytes])

        queue = PendingQueue(redis_mock)
        result = await queue.get_pending(tenant_id, limit=10)

        assert len(result) == 1
        assert result[0][0] == raw_bytes
        assert result[0][1] == job_data

    @pytest.mark.asyncio
    async def test_removes_poison_messages(self):
        """Should remove and skip invalid JSON (poison messages)."""
        from intric.worker.feeder.queues import PendingQueue

        tenant_id = uuid4()
        valid_job = {"job_id": str(uuid4())}
        valid_bytes = json.dumps(valid_job).encode()
        poison_bytes = b"not valid json {"

        redis_mock = MagicMock()
        redis_mock.lrange = AsyncMock(return_value=[poison_bytes, valid_bytes])
        redis_mock.lrem = AsyncMock()

        queue = PendingQueue(redis_mock)
        result = await queue.get_pending(tenant_id, limit=10)

        # Should only return valid job
        assert len(result) == 1
        assert result[0][1] == valid_job

        # Should attempt to remove poison message
        redis_mock.lrem.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_empty_list_on_redis_error(self):
        """Should return empty list and not raise on Redis error."""
        from intric.worker.feeder.queues import PendingQueue

        redis_mock = MagicMock()
        redis_mock.lrange = AsyncMock(side_effect=Exception("Redis error"))

        queue = PendingQueue(redis_mock)
        result = await queue.get_pending(uuid4(), limit=10)

        assert result == []

    @pytest.mark.asyncio
    async def test_uses_correct_key_format(self):
        """Should use tenant:{tenant_id}:crawl_pending key pattern."""
        from intric.worker.feeder.queues import PendingQueue

        tenant_id = uuid4()

        redis_mock = MagicMock()
        redis_mock.lrange = AsyncMock(return_value=[])

        queue = PendingQueue(redis_mock)
        await queue.get_pending(tenant_id, limit=5)

        redis_mock.lrange.assert_called_once_with(
            f"tenant:{tenant_id}:crawl_pending", 0, 4
        )


class TestPendingQueueRemove:
    """Tests for PendingQueue.remove method."""

    @pytest.mark.asyncio
    async def test_removes_job_using_exact_bytes(self):
        """Should remove job using exact original bytes."""
        from intric.worker.feeder.queues import PendingQueue

        tenant_id = uuid4()
        raw_bytes = b'{"job_id": "123"}'

        redis_mock = MagicMock()
        redis_mock.lrem = AsyncMock()

        queue = PendingQueue(redis_mock)
        await queue.remove(tenant_id, raw_bytes)

        redis_mock.lrem.assert_called_once_with(
            f"tenant:{tenant_id}:crawl_pending", 1, raw_bytes
        )

    @pytest.mark.asyncio
    async def test_does_not_raise_on_redis_error(self):
        """Should swallow Redis errors (best effort removal)."""
        from intric.worker.feeder.queues import PendingQueue

        redis_mock = MagicMock()
        redis_mock.lrem = AsyncMock(side_effect=Exception("Redis error"))

        queue = PendingQueue(redis_mock)
        # Should not raise
        await queue.remove(uuid4(), b"data")


class TestJobEnqueuerEnqueue:
    """Tests for JobEnqueuer.enqueue method."""

    @pytest.mark.asyncio
    async def test_returns_success_on_successful_enqueue(self):
        """Should return (True, False, job_id) on successful enqueue."""
        from intric.worker.feeder.queues import JobEnqueuer

        job_id = uuid4()
        tenant_id = uuid4()
        job_data = {
            "job_id": str(job_id),
            "user_id": str(uuid4()),
            "website_id": str(uuid4()),
            "run_id": str(uuid4()),
            "url": "https://example.com",
            "download_files": False,
            "crawl_type": "full",
        }

        with (
            patch("intric.worker.feeder.queues.job_manager") as mock_manager,
            patch("intric.jobs.job_models.Task"),
            patch("intric.websites.crawl_dependencies.crawl_models.CrawlTask"),
            patch("intric.websites.crawl_dependencies.crawl_models.CrawlType"),
        ):
            mock_manager.enqueue = AsyncMock()

            enqueuer = JobEnqueuer()
            success, is_duplicate, returned_id = await enqueuer.enqueue(
                job_data, tenant_id
            )

            assert success is True
            assert is_duplicate is False
            assert returned_id == job_id
            mock_manager.enqueue.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_failure_on_invalid_job_id(self):
        """Should return (False, False, nil_uuid) when job_id is invalid."""
        from intric.worker.feeder.queues import JobEnqueuer

        job_data = {"job_id": "not-a-uuid"}

        enqueuer = JobEnqueuer()
        success, is_duplicate, returned_id = await enqueuer.enqueue(job_data, uuid4())

        assert success is False
        assert is_duplicate is False
        assert returned_id == UUID("00000000-0000-0000-0000-000000000000")

    @pytest.mark.asyncio
    async def test_returns_failure_on_missing_job_id(self):
        """Should return (False, False, nil_uuid) when job_id is missing."""
        from intric.worker.feeder.queues import JobEnqueuer

        job_data = {"url": "https://example.com"}

        enqueuer = JobEnqueuer()
        success, is_duplicate, returned_id = await enqueuer.enqueue(job_data, uuid4())

        assert success is False
        assert is_duplicate is False
        assert returned_id == UUID("00000000-0000-0000-0000-000000000000")

    @pytest.mark.asyncio
    async def test_treats_duplicate_job_as_success(self):
        """Should return (True, True, job_id) when job already exists in ARQ."""
        from intric.worker.feeder.queues import JobEnqueuer

        job_id = uuid4()
        job_data = {
            "job_id": str(job_id),
            "user_id": str(uuid4()),
            "website_id": str(uuid4()),
            "run_id": str(uuid4()),
            "url": "https://example.com",
            "download_files": False,
            "crawl_type": "full",
        }

        with (
            patch("intric.worker.feeder.queues.job_manager") as mock_manager,
            patch("intric.jobs.job_models.Task"),
            patch("intric.websites.crawl_dependencies.crawl_models.CrawlTask"),
            patch("intric.websites.crawl_dependencies.crawl_models.CrawlType"),
        ):
            mock_manager.enqueue = AsyncMock(
                side_effect=Exception("Job already exists")
            )

            enqueuer = JobEnqueuer()
            success, is_duplicate, returned_id = await enqueuer.enqueue(
                job_data, uuid4()
            )

            assert success is True
            assert is_duplicate is True  # This is a duplicate!
            assert returned_id == job_id

    @pytest.mark.asyncio
    async def test_returns_failure_on_real_error(self):
        """Should return (False, False, job_id) on non-duplicate errors."""
        from intric.worker.feeder.queues import JobEnqueuer

        job_id = uuid4()
        job_data = {
            "job_id": str(job_id),
            "user_id": str(uuid4()),
            "website_id": str(uuid4()),
            "run_id": str(uuid4()),
            "url": "https://example.com",
            "download_files": False,
            "crawl_type": "full",
        }

        with (
            patch("intric.worker.feeder.queues.job_manager") as mock_manager,
            patch("intric.jobs.job_models.Task"),
            patch("intric.websites.crawl_dependencies.crawl_models.CrawlTask"),
            patch("intric.websites.crawl_dependencies.crawl_models.CrawlType"),
        ):
            mock_manager.enqueue = AsyncMock(
                side_effect=Exception("Connection refused")
            )

            enqueuer = JobEnqueuer()
            success, is_duplicate, returned_id = await enqueuer.enqueue(
                job_data, uuid4()
            )

            assert success is False
            assert is_duplicate is False
            assert returned_id == job_id


class TestJobEnqueuerDuplicateDetection:
    """Tests for duplicate job detection patterns."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "error_message",
        [
            "Job already exists",
            "duplicate job_id",
            "Job exists in queue",
            "ALREADY EXISTS",
            "Duplicate entry",
        ],
    )
    async def test_detects_various_duplicate_patterns(self, error_message):
        """Should detect various duplicate job error patterns."""
        from intric.worker.feeder.queues import JobEnqueuer

        job_id = uuid4()
        job_data = {
            "job_id": str(job_id),
            "user_id": str(uuid4()),
            "website_id": str(uuid4()),
            "run_id": str(uuid4()),
            "url": "https://example.com",
            "download_files": False,
            "crawl_type": "full",
        }

        with (
            patch("intric.worker.feeder.queues.job_manager") as mock_manager,
            patch("intric.jobs.job_models.Task"),
            patch("intric.websites.crawl_dependencies.crawl_models.CrawlTask"),
            patch("intric.websites.crawl_dependencies.crawl_models.CrawlType"),
        ):
            mock_manager.enqueue = AsyncMock(side_effect=Exception(error_message))

            enqueuer = JobEnqueuer()
            success, is_duplicate, _ = await enqueuer.enqueue(job_data, uuid4())

            assert success is True, f"Should treat '{error_message}' as duplicate"
            assert is_duplicate is True, (
                f"'{error_message}' should be marked as duplicate"
            )
