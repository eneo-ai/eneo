"""
Integration tests for the model migration lifecycle.

These tests verify end-to-end that:
1. Questions are NOT migrated — their completion_model_id stays unchanged
2. The source model is marked with migrated_to_model_id after migration
3. Soft-deleted models are hidden from listings but preserved in DB
4. The RESTRICT FK on questions prevents hard-delete of referenced models
5. Already-migrated models are rejected for re-migration
6. Lifecycle cleanup removes migrated or soft-deleted models only when safe
7. Migration history remains readable after cleanup via tenant/migration history
"""

from datetime import datetime

import pytest
from sqlalchemy import select, delete

from intric.completion_models.infrastructure.model_cleanup_worker import (
    cleanup_orphaned_models,
)
from intric.database.tables.app_template_table import AppTemplates
from intric.database.tables.ai_models_table import CompletionModels
from intric.database.tables.completion_model_migration_history_table import (
    CompletionModelMigrationHistory,
)
from intric.database.tables.questions_table import Questions
from intric.database.tables.sessions_table import Sessions
from intric.database.tables.assistant_template_table import AssistantTemplates
from intric.main.exceptions import ValidationException


@pytest.mark.integration
@pytest.mark.asyncio
class TestQuestionsNotMigrated:
    """Core invariant: questions must keep their original completion_model_id."""

    async def test_migration_does_not_touch_questions(
        self,
        db_container,
        completion_model_factory,
        assistant_factory,
        admin_user,
    ):
        """
        Create a question referencing model A, migrate A → B.
        Verify the question still points to A.
        """
        async with db_container() as container:
            session = container.session()

            old_model = await completion_model_factory(session, "gpt-3.5-turbo", provider="openai")
            new_model = await completion_model_factory(session, "gpt-4", provider="openai")

            # Create an assistant and a session for the question
            assistant = await assistant_factory(session, "Test Assistant", old_model.id)

            test_session = Sessions(
                name="Test Session",
                user_id=admin_user.id,
                assistant_id=assistant.id,
            )
            session.add(test_session)
            await session.flush()

            # Create a question referencing old_model
            question = Questions(
                question="What is the meaning of life?",
                answer="42",
                num_tokens_question=10,
                num_tokens_answer=5,
                tenant_id=admin_user.tenant_id,
                assistant_id=assistant.id,
                session_id=test_session.id,
                completion_model_id=old_model.id,
            )
            session.add(question)
            await session.flush()
            question_id = question.id

            # Migrate all entity types (including the default which now
            # excludes questions)
            migration_service = container.completion_model_migration_service()
            result = await migration_service.migrate_model_usage(
                from_model_id=old_model.id,
                to_model_id=new_model.id,
                user=admin_user,
                confirm_migration=True,
            )

            assert result.success is True
            # Questions should NOT appear in migration details
            assert "questions" not in result.details

            # Verify: question still points to old_model
            stmt = select(Questions).where(Questions.id == question_id)
            updated_question = (await session.execute(stmt)).scalar_one()
            assert updated_question.completion_model_id == old_model.id, (
                "Question must retain its original completion_model_id after migration"
            )


