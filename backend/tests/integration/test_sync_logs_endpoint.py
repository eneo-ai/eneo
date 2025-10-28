"""Integration tests for sync logs API endpoint."""

import pytest
from datetime import datetime, timedelta
from uuid import uuid4

from intric.integration.domain.entities.sync_log import SyncLog
from intric.integration.domain.entities.integration_knowledge import (
    IntegrationKnowledge,
)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_sync_logs_endpoint_success(client, admin_user_api_key, db_container):
    """Test GET /sync-logs/{id}/ endpoint returns paginated logs."""
    async with db_container() as container:
        # Arrange
        user_repo = container.user_repo()
        integration_knowledge_repo = container.integration_knowledge_repo()
        sync_log_repo = container.sync_log_repo()

        # Get admin user
        admin_user = await user_repo.one(id=admin_user_api_key.user_id)

        # Create integration knowledge
        knowledge = IntegrationKnowledge(
            name="Test SharePoint",
            space_id=uuid4(),
            user_integration_id=uuid4(),
            embedding_model=None,
            tenant_id=admin_user.tenant_id,
            url="https://sharepoint.example.com",
        )
        created_knowledge = await integration_knowledge_repo.add(knowledge)

        # Create 15 sync logs
        now = datetime.utcnow()
        for i in range(15):
            log = SyncLog(
                integration_knowledge_id=created_knowledge.id,
                sync_type="full" if i % 2 == 0 else "delta",
                status="success",
                metadata={
                    "files_processed": 10 + i,
                    "files_deleted": i,
                    "pages_processed": 5,
                },
                started_at=now - timedelta(hours=i),
                completed_at=now - timedelta(hours=i) + timedelta(seconds=120),
                created_at=now - timedelta(hours=i),
            )
            await sync_log_repo.add(log)

        # Act
        response = await client.get(
            f"/api/v1/integrations/sync-logs/{created_knowledge.id}/",
            headers={"X-API-Key": admin_user_api_key.key},
        )

        # Assert
        assert response.status_code == 200
        data = response.json()

        assert "items" in data
        assert "total_count" in data
        assert "page_size" in data
        assert "offset" in data
        assert "current_page" in data
        assert "total_pages" in data
        assert "has_next" in data
        assert "has_previous" in data

        assert data["total_count"] == 15
        assert data["page_size"] == 10
        assert data["offset"] == 0
        assert data["current_page"] == 1
        assert data["total_pages"] == 2
        assert data["has_next"] is True
        assert data["has_previous"] is False
        assert len(data["items"]) == 10


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_sync_logs_pagination_second_page(
    client, admin_user_api_key, db_container
):
    """Test pagination with offset to get second page."""
    async with db_container() as container:
        # Arrange
        user_repo = container.user_repo()
        integration_knowledge_repo = container.integration_knowledge_repo()
        sync_log_repo = container.sync_log_repo()

        admin_user = await user_repo.one(id=admin_user_api_key.user_id)

        knowledge = IntegrationKnowledge(
            name="Test SharePoint",
            space_id=uuid4(),
            user_integration_id=uuid4(),
            embedding_model=None,
            tenant_id=admin_user.tenant_id,
            url="https://sharepoint.example.com",
        )
        created_knowledge = await integration_knowledge_repo.add(knowledge)

        # Create 25 sync logs
        now = datetime.utcnow()
        for i in range(25):
            log = SyncLog(
                integration_knowledge_id=created_knowledge.id,
                sync_type="full",
                status="success",
                metadata={"files_processed": i},
                started_at=now - timedelta(hours=i),
                created_at=now - timedelta(hours=i),
            )
            await sync_log_repo.add(log)

        # Act - Request second page
        response = await client.get(
            f"/api/v1/integrations/sync-logs/{created_knowledge.id}/?skip=10&limit=10",
            headers={"X-API-Key": admin_user_api_key.key},
        )

        # Assert
        assert response.status_code == 200
        data = response.json()

        assert data["offset"] == 10
        assert data["current_page"] == 2
        assert data["has_previous"] is True
        assert data["has_next"] is True
        assert len(data["items"]) == 10


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_sync_logs_pagination_last_page(
    client, admin_user_api_key, db_container
):
    """Test pagination for last page."""
    async with db_container() as container:
        # Arrange
        user_repo = container.user_repo()
        integration_knowledge_repo = container.integration_knowledge_repo()
        sync_log_repo = container.sync_log_repo()

        admin_user = await user_repo.one(id=admin_user_api_key.user_id)

        knowledge = IntegrationKnowledge(
            name="Test SharePoint",
            space_id=uuid4(),
            user_integration_id=uuid4(),
            embedding_model=None,
            tenant_id=admin_user.tenant_id,
            url="https://sharepoint.example.com",
        )
        created_knowledge = await integration_knowledge_repo.add(knowledge)

        # Create 25 sync logs
        now = datetime.utcnow()
        for i in range(25):
            log = SyncLog(
                integration_knowledge_id=created_knowledge.id,
                sync_type="full",
                status="success",
                started_at=now - timedelta(hours=i),
                created_at=now - timedelta(hours=i),
            )
            await sync_log_repo.add(log)

        # Act - Request last page
        response = await client.get(
            f"/api/v1/integrations/sync-logs/{created_knowledge.id}/?skip=20&limit=10",
            headers={"X-API-Key": admin_user_api_key.key},
        )

        # Assert
        assert response.status_code == 200
        data = response.json()

        assert data["offset"] == 20
        assert data["current_page"] == 3
        assert data["has_previous"] is True
        assert data["has_next"] is False
        assert len(data["items"]) == 5


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_sync_logs_empty_result(client, admin_user_api_key, db_container):
    """Test getting sync logs when none exist."""
    async with db_container() as container:
        # Arrange
        user_repo = container.user_repo()
        integration_knowledge_repo = container.integration_knowledge_repo()

        admin_user = await user_repo.one(id=admin_user_api_key.user_id)

        knowledge = IntegrationKnowledge(
            name="Test SharePoint",
            space_id=uuid4(),
            user_integration_id=uuid4(),
            embedding_model=None,
            tenant_id=admin_user.tenant_id,
            url="https://sharepoint.example.com",
        )
        created_knowledge = await integration_knowledge_repo.add(knowledge)

        # Act
        response = await client.get(
            f"/api/v1/integrations/sync-logs/{created_knowledge.id}/",
            headers={"X-API-Key": admin_user_api_key.key},
        )

        # Assert
        assert response.status_code == 200
        data = response.json()

        assert data["total_count"] == 0
        assert data["current_page"] == 1
        assert data["total_pages"] == 1
        assert data["has_next"] is False
        assert data["has_previous"] is False
        assert len(data["items"]) == 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_sync_logs_custom_limit(client, admin_user_api_key, db_container):
    """Test custom limit parameter."""
    async with db_container() as container:
        # Arrange
        user_repo = container.user_repo()
        integration_knowledge_repo = container.integration_knowledge_repo()
        sync_log_repo = container.sync_log_repo()

        admin_user = await user_repo.one(id=admin_user_api_key.user_id)

        knowledge = IntegrationKnowledge(
            name="Test SharePoint",
            space_id=uuid4(),
            user_integration_id=uuid4(),
            embedding_model=None,
            tenant_id=admin_user.tenant_id,
            url="https://sharepoint.example.com",
        )
        created_knowledge = await integration_knowledge_repo.add(knowledge)

        # Create 30 sync logs
        now = datetime.utcnow()
        for i in range(30):
            log = SyncLog(
                integration_knowledge_id=created_knowledge.id,
                sync_type="full",
                status="success",
                started_at=now - timedelta(hours=i),
                created_at=now - timedelta(hours=i),
            )
            await sync_log_repo.add(log)

        # Act - Request with custom limit
        response = await client.get(
            f"/api/v1/integrations/sync-logs/{created_knowledge.id}/?skip=0&limit=20",
            headers={"X-API-Key": admin_user_api_key.key},
        )

        # Assert
        assert response.status_code == 200
        data = response.json()

        assert data["page_size"] == 20
        assert len(data["items"]) == 20
        assert data["total_pages"] == 2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_sync_logs_computed_fields(client, admin_user_api_key, db_container):
    """Test that computed fields are properly calculated."""
    async with db_container() as container:
        # Arrange
        user_repo = container.user_repo()
        integration_knowledge_repo = container.integration_knowledge_repo()
        sync_log_repo = container.sync_log_repo()

        admin_user = await user_repo.one(id=admin_user_api_key.user_id)

        knowledge = IntegrationKnowledge(
            name="Test SharePoint",
            space_id=uuid4(),
            user_integration_id=uuid4(),
            embedding_model=None,
            tenant_id=admin_user.tenant_id,
            url="https://sharepoint.example.com",
        )
        created_knowledge = await integration_knowledge_repo.add(knowledge)

        # Create a sync log with metadata
        now = datetime.utcnow()
        log = SyncLog(
            integration_knowledge_id=created_knowledge.id,
            sync_type="delta",
            status="success",
            metadata={
                "files_processed": 15,
                "files_deleted": 2,
                "pages_processed": 5,
                "folders_processed": 3,
                "skipped_items": 1,
            },
            started_at=now,
            completed_at=now + timedelta(seconds=300),
            created_at=now,
        )
        await sync_log_repo.add(log)

        # Act
        response = await client.get(
            f"/api/v1/integrations/sync-logs/{created_knowledge.id}/",
            headers={"X-API-Key": admin_user_api_key.key},
        )

        # Assert
        assert response.status_code == 200
        data = response.json()
        item = data["items"][0]

        assert item["files_processed"] == 15
        assert item["files_deleted"] == 2
        assert item["pages_processed"] == 5
        assert item["folders_processed"] == 3
        assert item["skipped_items"] == 1
        assert item["total_items_processed"] == 23  # 15 + 5 + 3
        assert item["duration_seconds"] == 300.0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_sync_logs_error_status(client, admin_user_api_key, db_container):
    """Test sync logs with error status."""
    async with db_container() as container:
        # Arrange
        user_repo = container.user_repo()
        integration_knowledge_repo = container.integration_knowledge_repo()
        sync_log_repo = container.sync_log_repo()

        admin_user = await user_repo.one(id=admin_user_api_key.user_id)

        knowledge = IntegrationKnowledge(
            name="Test SharePoint",
            space_id=uuid4(),
            user_integration_id=uuid4(),
            embedding_model=None,
            tenant_id=admin_user.tenant_id,
            url="https://sharepoint.example.com",
        )
        created_knowledge = await integration_knowledge_repo.add(knowledge)

        # Create error log
        now = datetime.utcnow()
        log = SyncLog(
            integration_knowledge_id=created_knowledge.id,
            sync_type="delta",
            status="error",
            error_message="SharePoint API returned 401 Unauthorized",
            started_at=now,
            completed_at=now + timedelta(seconds=30),
            created_at=now,
        )
        await sync_log_repo.add(log)

        # Act
        response = await client.get(
            f"/api/v1/integrations/sync-logs/{created_knowledge.id}/",
            headers={"X-API-Key": admin_user_api_key.key},
        )

        # Assert
        assert response.status_code == 200
        data = response.json()
        item = data["items"][0]

        assert item["status"] == "error"
        assert item["error_message"] == "SharePoint API returned 401 Unauthorized"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
