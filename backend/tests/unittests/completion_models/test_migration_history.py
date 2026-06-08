"""
Tests for migration history persistence and name resolution.

Verifies that:
- create_migration_history stores technical model names and provider types
- _convert_to_public_models resolves names correctly in all scenarios
- ModelMigrationHistory Pydantic model handles nullable foreign keys
"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from intric.completion_models.application.completion_model_migration_history_service import (
    CompletionModelMigrationHistoryService,
)
from intric.completion_models.domain.completion_model_migration_history_repo import (
    CompletionModelMigrationHistoryRepo,
)
from intric.completion_models.presentation.completion_model_models import (
    ModelMigrationHistory,
)


def _make_db_record(
    *,
    from_model_id=None,
    to_model_id=None,
    from_model_name=None,
    to_model_name=None,
    from_provider_type=None,
    to_provider_type=None,
    initiated_by=None,
    status="completed",
    migrated_count=5,
    started_at=None,
    completed_at=None,
    duration_seconds=1.23,
    error_message=None,
):
    """Create a mock database record mimicking CompletionModelMigrationHistory row."""
    record = SimpleNamespace(
        id=uuid4(),
        migration_id=uuid4(),
        tenant_id=uuid4(),
        from_model_id=from_model_id,
        to_model_id=to_model_id,
        from_model_name=from_model_name,
        to_model_name=to_model_name,
        from_provider_type=from_provider_type,
        to_provider_type=to_provider_type,
        initiated_by=initiated_by or uuid4(),
        status=status,
        entity_types=["assistants", "apps"],
        affected_count=10,
        migrated_count=migrated_count,
        failed_count=0,
        duration_seconds=duration_seconds,
        error_message=error_message,
        warnings=None,
        migration_details=None,
        started_at=started_at or datetime(2026, 1, 15, 10, 0, 0),
        completed_at=completed_at or datetime(2026, 1, 15, 10, 0, 1),
        created_at=datetime(2026, 1, 15, 10, 0, 0),
        updated_at=datetime(2026, 1, 15, 10, 0, 1),
    )
    return record


class TestCreateMigrationHistory:
    """Tests for the repo's create_migration_history method."""

    @pytest.mark.asyncio
    async def test_create_stores_model_names_and_provider_types(self):
        """create_migration_history should store technical model names and provider types."""
        session = AsyncMock()
        session.add = MagicMock()
        repo = CompletionModelMigrationHistoryRepo(session)

        migration_id = uuid4()
        tenant_id = uuid4()
        from_model_id = uuid4()
        to_model_id = uuid4()
        initiated_by = uuid4()

        await repo.create_migration_history(
            migration_id=migration_id,
            tenant_id=tenant_id,
            from_model_id=from_model_id,
            to_model_id=to_model_id,
            initiated_by=initiated_by,
            status="pending",
            from_model_name="gpt-4o",
            to_model_name="gpt-4o-mini",
            from_provider_type="openai",
            to_provider_type="anthropic",
        )

        # Verify session.add was called
        session.add.assert_called_once()
        added_record = session.add.call_args[0][0]

        assert added_record.from_model_name == "gpt-4o"
        assert added_record.to_model_name == "gpt-4o-mini"
        assert added_record.from_provider_type == "openai"
        assert added_record.to_provider_type == "anthropic"
        assert added_record.from_model_id == from_model_id
        assert added_record.to_model_id == to_model_id
        assert added_record.migration_id == migration_id

    @pytest.mark.asyncio
    async def test_create_stores_none_names_when_not_provided(self):
        """create_migration_history should store None for names when not provided."""
        session = AsyncMock()
        session.add = MagicMock()
        repo = CompletionModelMigrationHistoryRepo(session)

        await repo.create_migration_history(
            migration_id=uuid4(),
            tenant_id=uuid4(),
            from_model_id=uuid4(),
            to_model_id=uuid4(),
            initiated_by=uuid4(),
            status="pending",
        )

        added_record = session.add.call_args[0][0]
        assert added_record.from_model_name is None
        assert added_record.to_model_name is None
        assert added_record.from_provider_type is None
        assert added_record.to_provider_type is None

    @pytest.mark.asyncio
    async def test_create_record_contains_all_expected_fields(self):
        """Created history record should contain all expected fields."""
        session = AsyncMock()
        session.add = MagicMock()
        repo = CompletionModelMigrationHistoryRepo(session)

        migration_id = uuid4()
        tenant_id = uuid4()
        from_model_id = uuid4()
        to_model_id = uuid4()
        initiated_by = uuid4()
        started_at = datetime(2026, 3, 1, 12, 0, 0)
        entity_types = ["assistants", "apps", "services"]

        await repo.create_migration_history(
            migration_id=migration_id,
            tenant_id=tenant_id,
            from_model_id=from_model_id,
            to_model_id=to_model_id,
            initiated_by=initiated_by,
            status="in_progress",
            entity_types=entity_types,
            affected_count=42,
            started_at=started_at,
            from_model_name="claude-3-opus",
            to_model_name="claude-3.5-sonnet",
            from_provider_type="anthropic",
            to_provider_type="anthropic",
        )

        added_record = session.add.call_args[0][0]

        assert added_record.migration_id == migration_id
        assert added_record.tenant_id == tenant_id
        assert added_record.from_model_id == from_model_id
        assert added_record.to_model_id == to_model_id
        assert added_record.from_model_name == "claude-3-opus"
        assert added_record.to_model_name == "claude-3.5-sonnet"
        assert added_record.from_provider_type == "anthropic"
        assert added_record.to_provider_type == "anthropic"
        assert added_record.initiated_by == initiated_by
        assert added_record.status == "in_progress"
        assert added_record.entity_types == entity_types
        assert added_record.affected_count == 42
        assert added_record.migrated_count == 0
        assert added_record.failed_count == 0
        assert added_record.started_at == started_at


