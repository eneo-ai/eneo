"""Unit tests for AuditService."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from intric.audit.application.audit_service import AuditService, _sanitize_csv_cell
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.actor_types import ActorType
from intric.audit.domain.audit_log import AuditLog
from intric.audit.domain.entity_types import EntityType
from intric.audit.domain.outcome import Outcome


@pytest.fixture
def mock_repository():
    """Create mock AuditLogRepository."""
    return AsyncMock()


@pytest.fixture
def mock_config_service():
    """Create mock AuditConfigService."""
    mock = AsyncMock()
    mock.is_action_enabled.return_value = True  # Default: all enabled
    return mock


@pytest.fixture
def mock_feature_flag_service():
    """Create mock FeatureFlagService."""
    mock = AsyncMock()
    mock.check_is_feature_enabled.return_value = True  # Default: enabled
    return mock


@pytest.fixture
def audit_service(mock_repository):
    """Create AuditService with mock repository only."""
    return AuditService(mock_repository)


@pytest.fixture
def audit_service_with_config(mock_repository, mock_config_service, mock_feature_flag_service):
    """Create AuditService with all dependencies."""
    return AuditService(
        mock_repository,
        audit_config_service=mock_config_service,
        feature_flag_service=mock_feature_flag_service,
    )


class TestBasicLogging:
    """Tests for basic audit log creation."""

    @pytest.mark.asyncio
    async def test_log_creates_audit_log_when_action_enabled(
        self, mock_repository, mock_config_service, mock_feature_flag_service
    ):
        """log() should create audit log when action is enabled."""
        mock_repository.create.return_value = MagicMock(spec=AuditLog)

        service = AuditService(
            mock_repository,
            audit_config_service=mock_config_service,
            feature_flag_service=mock_feature_flag_service,
        )

        result = await service.log(
            tenant_id=uuid4(),
            actor_id=uuid4(),
            action=ActionType.USER_CREATED,
            entity_type=EntityType.USER,
            entity_id=uuid4(),
            description="Test log",
            metadata={},
        )

        assert result is not None
        mock_repository.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_log_returns_none_when_feature_flag_disabled(
        self, mock_repository, mock_config_service, mock_feature_flag_service
    ):
        """log() should return None when audit_logging_enabled flag is False."""
        mock_feature_flag_service.check_is_feature_enabled.return_value = False

        service = AuditService(
            mock_repository,
            audit_config_service=mock_config_service,
            feature_flag_service=mock_feature_flag_service,
        )

        result = await service.log(
            tenant_id=uuid4(),
            actor_id=uuid4(),
            action=ActionType.USER_CREATED,
            entity_type=EntityType.USER,
            entity_id=uuid4(),
            description="Test log",
            metadata={},
        )

        assert result is None
        mock_repository.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_log_returns_none_when_action_disabled(
        self, mock_repository, mock_config_service, mock_feature_flag_service
    ):
        """log() should return None when action is disabled by config."""
        mock_config_service.is_action_enabled.return_value = False

        service = AuditService(
            mock_repository,
            audit_config_service=mock_config_service,
            feature_flag_service=mock_feature_flag_service,
        )

        result = await service.log(
            tenant_id=uuid4(),
            actor_id=uuid4(),
            action=ActionType.USER_CREATED,
            entity_type=EntityType.USER,
            entity_id=uuid4(),
            description="Test log",
            metadata={},
        )

        assert result is None
        mock_repository.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_log_without_config_service_always_logs(self, mock_repository):
        """When audit_config_service is None, all actions are logged."""
        mock_repository.create.return_value = MagicMock(spec=AuditLog)

        service = AuditService(mock_repository)  # No config service

        result = await service.log(
            tenant_id=uuid4(),
            actor_id=uuid4(),
            action=ActionType.USER_CREATED,
            entity_type=EntityType.USER,
            entity_id=uuid4(),
            description="Test log",
            metadata={},
        )

        assert result is not None
        mock_repository.create.assert_called_once()


class TestTwoStageFiltering:
    """Tests for 2-stage filtering logic."""

    @pytest.mark.asyncio
    async def test_should_log_action_stage1_feature_flag_check(
        self, mock_repository, mock_config_service, mock_feature_flag_service
    ):
        """_should_log_action checks feature flag first (stage 1)."""
        mock_feature_flag_service.check_is_feature_enabled.return_value = False

        service = AuditService(
            mock_repository,
            audit_config_service=mock_config_service,
            feature_flag_service=mock_feature_flag_service,
        )

        result = await service._should_log_action(uuid4(), ActionType.USER_CREATED)

        assert result is False
        mock_feature_flag_service.check_is_feature_enabled.assert_called_once()
        # Stage 2 should NOT be called if stage 1 returns False
        mock_config_service.is_action_enabled.assert_not_called()

    @pytest.mark.asyncio
    async def test_should_log_action_stage2_action_config_check(
        self, mock_repository, mock_config_service, mock_feature_flag_service
    ):
        """_should_log_action checks action config second (stage 2)."""
        mock_feature_flag_service.check_is_feature_enabled.return_value = True
        mock_config_service.is_action_enabled.return_value = False

        service = AuditService(
            mock_repository,
            audit_config_service=mock_config_service,
            feature_flag_service=mock_feature_flag_service,
        )

        result = await service._should_log_action(uuid4(), ActionType.USER_CREATED)

        assert result is False
        mock_feature_flag_service.check_is_feature_enabled.assert_called_once()
        mock_config_service.is_action_enabled.assert_called_once()

    @pytest.mark.asyncio
    async def test_should_log_action_graceful_degradation_on_flag_error(
        self, mock_repository, mock_config_service, mock_feature_flag_service
    ):
        """Feature flag service error should default to enabled (log the action)."""
        mock_feature_flag_service.check_is_feature_enabled.side_effect = Exception("Redis error")
        mock_config_service.is_action_enabled.return_value = True

        service = AuditService(
            mock_repository,
            audit_config_service=mock_config_service,
            feature_flag_service=mock_feature_flag_service,
        )

        result = await service._should_log_action(uuid4(), ActionType.USER_CREATED)

        # Should continue and check stage 2 (graceful degradation)
        assert result is True
        mock_config_service.is_action_enabled.assert_called_once()

    @pytest.mark.asyncio
    async def test_should_log_action_without_feature_flag_service(
        self, mock_repository, mock_config_service
    ):
        """When feature_flag_service is None, stage 1 is skipped."""
        mock_config_service.is_action_enabled.return_value = True

        service = AuditService(
            mock_repository,
            audit_config_service=mock_config_service,
            feature_flag_service=None,  # No feature flag service
        )

        result = await service._should_log_action(uuid4(), ActionType.USER_CREATED)

        assert result is True
        # Stage 1 skipped, stage 2 still called
        mock_config_service.is_action_enabled.assert_called_once()


class TestGetLogs:
    """Tests for get_logs method."""

    @pytest.mark.asyncio
    async def test_get_logs_delegates_to_repository(self, audit_service, mock_repository):
        """get_logs() should delegate to repository with correct params."""
        mock_repository.get_logs.return_value = ([], 0)
        tenant_id = uuid4()
        actor_id = uuid4()

        await audit_service.get_logs(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action=ActionType.USER_CREATED,
            page=2,
            page_size=50,
        )

        mock_repository.get_logs.assert_called_once_with(
            tenant_id=tenant_id,
            actor_id=actor_id,
            action=ActionType.USER_CREATED,
            from_date=None,
            to_date=None,
            page=2,
            page_size=50,
        )

    @pytest.mark.asyncio
    async def test_get_logs_default_pagination(self, audit_service, mock_repository):
        """get_logs() should use page=1, page_size=100 by default."""
        mock_repository.get_logs.return_value = ([], 0)
        tenant_id = uuid4()

        await audit_service.get_logs(tenant_id=tenant_id)

        call_args = mock_repository.get_logs.call_args
        assert call_args.kwargs["page"] == 1
        assert call_args.kwargs["page_size"] == 100


class TestGetUserLogs:
    """Tests for get_user_logs method (GDPR export)."""

    @pytest.mark.asyncio
    async def test_get_user_logs_delegates_to_repository(self, audit_service, mock_repository):
        """get_user_logs() should delegate to repository correctly."""
        mock_repository.get_user_logs.return_value = ([], 0)
        tenant_id = uuid4()
        user_id = uuid4()

        await audit_service.get_user_logs(
            tenant_id=tenant_id,
            user_id=user_id,
        )

        mock_repository.get_user_logs.assert_called_once_with(
            tenant_id=tenant_id,
            user_id=user_id,
            from_date=None,
            to_date=None,
            page=1,
            page_size=100,
        )


class TestExportCsv:
    """Tests for CSV export functionality."""

    @pytest.fixture
    def sample_log(self):
        """Create a sample audit log for testing."""
        return AuditLog(
            id=uuid4(),
            tenant_id=uuid4(),
            actor_id=uuid4(),
            actor_type=ActorType.USER,
            action=ActionType.USER_CREATED,
            entity_type=EntityType.USER,
            entity_id=uuid4(),
            timestamp=datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
            description="User test@example.com created",
            metadata={"email": "test@example.com"},
            outcome=Outcome.SUCCESS,
        )

    @pytest.mark.asyncio
    async def test_export_csv_header_row(self, audit_service, mock_repository):
        """export_csv() should include correct header row."""
        mock_repository.get_logs.return_value = ([], 0)

        result = await audit_service.export_csv(tenant_id=uuid4())

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
    async def test_export_csv_with_logs(self, audit_service, mock_repository, sample_log):
        """export_csv() should include log data in CSV format."""
        mock_repository.get_logs.return_value = ([sample_log], 1)

        result = await audit_service.export_csv(tenant_id=uuid4())

        assert "2024-01-15" in result
        assert "user_created" in result
        assert "success" in result
        assert "User test@example.com created" in result

    @pytest.mark.asyncio
    async def test_export_csv_sanitizes_description(self, audit_service, mock_repository):
        """export_csv() should sanitize descriptions starting with dangerous chars."""
        log_with_formula = AuditLog(
            id=uuid4(),
            tenant_id=uuid4(),
            actor_id=uuid4(),
            actor_type=ActorType.USER,
            action=ActionType.USER_CREATED,
            entity_type=EntityType.USER,
            entity_id=uuid4(),
            timestamp=datetime.now(timezone.utc),
            description="=SUM(A1:A10)",  # CSV injection attempt
            metadata={},
            outcome=Outcome.SUCCESS,
        )
        mock_repository.get_logs.return_value = ([log_with_formula], 1)

        result = await audit_service.export_csv(tenant_id=uuid4())

        # Should be prefixed with single quote
        assert "'=SUM(A1:A10)" in result

    @pytest.mark.asyncio
    async def test_export_csv_empty_result(self, audit_service, mock_repository):
        """export_csv() should return header-only CSV when no logs exist."""
        mock_repository.get_logs.return_value = ([], 0)

        result = await audit_service.export_csv(tenant_id=uuid4())

        lines = result.strip().split("\n")
        assert len(lines) == 1  # Header only
        assert "Timestamp" in lines[0]

    @pytest.mark.asyncio
    async def test_export_csv_with_user_id_filter(self, audit_service, mock_repository, sample_log):
        """export_csv() with user_id should use get_user_logs (GDPR export)."""
        mock_repository.get_user_logs.return_value = ([sample_log], 1)
        user_id = uuid4()

        await audit_service.export_csv(tenant_id=uuid4(), user_id=user_id)

        mock_repository.get_user_logs.assert_called()
        mock_repository.get_logs.assert_not_called()

    @pytest.mark.asyncio
    async def test_export_csv_respects_max_records_limit(self, audit_service, mock_repository, sample_log):
        """export_csv() should stop at max_records limit."""
        # Return 100 logs but limit to 5
        logs = [sample_log] * 100
        mock_repository.get_logs.return_value = (logs, 100)

        result = await audit_service.export_csv(tenant_id=uuid4(), max_records=5)

        lines = result.strip().split("\n")
        assert len(lines) == 6  # Header + 5 data rows


class TestExportJsonl:
    """Tests for JSONL export functionality."""

    @pytest.fixture
    def sample_log(self):
        """Create a sample audit log for testing."""
        return AuditLog(
            id=uuid4(),
            tenant_id=uuid4(),
            actor_id=uuid4(),
            actor_type=ActorType.USER,
            action=ActionType.USER_CREATED,
            entity_type=EntityType.USER,
            entity_id=uuid4(),
            timestamp=datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
            description="User created",
            metadata={"key": "value"},
            outcome=Outcome.SUCCESS,
        )

    @pytest.mark.asyncio
    async def test_export_jsonl_format(self, audit_service, mock_repository, sample_log):
        """export_jsonl() should output one JSON object per line."""
        import json

        mock_repository.get_logs.return_value = ([sample_log], 1)

        result = await audit_service.export_jsonl(tenant_id=uuid4())

        lines = result.strip().split("\n")
        assert len(lines) == 1
        # Each line should be valid JSON
        for line in lines:
            parsed = json.loads(line)
            assert "id" in parsed
            assert "tenant_id" in parsed

    @pytest.mark.asyncio
    async def test_export_jsonl_includes_all_fields(self, audit_service, mock_repository, sample_log):
        """export_jsonl() should include all log fields."""
        import json

        mock_repository.get_logs.return_value = ([sample_log], 1)

        result = await audit_service.export_jsonl(tenant_id=uuid4())

        parsed = json.loads(result.strip())
        expected_fields = [
            "id", "tenant_id", "timestamp", "actor_id", "actor_type",
            "action", "entity_type", "entity_id", "description",
            "outcome", "metadata", "ip_address", "user_agent",
            "request_id", "error_message"
        ]
        for field in expected_fields:
            assert field in parsed, f"Missing field: {field}"

    @pytest.mark.asyncio
    async def test_export_jsonl_uuid_serialization(self, audit_service, mock_repository, sample_log):
        """export_jsonl() should serialize UUIDs as strings."""
        import json

        mock_repository.get_logs.return_value = ([sample_log], 1)

        result = await audit_service.export_jsonl(tenant_id=uuid4())

        parsed = json.loads(result.strip())
        assert isinstance(parsed["id"], str)
        assert isinstance(parsed["tenant_id"], str)
        assert isinstance(parsed["actor_id"], str)

    @pytest.mark.asyncio
    async def test_export_jsonl_datetime_serialization(self, audit_service, mock_repository, sample_log):
        """export_jsonl() should serialize datetimes as ISO format."""
        import json

        mock_repository.get_logs.return_value = ([sample_log], 1)

        result = await audit_service.export_jsonl(tenant_id=uuid4())

        parsed = json.loads(result.strip())
        assert "2024-01-15" in parsed["timestamp"]
        assert "T" in parsed["timestamp"]  # ISO format has T separator

    @pytest.mark.asyncio
    async def test_export_jsonl_empty_result(self, audit_service, mock_repository):
        """export_jsonl() should return empty string for no matching logs."""
        mock_repository.get_logs.return_value = ([], 0)

        result = await audit_service.export_jsonl(tenant_id=uuid4())

        assert result == ""

    @pytest.mark.asyncio
    async def test_export_jsonl_respects_max_records(self, audit_service, mock_repository, sample_log):
        """export_jsonl() should stop at max_records limit."""
        logs = [sample_log] * 100
        mock_repository.get_logs.return_value = (logs, 100)

        result = await audit_service.export_jsonl(tenant_id=uuid4(), max_records=5)

        lines = result.strip().split("\n")
        assert len(lines) == 5


class TestErrorHandling:
    """Tests for error handling paths."""

    @pytest.mark.asyncio
    async def test_log_propagates_validation_errors(self, audit_service, mock_repository):
        """log() should propagate AuditLog validation errors."""
        mock_repository.create.return_value = MagicMock(spec=AuditLog)

        # Empty description should fail validation during AuditLog creation
        with pytest.raises(ValueError, match="must not be empty"):
            await audit_service.log(
                tenant_id=uuid4(),
                actor_id=uuid4(),
                action=ActionType.USER_CREATED,
                entity_type=EntityType.USER,
                entity_id=uuid4(),
                description="",  # Invalid
                metadata={},
            )


class TestLogAsync:
    """Tests for async logging (ARQ integration)."""

    @pytest.mark.asyncio
    async def test_log_async_returns_none_when_feature_flag_disabled(
        self, mock_repository, mock_config_service, mock_feature_flag_service
    ):
        """log_async() should return None when global audit flag is disabled."""
        mock_feature_flag_service.check_is_feature_enabled.return_value = False

        service = AuditService(
            mock_repository,
            audit_config_service=mock_config_service,
            feature_flag_service=mock_feature_flag_service,
        )

        with patch("intric.audit.application.audit_service.job_manager"):
            result = await service.log_async(
                tenant_id=uuid4(),
                actor_id=uuid4(),
                action=ActionType.USER_CREATED,
                entity_type=EntityType.USER,
                entity_id=uuid4(),
                description="Test",
                metadata={},
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_log_async_returns_none_when_action_disabled(
        self, mock_repository, mock_config_service, mock_feature_flag_service
    ):
        """log_async() should return None when action is disabled by config."""
        mock_config_service.is_action_enabled.return_value = False

        service = AuditService(
            mock_repository,
            audit_config_service=mock_config_service,
            feature_flag_service=mock_feature_flag_service,
        )

        with patch("intric.audit.application.audit_service.job_manager"):
            result = await service.log_async(
                tenant_id=uuid4(),
                actor_id=uuid4(),
                action=ActionType.USER_CREATED,
                entity_type=EntityType.USER,
                entity_id=uuid4(),
                description="Test",
                metadata={},
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_log_async_checks_filtering_before_enqueue(
        self, mock_repository, mock_config_service, mock_feature_flag_service
    ):
        """Filtering should happen BEFORE enqueueing to ARQ."""
        mock_config_service.is_action_enabled.return_value = False
        mock_job_manager = AsyncMock()

        service = AuditService(
            mock_repository,
            audit_config_service=mock_config_service,
            feature_flag_service=mock_feature_flag_service,
        )

        with patch("intric.audit.application.audit_service.job_manager", mock_job_manager):
            await service.log_async(
                tenant_id=uuid4(),
                actor_id=uuid4(),
                action=ActionType.USER_CREATED,
                entity_type=EntityType.USER,
                entity_id=uuid4(),
                description="Test",
                metadata={},
            )

        # job_manager should NOT be called when action is disabled
        mock_job_manager.enqueue.assert_not_called()

    @pytest.mark.asyncio
    async def test_log_async_failure_with_error_message_succeeds(self, audit_service):
        """FAILURE outcome with error_message should enqueue successfully."""
        mock_job_manager = AsyncMock()

        with patch("intric.audit.application.audit_service.job_manager", mock_job_manager):
            result = await audit_service.log_async(
                tenant_id=uuid4(),
                actor_id=uuid4(),
                action=ActionType.USER_CREATED,
                entity_type=EntityType.USER,
                entity_id=uuid4(),
                description="Operation failed",
                metadata={},
                outcome=Outcome.FAILURE,
                error_message="Database connection error",
            )

        assert result is not None
        mock_job_manager.enqueue.assert_called_once()
