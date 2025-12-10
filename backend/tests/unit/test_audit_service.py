"""Unit tests for AuditService."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from intric.audit.application.audit_service import AuditService
from intric.audit.domain.action_types import ActionType
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
            search=None,
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


# NOTE: Export tests (TestExportCsv, TestExportJsonl) have been moved to
# test_audit_export_service.py as part of service extraction refactoring.
# See AuditExportService for the new export functionality.


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
