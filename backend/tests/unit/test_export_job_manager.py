"""Unit tests for ExportJobManager Redis operations."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from intric.audit.domain.export_job import ExportJob, ExportJobStatus
from intric.audit.infrastructure.export_job_manager import ExportJobManager


class TestExportJobManagerKeyGeneration:
    """Tests for Redis key generation."""

    def test_job_key_format(self):
        """Verify job key follows expected pattern."""
        redis_mock = MagicMock()
        manager = ExportJobManager(redis_mock)

        tenant_id = uuid4()
        job_id = uuid4()

        key = manager._job_key(tenant_id, job_id)

        assert key == f"audit_export:{tenant_id}:{job_id}"

    def test_tenant_jobs_pattern(self):
        """Verify tenant jobs pattern for scanning."""
        redis_mock = MagicMock()
        manager = ExportJobManager(redis_mock)

        tenant_id = uuid4()
        pattern = manager._tenant_jobs_pattern(tenant_id)

        assert pattern == f"audit_export:{tenant_id}:*"


class TestExportJobCreation:
    """Tests for job creation."""

    @pytest.fixture
    def mock_settings(self):
        """Mock settings with export configuration."""
        settings = MagicMock()
        settings.export_max_age_hours = 24
        return settings

    @pytest.fixture
    def manager_with_mocks(self, mock_settings):
        """Create manager with mocked Redis."""
        redis_mock = AsyncMock()
        with patch(
            "intric.audit.infrastructure.export_job_manager.get_settings",
            return_value=mock_settings,
        ):
            manager = ExportJobManager(redis_mock)
        return manager, redis_mock

    @pytest.mark.asyncio
    async def test_create_job_stores_in_redis(self, manager_with_mocks, mock_settings):
        """Verify job creation stores data in Redis with correct TTL."""
        manager, redis_mock = manager_with_mocks
        manager._settings = mock_settings

        job_id = uuid4()
        tenant_id = uuid4()

        await manager.create_job(job_id, tenant_id, format="csv")

        # Verify Redis setex was called
        redis_mock.setex.assert_called_once()
        call_args = redis_mock.setex.call_args

        # Check key format
        assert f"audit_export:{tenant_id}:{job_id}" == call_args[0][0]

        # Check TTL (24 hours in seconds)
        assert call_args[0][1] == 24 * 3600

        # Check job data
        stored_data = json.loads(call_args[0][2])
        assert stored_data["job_id"] == str(job_id)
        assert stored_data["tenant_id"] == str(tenant_id)
        assert stored_data["status"] == "pending"
        assert stored_data["format"] == "csv"

    @pytest.mark.asyncio
    async def test_create_job_returns_pending_status(self, manager_with_mocks, mock_settings):
        """Verify created job starts in pending status."""
        manager, redis_mock = manager_with_mocks
        manager._settings = mock_settings

        job = await manager.create_job(uuid4(), uuid4(), format="jsonl")

        assert job.status == ExportJobStatus.PENDING
        assert job.progress == 0
        assert job.format == "jsonl"

    @pytest.mark.asyncio
    async def test_create_job_sets_expiration(self, manager_with_mocks, mock_settings):
        """Verify job expires_at is set correctly."""
        manager, redis_mock = manager_with_mocks
        manager._settings = mock_settings

        before = datetime.now(timezone.utc)
        job = await manager.create_job(uuid4(), uuid4())
        after = datetime.now(timezone.utc)

        # expires_at should be ~24 hours from now
        expected_min = before + timedelta(hours=24)
        expected_max = after + timedelta(hours=24)

        assert expected_min <= job.expires_at <= expected_max


class TestExportJobRetrieval:
    """Tests for job retrieval."""

    @pytest.fixture
    def manager_with_mocks(self):
        """Create manager with mocked Redis."""
        redis_mock = AsyncMock()
        settings_mock = MagicMock()
        settings_mock.export_max_age_hours = 24

        with patch(
            "intric.audit.infrastructure.export_job_manager.get_settings",
            return_value=settings_mock,
        ):
            manager = ExportJobManager(redis_mock)

        return manager, redis_mock

    @pytest.mark.asyncio
    async def test_get_job_returns_none_when_not_found(self, manager_with_mocks):
        """Verify None is returned for non-existent job."""
        manager, redis_mock = manager_with_mocks
        redis_mock.get.return_value = None

        result = await manager.get_job(uuid4(), uuid4())

        assert result is None

    @pytest.mark.asyncio
    async def test_get_job_parses_redis_data(self, manager_with_mocks):
        """Verify job is correctly parsed from Redis."""
        manager, redis_mock = manager_with_mocks

        job_id = uuid4()
        tenant_id = uuid4()
        now = datetime.now(timezone.utc)

        stored_data = {
            "job_id": str(job_id),
            "tenant_id": str(tenant_id),
            "status": "processing",
            "progress": 50,
            "total_records": 1000,
            "processed_records": 500,
            "format": "csv",
            "file_path": None,
            "file_size_bytes": None,
            "error_message": None,
            "cancelled": False,
            "created_at": now.isoformat(),
            "started_at": now.isoformat(),
            "completed_at": None,
            "expires_at": (now + timedelta(hours=24)).isoformat(),
        }
        redis_mock.get.return_value = json.dumps(stored_data)

        result = await manager.get_job(tenant_id, job_id)

        assert result is not None
        assert result.job_id == job_id
        assert result.tenant_id == tenant_id
        assert result.status == ExportJobStatus.PROCESSING
        assert result.progress == 50


class TestExportJobProgressUpdates:
    """Tests for progress update functionality."""

    @pytest.fixture
    def manager_with_job(self):
        """Create manager with existing job in Redis."""
        redis_mock = AsyncMock()
        settings_mock = MagicMock()
        settings_mock.export_max_age_hours = 24

        with patch(
            "intric.audit.infrastructure.export_job_manager.get_settings",
            return_value=settings_mock,
        ):
            manager = ExportJobManager(redis_mock)

        job_id = uuid4()
        tenant_id = uuid4()
        now = datetime.now(timezone.utc)

        job_data = {
            "job_id": str(job_id),
            "tenant_id": str(tenant_id),
            "status": "pending",
            "progress": 0,
            "total_records": 0,
            "processed_records": 0,
            "format": "csv",
            "file_path": None,
            "file_size_bytes": None,
            "error_message": None,
            "cancelled": False,
            "created_at": now.isoformat(),
            "started_at": None,
            "completed_at": None,
            "expires_at": (now + timedelta(hours=24)).isoformat(),
        }
        redis_mock.get.return_value = json.dumps(job_data)

        return manager, redis_mock, job_id, tenant_id

    @pytest.mark.asyncio
    async def test_update_progress_calculates_percentage(self, manager_with_job):
        """Verify progress percentage is calculated correctly."""
        manager, redis_mock, job_id, tenant_id = manager_with_job

        result = await manager.update_progress(
            tenant_id=tenant_id,
            job_id=job_id,
            processed_records=500,
            total_records=1000,
        )

        assert result.progress == 50
        assert result.processed_records == 500
        assert result.total_records == 1000

    @pytest.mark.asyncio
    async def test_update_progress_caps_at_99_percent(self, manager_with_job):
        """Verify progress never exceeds 99% during processing."""
        manager, redis_mock, job_id, tenant_id = manager_with_job

        result = await manager.update_progress(
            tenant_id=tenant_id,
            job_id=job_id,
            processed_records=999,
            total_records=1000,
        )

        assert result.progress == 99

    @pytest.mark.asyncio
    async def test_update_progress_transitions_to_processing(self, manager_with_job):
        """Verify job transitions from pending to processing on first update."""
        manager, redis_mock, job_id, tenant_id = manager_with_job

        result = await manager.update_progress(
            tenant_id=tenant_id,
            job_id=job_id,
            processed_records=100,
            total_records=1000,
        )

        assert result.status == ExportJobStatus.PROCESSING
        assert result.started_at is not None

    @pytest.mark.asyncio
    async def test_update_progress_handles_zero_total(self, manager_with_job):
        """Verify zero total records doesn't cause division error."""
        manager, redis_mock, job_id, tenant_id = manager_with_job

        result = await manager.update_progress(
            tenant_id=tenant_id,
            job_id=job_id,
            processed_records=0,
            total_records=0,
        )

        assert result.progress == 0


