"""Unit tests for the queues module.

Tests PendingQueue and JobEnqueuer classes for feeder job management.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest


def _job_data() -> dict[str, object]:
    return {
        "job_id": str(uuid4()),
        "user_id": str(uuid4()),
        "website_id": str(uuid4()),
        "run_id": str(uuid4()),
        "url": "https://example.com",
        "download_files": True,
        "crawl_type": "crawl",
    }


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
        job_data = _job_data()
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
        valid_job = _job_data()
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


class TestPendingQueueAdd:
    """Tests for PendingQueue.add method."""

    @pytest.mark.asyncio
    async def test_pushes_deterministic_payload_bytes(self):
        """Should serialize job data consistently for exact queue matching."""
        from intric.worker.feeder.queues import CrawlPendingJobData, PendingQueue

        tenant_id = uuid4()
        job_data: CrawlPendingJobData = {
            "job_id": str(uuid4()),
            "user_id": str(uuid4()),
            "website_id": str(uuid4()),
            "run_id": str(uuid4()),
            "url": "https://example.com",
            "download_files": True,
            "crawl_type": "crawl",
        }

        redis_mock = MagicMock()
        redis_mock.rpush = AsyncMock()

        queue = PendingQueue(redis_mock)
        await queue.add(tenant_id, job_data)

        redis_mock.rpush.assert_called_once_with(
            f"tenant:{tenant_id}:crawl_pending",
            json.dumps(job_data, default=str, sort_keys=True),
        )

    @pytest.mark.asyncio
    async def test_raises_typed_error_on_rpush_failure(self):
        """Should preserve the original Redis failure for caller rollback policy."""
        from intric.worker.feeder.queues import (
            CrawlPendingJobData,
            PendingQueue,
            PendingQueueAddError,
        )

        tenant_id = uuid4()
        job_data: CrawlPendingJobData = {
            "job_id": str(uuid4()),
            "user_id": str(uuid4()),
            "website_id": str(uuid4()),
            "run_id": str(uuid4()),
            "url": "https://example.com",
            "download_files": False,
            "crawl_type": "crawl",
        }
        redis_error = RuntimeError("redis unavailable")

        redis_mock = MagicMock()
        redis_mock.rpush = AsyncMock(side_effect=redis_error)

        queue = PendingQueue(redis_mock)
        with pytest.raises(PendingQueueAddError) as exc_info:
            await queue.add(tenant_id, job_data)

        assert exc_info.value.tenant_id == tenant_id
        assert exc_info.value.__cause__ is redis_error
        assert "redis unavailable" in str(exc_info.value)


class TestJobEnqueuerEnqueue:
    """Tests for JobEnqueuer.enqueue method."""

    @pytest.mark.asyncio
    async def test_delegates_pending_payload_to_typed_crawl_enqueue(self):
        """Pending queue JSON stays at the edge before typed enqueue."""
        from intric.websites.domain.crawl_run import CrawlType
        from intric.worker.feeder.crawl_enqueue import (
            CrawlEnqueued,
        )
        from intric.worker.feeder.queues import JobEnqueuer

        job_id = uuid4()
        user_id = uuid4()
        website_id = uuid4()
        run_id = uuid4()
        job_data = {
            "job_id": str(job_id),
            "user_id": str(user_id),
            "website_id": str(website_id),
            "run_id": str(run_id),
            "url": "https://example.com",
            "download_files": True,
            "crawl_type": "sitemap",
        }

        with patch(
            "intric.worker.feeder.queues.enqueue_crawl_job",
            new=AsyncMock(return_value=CrawlEnqueued(job_id=job_id)),
        ) as enqueue_crawl_job:
            result = await JobEnqueuer().enqueue(job_data, uuid4())

        assert result == CrawlEnqueued(job_id=job_id)
        enqueue_crawl_job.assert_awaited_once_with(
            job_id=job_id,
            user_id=user_id,
            website_id=website_id,
            run_id=run_id,
            url="https://example.com",
            download_files=True,
            crawl_type=CrawlType.SITEMAP,
        )

    @pytest.mark.asyncio
    async def test_returns_success_on_successful_enqueue(self):
        """Should preserve the typed successful enqueue result."""
        from intric.worker.feeder.crawl_enqueue import (
            CrawlEnqueued,
        )
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
            "crawl_type": "crawl",
        }

        with patch(
            "intric.worker.feeder.queues.enqueue_crawl_job",
            new=AsyncMock(return_value=CrawlEnqueued(job_id=job_id)),
        ) as enqueue_crawl_job:
            enqueuer = JobEnqueuer()
            result = await enqueuer.enqueue(job_data, tenant_id)

        assert result == CrawlEnqueued(job_id=job_id)
        enqueue_crawl_job.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_treats_native_arq_duplicate_return_as_duplicate(self):
        """Should mark duplicate when ARQ returns None for an existing job id."""
        from intric.worker.feeder.crawl_enqueue import (
            CrawlEnqueueDuplicate,
        )
        from intric.worker.feeder.queues import JobEnqueuer

        job_id = uuid4()
        job_data = {
            "job_id": str(job_id),
            "user_id": str(uuid4()),
            "website_id": str(uuid4()),
            "run_id": str(uuid4()),
            "url": "https://example.com",
            "download_files": False,
            "crawl_type": "crawl",
        }

        with patch(
            "intric.worker.feeder.queues.enqueue_crawl_job",
            new=AsyncMock(return_value=CrawlEnqueueDuplicate(job_id=job_id)),
        ):
            enqueuer = JobEnqueuer()
            result = await enqueuer.enqueue(job_data, uuid4())

        assert result == CrawlEnqueueDuplicate(job_id=job_id)

    @pytest.mark.asyncio
    async def test_returns_failure_on_invalid_job_id(self):
        """Should return a typed failure when job_id is invalid."""
        from intric.worker.feeder.crawl_enqueue import CrawlEnqueueFailed
        from intric.worker.feeder.queues import JobEnqueuer

        job_data = {"job_id": "not-a-uuid"}

        enqueuer = JobEnqueuer()
        result = await enqueuer.enqueue(job_data, uuid4())

        assert isinstance(result, CrawlEnqueueFailed)
        assert result.job_id == UUID("00000000-0000-0000-0000-000000000000")

    @pytest.mark.asyncio
    async def test_returns_failure_on_missing_job_id(self):
        """Should return a typed failure when job_id is missing."""
        from intric.worker.feeder.crawl_enqueue import CrawlEnqueueFailed
        from intric.worker.feeder.queues import JobEnqueuer

        job_data = {"url": "https://example.com"}

        enqueuer = JobEnqueuer()
        result = await enqueuer.enqueue(job_data, uuid4())

        assert isinstance(result, CrawlEnqueueFailed)
        assert result.job_id == UUID("00000000-0000-0000-0000-000000000000")

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("user_id", "not-a-uuid"),
            ("website_id", "not-a-uuid"),
            ("run_id", "not-a-uuid"),
            ("crawl_type", "not-a-crawl-type"),
        ],
    )
    async def test_returns_failure_on_invalid_pending_payload_fields(
        self, field: str, value: object
    ):
        """Invalid payload fields fail before the typed enqueue owner is called."""
        from intric.worker.feeder.crawl_enqueue import CrawlEnqueueFailed
        from intric.worker.feeder.queues import JobEnqueuer

        job_id = uuid4()
        job_data = {
            "job_id": str(job_id),
            "user_id": str(uuid4()),
            "website_id": str(uuid4()),
            "run_id": str(uuid4()),
            "url": "https://example.com",
            "download_files": False,
            "crawl_type": "crawl",
        }
        job_data[field] = value

        with patch(
            "intric.worker.feeder.queues.enqueue_crawl_job",
            new=AsyncMock(),
        ) as enqueue_crawl_job:
            result = await JobEnqueuer().enqueue(job_data, uuid4())

        assert isinstance(result, CrawlEnqueueFailed)
        assert result.job_id == job_id
        enqueue_crawl_job.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_does_not_parse_duplicate_exceptions_as_success(self):
        """Only JobManager.enqueue(False) is a duplicate signal."""
        from intric.worker.feeder.crawl_enqueue import (
            CrawlEnqueueFailed,
        )
        from intric.worker.feeder.queues import JobEnqueuer

        job_id = uuid4()
        enqueue_error = Exception("Job already exists")
        job_data = {
            "job_id": str(job_id),
            "user_id": str(uuid4()),
            "website_id": str(uuid4()),
            "run_id": str(uuid4()),
            "url": "https://example.com",
            "download_files": False,
            "crawl_type": "crawl",
        }

        with patch(
            "intric.worker.feeder.queues.enqueue_crawl_job",
            new=AsyncMock(
                return_value=CrawlEnqueueFailed(
                    job_id=job_id,
                    error=enqueue_error,
                )
            ),
        ):
            enqueuer = JobEnqueuer()
            result = await enqueuer.enqueue(job_data, uuid4())

        assert result == CrawlEnqueueFailed(job_id=job_id, error=enqueue_error)

    @pytest.mark.asyncio
    async def test_returns_failure_on_real_error(self):
        """Should preserve typed failures on non-duplicate errors."""
        from intric.worker.feeder.crawl_enqueue import (
            CrawlEnqueueFailed,
        )
        from intric.worker.feeder.queues import JobEnqueuer

        job_id = uuid4()
        enqueue_error = Exception("Connection refused")
        job_data = {
            "job_id": str(job_id),
            "user_id": str(uuid4()),
            "website_id": str(uuid4()),
            "run_id": str(uuid4()),
            "url": "https://example.com",
            "download_files": False,
            "crawl_type": "crawl",
        }

        with patch(
            "intric.worker.feeder.queues.enqueue_crawl_job",
            new=AsyncMock(
                return_value=CrawlEnqueueFailed(
                    job_id=job_id,
                    error=enqueue_error,
                )
            ),
        ):
            enqueuer = JobEnqueuer()
            result = await enqueuer.enqueue(job_data, uuid4())

        assert result == CrawlEnqueueFailed(job_id=job_id, error=enqueue_error)


class TestJobEnqueuerDuplicateDetection:
    """Tests that duplicate detection stays bound to ARQ's native signal."""

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
    async def test_exception_text_does_not_define_duplicate_semantics(
        self, error_message
    ):
        """Wrapped queue errors must stay visible instead of becoming duplicates."""
        from intric.worker.feeder.crawl_enqueue import (
            CrawlEnqueueFailed,
        )
        from intric.worker.feeder.queues import JobEnqueuer

        job_id = uuid4()
        enqueue_error = Exception(error_message)
        job_data = {
            "job_id": str(job_id),
            "user_id": str(uuid4()),
            "website_id": str(uuid4()),
            "run_id": str(uuid4()),
            "url": "https://example.com",
            "download_files": False,
            "crawl_type": "crawl",
        }

        with patch(
            "intric.worker.feeder.queues.enqueue_crawl_job",
            new=AsyncMock(
                return_value=CrawlEnqueueFailed(
                    job_id=job_id,
                    error=enqueue_error,
                )
            ),
        ):
            enqueuer = JobEnqueuer()
            result = await enqueuer.enqueue(job_data, uuid4())

        assert result == CrawlEnqueueFailed(job_id=job_id, error=enqueue_error), (
            f"Should not swallow '{error_message}'"
        )
