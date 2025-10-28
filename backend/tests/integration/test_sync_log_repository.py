"""Integration tests for SyncLogRepository with database operations."""

import pytest
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID, uuid4

from intric.database.tables.ai_models_table import EmbeddingModels
from intric.database.tables.integration_table import (
    Integration as IntegrationDB,
    IntegrationKnowledge as IntegrationKnowledgeDB,
    TenantIntegration as TenantIntegrationDB,
    UserIntegration as UserIntegrationDB,
)
from intric.database.tables.spaces_table import Spaces
from intric.integration.domain.entities.sync_log import SyncLog
from sqlalchemy import text


async def create_integration_knowledge_record(
    container,
    integration_knowledge_id: Optional[UUID] = None,
) -> UUID:
    """Create minimal integration knowledge hierarchy required for sync log tests."""
    session = container.session()
    user = container.user()
    tenant = container.tenant()

    integration = IntegrationDB(
        name=f"sync-log-test-integration-{uuid4()}",
        description="Sync log test integration",
        integration_type="sharepoint",
    )
    session.add(integration)
    await session.flush()

    tenant_integration = TenantIntegrationDB(
        tenant_id=tenant.id,
        integration_id=integration.id,
    )
    session.add(tenant_integration)
    await session.flush()

    user_integration = UserIntegrationDB(
        user_id=user.id,
        tenant_id=tenant.id,
        tenant_integration_id=tenant_integration.id,
        authenticated=True,
    )
    session.add(user_integration)
    await session.flush()

    space = Spaces(
        name=f"sync-log-test-space-{uuid4()}",
        tenant_id=tenant.id,
    )
    session.add(space)
    await session.flush()

    embedding_model = EmbeddingModels(
        name=f"sync-log-embedding-{uuid4()}",
        open_source=False,
        family="openai",
        stability="stable",
        hosting="usa",
        dimensions=1536,
        max_input=8192,
    )
    session.add(embedding_model)
    await session.flush()

    knowledge_kwargs = {
        "name": "Sync Log Test Knowledge",
        "space_id": space.id,
        "embedding_model_id": embedding_model.id,
        "tenant_id": tenant.id,
        "user_integration_id": user_integration.id,
        "url": "https://example.com/test",
    }
    if integration_knowledge_id is not None:
        knowledge_kwargs["id"] = integration_knowledge_id

    integration_knowledge = IntegrationKnowledgeDB(**knowledge_kwargs)
    session.add(integration_knowledge)
    await session.flush()

    return integration_knowledge.id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sync_log_repo_add_and_retrieve(db_container):
    """Test adding and retrieving a sync log."""
    async with db_container() as container:
        # Arrange
        repo = container.sync_log_repo()
        integration_knowledge_id = await create_integration_knowledge_record(container)
        now = datetime.now(timezone.utc)

        sync_log = SyncLog(
            integration_knowledge_id=integration_knowledge_id,
            sync_type="full",
            status="success",
            metadata={
                "files_processed": 10,
                "files_deleted": 2,
                "pages_processed": 5,
            },
            started_at=now,
            completed_at=now + timedelta(seconds=120),
            created_at=now,
        )

        # Act
        created_log = await repo.add(sync_log)

        # Assert
        assert created_log.id is not None
        assert created_log.integration_knowledge_id == integration_knowledge_id
        assert created_log.status == "success"

        # Retrieve and verify
        retrieved = await repo.get_by_id(created_log.id)
        assert retrieved is not None
        assert retrieved.files_processed == 10
        assert retrieved.files_deleted == 2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sync_log_repo_get_by_integration_knowledge(db_container):
    """Test retrieving sync logs for an integration."""
    async with db_container() as container:
        # Arrange
        repo = container.sync_log_repo()
        session = container.session()
        integration_knowledge_id = await create_integration_knowledge_record(container)
        now = datetime.now(timezone.utc)

        # Create multiple sync logs
        inserted_logs = []
        for i in range(15):
            log = SyncLog(
                integration_knowledge_id=integration_knowledge_id,
                sync_type="delta" if i % 2 == 0 else "full",
                status="success",
                metadata={"files_processed": i},
                started_at=now - timedelta(hours=i),
                completed_at=now - timedelta(hours=i) + timedelta(seconds=60),
                created_at=now - timedelta(hours=i),
            )
            created = await repo.add(log)
            inserted_logs.append(created)
            await session.execute(
                text(
                    "UPDATE sync_logs SET created_at = :created_at WHERE id = :id"
                ),
                {
                    "created_at": now - timedelta(hours=i),
                    "id": created.id,
                },
            )
            await session.flush()

        # Act
        logs = await repo.get_by_integration_knowledge(
            integration_knowledge_id=integration_knowledge_id, limit=10, offset=0
        )

        # Assert
        assert len(logs) == 10
        # Should be ordered by created_at DESC (most recent first)
        created_at_values = [log.created_at for log in logs]
        assert created_at_values == sorted(created_at_values, reverse=True)
        expected_files = [log.files_processed for log in inserted_logs][:10]
        assert [log.files_processed for log in logs] == expected_files


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sync_log_repo_pagination_with_offset(db_container):
    """Test pagination with offset."""
    async with db_container() as container:
        # Arrange
        repo = container.sync_log_repo()
        integration_knowledge_id = await create_integration_knowledge_record(container)
        now = datetime.now(timezone.utc)

        # Create 25 sync logs
        created_ids = []
        for i in range(25):
            log = SyncLog(
                integration_knowledge_id=integration_knowledge_id,
                sync_type="full",
                status="success",
                metadata={"files_processed": i},
                started_at=now - timedelta(hours=i),
                completed_at=now - timedelta(hours=i) + timedelta(seconds=30),
                created_at=now - timedelta(hours=i),
            )
            created = await repo.add(log)
            created_ids.append(created.id)

        # Act - Get page 1 (offset 0, limit 10)
        page1 = await repo.get_by_integration_knowledge(
            integration_knowledge_id=integration_knowledge_id, limit=10, offset=0
        )

        # Get page 2 (offset 10, limit 10)
        page2 = await repo.get_by_integration_knowledge(
            integration_knowledge_id=integration_knowledge_id, limit=10, offset=10
        )

        # Get page 3 (offset 20, limit 10)
        page3 = await repo.get_by_integration_knowledge(
            integration_knowledge_id=integration_knowledge_id, limit=10, offset=20
        )

        # Assert
        assert len(page1) == 10
        assert len(page2) == 10
        assert len(page3) == 5

        # Verify no overlap between pages
        page1_ids = {log.id for log in page1}
        page2_ids = {log.id for log in page2}
        page3_ids = {log.id for log in page3}

        assert len(page1_ids & page2_ids) == 0  # No overlap
        assert len(page2_ids & page3_ids) == 0  # No overlap
        assert len(page1_ids & page3_ids) == 0  # No overlap


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sync_log_repo_count_by_integration_knowledge(db_container):
    """Test counting sync logs for an integration."""
    async with db_container() as container:
        # Arrange
        repo = container.sync_log_repo()
        integration_knowledge_id = await create_integration_knowledge_record(container)
        now = datetime.now(timezone.utc)

        # Create 7 sync logs
        for i in range(7):
            log = SyncLog(
                integration_knowledge_id=integration_knowledge_id,
                sync_type="full",
                status="success",
                started_at=now - timedelta(hours=i),
                completed_at=now - timedelta(hours=i) + timedelta(seconds=30),
                created_at=now - timedelta(hours=i),
            )
            await repo.add(log)

        # Act
        count = await repo.count_by_integration_knowledge(
            integration_knowledge_id=integration_knowledge_id
        )

        # Assert
        assert count == 7


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sync_log_repo_count_other_integration_not_included(db_container):
    """Test that count doesn't include logs from other integrations."""
    async with db_container() as container:
        # Arrange
        repo = container.sync_log_repo()
        knowledge_1_id = await create_integration_knowledge_record(container)
        knowledge_2_id = await create_integration_knowledge_record(container)
        now = datetime.now(timezone.utc)

        # Create logs for integration 1
        for i in range(5):
            log = SyncLog(
                integration_knowledge_id=knowledge_1_id,
                sync_type="full",
                status="success",
                started_at=now - timedelta(hours=i),
                created_at=now - timedelta(hours=i),
            )
            await repo.add(log)

        # Create logs for integration 2
        for i in range(3):
            log = SyncLog(
                integration_knowledge_id=knowledge_2_id,
                sync_type="full",
                status="success",
                started_at=now - timedelta(hours=i),
                created_at=now - timedelta(hours=i),
            )
            await repo.add(log)

        # Act
        count_1 = await repo.count_by_integration_knowledge(
            integration_knowledge_id=knowledge_1_id
        )
        count_2 = await repo.count_by_integration_knowledge(
            integration_knowledge_id=knowledge_2_id
        )

        # Assert
        assert count_1 == 5
        assert count_2 == 3


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sync_log_repo_ordered_by_created_at_desc(db_container):
    """Test that logs are ordered by created_at descending (most recent first)."""
    async with db_container() as container:
        # Arrange
        repo = container.sync_log_repo()
        session = container.session()
        integration_knowledge_id = await create_integration_knowledge_record(container)
        now = datetime.now(timezone.utc)

        # Create logs with specific timestamps
        timestamps = [
            now - timedelta(hours=3),
            now - timedelta(hours=1),
            now - timedelta(hours=2),
        ]

        created_entries = []
        for ts in timestamps:
            log = SyncLog(
                integration_knowledge_id=integration_knowledge_id,
                sync_type="full",
                status="success",
                started_at=ts,
                created_at=ts,
            )
            created = await repo.add(log)
            created_entries.append((ts, created.id))
            await session.execute(
                text(
                    "UPDATE sync_logs SET created_at = :created_at WHERE id = :id"
                ),
                {
                    "created_at": ts,
                    "id": created.id,
                },
            )
            await session.flush()

        # Act
        logs = await repo.get_by_integration_knowledge(
            integration_knowledge_id=integration_knowledge_id,
            limit=10,
            offset=0,
        )

        # Assert - Should be in descending order
        assert len(logs) == 3
        created_at_values = [log.created_at for log in logs]
        assert created_at_values == sorted(created_at_values, reverse=True)
        expected_order = [
            log_id for ts, log_id in sorted(created_entries, key=lambda item: item[0], reverse=True)
        ]
        assert [log.id for log in logs] == expected_order


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sync_log_repo_get_recent_by_integration_knowledge(db_container):
    """Test getting recent sync logs (default limit)."""
    async with db_container() as container:
        # Arrange
        repo = container.sync_log_repo()
        integration_knowledge_id = await create_integration_knowledge_record(container)
        now = datetime.now(timezone.utc)

        # Create 15 logs
        for i in range(15):
            log = SyncLog(
                integration_knowledge_id=integration_knowledge_id,
                sync_type="full",
                status="success",
                started_at=now - timedelta(hours=i),
                created_at=now - timedelta(hours=i),
            )
            await repo.add(log)

        # Act
        recent = await repo.get_recent_by_integration_knowledge(
            integration_knowledge_id=integration_knowledge_id
        )

        # Assert - Should return 10 most recent (default limit)
        assert len(recent) == 10


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sync_log_repo_update_status(db_container):
    """Test updating sync log status."""
    async with db_container() as container:
        # Arrange
        repo = container.sync_log_repo()
        integration_knowledge_id = await create_integration_knowledge_record(container)
        now = datetime.now(timezone.utc)

        log = SyncLog(
            integration_knowledge_id=integration_knowledge_id,
            sync_type="full",
            status="in_progress",
            started_at=now,
            created_at=now,
        )
        created = await repo.add(log)

        # Act
        created.status = "success"
        created.completed_at = now + timedelta(seconds=60)
        created.metadata = {"files_processed": 20}
        updated = await repo.update(created)

        # Assert
        retrieved = await repo.get_by_id(updated.id)
        assert retrieved.status == "success"
        assert retrieved.metadata["files_processed"] == 20


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sync_log_repo_with_error_status(db_container):
    """Test sync log with error status and message."""
    async with db_container() as container:
        # Arrange
        repo = container.sync_log_repo()
        integration_knowledge_id = await create_integration_knowledge_record(container)
        now = datetime.now(timezone.utc)

        log = SyncLog(
            integration_knowledge_id=integration_knowledge_id,
            sync_type="delta",
            status="error",
            error_message="SharePoint API returned 401 Unauthorized",
            started_at=now,
            completed_at=now + timedelta(seconds=30),
            created_at=now,
        )

        # Act
        created = await repo.add(log)

        # Assert
        retrieved = await repo.get_by_id(created.id)
        assert retrieved.status == "error"
        assert retrieved.error_message == "SharePoint API returned 401 Unauthorized"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sync_log_repo_limit_enforced(db_container):
    """Test that limit parameter is respected."""
    async with db_container() as container:
        # Arrange
        repo = container.sync_log_repo()
        integration_knowledge_id = await create_integration_knowledge_record(container)
        now = datetime.now(timezone.utc)

        # Create 20 logs
        for i in range(20):
            log = SyncLog(
                integration_knowledge_id=integration_knowledge_id,
                sync_type="full",
                status="success",
                started_at=now - timedelta(hours=i),
                created_at=now - timedelta(hours=i),
            )
            await repo.add(log)

        # Act with different limits
        logs_5 = await repo.get_by_integration_knowledge(
            integration_knowledge_id=integration_knowledge_id,
            limit=5,
            offset=0,
        )
        logs_15 = await repo.get_by_integration_knowledge(
            integration_knowledge_id=integration_knowledge_id,
            limit=15,
            offset=0,
        )

        # Assert
        assert len(logs_5) == 5
        assert len(logs_15) == 15


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sync_log_repo_empty_result(db_container):
    """Test getting logs when none exist."""
    async with db_container() as container:
        # Arrange
        repo = container.sync_log_repo()
        integration_knowledge_id = await create_integration_knowledge_record(container)

        # Act
        logs = await repo.get_by_integration_knowledge(
            integration_knowledge_id=integration_knowledge_id,
            limit=10,
            offset=0,
        )

        # Assert
        assert logs == []

        # Also test count
        count = await repo.count_by_integration_knowledge(
            integration_knowledge_id=integration_knowledge_id
        )
        assert count == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