@pytest.mark.integration
@pytest.mark.asyncio
class TestSourceModelMarkedAsMigrated:
    """After migration, the source model must have migrated_to_model_id set."""

    async def test_source_model_gets_migrated_to_model_id(
        self,
        db_container,
        completion_model_factory,
        assistant_factory,
        admin_user,
    ):
        async with db_container() as container:
            session = container.session()

            old_model = await completion_model_factory(session, "gpt-3.5-turbo", provider="openai")
            new_model = await completion_model_factory(session, "gpt-4", provider="openai")

            await assistant_factory(session, "Test Assistant", old_model.id)

            migration_service = container.completion_model_migration_service()
            result = await migration_service.migrate_model_usage(
                from_model_id=old_model.id,
                to_model_id=new_model.id,
                user=admin_user,
                confirm_migration=True,
            )

            assert result.success is True

            # Verify source model is marked
            stmt = select(CompletionModels).where(CompletionModels.id == old_model.id)
            source = (await session.execute(stmt)).scalar_one()
            assert source.migrated_to_model_id == new_model.id

    async def test_already_migrated_model_rejected(
        self,
        db_container,
        completion_model_factory,
        admin_user,
    ):
        """A model that has already been migrated cannot be migrated again."""
        async with db_container() as container:
            session = container.session()

            model_a = await completion_model_factory(session, "gpt-3.5-turbo", provider="openai")
            model_b = await completion_model_factory(session, "gpt-4", provider="openai")
            model_c = await completion_model_factory(session, "gpt-4o", provider="openai")

            # Migrate A → B
            migration_service = container.completion_model_migration_service()
            result = await migration_service.migrate_model_usage(
                from_model_id=model_a.id,
                to_model_id=model_b.id,
                user=admin_user,
                confirm_migration=True,
            )
            assert result.success is True

            # Try to migrate A → C — should fail
            with pytest.raises(ValidationException) as exc_info:
                await migration_service.migrate_model_usage(
                    from_model_id=model_a.id,
                    to_model_id=model_c.id,
                    user=admin_user,
                    confirm_migration=True,
                )

            assert "already been migrated" in str(exc_info.value)

    async def test_preflight_validation_catches_already_migrated(
        self,
        db_container,
        completion_model_factory,
        admin_user,
    ):
        """validate_migration() must also catch already-migrated models."""
        async with db_container() as container:
            session = container.session()

            model_a = await completion_model_factory(session, "gpt-3.5-turbo", provider="openai")
            model_b = await completion_model_factory(session, "gpt-4", provider="openai")
            model_c = await completion_model_factory(session, "gpt-4o", provider="openai")

            # Migrate A → B
            migration_service = container.completion_model_migration_service()
            await migration_service.migrate_model_usage(
                from_model_id=model_a.id,
                to_model_id=model_b.id,
                user=admin_user,
                confirm_migration=True,
            )

            # Preflight A → C — should fail
            with pytest.raises(ValidationException) as exc_info:
                await migration_service.validate_migration(
                    model_a.id, model_c.id, admin_user.tenant_id
                )

            assert "already been migrated" in str(exc_info.value)


@pytest.mark.integration
@pytest.mark.asyncio
class TestSoftDelete:
    """Soft-deleted models are hidden from listings but preserved in DB."""

    async def test_soft_deleted_model_hidden_from_repo_listing(
        self,
        db_container,
        completion_model_factory,
        admin_user,
    ):
        async with db_container() as container:
            session = container.session()

            model = await completion_model_factory(session, "gpt-to-delete", provider="openai")
            model_id = model.id

            # Soft-delete
            from datetime import datetime
            model.deleted_at = datetime.utcnow()
            await session.flush()

            # Verify hidden from domain repo
            repo = container.completion_model_repo2()
            all_models = await repo.all(with_deprecated=True)
            model_ids = [m.id for m in all_models]
            assert model_id not in model_ids

            # Verify still exists in DB
            stmt = select(CompletionModels).where(CompletionModels.id == model_id)
            db_model = (await session.execute(stmt)).scalar_one_or_none()
            assert db_model is not None
            assert db_model.deleted_at is not None