class TestExportJobCompletion:
    """Tests for job completion states."""

    @pytest.fixture
    def manager_with_processing_job(self):
        """Create manager with job in processing state."""
        redis_mock = AsyncMock()
        settings_mock = MagicMock()
        settings_mock.export_max_age_hours = 24

        with patch(
            "intric.audit.infrastructure.export_job_manager.get_settings",
            return_value=settings_mock,
        ):
            manager = ExportJobManager(redis_mock)

        job_id = uuid4()
        tenant_id = uuid4()
        now = datetime.now(timezone.utc)

        job_data = {
            "job_id": str(job_id),
            "tenant_id": str(tenant_id),
            "status": "processing",
            "progress": 50,
            "total_records": 1000,
            "processed_records": 500,
            "format": "csv",
            "file_path": None,
            "file_size_bytes": None,
            "error_message": None,
            "cancelled": False,
            "created_at": now.isoformat(),
            "started_at": now.isoformat(),
            "completed_at": None,
            "expires_at": (now + timedelta(hours=24)).isoformat(),
        }
        redis_mock.get.return_value = json.dumps(job_data)

        return manager, redis_mock, job_id, tenant_id

    @pytest.mark.asyncio
    async def test_complete_job_sets_final_state(self, manager_with_processing_job):
        """Verify job completion sets all final fields."""
        manager, redis_mock, job_id, tenant_id = manager_with_processing_job

        result = await manager.complete_job(
            tenant_id=tenant_id,
            job_id=job_id,
            file_path="/app/exports/test.csv",
            file_size_bytes=1024000,
            total_records=1000,
        )

        assert result.status == ExportJobStatus.COMPLETED
        assert result.progress == 100
        assert result.file_path == "/app/exports/test.csv"
        assert result.file_size_bytes == 1024000
        assert result.completed_at is not None

    @pytest.mark.asyncio
    async def test_fail_job_stores_error_message(self, manager_with_processing_job):
        """Verify failure stores error message."""
        manager, redis_mock, job_id, tenant_id = manager_with_processing_job

        result = await manager.fail_job(
            tenant_id=tenant_id,
            job_id=job_id,
            error_message="Database connection lost",
        )

        assert result.status == ExportJobStatus.FAILED
        assert result.error_message == "Database connection lost"
        assert result.completed_at is not None


