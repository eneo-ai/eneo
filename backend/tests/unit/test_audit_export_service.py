"""Unit tests for AuditExportService."""

from datetime import datetime, timezone
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from intric.audit.application.audit_export_service import AuditExportService, ExportTooLargeError


def make_raw_log_dict(
    timestamp: datetime = None,
    actor_id: str = None,
    actor_type: str = "user",
    action: str = "user_created",
    entity_type: str = "user",
    entity_id: str = None,
    description: str = "Test log entry",
    outcome: str = "success",
    error_message: str = None,
    metadata: dict = None,
) -> dict:
    """Create a raw log dictionary as returned by stream_logs_raw."""
    return {
        "timestamp": (timestamp or datetime.now(timezone.utc)).isoformat(),
        "actor_id": actor_id or str(uuid4()),
        "actor_type": actor_type,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id or str(uuid4()),
        "description": description,
        "outcome": outcome,
        "error_message": error_message,
        "metadata": metadata or {},
    }


async def async_generator_from_list(items: list) -> AsyncIterator:
    """Convert a list to an async generator."""
    for item in items:
        yield item


def make_stream_mock(items: list = None):
    """Create a mock that returns a fresh async generator on each call.

    AsyncMock doesn't work for async generators because it wraps the
    return_value in a coroutine. Using side_effect with a lambda
    ensures each call gets a fresh async generator.
    """
    items = items if items is not None else []
    mock = MagicMock(side_effect=lambda **kwargs: async_generator_from_list(items))
    return mock


@pytest.fixture
def mock_repository():
    """Create mock AuditLogRepository with streaming methods.

    Uses MagicMock with side_effect instead of AsyncMock because
    async generators need __aiter__, not __await__.
    The count methods use AsyncMock for OOM protection pre-flight checks.
    """
    repo = MagicMock()
    # Default: return empty async generators
    repo.stream_logs_raw = make_stream_mock([])
    repo.stream_user_logs_raw = make_stream_mock([])
    # OOM protection count methods (AsyncMock for await)
    repo.count_logs = AsyncMock(return_value=0)
    repo.count_user_logs = AsyncMock(return_value=0)
    return repo


@pytest.fixture
def export_service(mock_repository):
    """Create AuditExportService with mock repository."""
    return AuditExportService(mock_repository)


class TestExportCsv:
    """Tests for CSV export functionality."""

    @pytest.fixture
    def sample_log_dict(self):
        """Create a sample raw log dictionary for testing."""
        return make_raw_log_dict(
            timestamp=datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
            description="User test@example.com created",
            action="user_created",
            metadata={"email": "test@example.com"},
        )

    @pytest.mark.asyncio
    async def test_export_csv_header_row(self, export_service, mock_repository):
        """export_csv() should include correct header row."""
        # Uses default empty stream from fixture
        result = await export_service.export_csv(tenant_id=uuid4())

        assert "Timestamp" in result
        assert "Actor ID" in result
        assert "Actor Type" in result
        assert "Action" in result
        assert "Entity Type" in result
        assert "Entity ID" in result
        assert "Description" in result
        assert "Outcome" in result
        assert "Error Message" in result
        assert "Metadata" in result

    @pytest.mark.asyncio
    async def test_export_csv_with_logs(self, export_service, mock_repository, sample_log_dict):
        """export_csv() should include log data in CSV format."""
        mock_repository.stream_logs_raw = make_stream_mock([sample_log_dict])

        result = await export_service.export_csv(tenant_id=uuid4())

        assert "2024-01-15" in result
        assert "user_created" in result
        assert "success" in result
        assert "User test@example.com created" in result

    @pytest.mark.asyncio
    async def test_export_csv_sanitizes_description(self, export_service, mock_repository):
        """export_csv() should sanitize descriptions starting with dangerous chars."""
        log_with_formula = make_raw_log_dict(description="=SUM(A1:A10)")
        mock_repository.stream_logs_raw = make_stream_mock([log_with_formula])

        result = await export_service.export_csv(tenant_id=uuid4())

        # Should be prefixed with single quote
        assert "'=SUM(A1:A10)" in result

    @pytest.mark.asyncio
    async def test_export_csv_empty_result(self, export_service, mock_repository):
        """export_csv() should return header-only CSV when no logs exist."""
        # Uses default empty stream from fixture
        result = await export_service.export_csv(tenant_id=uuid4())

        lines = result.strip().split("\n")
        assert len(lines) == 1  # Header only
        assert "Timestamp" in lines[0]

    @pytest.mark.asyncio
    async def test_export_csv_with_user_id_filter(self, export_service, mock_repository, sample_log_dict):
        """export_csv() with user_id should use stream_user_logs_raw (GDPR export)."""
        mock_repository.stream_user_logs_raw = make_stream_mock([sample_log_dict])
        user_id = uuid4()

        await export_service.export_csv(tenant_id=uuid4(), user_id=user_id)

        mock_repository.stream_user_logs_raw.assert_called()
        mock_repository.stream_logs_raw.assert_not_called()

    @pytest.mark.asyncio
    async def test_export_csv_respects_max_records_limit(self, export_service, mock_repository, sample_log_dict):
        """export_csv() should stop at max_records limit."""
        # Return 100 logs but limit to 5
        logs = [make_raw_log_dict() for _ in range(100)]
        mock_repository.stream_logs_raw = make_stream_mock(logs)

        result = await export_service.export_csv(tenant_id=uuid4(), max_records=5)

        lines = result.strip().split("\n")
        assert len(lines) == 6  # Header + 5 data rows