@pytest.mark.integration
@pytest.mark.asyncio
class TestRestrictForeignKey:
    """RESTRICT FK prevents hard-delete of models referenced by questions."""

    async def test_cannot_hard_delete_model_with_questions(
        self,
        db_container,
        completion_model_factory,
        assistant_factory,
        admin_user,
    ):
        """
        The RESTRICT FK on questions.completion_model_id must prevent
        hard-delete of a model that has question references.
        """
        async with db_container() as container:
            session = container.session()

            model = await completion_model_factory(session, "gpt-referenced", provider="openai")
            assistant = await assistant_factory(session, "Test", model.id)

            test_session = Sessions(
                name="Test Session",
                user_id=admin_user.id,
                assistant_id=assistant.id,
            )
            session.add(test_session)
            await session.flush()

            question = Questions(
                question="Test",
                answer="Test",
                num_tokens_question=1,
                num_tokens_answer=1,
                tenant_id=admin_user.tenant_id,
                assistant_id=assistant.id,
                session_id=test_session.id,
                completion_model_id=model.id,
            )
            session.add(question)
            await session.flush()

            # Attempt hard-delete — should fail due to RESTRICT FK
            from sqlalchemy.exc import IntegrityError

            with pytest.raises(IntegrityError):
                await session.execute(
                    delete(CompletionModels).where(CompletionModels.id == model.id)
                )
                await session.flush()


