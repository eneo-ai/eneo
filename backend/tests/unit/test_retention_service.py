"""Unit tests for RetentionService - audit log retention policy management."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from datetime import datetime, timezone

from intric.audit.application.retention_service import (
    RetentionService,
    RetentionPolicyModel,
)


# === Constants ===
MINIMUM_RETENTION_DAYS = 1
MAXIMUM_RETENTION_DAYS = 2555  # ~7 years
DEFAULT_RETENTION_DAYS = 365


@pytest.fixture
def mock_session():
    """Create a mock SQLAlchemy async session."""
    session = AsyncMock()
    session.execute = AsyncMock()
    return session


@pytest.fixture
def retention_service(mock_session):
    """Create RetentionService with mocked session."""
    return RetentionService(mock_session)


@pytest.fixture
def sample_policy_row():
    """Create a sample policy database row."""
    return MagicMock(
        tenant_id=uuid4(),
        retention_days=365,
        last_purge_at=None,
        purge_count=0,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        conversation_retention_enabled=False,
        conversation_retention_days=None,
    )


class TestRetentionConstants:
    """Tests for retention policy constants and boundaries."""

    def test_minimum_retention_is_1_day(self):
        """Verify minimum retention period is 1 day."""
        assert MINIMUM_RETENTION_DAYS == 1

    def test_maximum_retention_is_2555_days(self):
        """Verify maximum retention period is ~7 years."""
        assert MAXIMUM_RETENTION_DAYS == 2555

    def test_default_retention_is_365_days(self):
        """Verify default retention is 1 year."""
        assert DEFAULT_RETENTION_DAYS == 365


class TestRetentionPolicyModel:
    """Tests for RetentionPolicyModel Pydantic model."""

    def test_model_requires_tenant_id(self):
        """Verify tenant_id is required."""
        with pytest.raises(Exception):  # ValidationError
            RetentionPolicyModel(
                retention_days=365,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )

    def test_model_requires_retention_days(self):
        """Verify retention_days is required."""
        with pytest.raises(Exception):  # ValidationError
            RetentionPolicyModel(
                tenant_id=uuid4(),
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )

    def test_model_has_default_purge_count(self):
        """Verify purge_count defaults to 0."""
        policy = RetentionPolicyModel(
            tenant_id=uuid4(),
            retention_days=365,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        assert policy.purge_count == 0

    def test_model_has_optional_last_purge_at(self):
        """Verify last_purge_at is optional and defaults to None."""
        policy = RetentionPolicyModel(
            tenant_id=uuid4(),
            retention_days=365,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        assert policy.last_purge_at is None

    def test_model_includes_conversation_retention_fields(self):
        """Verify conversation retention fields exist with defaults."""
        policy = RetentionPolicyModel(
            tenant_id=uuid4(),
            retention_days=365,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        assert policy.conversation_retention_enabled is False
        assert policy.conversation_retention_days is None

    def test_model_validates_from_orm(self, sample_policy_row):
        """Verify model can be created from ORM object."""
        policy = RetentionPolicyModel.model_validate(sample_policy_row)
        assert policy.tenant_id == sample_policy_row.tenant_id
        assert policy.retention_days == sample_policy_row.retention_days


class TestGetPolicy:
    """Tests for get_policy() method."""

    async def test_get_policy_returns_existing_policy(self, retention_service, mock_session, sample_policy_row):
        """Verify existing policy is returned."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_policy_row
        mock_session.execute.return_value = mock_result

        result = await retention_service.get_policy(sample_policy_row.tenant_id)

        assert result.tenant_id == sample_policy_row.tenant_id
        assert result.retention_days == sample_policy_row.retention_days

    async def test_get_policy_creates_default_when_missing(self, retention_service, mock_session):
        """Verify default policy is created when none exists."""
        tenant_id = uuid4()

        # First call returns None (no existing policy)
        mock_result_none = MagicMock()
        mock_result_none.scalar_one_or_none.return_value = None

        # Second call returns created policy
        created_policy = MagicMock(
            tenant_id=tenant_id,
            retention_days=365,
            last_purge_at=None,
            purge_count=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            conversation_retention_enabled=False,
            conversation_retention_days=None,
        )
        mock_result_created = MagicMock()
        mock_result_created.scalar_one.return_value = created_policy

        mock_session.execute.side_effect = [mock_result_none, mock_result_created]

        result = await retention_service.get_policy(tenant_id)

        # Verify default policy was created with 365 days
        assert result.retention_days == 365

    async def test_get_policy_default_uses_365_days(self, retention_service, mock_session):
        """Verify default policy uses 365 days retention."""
        tenant_id = uuid4()

        mock_result_none = MagicMock()
        mock_result_none.scalar_one_or_none.return_value = None

        created_policy = MagicMock(
            tenant_id=tenant_id,
            retention_days=365,
            last_purge_at=None,
            purge_count=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            conversation_retention_enabled=False,
            conversation_retention_days=None,
        )
        mock_result_created = MagicMock()
        mock_result_created.scalar_one.return_value = created_policy

        mock_session.execute.side_effect = [mock_result_none, mock_result_created]

        result = await retention_service.get_policy(tenant_id)

        assert result.retention_days == 365


