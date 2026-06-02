"""
Integration tests for TranscriptionModelMigrationService.

Transcription migration is the simplest case of the shared migration engine: it
only repoints references (`apps.transcription_model_id` and the
`spaces_transcription_models` many-to-many) and marks the source migrated — no
re-indexing, no kwargs reset, no usage-stats recalculation.

These tests lock in:
- apps repoint
- spaces many-to-many repoint
- source marked migrated (migrated_to_model_id)
- already-migrated and same-model rejections
"""

import pytest
from sqlalchemy import select

from intric.database.tables.ai_models_table import TranscriptionModels
from intric.database.tables.app_table import Apps
from intric.database.tables.spaces_table import SpacesTranscriptionModels
from intric.main.exceptions import ValidationException


@pytest.mark.integration
@pytest.mark.asyncio
class TestTranscriptionModelMigration:
    """End-to-end tests for transcription model migration."""

    async def test_migrate_apps_successfully(
        self,
        db_container,
        transcription_model_factory,
        app_factory,
        admin_user,
    ):
        async with db_container() as container:
            session = container.session()

            old_model = await transcription_model_factory(session, "whisper-old")
            new_model = await transcription_model_factory(session, "whisper-new")

            # App referencing the source transcription model (completion model
            # left null — both FKs are nullable).
            app = await app_factory(
                session, "Transcribe App", None, transcription_model_id=old_model.id
            )

            migration_service = container.transcription_model_migration_service()
            result = await migration_service.migrate_model_usage(
                from_model_id=old_model.id,
                to_model_id=new_model.id,
                entity_types=["apps"],
                user=admin_user,
                confirm_migration=True,
            )

            assert result.success is True
            assert result.migrated_count == 1
            assert result.details["apps"] == 1

            updated_app = (
                await session.execute(select(Apps).where(Apps.id == app.id))
            ).scalar_one()
            assert updated_app.transcription_model_id == new_model.id

            # The source has no remaining apps/spaces, so even an apps-only API
            # call has completed the source migration and can latch it.
            src = (
                await session.execute(
                    select(TranscriptionModels).where(
                        TranscriptionModels.id == old_model.id
                    )
                )
            ).scalar_one()
            assert src.migrated_to_model_id == new_model.id

    async def test_partial_migrations_latch_after_last_remaining_surface(
        self,
        db_container,
        transcription_model_factory,
        app_factory,
        space_factory,
        admin_user,
    ):
        async with db_container() as container:
            session = container.session()

            old_model = await transcription_model_factory(session, "whisper-old")
            new_model = await transcription_model_factory(session, "whisper-new")

            await app_factory(
                session, "Transcribe App", None, transcription_model_id=old_model.id
            )
            space = await space_factory(session, "Transcription Space")
            session.add(
                SpacesTranscriptionModels(
                    space_id=space.id, transcription_model_id=old_model.id
                )
            )
            await session.flush()

            migration_service = container.transcription_model_migration_service()
            await migration_service.migrate_model_usage(
                from_model_id=old_model.id,
                to_model_id=new_model.id,
                entity_types=["apps"],
                user=admin_user,
                confirm_migration=True,
            )

            src = (
                await session.execute(
                    select(TranscriptionModels).where(
                        TranscriptionModels.id == old_model.id
                    )
                )
            ).scalar_one()
            assert src.migrated_to_model_id is None

            result = await migration_service.migrate_model_usage(
                from_model_id=old_model.id,
                to_model_id=new_model.id,
                entity_types=["spaces"],
                user=admin_user,
                confirm_migration=True,
            )

            assert result.success is True
            assert result.details["spaces"] == 1
            await session.refresh(src)
            assert src.migrated_to_model_id == new_model.id

    async def test_partial_migrations_reject_split_targets(
        self,
        db_container,
        transcription_model_factory,
        app_factory,
        space_factory,
        admin_user,
    ):
        async with db_container() as container:
            session = container.session()

            old_model = await transcription_model_factory(session, "whisper-old")
            first_target = await transcription_model_factory(session, "whisper-new-a")
            second_target = await transcription_model_factory(session, "whisper-new-b")

            await app_factory(
                session, "Transcribe App", None, transcription_model_id=old_model.id
            )
            space = await space_factory(session, "Transcription Space")
            session.add(
                SpacesTranscriptionModels(
                    space_id=space.id, transcription_model_id=old_model.id
                )
            )
            await session.flush()

            migration_service = container.transcription_model_migration_service()
            await migration_service.migrate_model_usage(
                from_model_id=old_model.id,
                to_model_id=first_target.id,
                entity_types=["apps"],
                user=admin_user,
                confirm_migration=True,
            )

            with pytest.raises(ValidationException):
                await migration_service.migrate_model_usage(
                    from_model_id=old_model.id,
                    to_model_id=second_target.id,
                    entity_types=["spaces"],
                    user=admin_user,
                    confirm_migration=True,
                )

    async def test_migrate_spaces_successfully(
        self,
        db_container,
        transcription_model_factory,
        space_factory,
        admin_user,
    ):
        async with db_container() as container:
            session = container.session()

            old_model = await transcription_model_factory(session, "whisper-old")
            new_model = await transcription_model_factory(session, "whisper-new")

            space = await space_factory(session, "Transcription Space")
            session.add(
                SpacesTranscriptionModels(
                    space_id=space.id, transcription_model_id=old_model.id
                )
            )
            await session.flush()

            migration_service = container.transcription_model_migration_service()
            result = await migration_service.migrate_model_usage(
                from_model_id=old_model.id,
                to_model_id=new_model.id,
                entity_types=["spaces"],
                user=admin_user,
                confirm_migration=True,
            )

            assert result.success is True
            assert result.details["spaces"] == 1

            # Space now references the new model, not the old one.
            links = (
                (
                    await session.execute(
                        select(SpacesTranscriptionModels.transcription_model_id).where(
                            SpacesTranscriptionModels.space_id == space.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert new_model.id in links
            assert old_model.id not in links

    async def test_source_marked_and_double_migration_rejected(
        self,
        db_container,
        transcription_model_factory,
        admin_user,
    ):
        async with db_container() as container:
            session = container.session()

            old_model = await transcription_model_factory(session, "whisper-old")
            new_model = await transcription_model_factory(session, "whisper-new")

            migration_service = container.transcription_model_migration_service()
            # No apps/spaces — still marks the source migrated.
            await migration_service.migrate_model_usage(
                from_model_id=old_model.id,
                to_model_id=new_model.id,
                user=admin_user,
                confirm_migration=True,
            )

            src = (
                await session.execute(
                    select(TranscriptionModels).where(
                        TranscriptionModels.id == old_model.id
                    )
                )
            ).scalar_one()
            assert src.migrated_to_model_id == new_model.id

            # Migrating an already-migrated source must be rejected.
            with pytest.raises(ValidationException):
                await migration_service.migrate_model_usage(
                    from_model_id=old_model.id,
                    to_model_id=new_model.id,
                    user=admin_user,
                    confirm_migration=True,
                )

    async def test_same_model_rejected(
        self,
        db_container,
        transcription_model_factory,
        admin_user,
    ):
        async with db_container() as container:
            session = container.session()

            model = await transcription_model_factory(session, "whisper-x")

            migration_service = container.transcription_model_migration_service()
            with pytest.raises(ValidationException):
                await migration_service.migrate_model_usage(
                    from_model_id=model.id,
                    to_model_id=model.id,
                    user=admin_user,
                    confirm_migration=True,
                )