@pytest.mark.integration
@pytest.mark.asyncio
class TestLifecycleCleanup:
    """Lifecycle cleanup should delete models only after all references are gone."""

    async def test_cleanup_removes_migrated_source_without_soft_delete(
        self,
        db_container,
        completion_model_factory,
        assistant_factory,
        admin_user,
    ):
        old_model_id = None

        async with db_container() as container:
            session = container.session()

            old_model = await completion_model_factory(session, "gpt-cleanup-old", provider="openai")
            new_model = await completion_model_factory(session, "gpt-cleanup-new", provider="openai")
            await assistant_factory(session, "Cleanup Assistant", old_model.id)

            migration_service = container.completion_model_migration_service()
            result = await migration_service.migrate_model_usage(
                from_model_id=old_model.id,
                to_model_id=new_model.id,
                user=admin_user,
                confirm_migration=True,
            )
            assert result.success is True
            old_model_id = old_model.id

        async with db_container() as container:
            cleanup_result = await cleanup_orphaned_models(container)
            session = container.session()

            assert any(
                model["id"] == str(old_model_id)
                for model in cleanup_result["removed_models"]
            )

            stmt = select(CompletionModels).where(CompletionModels.id == old_model_id)
            assert (await session.execute(stmt)).scalar_one_or_none() is None

    async def test_cleanup_keeps_migrated_source_while_questions_exist(
        self,
        db_container,
        completion_model_factory,
        assistant_factory,
        admin_user,
    ):
        old_model_id = None

        async with db_container() as container:
            session = container.session()

            old_model = await completion_model_factory(session, "gpt-history-old", provider="openai")
            new_model = await completion_model_factory(session, "gpt-history-new", provider="openai")

            assistant = await assistant_factory(session, "History Assistant", old_model.id)
            test_session = Sessions(
                name="History Session",
                user_id=admin_user.id,
                assistant_id=assistant.id,
            )
            session.add(test_session)
            await session.flush()

            session.add(
                Questions(
                    question="Keep historical attribution",
                    answer="Still on old model",
                    num_tokens_question=10,
                    num_tokens_answer=5,
                    tenant_id=admin_user.tenant_id,
                    assistant_id=assistant.id,
                    session_id=test_session.id,
                    completion_model_id=old_model.id,
                )
            )
            await session.flush()

            migration_service = container.completion_model_migration_service()
            result = await migration_service.migrate_model_usage(
                from_model_id=old_model.id,
                to_model_id=new_model.id,
                user=admin_user,
                confirm_migration=True,
            )
            assert result.success is True
            old_model_id = old_model.id

        async with db_container() as container:
            cleanup_result = await cleanup_orphaned_models(container)
            session = container.session()

            assert all(
                model["id"] != str(old_model_id)
                for model in cleanup_result["removed_models"]
            )

            stmt = select(CompletionModels).where(CompletionModels.id == old_model_id)
            assert (await session.execute(stmt)).scalar_one_or_none() is not None

    async def test_active_template_blocks_cleanup(
        self,
        db_container,
        completion_model_factory,
        admin_user,
    ):
        model_id = None

        async with db_container() as container:
            session = container.session()
            model = await completion_model_factory(session, "gpt-template-active", provider="openai")
            model.deleted_at = datetime.utcnow()

            session.add(
                AssistantTemplates(
                    name="Template keeps model alive",
                    description="active template",
                    category="general",
                    prompt_text=None,
                    completion_model_kwargs=None,
                    wizard=None,
                    tenant_id=admin_user.tenant_id,
                    completion_model_id=model.id,
                )
            )
            await session.flush()
            model_id = model.id

        async with db_container() as container:
            cleanup_result = await cleanup_orphaned_models(container)
            session = container.session()

            assert any(
                model["id"] == str(model_id) and model["reason"] == "active_references"
                for model in cleanup_result["skipped_models"]
            )

            stmt = select(CompletionModels).where(CompletionModels.id == model_id)
            assert (await session.execute(stmt)).scalar_one_or_none() is not None

    async def test_soft_deleted_template_does_not_block_cleanup(
        self,
        db_container,
        completion_model_factory,
        admin_user,
    ):
        model_id = None

        async with db_container() as container:
            session = container.session()
            model = await completion_model_factory(session, "gpt-template-soft-deleted", provider="openai")
            model.deleted_at = datetime.utcnow()

            session.add(
                AppTemplates(
                    name="Soft-deleted app template",
                    description="deleted template",
                    category="general",
                    prompt_text=None,
                    input_description=None,
                    input_type="text",
                    completion_model_kwargs=None,
                    wizard=None,
                    tenant_id=admin_user.tenant_id,
                    completion_model_id=model.id,
                    deleted_at=datetime.utcnow(),
                )
            )
            await session.flush()
            model_id = model.id

        async with db_container() as container:
            cleanup_result = await cleanup_orphaned_models(container)
            session = container.session()

            assert any(
                model["id"] == str(model_id)
                for model in cleanup_result["removed_models"]
            )

            stmt = select(CompletionModels).where(CompletionModels.id == model_id)
            assert (await session.execute(stmt)).scalar_one_or_none() is None

    async def test_migration_history_record_survives_cleanup_via_migration_id(
        self,
        db_container,
        completion_model_factory,
        assistant_factory,
        admin_user,
    ):
        old_model_id = None
        new_model_id = None
        old_model_name = None
        migration_id = None

        async with db_container() as container:
            session = container.session()

            old_model = await completion_model_factory(session, "gpt-history-query-old", provider="openai")
            new_model = await completion_model_factory(session, "gpt-history-query-new", provider="openai")
            await assistant_factory(session, "History Query Assistant", old_model.id)

            migration_service = container.completion_model_migration_service()
            result = await migration_service.migrate_model_usage(
                from_model_id=old_model.id,
                to_model_id=new_model.id,
                user=admin_user,
                confirm_migration=True,
            )
            assert result.success is True

            old_model_id = old_model.id
            new_model_id = new_model.id
            old_model_name = old_model.name
            migration_id = result.migration_id

        async with db_container() as container:
            cleanup_result = await cleanup_orphaned_models(container)
            assert any(
                model["id"] == str(old_model_id)
                for model in cleanup_result["removed_models"]
            )

        async with db_container() as container:
            session = container.session()
            history_service = container.completion_model_migration_history_service()

            by_id = await history_service.get_migration_history_by_id(
                migration_id, admin_user.tenant_id
            )
            count = await history_service.count_migration_history_for_model(
                old_model_id, admin_user.tenant_id
            )

            assert count == 0
            assert by_id is not None
            assert by_id.from_model_id is None
            assert by_id.to_model_id == new_model_id
            assert by_id.from_model_name == old_model_name

            stmt = select(CompletionModelMigrationHistory).where(
                CompletionModelMigrationHistory.migration_id == migration_id
            )
            record = (await session.execute(stmt)).scalar_one()
            assert record.from_model_name == old_model_name
            assert record.from_provider_type == "openai"