class TestExportJsonl:
    """Tests for JSONL export functionality."""

    @pytest.fixture
    def sample_log_dict(self):
        """Create a sample raw log dictionary for testing."""
        return make_raw_log_dict(
            timestamp=datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
            description="User created",
            metadata={"key": "value"},
        )

    @pytest.mark.asyncio
    async def test_export_jsonl_format(self, export_service, mock_repository, sample_log_dict):
        """export_jsonl() should output one JSON object per line."""
        import json

        mock_repository.stream_logs_raw = make_stream_mock([sample_log_dict])

        result = await export_service.export_jsonl(tenant_id=uuid4())

        lines = result.strip().split("\n")
        assert len(lines) == 1
        # Each line should be valid JSON
        for line in lines:
            parsed = json.loads(line)
            assert "timestamp" in parsed
            assert "actor_id" in parsed

    @pytest.mark.asyncio
    async def test_export_jsonl_includes_all_fields(self, export_service, mock_repository, sample_log_dict):
        """export_jsonl() should include all log fields."""
        import json

        mock_repository.stream_logs_raw = make_stream_mock([sample_log_dict])

        result = await export_service.export_jsonl(tenant_id=uuid4())
        parsed = json.loads(result.strip())

        expected_fields = [
            "timestamp", "actor_id", "actor_type", "action",
            "entity_type", "entity_id", "description", "outcome",
            "metadata"
        ]
        for field in expected_fields:
            assert field in parsed

    @pytest.mark.asyncio
    async def test_export_jsonl_empty_result(self, export_service, mock_repository):
        """export_jsonl() should return empty string when no logs exist."""
        # Uses default empty stream from fixture
        result = await export_service.export_jsonl(tenant_id=uuid4())

        assert result == ""

    @pytest.mark.asyncio
    async def test_export_jsonl_respects_max_records(self, export_service, mock_repository, sample_log_dict):
        """export_jsonl() should stop at max_records limit."""
        logs = [make_raw_log_dict() for _ in range(100)]
        mock_repository.stream_logs_raw = make_stream_mock(logs)

        result = await export_service.export_jsonl(tenant_id=uuid4(), max_records=5)

        lines = result.strip().split("\n")
        assert len(lines) == 5

    @pytest.mark.asyncio
    async def test_export_jsonl_with_user_id_filter(self, export_service, mock_repository, sample_log_dict):
        """export_jsonl() with user_id should use stream_user_logs_raw (GDPR export)."""
        mock_repository.stream_user_logs_raw = make_stream_mock([sample_log_dict])
        user_id = uuid4()

        await export_service.export_jsonl(tenant_id=uuid4(), user_id=user_id)

        mock_repository.stream_user_logs_raw.assert_called()
        mock_repository.stream_logs_raw.assert_not_called()


