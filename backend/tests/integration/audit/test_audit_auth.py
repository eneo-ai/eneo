"""Integration tests for audit API authentication."""

import pytest
from uuid import uuid4

from intric.audit.application.audit_service import AuditService
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl


@pytest.mark.asyncio
async def test_audit_logs_requires_authentication(client, test_tenant, test_user, db_session):
    """Test that audit endpoints require authentication."""
    # Create a log first
    async with db_session() as session:
        repository = AuditLogRepositoryImpl(session)
        service = AuditService(repository)

        await service.log(
            tenant_id=test_tenant.id,
            actor_id=test_user,
            action=ActionType.USER_CREATED,
            entity_type=EntityType.USER,
            entity_id=uuid4(),
            description="Test log",
            metadata={},
        )

    # Try to access without authentication - should fail
    response = await client.get("/api/v1/audit/logs")
    assert response.status_code == 401  # Unauthorized


@pytest.mark.asyncio
async def test_audit_logs_rejects_super_admin_key(client, test_tenant, test_user, db_session, super_admin_token):
    """Test that audit endpoints reject super admin API key (no tenant context)."""
    # Create a log
    async with db_session() as session:
        repository = AuditLogRepositoryImpl(session)
        service = AuditService(repository)

        await service.log(
            tenant_id=test_tenant.id,
            actor_id=test_user,
            action=ActionType.ASSISTANT_CREATED,
            entity_type=EntityType.ASSISTANT,
            entity_id=uuid4(),
            description="Test API key log",
            metadata={},
        )

    # Query with super admin API key (should fail - no tenant context)
    response = await client.get(
        "/api/v1/audit/logs",
        headers={"X-API-Key": super_admin_token}
    )

    # Super admin key has no tenant, so audit endpoints correctly reject it
    assert response.status_code == 401  # Unauthorized (no tenant context)