class TestExportJobCancellation:
    """Tests for job cancellation functionality."""

    @pytest.fixture
    def manager_with_cancellable_job(self):
        """Create manager with job that can be cancelled."""
        redis_mock = AsyncMock()
        settings_mock = MagicMock()
        settings_mock.export_max_age_hours = 24

        with patch(
            "intric.audit.infrastructure.export_job_manager.get_settings",
            return_value=settings_mock,
        ):
            manager = ExportJobManager(redis_mock)

        job_id = uuid4()
        tenant_id = uuid4()
        now = datetime.now(timezone.utc)

        job_data = {
            "job_id": str(job_id),
            "tenant_id": str(tenant_id),
            "status": "processing",
            "progress": 25,
            "total_records": 1000,
            "processed_records": 250,
            "format": "csv",
            "file_path": None,
            "file_size_bytes": None,
            "error_message": None,
            "cancelled": False,
            "created_at": now.isoformat(),
            "started_at": now.isoformat(),
            "completed_at": None,
            "expires_at": (now + timedelta(hours=24)).isoformat(),
        }
        redis_mock.get.return_value = json.dumps(job_data)

        return manager, redis_mock, job_id, tenant_id

    @pytest.mark.asyncio
    async def test_set_cancelled_flags_job(self, manager_with_cancellable_job):
        """Verify cancellation sets the cancelled flag."""
        manager, redis_mock, job_id, tenant_id = manager_with_cancellable_job

        result = await manager.set_cancelled(tenant_id, job_id)

        assert result is True

        # Verify Redis was updated with cancelled flag
        call_args = redis_mock.setex.call_args
        stored_data = json.loads(call_args[0][2])
        assert stored_data["cancelled"] is True

    @pytest.mark.asyncio
    async def test_set_cancelled_returns_false_for_completed_job(self):
        """Verify completed jobs cannot be cancelled."""
        redis_mock = AsyncMock()
        settings_mock = MagicMock()
        settings_mock.export_max_age_hours = 24

        with patch(
            "intric.audit.infrastructure.export_job_manager.get_settings",
            return_value=settings_mock,
        ):
            manager = ExportJobManager(redis_mock)

        job_id = uuid4()
        tenant_id = uuid4()
        now = datetime.now(timezone.utc)

        # Job already completed
        job_data = {
            "job_id": str(job_id),
            "tenant_id": str(tenant_id),
            "status": "completed",
            "progress": 100,
            "total_records": 1000,
            "processed_records": 1000,
            "format": "csv",
            "file_path": "/app/exports/test.csv",
            "file_size_bytes": 1024000,
            "error_message": None,
            "cancelled": False,
            "created_at": now.isoformat(),
            "started_at": now.isoformat(),
            "completed_at": now.isoformat(),
            "expires_at": (now + timedelta(hours=24)).isoformat(),
        }
        redis_mock.get.return_value = json.dumps(job_data)

        result = await manager.set_cancelled(tenant_id, job_id)

        assert result is False
        redis_mock.setex.assert_not_called()

    @pytest.mark.asyncio
    async def test_is_cancelled_returns_true_when_flagged(self, manager_with_cancellable_job):
        """Verify is_cancelled detects cancellation flag."""
        manager, redis_mock, job_id, tenant_id = manager_with_cancellable_job

        # Update mock to return cancelled job
        now = datetime.now(timezone.utc)
        job_data = {
            "job_id": str(job_id),
            "tenant_id": str(tenant_id),
            "status": "processing",
            "progress": 25,
            "total_records": 1000,
            "processed_records": 250,
            "format": "csv",
            "file_path": None,
            "file_size_bytes": None,
            "error_message": None,
            "cancelled": True,  # Flag set
            "created_at": now.isoformat(),
            "started_at": now.isoformat(),
            "completed_at": None,
            "expires_at": (now + timedelta(hours=24)).isoformat(),
        }
        redis_mock.get.return_value = json.dumps(job_data)

        result = await manager.is_cancelled(tenant_id, job_id)

        assert result is True

    @pytest.mark.asyncio
    async def test_is_cancelled_returns_true_for_missing_job(self, manager_with_cancellable_job):
        """Verify missing job is treated as cancelled."""
        manager, redis_mock, job_id, tenant_id = manager_with_cancellable_job
        redis_mock.get.return_value = None

        result = await manager.is_cancelled(tenant_id, job_id)

        assert result is True


