"""Fixtures for integration domain tests."""

import pytest
from datetime import datetime, timedelta
from uuid import uuid4

from intric.integration.domain.entities.sync_log import SyncLog


@pytest.fixture
async def integration_knowledge_factory(db_container):
    """Factory for creating IntegrationKnowledge for testing."""

    async def _create_integration_knowledge(
        name: str = "Test SharePoint",
        url: str = "https://sharepoint.example.com",
        **extra,
    ):
        """Create an IntegrationKnowledge entity and save to database via raw SQL.

        This bypasses the complex entity/mapper initialization to create a minimal
        test record. For full integration tests with UserIntegration, use the real
        repository directly.
        """
        from sqlalchemy import text
        from intric.database.database import sessionmanager

        # Get tenant from db_container
        async with db_container() as container:
            tenant_repo = container.tenant_repo()
            tenants = await tenant_repo.get_all_tenants()
            tenant = tenants[0] if tenants else None
            if not tenant:
                raise ValueError("No test tenant found")

        # Insert directly into database
        async with sessionmanager.session() as session:
            async with session.begin():
                result = await session.execute(text("""
                    INSERT INTO integration_knowledge (
                        id, name, space_id, user_integration_id,
                        tenant_id, url, created_at, updated_at
                    ) VALUES (
                        gen_random_uuid(), :name, :space_id, :user_integration_id,
                        :tenant_id, :url, NOW(), NOW()
                    ) RETURNING id
                """), {
                    "name": name,
                    "space_id": str(uuid4()),
                    "user_integration_id": str(uuid4()),
                    "tenant_id": str(tenant.id),
                    "url": url,
                })
                knowledge_id = result.scalar()

        # Return simple object with id
        class _Knowledge:
            pass
        k = _Knowledge()
        k.id = knowledge_id
        return k

    return _create_integration_knowledge


@pytest.fixture
async def sync_log_factory():
    """Factory for creating SyncLog entities for testing."""

    async def _create_sync_log(
        integration_knowledge_id,
        sync_type: str = "full",
        status: str = "success",
        metadata: dict = None,
        started_at: datetime = None,
        completed_at: datetime = None,
        created_at: datetime = None,
        error_message: str = None,
        **extra,
    ):
        """Create a SyncLog entity with sensible defaults."""
        if created_at is None:
            created_at = datetime.utcnow()

        if started_at is None:
            started_at = created_at

        if completed_at is None and status == "success":
            completed_at = started_at + timedelta(seconds=120)

        if metadata is None:
            metadata = {
                "files_processed": 0,
                "files_deleted": 0,
                "pages_processed": 0,
                "folders_processed": 0,
                "skipped_items": 0,
            }

        log = SyncLog(
            integration_knowledge_id=integration_knowledge_id,
            sync_type=sync_type,
            status=status,
            metadata=metadata,
            started_at=started_at,
            completed_at=completed_at,
            created_at=created_at,
            error_message=error_message,
            **extra,
        )
        return log

    return _create_sync_log


@pytest.fixture
async def create_sync_logs_in_db(sync_log_factory, db_container):
    """Factory for creating and saving multiple SyncLog records to database."""

    async def _create_and_save(
        integration_knowledge_id, count: int = 10, **log_kwargs
    ):
        """Create and save sync logs to database."""
        async with db_container() as container:
            repo = container.sync_log_repo()
            now = datetime.utcnow()

            created_logs = []
            for i in range(count):
                # Create log with variations
                log_params = {
                    "integration_knowledge_id": integration_knowledge_id,
                    "created_at": now - timedelta(hours=i),
                    "started_at": now - timedelta(hours=i),
                    "completed_at": now - timedelta(hours=i) + timedelta(seconds=120),
                    **log_kwargs,
                }

                log = await sync_log_factory(**log_params)
                created = await repo.add(log)
                created_logs.append(created)

            return created_logs

    return _create_and_save


@pytest.fixture
async def sync_log_repository(db_container):
    """Fixture providing SyncLogRepository instance."""

    async def _get_repo():
        async with db_container() as container:
            return container.sync_log_repo()

    return _get_repo


@pytest.fixture
def change_key_service_mock():
    """Mock OfficeChangeKeyService for testing."""
    from unittest.mock import AsyncMock

    service = AsyncMock()
    service.should_process = AsyncMock()
    service.update_change_key = AsyncMock()
    service.invalidate_change_key = AsyncMock()
    service.clear_integration_cache = AsyncMock()

    return service


@pytest.fixture
def redis_mock():
    """Mock Redis client for testing."""
    from unittest.mock import AsyncMock

    redis = AsyncMock()
    redis.get = AsyncMock()
    redis.setex = AsyncMock()
    redis.delete = AsyncMock()
    redis.eval = AsyncMock()

    return redis