class TestConvertToPublicModels:
    """Tests for the service's _convert_to_public_models name resolution."""

    def _make_service(self):
        """Create a service with mocked session."""
        session = AsyncMock()
        service = CompletionModelMigrationHistoryService(session)
        return service

    @pytest.mark.asyncio
    async def test_uses_stored_name_when_model_deleted(self):
        """Deleted models keep readable names, but not dead UUID fallbacks."""
        service = self._make_service()

        record = _make_db_record(
            from_model_id=None,
            to_model_id=None,
            from_model_name="gpt-4-0613",
            to_model_name="gpt-4o",
        )

        # Mock batch lookups to return empty dicts (no models found in DB)
        service._get_model_names = AsyncMock(return_value={})
        service._get_user_names = AsyncMock(
            return_value={record.initiated_by: "admin@example.com"}
        )

        result = await service._convert_to_public_models([record])

        assert len(result) == 1
        assert result[0].from_model_name == "gpt-4-0613"
        assert result[0].to_model_name == "gpt-4o"
        assert result[0].from_model_id is None
        assert result[0].to_model_id is None

    @pytest.mark.asyncio
    async def test_uses_stored_name_as_primary_source_even_when_model_exists(self):
        """Stored name should be used as primary source, even if the model still exists in DB."""
        service = self._make_service()

        from_id = uuid4()
        to_id = uuid4()

        record = _make_db_record(
            from_model_id=from_id,
            to_model_id=to_id,
            from_model_name="gpt-4-0613",
            to_model_name="gpt-4o",
        )

        # Live DB has different names (e.g. model was renamed)
        service._get_model_names = AsyncMock(
            return_value={
                from_id: "gpt-4-0613-renamed",
                to_id: "gpt-4o-renamed",
            }
        )
        service._get_user_names = AsyncMock(
            return_value={record.initiated_by: "admin@example.com"}
        )

        result = await service._convert_to_public_models([record])

        assert len(result) == 1
        # Stored names take priority over live DB names
        assert result[0].from_model_name == "gpt-4-0613"
        assert result[0].to_model_name == "gpt-4o"
        # IDs are still present since models exist
        assert result[0].from_model_id == from_id
        assert result[0].to_model_id == to_id

    @pytest.mark.asyncio
    async def test_falls_back_to_deleted_model_when_both_name_and_id_null(self):
        """Should fall back to 'Deleted model' when both stored name and model_id are null."""
        service = self._make_service()

        record = _make_db_record(
            from_model_id=None,
            to_model_id=None,
            from_model_name=None,
            to_model_name=None,
        )

        service._get_model_names = AsyncMock(return_value={})
        service._get_user_names = AsyncMock(
            return_value={record.initiated_by: "admin@example.com"}
        )

        result = await service._convert_to_public_models([record])

        assert len(result) == 1
        assert result[0].from_model_name == "Deleted model"
        assert result[0].to_model_name == "Deleted model"

    @pytest.mark.asyncio
    async def test_falls_back_to_live_name_when_stored_name_is_none(self):
        """When stored name is None but model still exists, should use live DB name."""
        service = self._make_service()

        from_id = uuid4()
        to_id = uuid4()

        record = _make_db_record(
            from_model_id=from_id,
            to_model_id=to_id,
            from_model_name=None,
            to_model_name=None,
        )

        # Model still exists in DB with these names
        service._get_model_names = AsyncMock(
            return_value={
                from_id: "gpt-4-live",
                to_id: "gpt-4o-live",
            }
        )
        service._get_user_names = AsyncMock(
            return_value={record.initiated_by: "admin@example.com"}
        )

        result = await service._convert_to_public_models([record])

        assert len(result) == 1
        assert result[0].from_model_name == "gpt-4-live"
        assert result[0].to_model_name == "gpt-4o-live"

    @pytest.mark.asyncio
    async def test_convert_empty_list_returns_empty(self):
        """Converting an empty list should return an empty list without DB queries."""
        service = self._make_service()

        result = await service._convert_to_public_models([])

        assert result == []

    @pytest.mark.asyncio
    async def test_convert_populates_all_public_model_fields(self):
        """All fields on ModelMigrationHistory should be populated from the DB record."""
        service = self._make_service()

        from_id = uuid4()
        to_id = uuid4()
        initiated_by = uuid4()
        started = datetime(2026, 3, 15, 14, 0, 0)
        completed = datetime(2026, 3, 15, 14, 0, 5)

        record = _make_db_record(
            from_model_id=from_id,
            to_model_id=to_id,
            from_model_name="source-model",
            to_model_name="target-model",
            initiated_by=initiated_by,
            status="completed",
            migrated_count=17,
            started_at=started,
            completed_at=completed,
            duration_seconds=5.0,
            error_message=None,
        )

        service._get_model_names = AsyncMock(return_value={})
        service._get_user_names = AsyncMock(
            return_value={initiated_by: "user@company.com"}
        )

        result = await service._convert_to_public_models([record])

        assert len(result) == 1
        public = result[0]

        assert public.id == record.id
        assert public.from_model_id == from_id
        assert public.from_model_name == "source-model"
        assert public.to_model_id == to_id
        assert public.to_model_name == "target-model"
        assert public.migrated_count == 17
        assert public.status == "completed"
        assert public.initiated_by_id == initiated_by
        assert public.initiated_by_name == "user@company.com"
        assert public.started_at == started
        assert public.completed_at == completed
        assert public.duration == 5.0
        assert public.error_message is None

    @pytest.mark.asyncio
    async def test_deleted_models_keep_null_ids_after_cleanup(self):
        """Deleted models should expose readable snapshots, not stale UUIDs."""
        service = self._make_service()

        record = _make_db_record(
            from_model_id=None,
            to_model_id=None,
            from_model_name="old-source",
            to_model_name="target-model",
            from_provider_type="openai",
            to_provider_type="anthropic",
        )

        service._get_model_names = AsyncMock(return_value={})
        service._get_user_names = AsyncMock(
            return_value={record.initiated_by: "admin@example.com"}
        )

        result = await service._convert_to_public_models([record])

        assert result[0].from_model_id is None
        assert result[0].to_model_id is None

    @pytest.mark.asyncio
    async def test_convert_multiple_records(self):
        """Should correctly handle multiple records in a single batch."""
        service = self._make_service()

        user_id = uuid4()
        record1 = _make_db_record(
            from_model_id=None,
            to_model_id=uuid4(),
            from_model_name="old-model",
            to_model_name="new-model",
            initiated_by=user_id,
            status="completed",
        )
        record2 = _make_db_record(
            from_model_id=uuid4(),
            to_model_id=None,
            from_model_name="another-old",
            to_model_name=None,
            initiated_by=user_id,
            status="failed",
            error_message="Something went wrong",
        )

        service._get_model_names = AsyncMock(return_value={})
        service._get_user_names = AsyncMock(
            return_value={user_id: "admin@test.com"}
        )

        result = await service._convert_to_public_models([record1, record2])

        assert len(result) == 2

        assert result[0].from_model_name == "old-model"
        assert result[0].to_model_name == "new-model"
        assert result[0].status == "completed"

        assert result[1].from_model_name == "another-old"
        assert result[1].to_model_name == "Deleted model"
        assert result[1].status == "failed"
        assert result[1].error_message == "Something went wrong"