class TestCsvSanitization:
    """Tests for CSV injection prevention."""

    @pytest.mark.asyncio
    async def test_sanitizes_equals_prefix(self, export_service, mock_repository):
        """Should sanitize values starting with '='."""
        log = make_raw_log_dict(description="=1+1")
        mock_repository.stream_logs_raw = make_stream_mock([log])

        result = await export_service.export_csv(tenant_id=uuid4())
        assert "'=1+1" in result

    @pytest.mark.asyncio
    async def test_sanitizes_plus_prefix(self, export_service, mock_repository):
        """Should sanitize values starting with '+'."""
        log = make_raw_log_dict(description="+1234567890")
        mock_repository.stream_logs_raw = make_stream_mock([log])

        result = await export_service.export_csv(tenant_id=uuid4())
        assert "'+1234567890" in result

    @pytest.mark.asyncio
    async def test_sanitizes_minus_prefix(self, export_service, mock_repository):
        """Should sanitize values starting with '-'."""
        log = make_raw_log_dict(description="-1234567890")
        mock_repository.stream_logs_raw = make_stream_mock([log])

        result = await export_service.export_csv(tenant_id=uuid4())
        assert "'-1234567890" in result

    @pytest.mark.asyncio
    async def test_sanitizes_at_prefix(self, export_service, mock_repository):
        """Should sanitize values starting with '@'."""
        log = make_raw_log_dict(description="@SUM(A1)")
        mock_repository.stream_logs_raw = make_stream_mock([log])

        result = await export_service.export_csv(tenant_id=uuid4())
        assert "'@SUM(A1)" in result


class TestDatetimeHandling:
    """Tests for datetime object serialization in raw dict exports.

    SQLAlchemy Core with asyncpg returns native Python datetime objects,
    not ISO strings. The _raw_dict_to_csv_row method must handle both.
    """

    def make_log_with_datetime(self, ts: datetime) -> dict:
        """Create a log dict with a native datetime object (not ISO string)."""
        return {
            "timestamp": ts,  # Native datetime, not .isoformat()
            "actor_id": str(uuid4()),
            "actor_type": "user",
            "action": "user_created",
            "entity_type": "user",
            "entity_id": str(uuid4()),
            "description": "Test log with datetime object",
            "outcome": "success",
            "error_message": None,
            "metadata": {},
        }

    @pytest.mark.asyncio
    async def test_handles_native_datetime_objects(self, export_service, mock_repository):
        """export_csv() should correctly serialize native datetime objects."""
        ts = datetime(2024, 6, 15, 14, 30, 45, tzinfo=timezone.utc)
        log = self.make_log_with_datetime(ts)
        mock_repository.stream_logs_raw = make_stream_mock([log])

        result = await export_service.export_csv(tenant_id=uuid4())

        # Should contain ISO format timestamp
        assert "2024-06-15T14:30:45" in result

    @pytest.mark.asyncio
    async def test_handles_iso_string_timestamps(self, export_service, mock_repository):
        """export_csv() should pass through ISO string timestamps unchanged."""
        log = make_raw_log_dict(
            timestamp=datetime(2024, 6, 15, 14, 30, 45, tzinfo=timezone.utc)
        )  # Uses .isoformat() internally
        mock_repository.stream_logs_raw = make_stream_mock([log])

        result = await export_service.export_csv(tenant_id=uuid4())

        # Should contain ISO format timestamp
        assert "2024-06-15T14:30:45" in result

    @pytest.mark.asyncio
    async def test_consistent_output_format_regardless_of_input_type(
        self, export_service, mock_repository
    ):
        """Both datetime objects and ISO strings should produce consistent output."""
        ts = datetime(2024, 6, 15, 14, 30, 45, tzinfo=timezone.utc)

        # Log with datetime object
        log_with_dt = self.make_log_with_datetime(ts)
        mock_repository.stream_logs_raw = make_stream_mock([log_with_dt])
        result_from_dt = await export_service.export_csv(tenant_id=uuid4())

        # Log with ISO string
        log_with_str = make_raw_log_dict(timestamp=ts)
        mock_repository.stream_logs_raw = make_stream_mock([log_with_str])
        result_from_str = await export_service.export_csv(tenant_id=uuid4())

        # Both should contain the same timestamp format
        assert "2024-06-15T14:30:45" in result_from_dt
        assert "2024-06-15T14:30:45" in result_from_str


