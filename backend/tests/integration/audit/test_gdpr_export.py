"""Integration tests for GDPR Article 15 export functionality."""

import pytest
from uuid import uuid4

from intric.audit.application.audit_service import AuditService
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_gdpr_export_includes_actor_and_target(db_session, test_tenant, test_user):
    """Test that GDPR export includes logs where user is both actor and target."""
    async with db_session() as session:
        repository = AuditLogRepositoryImpl(session)
        service = AuditService(repository)

        # Log where test_user is actor
        log1 = await service.log(
            tenant_id=test_tenant.id,
            actor_id=test_user,
            action=ActionType.ASSISTANT_CREATED,
            entity_type=EntityType.ASSISTANT,
            entity_id=uuid4(),
            description="User created assistant",
            metadata={
                "actor": {"id": str(test_user), "name": "Test User"},
                "target": {"id": str(uuid4()), "type": "assistant"},
            },
        )

        # Log where test_user is target
        log2 = await service.log(
            tenant_id=test_tenant.id,
            actor_id=test_user,
            action=ActionType.USER_UPDATED,
            entity_type=EntityType.USER,
            entity_id=test_user,
            description="Updated user profile",
            metadata={
                "actor": {"id": str(test_user), "name": "Test User"},
                "target": {"id": str(test_user), "name": "Test User"},
            },
        )

        # Get GDPR export for test_user
        user_logs, count = await service.get_user_logs(
            tenant_id=test_tenant.id,
            user_id=test_user,
        )

        # Should include both logs
        assert count >= 2
        log_ids = [log.id for log in user_logs]
        assert log1.id in log_ids
        assert log2.id in log_ids


@pytest.mark.asyncio
async def test_csv_export_format(db_session, test_tenant, test_user):
    """Test that CSV export produces valid GDPR-compliant CSV."""
    async with db_session() as session:
        repository = AuditLogRepositoryImpl(session)
        service = AuditService(repository)

        # Create test log
        await service.log(
            tenant_id=test_tenant.id,
            actor_id=test_user,
            action=ActionType.FILE_UPLOADED,
            entity_type=EntityType.FILE,
            entity_id=uuid4(),
            description="User uploaded file",
            metadata={
                "actor": {"id": str(test_user), "name": "Test User"},
                "file": {"name": "document.pdf", "size": 12345},
            },
        )

        # Export to CSV
        csv_content = await service.export_csv(
            tenant_id=test_tenant.id,
            user_id=test_user,
        )

        # Verify CSV structure
        assert "Timestamp,Actor ID,Actor Type,Action,Entity Type" in csv_content
        assert str(test_user) in csv_content
        assert "file_uploaded" in csv_content
        assert "User uploaded file" in csv_content

        # Verify it's valid CSV (can be split into rows)
        rows = csv_content.strip().split("\n")
        assert len(rows) >= 2  # Header + at least one data row


@pytest.mark.asyncio
async def test_csv_export_with_metadata(db_session, test_tenant, test_user):
    """Test that CSV export includes metadata correctly."""
    async with db_session() as session:
        repository = AuditLogRepositoryImpl(session)
        service = AuditService(repository)

        # Create log with rich metadata
        metadata = {
            "actor": {"id": str(test_user), "name": "Test User", "role": "admin"},
            "file": {"name": "important.pdf", "size": 54321, "type": "pdf"},
            "changes": {"status": {"old": "draft", "new": "published"}},
        }

        await service.log(
            tenant_id=test_tenant.id,
            actor_id=test_user,
            action=ActionType.FILE_UPLOADED,
            entity_type=EntityType.FILE,
            entity_id=uuid4(),
            description="User uploaded important file",
            metadata=metadata,
        )

        # Export to CSV
        csv_content = await service.export_csv(
            tenant_id=test_tenant.id,
            user_id=test_user,
        )

        # Verify metadata is present in CSV
        assert "important.pdf" in csv_content or "metadata" in csv_content.lower()

        # Verify CSV is valid
        rows = csv_content.strip().split("\n")
        assert len(rows) >= 2