class TestModelMigrationHistoryPydanticModel:
    """Tests for the ModelMigrationHistory Pydantic model serialization."""

    def test_accepts_none_for_model_ids(self):
        """ModelMigrationHistory should accept None for both from_model_id and to_model_id."""
        history = ModelMigrationHistory(
            id=uuid4(),
            from_model_id=None,
            from_model_name="gpt-4",
            to_model_id=None,
            to_model_name="gpt-4o",
            migrated_count=10,
            status="completed",
            initiated_by_id=uuid4(),
            initiated_by_name="admin@example.com",
        )

        assert history.from_model_id is None
        assert history.to_model_id is None
        assert history.from_model_name == "gpt-4"
        assert history.to_model_name == "gpt-4o"

    def test_accepts_uuids_for_model_ids(self):
        """ModelMigrationHistory should accept UUIDs for both model IDs."""
        from_id = uuid4()
        to_id = uuid4()

        history = ModelMigrationHistory(
            id=uuid4(),
            from_model_id=from_id,
            from_model_name="gpt-4",
            to_model_id=to_id,
            to_model_name="gpt-4o",
            migrated_count=10,
            status="completed",
            initiated_by_id=uuid4(),
            initiated_by_name="admin@example.com",
        )

        assert history.from_model_id == from_id
        assert history.to_model_id == to_id

    def test_optional_fields_default_to_none(self):
        """Optional fields should default to None when not provided."""
        history = ModelMigrationHistory(
            id=uuid4(),
            from_model_id=None,
            from_model_name="gpt-4",
            to_model_id=None,
            to_model_name="gpt-4o",
            migrated_count=0,
            status="pending",
            initiated_by_id=uuid4(),
            initiated_by_name="admin@example.com",
        )

        assert history.started_at is None
        assert history.completed_at is None
        assert history.duration is None
        assert history.error_message is None

    def test_serialization_roundtrip(self):
        """Model should serialize to dict and back correctly."""
        original_id = uuid4()
        from_id = uuid4()
        to_id = uuid4()
        initiated_by = uuid4()
        now = datetime(2026, 3, 15, 12, 0, 0)

        history = ModelMigrationHistory(
            id=original_id,
            from_model_id=from_id,
            from_model_name="gpt-4",
            to_model_id=to_id,
            to_model_name="gpt-4o",
            migrated_count=25,
            status="completed",
            initiated_by_id=initiated_by,
            initiated_by_name="admin@example.com",
            started_at=now,
            completed_at=now,
            duration=3.14,
            error_message=None,
        )

        data = history.model_dump()
        restored = ModelMigrationHistory(**data)

        assert restored.id == original_id
        assert restored.from_model_id == from_id
        assert restored.from_model_name == "gpt-4"
        assert restored.to_model_id == to_id
        assert restored.to_model_name == "gpt-4o"
        assert restored.migrated_count == 25
        assert restored.status == "completed"
        assert restored.duration == 3.14

    def test_serialization_with_none_ids(self):
        """Serialization should handle None model IDs correctly."""
        history = ModelMigrationHistory(
            id=uuid4(),
            from_model_id=None,
            from_model_name="Deleted model",
            to_model_id=None,
            to_model_name="Deleted model",
            migrated_count=0,
            status="failed",
            initiated_by_id=uuid4(),
            initiated_by_name="admin@example.com",
            error_message="Migration failed",
        )

        data = history.model_dump()

        assert data["from_model_id"] is None
        assert data["to_model_id"] is None
        assert data["from_model_name"] == "Deleted model"
        assert data["to_model_name"] == "Deleted model"
        assert data["error_message"] == "Migration failed"