class TestGeneratorExports:
    """Tests for generator-based export methods (for StreamingResponse)."""

    @pytest.fixture
    def sample_logs(self):
        """Create sample logs for testing."""
        return [make_raw_log_dict() for _ in range(5)]

    @pytest.mark.asyncio
    async def test_export_csv_stream_yields_header_first(self, export_service, mock_repository):
        """export_csv_stream() should yield header as first chunk."""
        mock_repository.stream_logs_raw = make_stream_mock([])

        chunks = []
        async for chunk in export_service.export_csv_stream(tenant_id=uuid4()):
            chunks.append(chunk)

        assert len(chunks) == 1  # Just header for empty result
        assert "Timestamp" in chunks[0]
        assert "Actor ID" in chunks[0]

    @pytest.mark.asyncio
    async def test_export_csv_stream_yields_data(
        self, export_service, mock_repository, sample_logs
    ):
        """export_csv_stream() should yield CSV data after header."""
        mock_repository.stream_logs_raw = make_stream_mock(sample_logs)

        chunks = []
        async for chunk in export_service.export_csv_stream(tenant_id=uuid4()):
            chunks.append(chunk)

        # At least header + data
        assert len(chunks) >= 2
        # First chunk is header
        assert "Timestamp" in chunks[0]
        # Subsequent chunks contain data
        full_content = "".join(chunks)
        assert full_content.count("\n") >= 6  # Header + 5 data rows

    @pytest.mark.asyncio
    async def test_export_csv_stream_batches_large_datasets(
        self, export_service, mock_repository
    ):
        """export_csv_stream() should batch large datasets."""
        # Create more than STREAM_BATCH_SIZE logs
        large_logs = [make_raw_log_dict() for _ in range(1500)]
        mock_repository.stream_logs_raw = make_stream_mock(large_logs)

        chunks = []
        async for chunk in export_service.export_csv_stream(tenant_id=uuid4()):
            chunks.append(chunk)

        # Should have multiple batches: header + at least 2 data batches
        assert len(chunks) >= 3  # header + 1000-row batch + 500-row batch

    @pytest.mark.asyncio
    async def test_export_csv_stream_respects_max_records(
        self, export_service, mock_repository
    ):
        """export_csv_stream() should respect max_records limit."""
        logs = [make_raw_log_dict() for _ in range(100)]
        mock_repository.stream_logs_raw = make_stream_mock(logs)

        chunks = []
        async for chunk in export_service.export_csv_stream(tenant_id=uuid4(), max_records=5):
            chunks.append(chunk)

        full_content = "".join(chunks)
        lines = full_content.strip().split("\n")
        assert len(lines) == 6  # Header + 5 data rows

    @pytest.mark.asyncio
    async def test_export_jsonl_stream_yields_data(
        self, export_service, mock_repository, sample_logs
    ):
        """export_jsonl_stream() should yield JSONL data as bytes."""
        import json

        mock_repository.stream_logs_raw = make_stream_mock(sample_logs)

        chunks = []
        async for chunk in export_service.export_jsonl_stream(tenant_id=uuid4()):
            chunks.append(chunk)

        # Should have yielded bytes data
        assert len(chunks) >= 1
        assert all(isinstance(c, bytes) for c in chunks)  # Verify bytes type
        full_content = b"".join(chunks).decode("utf-8")
        lines = full_content.strip().split("\n")
        assert len(lines) == 5

        # Each line should be valid JSON
        for line in lines:
            parsed = json.loads(line)
            assert "timestamp" in parsed
            assert "actor_id" in parsed

    @pytest.mark.asyncio
    async def test_export_jsonl_stream_empty_result(self, export_service, mock_repository):
        """export_jsonl_stream() should yield nothing for empty dataset."""
        mock_repository.stream_logs_raw = make_stream_mock([])

        chunks = []
        async for chunk in export_service.export_jsonl_stream(tenant_id=uuid4()):
            chunks.append(chunk)

        assert len(chunks) == 0

    @pytest.mark.asyncio
    async def test_export_jsonl_stream_batches_large_datasets(
        self, export_service, mock_repository
    ):
        """export_jsonl_stream() should batch large datasets."""
        large_logs = [make_raw_log_dict() for _ in range(1500)]
        mock_repository.stream_logs_raw = make_stream_mock(large_logs)

        chunks = []
        async for chunk in export_service.export_jsonl_stream(tenant_id=uuid4()):
            chunks.append(chunk)

        # Should have multiple batches
        assert len(chunks) >= 2  # 1000-row batch + 500-row batch

    @pytest.mark.asyncio
    async def test_export_jsonl_stream_respects_max_records(
        self, export_service, mock_repository
    ):
        """export_jsonl_stream() should respect max_records limit."""
        logs = [make_raw_log_dict() for _ in range(100)]
        mock_repository.stream_logs_raw = make_stream_mock(logs)

        chunks = []
        async for chunk in export_service.export_jsonl_stream(tenant_id=uuid4(), max_records=5):
            chunks.append(chunk)

        full_content = b"".join(chunks).decode("utf-8")
        lines = full_content.strip().split("\n")
        assert len(lines) == 5

    @pytest.mark.asyncio
    async def test_export_csv_stream_with_user_id_filter(
        self, export_service, mock_repository, sample_logs
    ):
        """export_csv_stream() with user_id should use stream_user_logs_raw."""
        mock_repository.stream_user_logs_raw = make_stream_mock(sample_logs)
        user_id = uuid4()

        chunks = []
        async for chunk in export_service.export_csv_stream(tenant_id=uuid4(), user_id=user_id):
            chunks.append(chunk)

        mock_repository.stream_user_logs_raw.assert_called()
        mock_repository.stream_logs_raw.assert_not_called()

    @pytest.mark.asyncio
    async def test_export_jsonl_stream_with_user_id_filter(
        self, export_service, mock_repository, sample_logs
    ):
        """export_jsonl_stream() with user_id should use stream_user_logs_raw."""
        mock_repository.stream_user_logs_raw = make_stream_mock(sample_logs)
        user_id = uuid4()

        chunks = []
        async for chunk in export_service.export_jsonl_stream(tenant_id=uuid4(), user_id=user_id):
            chunks.append(chunk)

        mock_repository.stream_user_logs_raw.assert_called()
        mock_repository.stream_logs_raw.assert_not_called()


