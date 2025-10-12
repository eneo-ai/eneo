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
from intric.database.tables.app_table import Apps
from intric.database.tables.service_table import Services
from intric.database.tables.spaces_table import SpacesCompletionModels
from intric.main.exceptions import ValidationException
from intric.ai_models.model_enums import ModelFamily

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

    async def test_migrate_apps_successfully(
        self,
        db_container,
        completion_model_factory,
        app_factory,
        admin_user,
    ):
        """Test successful migration of apps from one model to another."""
        # Arrange: Create two models and apps using the first model
        async with db_container() as container:
            session = container.session()

            old_model = await completion_model_factory(session, "gpt-3.5-turbo", provider="openai")
            new_model = await completion_model_factory(session, "gpt-4", provider="openai")

            app1 = await app_factory(session, "Test App 1", old_model.id)
            await app_factory(session, "Test App 2", old_model.id)

            # Act: Perform migration
            migration_service = container.completion_model_migration_service()
            result = await migration_service.migrate_model_usage(
                from_model_id=old_model.id,
                to_model_id=new_model.id,
                entity_types=["apps"],
                user=admin_user,
                confirm_migration=True,
            )

            # Assert: Verify migration succeeded
            assert result.success is True
            assert result.migrated_count == 2
            assert result.failed_count == 0
            assert "apps" in result.details
            assert result.details["apps"] == 2

            # Verify apps now use the new model
            stmt = select(Apps).where(Apps.id == app1.id)
            updated_app = (await session.execute(stmt)).scalar_one()
            assert updated_app.completion_model_id == new_model.id

            # Verify NO apps still use the old model
            stmt_old = select(Apps).where(Apps.completion_model_id == old_model.id)
            apps_with_old_model = (await session.execute(stmt_old)).scalars().all()
            assert len(apps_with_old_model) == 0, "No apps should still be using the old model"

    async def test_migrate_services_successfully(
        self,
        db_container,
        completion_model_factory,
        service_factory,
        admin_user,
    ):
        """Test successful migration of services from one model to another."""
        # Arrange: Create two models and services using the first model
        async with db_container() as container:
            session = container.session()

            old_model = await completion_model_factory(session, "gpt-3.5-turbo", provider="openai")
            new_model = await completion_model_factory(session, "gpt-4", provider="openai")

            service1 = await service_factory(session, "Test Service 1", old_model.id)
            service2 = await service_factory(session, "Test Service 2", old_model.id)
            service3 = await service_factory(session, "Test Service 3", old_model.id)

            # Act: Perform migration
            migration_service = container.completion_model_migration_service()
            result = await migration_service.migrate_model_usage(
                from_model_id=old_model.id,
                to_model_id=new_model.id,
                entity_types=["services"],
                user=admin_user,
                confirm_migration=True,
            )

            # Assert: Verify migration succeeded
            assert result.success is True
            assert result.migrated_count == 3
            assert result.failed_count == 0
            assert "services" in result.details
            assert result.details["services"] == 3

            # Verify services now use the new model
            stmt = select(Services).where(Services.id.in_([service1.id, service2.id, service3.id]))
            updated_services = (await session.execute(stmt)).scalars().all()
            for service in updated_services:
                assert service.completion_model_id == new_model.id

            # Verify NO services still use the old model
            stmt_old = select(Services).where(Services.completion_model_id == old_model.id)
            services_with_old_model = (await session.execute(stmt_old)).scalars().all()
            assert len(services_with_old_model) == 0, "No services should still be using the old model"

    async def test_migrate_all_entity_types_together(
        self,
        db_container,
        completion_model_factory,
        assistant_factory,
        app_factory,
        service_factory,
        space_factory,
        admin_user,
    ):
        """Test migration of all entity types in a single operation.

        This simulates a real-world scenario where an organization wants to
        migrate all usage of an old model to a new model across all entity types.
        """
        # Arrange: Create comprehensive test data
        async with db_container() as container:
            session = container.session()

            old_model = await completion_model_factory(session, "gpt-3.5-turbo", provider="openai")
            new_model = await completion_model_factory(session, "gpt-4", provider="openai")

            # Create multiple entities of each type using the old model
            assistant1 = await assistant_factory(session, "Assistant 1", old_model.id)
            assistant2 = await assistant_factory(session, "Assistant 2", old_model.id)

            app1 = await app_factory(session, "App 1", old_model.id)
            app2 = await app_factory(session, "App 2", old_model.id)

            service1 = await service_factory(session, "Service 1", old_model.id)
            service2 = await service_factory(session, "Service 2", old_model.id)

            space1 = await space_factory(session, "Space 1", [old_model.id])
            space2 = await space_factory(session, "Space 2", [old_model.id])

            # Act: Migrate ALL entity types at once
            migration_service = container.completion_model_migration_service()
            result = await migration_service.migrate_model_usage(
                from_model_id=old_model.id,
                to_model_id=new_model.id,
                entity_types=["assistants", "apps", "services", "spaces"],
                user=admin_user,
                confirm_migration=True,
            )

            # Assert: Verify overall migration succeeded
            assert result.success is True
            assert result.migrated_count == 8  # 2 assistants + 2 apps + 2 services + 2 spaces
            assert result.failed_count == 0

            # Verify details breakdown
            assert result.details["assistants"] == 2
            assert result.details["apps"] == 2
            assert result.details["services"] == 2
            assert result.details["spaces"] == 2

            # Verify NO entities still use the old model
            # Check assistants
            stmt = select(Assistants).where(Assistants.completion_model_id == old_model.id)
            assert len((await session.execute(stmt)).scalars().all()) == 0

            # Check apps
            stmt = select(Apps).where(Apps.completion_model_id == old_model.id)
            assert len((await session.execute(stmt)).scalars().all()) == 0

            # Check services
            stmt = select(Services).where(Services.completion_model_id == old_model.id)
            assert len((await session.execute(stmt)).scalars().all()) == 0

            # Check spaces
            stmt = select(SpacesCompletionModels).where(
                SpacesCompletionModels.completion_model_id == old_model.id
            )
            assert len((await session.execute(stmt)).scalars().all()) == 0

            # Verify all entities now use the new model
            # Check assistants
            stmt = select(Assistants).where(Assistants.id.in_([assistant1.id, assistant2.id]))
            assistants = (await session.execute(stmt)).scalars().all()
            for assistant in assistants:
                assert assistant.completion_model_id == new_model.id

            # Check apps
            stmt = select(Apps).where(Apps.id.in_([app1.id, app2.id]))
            apps = (await session.execute(stmt)).scalars().all()
            for app in apps:
                assert app.completion_model_id == new_model.id

            # Check services
            stmt = select(Services).where(Services.id.in_([service1.id, service2.id]))
            services = (await session.execute(stmt)).scalars().all()
            for service in services:
                assert service.completion_model_id == new_model.id

            # Check spaces
            for space in [space1, space2]:
                stmt = select(SpacesCompletionModels).where(SpacesCompletionModels.space_id == space.id)
                space_models = (await session.execute(stmt)).scalars().all()
                model_ids = [m.completion_model_id for m in space_models]
                assert new_model.id in model_ids
                assert old_model.id not in model_ids

    async def test_migrate_assistant_respects_space_model_availability(
        self,
        db_container,
        completion_model_factory,
        assistant_factory,
        space_factory,
        admin_user,
    ):
        """Test that migration respects space model availability/restrictions.

        If an assistant uses a model that is NOT available in its space,
        after migration the assistant should use the new model, but the space
        should NOT automatically get the new model added (unless the old model
        was already in the space).
        """
        # Arrange: Create assistant with model that's NOT in its space
        async with db_container() as container:
            session = container.session()

            old_model = await completion_model_factory(session, "gpt-3.5-turbo", provider="openai")
            new_model = await completion_model_factory(session, "gpt-4", provider="openai")
            other_model = await completion_model_factory(session, "claude-3", provider="anthropic")

            # Create space WITHOUT old_model (only has other_model)
            # This represents a space where old_model is "unavailable"
            space = await space_factory(session, "Restricted Space", [other_model.id])

            # Create assistant in this space using old_model
            # Note: In production, this might be prevented, but testing edge case
            assistant = await assistant_factory(
                session,
                "Test Assistant",
                old_model.id,
                space_id=space.id
            )

            # Verify initial state: space does NOT have old_model
            stmt = select(SpacesCompletionModels).where(SpacesCompletionModels.space_id == space.id)
            initial_space_models = (await session.execute(stmt)).scalars().all()
            initial_model_ids = [m.completion_model_id for m in initial_space_models]
            assert old_model.id not in initial_model_ids, "Space should not have old_model initially"
            assert other_model.id in initial_model_ids, "Space should have other_model"

            # Act: Migrate assistants
            migration_service = container.completion_model_migration_service()
            result = await migration_service.migrate_model_usage(
                from_model_id=old_model.id,
                to_model_id=new_model.id,
                entity_types=["assistants"],
                user=admin_user,
                confirm_migration=True,
            )

            # Assert: Migration succeeded
            assert result.success is True
            assert result.migrated_count == 1

            # Verify assistant now uses new_model
            stmt = select(Assistants).where(Assistants.id == assistant.id)
            updated_assistant = (await session.execute(stmt)).scalar_one()
            assert updated_assistant.completion_model_id == new_model.id

            # CRITICAL: Verify space still does NOT have new_model
            # The space model availability should be respected
            stmt = select(SpacesCompletionModels).where(SpacesCompletionModels.space_id == space.id)
            final_space_models = (await session.execute(stmt)).scalars().all()
            final_model_ids = [m.completion_model_id for m in final_space_models]

            assert new_model.id not in final_model_ids, (
                "Space should NOT automatically get new_model since old_model was not in space"
            )
            assert other_model.id in final_model_ids, "Space should still have other_model"
            assert len(final_model_ids) == 1, "Space should still have exactly 1 model"

    # ============================================================================
    # Validation Error Tests
    # ============================================================================

    async def test_reject_migration_same_source_and_target_model(
        self,
        db_container,
        completion_model_factory,
        admin_user,
    ):
        """Test that migration is rejected when source and target models are the same."""
        async with db_container() as container:
            session = container.session()

            model = await completion_model_factory(session, "gpt-4", provider="openai")

            # Act & Assert: Attempt migration with same source and target
            migration_service = container.completion_model_migration_service()
            with pytest.raises(ValidationException) as exc_info:
                await migration_service.migrate_model_usage(
                    from_model_id=model.id,
                    to_model_id=model.id,
                    entity_types=["assistants"],
                    user=admin_user,
                    confirm_migration=True,
                )

            # Verify error message mentions same models
            assert "same" in str(exc_info.value).lower()
            assert "source and target" in str(exc_info.value).lower()

    async def test_reject_migration_nonexistent_source_model(
        self,
        db_container,
        completion_model_factory,
        admin_user,
    ):
        """Test that migration is rejected when source model doesn't exist."""
        from uuid import uuid4

        async with db_container() as container:
            session = container.session()

            target_model = await completion_model_factory(session, "gpt-4", provider="openai")
            fake_source_id = uuid4()

            # Act & Assert: Attempt migration with non-existent source model
            migration_service = container.completion_model_migration_service()
            with pytest.raises(ValidationException) as exc_info:
                await migration_service.migrate_model_usage(
                    from_model_id=fake_source_id,
                    to_model_id=target_model.id,
                    entity_types=["assistants"],
                    user=admin_user,
                    confirm_migration=True,
                )

            # Verify error message indicates validation failure
            # Note: When model doesn't exist in repo, it's caught and wrapped in generic error
            assert "validation failed" in str(exc_info.value).lower()

    async def test_reject_migration_nonexistent_target_model(
        self,
        db_container,
        completion_model_factory,
        admin_user,
    ):
        """Test that migration is rejected when target model doesn't exist."""
        from uuid import uuid4

        async with db_container() as container:
            session = container.session()

            source_model = await completion_model_factory(session, "gpt-3.5-turbo", provider="openai")
            fake_target_id = uuid4()

            # Act & Assert: Attempt migration with non-existent target model
            migration_service = container.completion_model_migration_service()
            with pytest.raises(ValidationException) as exc_info:
                await migration_service.migrate_model_usage(
                    from_model_id=source_model.id,
                    to_model_id=fake_target_id,
                    entity_types=["assistants"],
                    user=admin_user,
                    confirm_migration=True,
                )

            # Verify error message indicates validation failure
            # Note: When model doesn't exist in repo, it's caught and wrapped in generic error
            assert "validation failed" in str(exc_info.value).lower()

    async def test_reject_migration_source_model_not_org_enabled(
        self,
        db_container,
        completion_model_factory,
        admin_user,
    ):
        """Test that migration is rejected when source model is not enabled for organization."""
        async with db_container() as container:
            session = container.session()

            # Create source model with is_org_enabled=False
            disabled_model = await completion_model_factory(
                session,
                "disabled-model",
                provider="openai",
                is_org_enabled=False
            )
            target_model = await completion_model_factory(session, "gpt-4", provider="openai")

            # Act & Assert: Attempt migration from disabled model
            migration_service = container.completion_model_migration_service()
            with pytest.raises(ValidationException) as exc_info:
                await migration_service.migrate_model_usage(
                    from_model_id=disabled_model.id,
                    to_model_id=target_model.id,
                    entity_types=["assistants"],
                    user=admin_user,
                    confirm_migration=True,
                )

            # Verify error message mentions source model not available/enabled
            error_msg = str(exc_info.value).lower()
            assert "source model" in error_msg
            assert ("not available" in error_msg or "not enabled" in error_msg)

    async def test_reject_migration_target_model_not_org_enabled(
        self,
        db_container,
        completion_model_factory,
        admin_user,
    ):
        """Test that migration is rejected when target model is not enabled for organization."""
        async with db_container() as container:
            session = container.session()

            source_model = await completion_model_factory(session, "gpt-3.5-turbo", provider="openai")
            # Create target model with is_org_enabled=False
            disabled_target = await completion_model_factory(
                session,
                "disabled-target",
                provider="openai",
                is_org_enabled=False
            )

            # Act & Assert: Attempt migration to disabled model
            migration_service = container.completion_model_migration_service()
            with pytest.raises(ValidationException) as exc_info:
                await migration_service.migrate_model_usage(
                    from_model_id=source_model.id,
                    to_model_id=disabled_target.id,
                    entity_types=["assistants"],
                    user=admin_user,
                    confirm_migration=True,
                )

            # Verify error message mentions target model not available/enabled
            error_msg = str(exc_info.value).lower()
            assert "target model" in error_msg
            assert ("not available" in error_msg or "not enabled" in error_msg)

    # ============================================================================
    # Compatibility Validation Tests
    # ============================================================================

    async def test_reject_migration_without_confirmation_when_incompatible(
        self,
        db_container,
        completion_model_factory,
        assistant_factory,
        admin_user,
    ):
        """Test that migration is rejected when models have compatibility issues and confirm_migration=False."""
        async with db_container() as container:
            session = container.session()

            # Create models with different families (incompatible)
            source_model = await completion_model_factory(
                session,
                "gpt-4",
                provider="openai",
                family=ModelFamily.OPEN_AI
            )
            target_model = await completion_model_factory(
                session,
                "claude-3-sonnet",
                provider="anthropic",
                family=ModelFamily.CLAUDE
            )

            # Create assistant using source model
            await assistant_factory(session, "Test Assistant", source_model.id)

            # Act & Assert: Attempt migration WITHOUT confirmation
            migration_service = container.completion_model_migration_service()
            with pytest.raises(ValidationException) as exc_info:
                await migration_service.migrate_model_usage(
                    from_model_id=source_model.id,
                    to_model_id=target_model.id,
                    entity_types=["assistants"],
                    user=admin_user,
                    confirm_migration=False,  # Don't confirm - should fail
                )

            # Verify error mentions compatibility issues
            error_msg = str(exc_info.value).lower()
            assert "compatibility" in error_msg
            assert "confirm_migration=true" in error_msg

    async def test_allow_migration_with_confirmation_despite_incompatibility(
        self,
        db_container,
        completion_model_factory,
        assistant_factory,
        admin_user,
    ):
        """Test that migration proceeds when confirm_migration=True despite compatibility warnings."""
        async with db_container() as container:
            session = container.session()

            # Create models with different families (incompatible)
            source_model = await completion_model_factory(
                session,
                "gpt-4",
                provider="openai",
                family=ModelFamily.OPEN_AI
            )
            target_model = await completion_model_factory(
                session,
                "claude-3-sonnet",
                provider="anthropic",
                family=ModelFamily.CLAUDE
            )

            # Create assistant using source model
            assistant = await assistant_factory(session, "Test Assistant", source_model.id)

            # Act: Migrate WITH confirmation despite incompatibility
            migration_service = container.completion_model_migration_service()
            result = await migration_service.migrate_model_usage(
                from_model_id=source_model.id,
                to_model_id=target_model.id,
                entity_types=["assistants"],
                user=admin_user,
                confirm_migration=True,  # Confirm despite warnings
            )

            # Assert: Migration should succeed but with warnings
            assert result.success is True
            assert result.migrated_count == 1
            assert result.warnings is not None
            assert len(result.warnings) > 0

            # Verify assistant was migrated
            stmt = select(Assistants).where(Assistants.id == assistant.id)
            updated_assistant = (await session.execute(stmt)).scalar_one()
            assert updated_assistant.completion_model_id == target_model.id

    async def test_warn_about_different_model_families(
        self,
        db_container,
        completion_model_factory,
        admin_user,
    ):
        """Test that migration warns when migrating between different model families."""
        async with db_container() as container:
            session = container.session()

            # Create models from different families
            openai_model = await completion_model_factory(
                session,
                "gpt-4",
                provider="openai",
                family=ModelFamily.OPEN_AI
            )
            claude_model = await completion_model_factory(
                session,
                "claude-3",
                provider="anthropic",
                family=ModelFamily.CLAUDE
            )

            # Act: Migrate with confirmation
            migration_service = container.completion_model_migration_service()
            result = await migration_service.migrate_model_usage(
                from_model_id=openai_model.id,
                to_model_id=claude_model.id,
                entity_types=["assistants"],
                user=admin_user,
                confirm_migration=True,
            )

            # Assert: Should have warning about different families
            assert result.warnings is not None
            family_warning = any("family" in w.lower() for w in result.warnings)
            assert family_warning, "Should warn about different model families"

    async def test_warn_about_vision_capability_loss(
        self,
        db_container,
        completion_model_factory,
        admin_user,
    ):
        """Test that migration warns when target model lacks vision capability."""
        async with db_container() as container:
            session = container.session()

            # Create source model WITH vision
            source_model = await completion_model_factory(
                session,
                "gpt-4-vision",
                provider="openai",
                vision=True
            )
            # Create target model WITHOUT vision
            target_model = await completion_model_factory(
                session,
                "gpt-3.5-turbo",
                provider="openai",
                vision=False
            )

            # Act: Migrate with confirmation
            migration_service = container.completion_model_migration_service()
            result = await migration_service.migrate_model_usage(
                from_model_id=source_model.id,
                to_model_id=target_model.id,
                entity_types=["assistants"],
                user=admin_user,
                confirm_migration=True,
            )

            # Assert: Should have warning about vision support
            assert result.warnings is not None
            vision_warning = any("vision" in w.lower() for w in result.warnings)
            assert vision_warning, "Should warn about loss of vision capability"

    async def test_warn_about_reasoning_capability_loss(
        self,
        db_container,
        completion_model_factory,
        admin_user,
    ):
        """Test that migration warns when target model lacks reasoning capability."""
        async with db_container() as container:
            session = container.session()

            # Create source model WITH reasoning
            source_model = await completion_model_factory(
                session,
                "gpt-4o-reasoning",
                provider="openai",
                reasoning=True
            )
            # Create target model WITHOUT reasoning
            target_model = await completion_model_factory(
                session,
                "gpt-4",
                provider="openai",
                reasoning=False
            )

            # Act: Migrate with confirmation
            migration_service = container.completion_model_migration_service()
            result = await migration_service.migrate_model_usage(
                from_model_id=source_model.id,
                to_model_id=target_model.id,
                entity_types=["assistants"],
                user=admin_user,
                confirm_migration=True,
            )

            # Assert: Should have warning about reasoning support
            assert result.warnings is not None
            reasoning_warning = any("reasoning" in w.lower() for w in result.warnings)
            assert reasoning_warning, "Should warn about loss of reasoning capability"

    async def test_warn_about_token_limit_reduction(
        self,
        db_container,
        completion_model_factory,
        admin_user,
    ):
        """Test that migration warns when target model has lower token limit."""
        async with db_container() as container:
            session = container.session()

            # Create source model with high token limit
            source_model = await completion_model_factory(
                session,
                "gpt-4-turbo",
                provider="openai",
                token_limit=128000
            )
            # Create target model with lower token limit
            target_model = await completion_model_factory(
                session,
                "gpt-3.5-turbo",
                provider="openai",
                token_limit=4096
            )

            # Act: Migrate with confirmation
            migration_service = container.completion_model_migration_service()
            result = await migration_service.migrate_model_usage(
                from_model_id=source_model.id,
                to_model_id=target_model.id,
                entity_types=["assistants"],
                user=admin_user,
                confirm_migration=True,
            )

            # Assert: Should have warning about token limit
            assert result.warnings is not None
            token_warning = any("token limit" in w.lower() for w in result.warnings)
            assert token_warning, "Should warn about lower token limit"

    async def test_warn_about_deprecated_target_model(
        self,
        db_container,
        completion_model_factory,
        admin_user,
    ):
        """Test that migration warns when target model is deprecated."""
        async with db_container() as container:
            session = container.session()

            source_model = await completion_model_factory(
                session,
                "gpt-4",
                provider="openai",
                is_deprecated=False
            )
            # Create deprecated target model
            deprecated_model = await completion_model_factory(
                session,
                "gpt-3.5-turbo-0301",
                provider="openai",
                is_deprecated=True
            )

            # Act: Migrate with confirmation
            migration_service = container.completion_model_migration_service()
            result = await migration_service.migrate_model_usage(
                from_model_id=source_model.id,
                to_model_id=deprecated_model.id,
                entity_types=["assistants"],
                user=admin_user,
                confirm_migration=True,
            )

            # Assert: Should have warning about deprecated model
            assert result.warnings is not None
            deprecated_warning = any("deprecated" in w.lower() for w in result.warnings)
            assert deprecated_warning, "Should warn about deprecated target model"

    # ============================================================================
    # Edge Case Tests
    # ============================================================================

    async def test_reject_invalid_entity_type(
        self,
        db_container,
        completion_model_factory,
        admin_user,
    ):
        """Test that migration rejects invalid entity types."""
        async with db_container() as container:
            session = container.session()

            source_model = await completion_model_factory(session, "gpt-3.5-turbo", provider="openai")
            target_model = await completion_model_factory(session, "gpt-4", provider="openai")

            # Act & Assert: Attempt migration with invalid entity type
            migration_service = container.completion_model_migration_service()
            with pytest.raises(ValidationException) as exc_info:
                await migration_service.migrate_model_usage(
                    from_model_id=source_model.id,
                    to_model_id=target_model.id,
                    entity_types=["invalid_entity_type", "assistants"],
                    user=admin_user,
                    confirm_migration=True,
                )

            # Verify error mentions invalid entity types
            assert "invalid entity type" in str(exc_info.value).lower()

    async def test_accept_entity_types_as_string(
        self,
        db_container,
        completion_model_factory,
        assistant_factory,
        admin_user,
    ):
        """Test that migration accepts entity_types as a string (backwards compatibility)."""
        async with db_container() as container:
            session = container.session()

            source_model = await completion_model_factory(session, "gpt-3.5-turbo", provider="openai")
            target_model = await completion_model_factory(session, "gpt-4", provider="openai")
            await assistant_factory(session, "Test Assistant", source_model.id)

            # Act: Pass entity_types as string instead of list
            migration_service = container.completion_model_migration_service()
            result = await migration_service.migrate_model_usage(
                from_model_id=source_model.id,
                to_model_id=target_model.id,
                entity_types="assistants",  # String instead of list
                user=admin_user,
                confirm_migration=True,
            )

            # Assert: Should still work (string converted to list)
            assert result.success is True
            assert result.migrated_count == 1

    async def test_migrate_with_no_entities_to_migrate(
        self,
        db_container,
        completion_model_factory,
        admin_user,
    ):
        """Test migration when no entities use the source model (edge case)."""
        async with db_container() as container:
            session = container.session()

            source_model = await completion_model_factory(session, "gpt-3.5-turbo", provider="openai")
            target_model = await completion_model_factory(session, "gpt-4", provider="openai")

            # Don't create any entities using source_model

            # Act: Migrate (should succeed but with 0 count)
            migration_service = container.completion_model_migration_service()
            result = await migration_service.migrate_model_usage(
                from_model_id=source_model.id,
                to_model_id=target_model.id,
                entity_types=["assistants", "apps", "services", "spaces"],
                user=admin_user,
                confirm_migration=True,
            )

            # Assert: Should succeed with 0 migrated
            assert result.success is True
            assert result.migrated_count == 0
            assert result.failed_count == 0

    async def test_migrate_all_entity_types_when_none_specified(
        self,
        db_container,
        completion_model_factory,
        assistant_factory,
        app_factory,
        admin_user,
    ):
        """Test that migration defaults to all entity types when entity_types is None."""
        async with db_container() as container:
            session = container.session()

            source_model = await completion_model_factory(session, "gpt-3.5-turbo", provider="openai")
            target_model = await completion_model_factory(session, "gpt-4", provider="openai")

            # Create entities of different types
            await assistant_factory(session, "Test Assistant", source_model.id)
            await app_factory(session, "Test App", source_model.id)

            # Act: Migrate with entity_types=None (should default to all types)
            migration_service = container.completion_model_migration_service()
            result = await migration_service.migrate_model_usage(
                from_model_id=source_model.id,
                to_model_id=target_model.id,
                entity_types=None,  # Should default to all entity types
                user=admin_user,
                confirm_migration=True,
            )

            # Assert: Should migrate all entity types
            assert result.success is True
            assert result.migrated_count == 2  # 1 assistant + 1 app
            # Verify both entity types were migrated
            assert "assistants" in result.details
            assert "apps" in result.details


