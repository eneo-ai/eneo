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
        # Arrange: Create two models and assistants using the first model
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