class TestExportJobConcurrencyLimit:
    """Tests for concurrent job limiting."""

    @pytest.fixture
    def manager_with_active_jobs(self):
        """Create manager with multiple active jobs."""
        redis_mock = AsyncMock()
        settings_mock = MagicMock()
        settings_mock.export_max_age_hours = 24

        with patch(
            "intric.audit.infrastructure.export_job_manager.get_settings",
            return_value=settings_mock,
        ):
            manager = ExportJobManager(redis_mock)

        tenant_id = uuid4()
        now = datetime.now(timezone.utc)

        # Create mock for scan to return multiple keys
        redis_mock.scan.return_value = (
            0,  # cursor = 0 means done
            [
                f"audit_export:{tenant_id}:{uuid4()}".encode(),
                f"audit_export:{tenant_id}:{uuid4()}".encode(),
            ],
        )

        # Create job data for active jobs
        def get_side_effect(key):
            job_data = {
                "job_id": str(uuid4()),
                "tenant_id": str(tenant_id),
                "status": "processing",
                "progress": 50,
                "total_records": 1000,
                "processed_records": 500,
                "format": "csv",
                "file_path": None,
                "file_size_bytes": None,
                "error_message": None,
                "cancelled": False,
                "created_at": now.isoformat(),
                "started_at": now.isoformat(),
                "completed_at": None,
                "expires_at": (now + timedelta(hours=24)).isoformat(),
            }
            return json.dumps(job_data)

        redis_mock.get.side_effect = get_side_effect

        return manager, redis_mock, tenant_id

    @pytest.mark.asyncio
    async def test_count_active_jobs_scans_redis(self, manager_with_active_jobs):
        """Verify active job counting uses Redis scan."""
        manager, redis_mock, tenant_id = manager_with_active_jobs

        count = await manager.count_active_jobs(tenant_id)

        # Should find 2 active jobs
        assert count == 2

    @pytest.mark.asyncio
    async def test_count_active_jobs_ignores_terminal_jobs(self):
        """Verify completed/failed jobs are not counted."""
        redis_mock = AsyncMock()
        settings_mock = MagicMock()
        settings_mock.export_max_age_hours = 24

        with patch(
            "intric.audit.infrastructure.export_job_manager.get_settings",
            return_value=settings_mock,
        ):
            manager = ExportJobManager(redis_mock)

        tenant_id = uuid4()
        now = datetime.now(timezone.utc)

        # Return keys for both active and terminal jobs
        redis_mock.scan.return_value = (
            0,
            [
                f"audit_export:{tenant_id}:active".encode(),
                f"audit_export:{tenant_id}:completed".encode(),
            ],
        )

        # First call returns processing job, second returns completed
        call_count = [0]

        def get_side_effect(key):
            call_count[0] += 1
            if call_count[0] == 1:
                status = "processing"
            else:
                status = "completed"

            job_data = {
                "job_id": str(uuid4()),
                "tenant_id": str(tenant_id),
                "status": status,
                "progress": 50 if status == "processing" else 100,
                "total_records": 1000,
                "processed_records": 500 if status == "processing" else 1000,
                "format": "csv",
                "file_path": None if status == "processing" else "/path/file.csv",
                "file_size_bytes": None if status == "processing" else 1024,
                "error_message": None,
                "cancelled": False,
                "created_at": now.isoformat(),
                "started_at": now.isoformat(),
                "completed_at": now.isoformat() if status == "completed" else None,
                "expires_at": (now + timedelta(hours=24)).isoformat(),
            }
            return json.dumps(job_data)

        redis_mock.get.side_effect = get_side_effect

        count = await manager.count_active_jobs(tenant_id)

        # Only 1 active job (the processing one)
        assert count == 1


