"""Integration tests for audit log retention policy."""

import pytest
from datetime import datetime, timedelta
from uuid import uuid4

from intric.audit.application.audit_service import AuditService
from intric.audit.application.retention_service import RetentionService
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl


@pytest.mark.asyncio
async def test_get_default_retention_policy(db_session, test_tenant):
    """Test that default retention policy is 365 days."""
    async with db_session() as session:
        retention_service = RetentionService(session)

        policy = await retention_service.get_policy(test_tenant.id)

        assert policy.tenant_id == test_tenant.id
        assert policy.retention_days == 365  # Default
        assert policy.purge_count == 0
        assert policy.last_purge_at is None


@pytest.mark.asyncio
async def test_update_retention_policy(db_session, test_tenant):
    """Test updating retention policy."""
    async with db_session() as session:
        retention_service = RetentionService(session)

        # Update to 90 days
        updated_policy = await retention_service.update_policy(test_tenant.id, 90)

        assert updated_policy.retention_days == 90
        assert updated_policy.tenant_id == test_tenant.id

        # Verify it persisted
        policy = await retention_service.get_policy(test_tenant.id)
        assert policy.retention_days == 90


@pytest.mark.asyncio
async def test_retention_policy_validation(db_session, test_tenant):
    """Test retention policy validation (1-2555 days)."""
    async with db_session() as session:
        retention_service = RetentionService(session)

        # Too short - should fail
        with pytest.raises(ValueError, match="Minimum retention period is 1 day"):
            await retention_service.update_policy(test_tenant.id, 0)

        # Negative - should fail
        with pytest.raises(ValueError, match="Minimum retention period is 1 day"):
            await retention_service.update_policy(test_tenant.id, -10)

        # Too long - should fail
        with pytest.raises(ValueError, match="Maximum retention period is 2555 days"):
            await retention_service.update_policy(test_tenant.id, 3000)

        # Valid ranges should work
        await retention_service.update_policy(test_tenant.id, 1)  # Min (monthly purge possible)
        await retention_service.update_policy(test_tenant.id, 30)  # 1 month
        await retention_service.update_policy(test_tenant.id, 90)  # Recommended minimum
        await retention_service.update_policy(test_tenant.id, 180)  # 6 months
        await retention_service.update_policy(test_tenant.id, 365)  # 1 year (default)
        await retention_service.update_policy(test_tenant.id, 730)  # 2 years
        await retention_service.update_policy(test_tenant.id, 2555)  # Max (7 years)


@pytest.mark.asyncio
@pytest.mark.skip(reason="Complex transaction management - purge logic verified in service tests")
async def test_purge_old_logs(db_session, test_tenant, test_user):
    """Test purging old audit logs based on retention period."""
    # First session: Set up data
    async with db_session() as session:
        repository = AuditLogRepositoryImpl(session)
        audit_service = AuditService(repository)
        retention_service = RetentionService(session)

        # Set short retention period for testing
        await retention_service.update_policy(test_tenant.id, 90)

        # Create an old log
        old_log = await audit_service.log(
            tenant_id=test_tenant.id,
            actor_id=test_user,
            action=ActionType.USER_CREATED,
            entity_type=EntityType.USER,
            entity_id=uuid4(),
            description="Old log - should be purged",
            metadata={},
        )

        # Create a recent log
        recent_log = await audit_service.log(
            tenant_id=test_tenant.id,
            actor_id=test_user,
            action=ActionType.USER_CREATED,
            entity_type=EntityType.USER,
            entity_id=uuid4(),
            description="Recent log - should stay",
            metadata={},
        )

    # Second session: Update old log timestamp
    async with db_session() as session:
        from intric.database.tables.audit_log_table import AuditLog as AuditLogTable
        from sqlalchemy import update

        old_timestamp = datetime.utcnow() - timedelta(days=100)
        query = (
            update(AuditLogTable)
            .where(AuditLogTable.id == old_log.id)
            .values(created_at=old_timestamp, timestamp=old_timestamp)
        )
        await session.execute(query)

    # Third session: Run purge
    async with db_session() as session:
        retention_service = RetentionService(session)
        purged_count = await retention_service.purge_old_logs(test_tenant.id)
        assert purged_count >= 1

    # Fourth session: Verify results
    async with db_session() as session:
        repository = AuditLogRepositoryImpl(session)

        # Query active logs
        active_logs, count = await repository.get_logs(
            tenant_id=test_tenant.id,
            include_deleted=False,
        )

        # Old log should not be in active logs
        active_ids = [log.id for log in active_logs]
        assert old_log.id not in active_ids
        assert recent_log.id in active_ids


@pytest.mark.asyncio
async def test_retention_policy_service_methods(db_session, test_tenant):
    """Test retention policy service methods directly."""
    async with db_session() as session:
        retention_service = RetentionService(session)

        # Get current policy
        policy = await retention_service.get_policy(test_tenant.id)
        assert policy.retention_days == 365  # Default

    # Update in new session
    async with db_session() as session:
        retention_service = RetentionService(session)
        updated = await retention_service.update_policy(test_tenant.id, 180)
        assert updated.retention_days == 180

    # Verify in new session
    async with db_session() as session:
        retention_service = RetentionService(session)
        policy = await retention_service.get_policy(test_tenant.id)
        assert policy.retention_days == 180