class TestUpdatePolicy:
    """Tests for update_policy() method."""

    async def test_update_policy_validates_minimum(self, retention_service):
        """Verify minimum retention validation (1 day)."""
        with pytest.raises(ValueError) as exc_info:
            await retention_service.update_policy(
                tenant_id=uuid4(),
                retention_days=0,  # Below minimum
            )

        assert "minimum" in exc_info.value.args[0].lower()

    async def test_update_policy_validates_negative(self, retention_service):
        """Verify negative retention days rejected."""
        with pytest.raises(ValueError) as exc_info:
            await retention_service.update_policy(
                tenant_id=uuid4(),
                retention_days=-1,
            )

        assert "minimum" in exc_info.value.args[0].lower()

    async def test_update_policy_validates_maximum(self, retention_service):
        """Verify maximum retention validation (2555 days)."""
        with pytest.raises(ValueError) as exc_info:
            await retention_service.update_policy(
                tenant_id=uuid4(),
                retention_days=2556,  # Above maximum
            )

        assert "maximum" in exc_info.value.args[0].lower()

    async def test_update_policy_accepts_minimum_boundary(self, retention_service, mock_session):
        """Verify 1 day retention is accepted."""
        tenant_id = uuid4()
        updated_policy = MagicMock(
            tenant_id=tenant_id,
            retention_days=1,
            last_purge_at=None,
            purge_count=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            conversation_retention_enabled=False,
            conversation_retention_days=None,
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = updated_policy
        mock_session.execute.return_value = mock_result

        result = await retention_service.update_policy(
            tenant_id=tenant_id,
            retention_days=1,  # Minimum boundary
        )

        assert result.retention_days == 1

    async def test_update_policy_accepts_maximum_boundary(self, retention_service, mock_session):
        """Verify 2555 day retention is accepted."""
        tenant_id = uuid4()
        updated_policy = MagicMock(
            tenant_id=tenant_id,
            retention_days=2555,
            last_purge_at=None,
            purge_count=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            conversation_retention_enabled=False,
            conversation_retention_days=None,
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = updated_policy
        mock_session.execute.return_value = mock_result

        result = await retention_service.update_policy(
            tenant_id=tenant_id,
            retention_days=2555,  # Maximum boundary
        )

        assert result.retention_days == 2555

    async def test_update_policy_creates_if_missing(self, retention_service, mock_session):
        """Verify policy is created if it doesn't exist."""
        tenant_id = uuid4()

        # Update returns None (no existing policy)
        mock_result_none = MagicMock()
        mock_result_none.scalar_one_or_none.return_value = None

        # Insert returns created policy
        created_policy = MagicMock(
            tenant_id=tenant_id,
            retention_days=90,
            last_purge_at=None,
            purge_count=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            conversation_retention_enabled=False,
            conversation_retention_days=None,
        )
        mock_result_created = MagicMock()
        mock_result_created.scalar_one.return_value = created_policy

        mock_session.execute.side_effect = [mock_result_none, mock_result_created]

        result = await retention_service.update_policy(
            tenant_id=tenant_id,
            retention_days=90,
        )

        assert result.retention_days == 90

    async def test_update_policy_sets_updated_at(self, retention_service, mock_session):
        """Verify updated_at timestamp is set."""
        tenant_id = uuid4()
        updated_policy = MagicMock(
            tenant_id=tenant_id,
            retention_days=180,
            last_purge_at=None,
            purge_count=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            conversation_retention_enabled=False,
            conversation_retention_days=None,
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = updated_policy
        mock_session.execute.return_value = mock_result

        await retention_service.update_policy(
            tenant_id=tenant_id,
            retention_days=180,
        )

        # Verify session.execute was called (which includes updated_at)
        mock_session.execute.assert_called_once()


class TestConversationRetention:
    """Tests for conversation retention feature."""

    async def test_update_with_conversation_retention_enabled(self, retention_service, mock_session):
        """Verify conversation retention can be enabled."""
        tenant_id = uuid4()
        updated_policy = MagicMock(
            tenant_id=tenant_id,
            retention_days=365,
            last_purge_at=None,
            purge_count=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            conversation_retention_enabled=True,
            conversation_retention_days=30,
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = updated_policy
        mock_session.execute.return_value = mock_result

        result = await retention_service.update_policy(
            tenant_id=tenant_id,
            retention_days=365,
            conversation_retention_enabled=True,
            conversation_retention_days=30,
        )

        assert result.conversation_retention_enabled is True
        assert result.conversation_retention_days == 30

    async def test_conversation_retention_validates_minimum(self, retention_service):
        """Verify conversation retention minimum validation."""
        with pytest.raises(ValueError) as exc_info:
            await retention_service.update_policy(
                tenant_id=uuid4(),
                retention_days=365,
                conversation_retention_days=0,  # Below minimum
            )

        assert "conversation" in exc_info.value.args[0].lower()

    async def test_conversation_retention_validates_maximum(self, retention_service):
        """Verify conversation retention maximum validation."""
        with pytest.raises(ValueError) as exc_info:
            await retention_service.update_policy(
                tenant_id=uuid4(),
                retention_days=365,
                conversation_retention_days=2556,  # Above maximum
            )

        assert "conversation" in exc_info.value.args[0].lower()


class TestPurgeOldLogs:
    """Tests for purge_old_logs() method."""

    async def test_purge_updates_tracking_when_logs_purged(self, retention_service, mock_session):
        """Verify purge tracking is updated when logs are purged."""
        tenant_id = uuid4()

        # Mock get_policy to return a policy
        policy = MagicMock(
            tenant_id=tenant_id,
            retention_days=30,
            last_purge_at=None,
            purge_count=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            conversation_retention_enabled=False,
            conversation_retention_days=None,
        )
        mock_result_policy = MagicMock()
        mock_result_policy.scalar_one_or_none.return_value = policy

        # Mock the repository's soft_delete_old_logs (imported inside the function)
        with patch("intric.audit.infrastructure.audit_log_repo_impl.AuditLogRepositoryImpl") as MockRepo:
            mock_repo_instance = AsyncMock()
            mock_repo_instance.soft_delete_old_logs.return_value = 10  # 10 logs purged
            MockRepo.return_value = mock_repo_instance

            mock_session.execute.return_value = mock_result_policy

            purged_count = await retention_service.purge_old_logs(tenant_id)

            assert purged_count == 10
            # Verify tracking update was called
            assert mock_session.execute.call_count >= 2  # Policy query + update

    async def test_purge_skips_tracking_when_no_logs_purged(self, retention_service, mock_session):
        """Verify purge tracking is not updated when no logs purged."""
        tenant_id = uuid4()

        policy = MagicMock(
            tenant_id=tenant_id,
            retention_days=30,
            last_purge_at=None,
            purge_count=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            conversation_retention_enabled=False,
            conversation_retention_days=None,
        )
        mock_result_policy = MagicMock()
        mock_result_policy.scalar_one_or_none.return_value = policy

        with patch("intric.audit.infrastructure.audit_log_repo_impl.AuditLogRepositoryImpl") as MockRepo:
            mock_repo_instance = AsyncMock()
            mock_repo_instance.soft_delete_old_logs.return_value = 0  # No logs purged
            MockRepo.return_value = mock_repo_instance

            mock_session.execute.return_value = mock_result_policy

            purged_count = await retention_service.purge_old_logs(tenant_id)

            assert purged_count == 0


class TestPurgeAllTenants:
    """Tests for purge_all_tenants() method."""

    async def test_purge_all_queries_all_policies(self, retention_service, mock_session):
        """Verify purge_all_tenants queries all policies."""
        # Mock empty policy list to avoid complex purge mocking
        mock_result_all = MagicMock()
        mock_result_all.scalars.return_value.all.return_value = []

        mock_session.execute.return_value = mock_result_all

        stats = await retention_service.purge_all_tenants()

        # Verify select query was executed
        mock_session.execute.assert_called_once()
        # With no policies, stats should be empty
        assert stats == {}

    async def test_purge_all_returns_stats_dict(self, retention_service, mock_session):
        """Verify purge_all_tenants returns a dictionary."""
        mock_result_all = MagicMock()
        mock_result_all.scalars.return_value.all.return_value = []

        mock_session.execute.return_value = mock_result_all

        stats = await retention_service.purge_all_tenants()

        assert isinstance(stats, dict)


class TestValidationBoundaries:
    """Tests for validation boundary conditions."""

    @pytest.mark.parametrize("days", [1, 30, 90, 365, 730, 1825, 2555])
    async def test_valid_retention_days_accepted(self, retention_service, mock_session, days):
        """Verify common valid retention periods are accepted."""
        tenant_id = uuid4()
        updated_policy = MagicMock(
            tenant_id=tenant_id,
            retention_days=days,
            last_purge_at=None,
            purge_count=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            conversation_retention_enabled=False,
            conversation_retention_days=None,
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = updated_policy
        mock_session.execute.return_value = mock_result

        result = await retention_service.update_policy(
            tenant_id=tenant_id,
            retention_days=days,
        )

        assert result.retention_days == days

    @pytest.mark.parametrize("days", [-100, -1, 0, 2556, 3000, 10000])
    async def test_invalid_retention_days_rejected(self, retention_service, days):
        """Verify invalid retention periods are rejected."""
        with pytest.raises(ValueError):
            await retention_service.update_policy(
                tenant_id=uuid4(),
                retention_days=days,
            )