class TestExportJobCleanup:
    """Tests for job cleanup functionality."""

    @pytest.fixture
    def manager_with_expired_jobs(self):
        """Create manager with expired jobs."""
        redis_mock = AsyncMock()
        settings_mock = MagicMock()
        settings_mock.export_max_age_hours = 24

        with patch(
            "intric.audit.infrastructure.export_job_manager.get_settings",
            return_value=settings_mock,
        ):
            manager = ExportJobManager(redis_mock)

        tenant_id = uuid4()
        expired_job_id = uuid4()
        valid_job_id = uuid4()

        now = datetime.now(timezone.utc)
        past = now - timedelta(hours=25)  # Expired

        redis_mock.scan.return_value = (
            0,
            [
                f"audit_export:{tenant_id}:{expired_job_id}".encode(),
                f"audit_export:{tenant_id}:{valid_job_id}".encode(),
            ],
        )

        call_count = [0]

        def get_side_effect(key):
            call_count[0] += 1
            is_expired = call_count[0] == 1

            job_data = {
                "job_id": str(expired_job_id if is_expired else valid_job_id),
                "tenant_id": str(tenant_id),
                "status": "completed",
                "progress": 100,
                "total_records": 1000,
                "processed_records": 1000,
                "format": "csv",
                "file_path": "/path/file.csv",
                "file_size_bytes": 1024,
                "error_message": None,
                "cancelled": False,
                "created_at": past.isoformat() if is_expired else now.isoformat(),
                "started_at": past.isoformat() if is_expired else now.isoformat(),
                "completed_at": past.isoformat() if is_expired else now.isoformat(),
                "expires_at": past.isoformat() if is_expired else (now + timedelta(hours=24)).isoformat(),
            }
            return json.dumps(job_data)

        redis_mock.get.side_effect = get_side_effect

        return manager, redis_mock, tenant_id, expired_job_id

    @pytest.mark.asyncio
    async def test_get_expired_jobs_returns_only_expired(self, manager_with_expired_jobs):
        """Verify only expired jobs are returned."""
        manager, redis_mock, tenant_id, expired_job_id = manager_with_expired_jobs

        expired_jobs = await manager.get_expired_jobs()

        # Should only return the expired job
        assert len(expired_jobs) == 1
        assert expired_jobs[0].job_id == expired_job_id

    @pytest.mark.asyncio
    async def test_delete_job_removes_from_redis(self):
        """Verify job deletion removes Redis key."""
        redis_mock = AsyncMock()
        redis_mock.delete.return_value = 1

        settings_mock = MagicMock()
        settings_mock.export_max_age_hours = 24

        with patch(
            "intric.audit.infrastructure.export_job_manager.get_settings",
            return_value=settings_mock,
        ):
            manager = ExportJobManager(redis_mock)

        tenant_id = uuid4()
        job_id = uuid4()

        result = await manager.delete_job(tenant_id, job_id)

        assert result is True
        redis_mock.delete.assert_called_once_with(f"audit_export:{tenant_id}:{job_id}")


