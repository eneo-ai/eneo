"""Integration tests for multi-tenant isolation in audit logging."""

import pytest
from uuid import uuid4

from intric.audit.application.audit_service import AuditService
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_tenant_isolation_basic(db_session, test_tenant, test_user):
    """Test that audit logs are properly filtered by tenant."""
    async with db_session() as session:
        repository = AuditLogRepositoryImpl(session)
        service = AuditService(repository)

        # Create logs for the test tenant (test_user is user_id UUID)
        log1 = await service.log(
            tenant_id=test_tenant.id,
            actor_id=test_user,
            action=ActionType.USER_CREATED,
            entity_type=EntityType.USER,
            entity_id=uuid4(),
            description="Created a user",
            metadata={"test": "A"},
        )

        log2 = await service.log(
            tenant_id=test_tenant.id,
            actor_id=test_user,
            action=ActionType.USER_UPDATED,
            entity_type=EntityType.USER,
            entity_id=uuid4(),
            description="Updated a user",
            metadata={"test": "B"},
        )

        # Query all logs for tenant
        tenant_logs, count = await service.get_logs(tenant_id=test_tenant.id)

        # Verify we get both logs
        assert count >= 2
        assert all(log.tenant_id == test_tenant.id for log in tenant_logs)

        # Verify our logs are in the results
        log_ids = [log.id for log in tenant_logs]
        assert log1.id in log_ids
        assert log2.id in log_ids


@pytest.mark.asyncio
async def test_tenant_isolation_with_filters(db_session, test_tenant, test_user):
    """Test tenant isolation with action filters."""
    async with db_session() as session:
        repository = AuditLogRepositoryImpl(session)
        service = AuditService(repository)

        # Create multiple logs with different actions
        created_logs = []
        for i in range(3):
            log = await service.log(
                tenant_id=test_tenant.id,
                actor_id=test_user,
                action=ActionType.ASSISTANT_CREATED,
                entity_type=EntityType.ASSISTANT,
                entity_id=uuid4(),
                description=f"Created assistant {i}",
                metadata={},
            )
            created_logs.append(log)

        # Query with action filter
        tenant_logs, count = await service.get_logs(
            tenant_id=test_tenant.id,
            action=ActionType.ASSISTANT_CREATED,
        )

        # Verify we get our logs
        assert count >= 3
        log_ids = [log.id for log in tenant_logs]
        for created_log in created_logs:
            assert created_log.id in log_ids

        # Verify all returned logs have the correct action
        assert all(log.action == ActionType.ASSISTANT_CREATED for log in tenant_logs)


@pytest.mark.asyncio
async def test_actor_filtering(db_session, test_tenant, test_user):
    """Test filtering logs by actor_id."""
    async with db_session() as session:
        repository = AuditLogRepositoryImpl(session)
        service = AuditService(repository)

        # Create log with test_user as actor
        log = await service.log(
            tenant_id=test_tenant.id,
            actor_id=test_user,
            action=ActionType.SPACE_CREATED,
            entity_type=EntityType.SPACE,
            entity_id=uuid4(),
            description="User created space",
            metadata={},
        )

        # Query logs filtered by actor
        actor_logs, count = await service.get_logs(
            tenant_id=test_tenant.id,
            actor_id=test_user,
        )

        # Verify we get the log
        assert count >= 1
        log_ids = [l.id for l in actor_logs]
        assert log.id in log_ids
        assert all(l.actor_id == test_user for l in actor_logs)
