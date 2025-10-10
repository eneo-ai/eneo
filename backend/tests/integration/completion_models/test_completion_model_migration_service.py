"""
Integration tests for CompletionModelMigrationService.

These tests verify end-to-end migration functionality including:
- Model validation
- Entity migration (assistants, apps, services, spaces)
- Compatibility checks
- Migration history tracking
- Usage statistics recalculation
"""
import pytest
from sqlalchemy import select

from intric.database.tables.assistant_table import Assistants
from intric.database.tables.spaces_table import SpacesCompletionModels

@pytest.mark.integration
@pytest.mark.asyncio
class TestCompletionModelMigration:
    """Test suite for model migration functionality."""

    async def test_migrate_assistants_successfully(
        self,
        db_container,
        completion_model_factory,
        assistant_factory,
        admin_user,
    ):
        """Test successful migration of assistants from one model to another."""
        async with db_container() as container:
            session = container.session()

            old_model = await completion_model_factory(session, "gpt-3.5-turbo", provider="openai")
            new_model = await completion_model_factory(session, "gpt-4", provider="openai")

            assistant1 = await assistant_factory(session, "Test Assistant 1", old_model.id, kwargs={ "temperature": 1.25 })

            # Act: Perform migration
            migration_service = container.completion_model_migration_service()
            result = await migration_service.migrate_model_usage(
                from_model_id=old_model.id,
                to_model_id=new_model.id,
                entity_types=["assistants"],
                user=admin_user,
                confirm_migration=True
            )

            # Assert: Verify migration succeeded
            assert result.success is True
            assert result.migrated_count == 1
            assert result.failed_count == 0
            assert "assistants" in result.details
            assert result.details["assistants"] == 1

            # Verify assistants now use the new model
            stmt = select(Assistants).where(Assistants.id == assistant1.id)
            updated_assistant = (await session.execute(stmt)).scalar_one()
            assert updated_assistant.completion_model_id == new_model.id
            # Kwargs should be reset to avoid parameter incompatibilities
            assert updated_assistant.completion_model_kwargs == {}

            # Verify NO assistants still use the old model
            stmt_old = select(Assistants).where(Assistants.completion_model_id == old_model.id)
            assistants_with_old_model = (await session.execute(stmt_old)).scalars().all()
            assert len(assistants_with_old_model) == 0, "No assistants should still be using the old model"

    async def test_migrate_spaces_successfully(
        self,
        db_container,
        completion_model_factory,
        space_factory,
        admin_user,
    ):
        """Test successful migration of spaces from one model to another."""
        async with db_container() as container:
            session = container.session()

            old_model = await completion_model_factory(session, "gpt-3.5-turbo", provider="openai")
            new_model = await completion_model_factory(session, "gpt-4", provider="openai")
            other_model = await completion_model_factory(session, "claude-3", provider="anthropic")

            # Create spaces with different model configurations
            space1 = await space_factory(session, "Space 1", [old_model.id])
            space2 = await space_factory(session, "Space 2", [old_model.id, other_model.id])
            space3 = await space_factory(session, "Space 3", [other_model.id])  # Should not be affected

            # Act: Migrate spaces from old_model to new_model
            migration_service = container.completion_model_migration_service()
            result = await migration_service.migrate_model_usage(
                from_model_id=old_model.id,
                to_model_id=new_model.id,
                entity_types=["spaces"],
                user=admin_user,
                confirm_migration=True,  # Confirm despite warnings
            )

            # Assert: Verify migration succeeded
            assert result.success is True
            assert result.migrated_count == 2  # space1 and space2
            assert result.failed_count == 0
            assert "spaces" in result.details
            assert result.details["spaces"] == 2

            # Verify space1 now has new_model (and NOT old_model)
            stmt = select(SpacesCompletionModels).where(SpacesCompletionModels.space_id == space1.id)
            space1_models = (await session.execute(stmt)).scalars().all()
            space1_model_ids = [m.completion_model_id for m in space1_models]
            assert new_model.id in space1_model_ids, "Space1 should have new model"
            assert old_model.id not in space1_model_ids, "Space1 should NOT have old model"
            assert len(space1_model_ids) == 1, "Space1 should have exactly 1 model"

            # Verify space2 now has new_model and other_model (and NOT old_model)
            stmt = select(SpacesCompletionModels).where(SpacesCompletionModels.space_id == space2.id)
            space2_models = (await session.execute(stmt)).scalars().all()
            space2_model_ids = [m.completion_model_id for m in space2_models]
            assert new_model.id in space2_model_ids, "Space2 should have new model"
            assert other_model.id in space2_model_ids, "Space2 should still have other model"
            assert old_model.id not in space2_model_ids, "Space2 should NOT have old model"
            assert len(space2_model_ids) == 2, "Space2 should have exactly 2 models"

            # Verify space3 is unchanged (only had other_model)
            stmt = select(SpacesCompletionModels).where(SpacesCompletionModels.space_id == space3.id)
            space3_models = (await session.execute(stmt)).scalars().all()
            space3_model_ids = [m.completion_model_id for m in space3_models]
            assert other_model.id in space3_model_ids, "Space3 should still have other model"
            assert new_model.id not in space3_model_ids, "Space3 should NOT have new model"
            assert old_model.id not in space3_model_ids, "Space3 should NOT have old model"
            assert len(space3_model_ids) == 1, "Space3 should have exactly 1 model"

            # Verify NO spaces still have the old model
            stmt = select(SpacesCompletionModels).where(
                SpacesCompletionModels.completion_model_id == old_model.id
            )
            spaces_with_old_model = (await session.execute(stmt)).scalars().all()
            assert len(spaces_with_old_model) == 0, "No spaces should still have the old model"