class TestExportJobDomainModel:
    """Tests for ExportJob domain model."""

    def test_is_terminal_for_completed(self):
        """Verify completed status is terminal."""
        job = ExportJob(
            job_id=uuid4(),
            tenant_id=uuid4(),
            status=ExportJobStatus.COMPLETED,
        )
        assert job.is_terminal() is True

    def test_is_terminal_for_failed(self):
        """Verify failed status is terminal."""
        job = ExportJob(
            job_id=uuid4(),
            tenant_id=uuid4(),
            status=ExportJobStatus.FAILED,
        )
        assert job.is_terminal() is True

    def test_is_terminal_for_cancelled(self):
        """Verify cancelled status is terminal."""
        job = ExportJob(
            job_id=uuid4(),
            tenant_id=uuid4(),
            status=ExportJobStatus.CANCELLED,
        )
        assert job.is_terminal() is True

    def test_is_not_terminal_for_pending(self):
        """Verify pending status is not terminal."""
        job = ExportJob(
            job_id=uuid4(),
            tenant_id=uuid4(),
            status=ExportJobStatus.PENDING,
        )
        assert job.is_terminal() is False

    def test_is_not_terminal_for_processing(self):
        """Verify processing status is not terminal."""
        job = ExportJob(
            job_id=uuid4(),
            tenant_id=uuid4(),
            status=ExportJobStatus.PROCESSING,
        )
        assert job.is_terminal() is False

    def test_can_be_cancelled_for_pending(self):
        """Verify pending jobs can be cancelled."""
        job = ExportJob(
            job_id=uuid4(),
            tenant_id=uuid4(),
            status=ExportJobStatus.PENDING,
        )
        assert job.can_be_cancelled() is True

    def test_can_be_cancelled_for_processing(self):
        """Verify processing jobs can be cancelled."""
        job = ExportJob(
            job_id=uuid4(),
            tenant_id=uuid4(),
            status=ExportJobStatus.PROCESSING,
        )
        assert job.can_be_cancelled() is True

    def test_cannot_cancel_completed(self):
        """Verify completed jobs cannot be cancelled."""
        job = ExportJob(
            job_id=uuid4(),
            tenant_id=uuid4(),
            status=ExportJobStatus.COMPLETED,
        )
        assert job.can_be_cancelled() is False

    def test_to_redis_dict_serialization(self):
        """Verify Redis serialization includes all fields."""
        job_id = uuid4()
        tenant_id = uuid4()
        now = datetime.now(timezone.utc)

        job = ExportJob(
            job_id=job_id,
            tenant_id=tenant_id,
            status=ExportJobStatus.PROCESSING,
            progress=50,
            total_records=1000,
            processed_records=500,
            format="jsonl",
            cancelled=False,
            created_at=now,
            started_at=now,
            expires_at=now + timedelta(hours=24),
        )

        data = job.to_redis_dict()

        assert data["job_id"] == str(job_id)
        assert data["tenant_id"] == str(tenant_id)
        assert data["status"] == "processing"
        assert data["progress"] == 50
        assert data["format"] == "jsonl"

    def test_from_redis_dict_deserialization(self):
        """Verify Redis deserialization reconstructs job."""
        job_id = uuid4()
        tenant_id = uuid4()
        now = datetime.now(timezone.utc)

        data = {
            "job_id": str(job_id),
            "tenant_id": str(tenant_id),
            "status": "completed",
            "progress": 100,
            "total_records": 5000,
            "processed_records": 5000,
            "format": "csv",
            "file_path": "/app/exports/test.csv",
            "file_size_bytes": 2048000,
            "error_message": None,
            "cancelled": False,
            "created_at": now.isoformat(),
            "started_at": now.isoformat(),
            "completed_at": now.isoformat(),
            "expires_at": (now + timedelta(hours=24)).isoformat(),
        }

        job = ExportJob.from_redis_dict(data)

        assert job.job_id == job_id
        assert job.tenant_id == tenant_id
        assert job.status == ExportJobStatus.COMPLETED
        assert job.file_size_bytes == 2048000