class TestOomProtection:
    """Tests for OOM protection in in-memory exports."""

    @pytest.mark.asyncio
    async def test_export_csv_raises_when_exceeds_limit(self, mock_repository):
        """export_csv() should raise ExportTooLargeError when count exceeds limit."""
        # Configure mock to return count exceeding limit
        mock_repository.count_logs = AsyncMock(return_value=150_000)
        mock_repository.stream_logs_raw = make_stream_mock([])

        service = AuditExportService(mock_repository)

        with pytest.raises(ExportTooLargeError) as exc_info:
            await service.export_csv(tenant_id=uuid4())

        assert exc_info.value.record_count == 150_000
        assert exc_info.value.limit == service.EXPORT_MEMORY_LIMIT
        # Stream should not be called when count check fails
        mock_repository.stream_logs_raw.assert_not_called()

    @pytest.mark.asyncio
    async def test_export_jsonl_raises_when_exceeds_limit(self, mock_repository):
        """export_jsonl() should raise ExportTooLargeError when count exceeds limit."""
        mock_repository.count_logs = AsyncMock(return_value=200_000)
        mock_repository.stream_logs_raw = make_stream_mock([])

        service = AuditExportService(mock_repository)

        with pytest.raises(ExportTooLargeError) as exc_info:
            await service.export_jsonl(tenant_id=uuid4())

        assert "200,000 found" in str(exc_info.value)
        assert "Use streaming export" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_export_csv_skips_check_with_max_records(self, mock_repository):
        """export_csv() should skip OOM check when max_records is set."""
        mock_repository.count_logs = AsyncMock(return_value=500_000)  # Would fail
        mock_repository.stream_logs_raw = make_stream_mock([make_raw_log_dict() for _ in range(5)])

        service = AuditExportService(mock_repository)

        # Should NOT raise because max_records is set (user acknowledges limit)
        result = await service.export_csv(tenant_id=uuid4(), max_records=5)

        assert "Timestamp" in result
        # count_logs should NOT be called when max_records is set
        mock_repository.count_logs.assert_not_called()

    @pytest.mark.asyncio
    async def test_export_jsonl_skips_check_with_max_records(self, mock_repository):
        """export_jsonl() should skip OOM check when max_records is set."""
        mock_repository.count_logs = AsyncMock(return_value=500_000)  # Would fail
        mock_repository.stream_logs_raw = make_stream_mock([make_raw_log_dict() for _ in range(3)])

        service = AuditExportService(mock_repository)

        # Should NOT raise because max_records is set
        result = await service.export_jsonl(tenant_id=uuid4(), max_records=3)

        assert result  # Should have content
        mock_repository.count_logs.assert_not_called()

    @pytest.mark.asyncio
    async def test_export_csv_proceeds_when_under_limit(self, mock_repository):
        """export_csv() should proceed when count is under limit."""
        mock_repository.count_logs = AsyncMock(return_value=50_000)  # Under 100k limit
        mock_repository.stream_logs_raw = make_stream_mock([make_raw_log_dict()])

        service = AuditExportService(mock_repository)

        result = await service.export_csv(tenant_id=uuid4())

        assert "Timestamp" in result
        mock_repository.stream_logs_raw.assert_called()

    @pytest.mark.asyncio
    async def test_export_too_large_error_message_format(self):
        """ExportTooLargeError should have clear, actionable message."""
        error = ExportTooLargeError(record_count=150_000, limit=100_000)

        message = str(error)
        assert "150,000" in message  # Formatted with commas
        assert "100,000" in message
        assert "streaming" in message.lower()
        assert "max_records" in message
