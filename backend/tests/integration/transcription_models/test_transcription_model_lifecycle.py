"""Integration tests for the transcription model lifecycle.

Covers the soft-delete parity added in the model-table alignment:
- tenant delete soft-deletes (keeps the row as a tombstone) and hides it from
  read paths, instead of hard-deleting and silently orphaning apps
- deletion is blocked while an app still references the model
- the weekly cleanup worker hard-deletes tombstones only once nothing references
  them (and never the target a migration points to)
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from intric.database.tables.ai_models_table import TranscriptionModels
from intric.database.tables.transcription_model_migration_history_table import (
    TranscriptionModelMigrationHistory,
)
from intric.main.exceptions import ModelInUseException, NotFoundException
from intric.tenant_models.application.tenant_model_service import (
    TenantTranscriptionModelService,
)
from intric.transcription_models.domain.transcription_model_repo import (
    TranscriptionModelRepository,
)
from intric.transcription_models.infrastructure.transcription_model_cleanup_worker import (  # noqa: E501
    cleanup_orphaned_transcription_models,
)
from intric.transcription_models.presentation.tenant_transcription_models_router import (
    TenantTranscriptionModelUpdate,
)


@pytest.mark.integration
@pytest.mark.asyncio
class TestTranscriptionModelSoftDelete:
    async def test_delete_soft_deletes_and_hides_from_reads(
        self, db_container, transcription_model_factory, admin_user
    ):
        async with db_container() as container:
            session = container.session()
            model = await transcription_model_factory(session, "whisper-del")
            model_id = model.id

            service = TenantTranscriptionModelService(session=session, user=admin_user)
            await service.delete(model_id)

            # Row is kept as a tombstone with deleted_at set.
            row = (
                await session.execute(
                    select(TranscriptionModels).where(
                        TranscriptionModels.id == model_id
                    )
                )
            ).scalar_one()
            assert row.deleted_at is not None

            # Read paths no longer surface it.
            repo = TranscriptionModelRepository(session, admin_user)
            assert all(m.id != model_id for m in await repo.all())
            assert await repo.one_or_none(model_id) is None

    async def test_delete_blocked_while_app_references_model(
        self, db_container, transcription_model_factory, app_factory, admin_user
    ):
        async with db_container() as container:
            session = container.session()
            model = await transcription_model_factory(session, "whisper-used")
            model_id = model.id
            await app_factory(
                session, "Transcribe App", None, transcription_model_id=model_id
            )

            service = TenantTranscriptionModelService(session=session, user=admin_user)
            with pytest.raises(ModelInUseException):
                await service.delete(model_id)

            # The model is untouched — not soft-deleted, app not orphaned.
            row = (
                await session.execute(
                    select(TranscriptionModels).where(
                        TranscriptionModels.id == model_id
                    )
                )
            ).scalar_one()
            assert row.deleted_at is None

    async def test_update_rejects_soft_deleted_model(
        self, db_container, transcription_model_factory, admin_user
    ):
        async with db_container() as container:
            session = container.session()
            model = await transcription_model_factory(session, "whisper-update-deleted")
            model.deleted_at = datetime.now(timezone.utc)
            await session.flush()

            service = TenantTranscriptionModelService(session=session, user=admin_user)
            with pytest.raises(NotFoundException):
                await service.update(
                    model.id,
                    TenantTranscriptionModelUpdate(description="should not update"),
                )


@pytest.mark.integration
@pytest.mark.asyncio
class TestTranscriptionModelCleanupWorker:
    async def test_cleanup_removes_soft_deleted_without_references(
        self, db_container, transcription_model_factory, admin_user
    ):
        async with db_container() as container:
            session = container.session()
            model = await transcription_model_factory(session, "whisper-tomb")
            model_id = model.id
            service = TenantTranscriptionModelService(session=session, user=admin_user)
            await service.delete(model_id)

        async with db_container() as container:
            result = await cleanup_orphaned_transcription_models(container)
            session = container.session()

            assert str(model_id) in [m["id"] for m in result["removed_models"]]
            assert (
                await session.execute(
                    select(TranscriptionModels).where(
                        TranscriptionModels.id == model_id
                    )
                )
            ).scalar_one_or_none() is None

    async def test_cleanup_removes_migrated_source_keeps_target(
        self, db_container, transcription_model_factory, admin_user
    ):
        async with db_container() as container:
            session = container.session()
            old_model = await transcription_model_factory(session, "whisper-old")
            new_model = await transcription_model_factory(session, "whisper-new")
            old_id, new_id = old_model.id, new_model.id

            migration_service = container.transcription_model_migration_service()
            await migration_service.migrate_model_usage(
                from_model_id=old_id,
                to_model_id=new_id,
                user=admin_user,
                confirm_migration=True,
            )

        async with db_container() as container:
            await cleanup_orphaned_transcription_models(container)
            session = container.session()

            # Migrated source is gone; the target it points to is preserved
            # (excluded from candidacy by the incoming-reference check).
            assert (
                await session.execute(
                    select(TranscriptionModels).where(TranscriptionModels.id == old_id)
                )
            ).scalar_one_or_none() is None
            assert (
                await session.execute(
                    select(TranscriptionModels).where(TranscriptionModels.id == new_id)
                )
            ).scalar_one_or_none() is not None

    async def test_cleanup_skips_tombstone_with_app_reference(
        self, db_container, transcription_model_factory, app_factory, admin_user
    ):
        # A tombstone that still carries an app reference (constructed directly to
        # bypass the service's in-use guard) must be left alone by the worker.
        async with db_container() as container:
            session = container.session()
            model = await transcription_model_factory(session, "whisper-stuck")
            model_id = model.id
            await app_factory(
                session, "Stuck App", None, transcription_model_id=model_id
            )
            model.deleted_at = datetime.now(timezone.utc)
            await session.flush()

        async with db_container() as container:
            result = await cleanup_orphaned_transcription_models(container)
            session = container.session()

            assert str(model_id) in [m["id"] for m in result["skipped_models"]]
            assert (
                await session.execute(
                    select(TranscriptionModels).where(
                        TranscriptionModels.id == model_id
                    )
                )
            ).scalar_one_or_none() is not None

    async def test_cleanup_protects_migration_target_that_is_itself_a_tombstone(
        self, db_container, transcription_model_factory, admin_user
    ):
        # The crux of the incoming-reference guard: a migration TARGET that is
        # *also* a tombstone (soft-deleted) must NOT be hard-deleted while a
        # source still points at it via migrated_to_model_id (the self-FK is
        # RESTRICT). The source is removed; the target survives this pass and
        # only becomes eligible once the source is gone.
        async with db_container() as container:
            session = container.session()
            source = await transcription_model_factory(session, "whisper-src")
            target = await transcription_model_factory(session, "whisper-tgt")
            source_id, target_id = source.id, target.id

            migration_service = container.transcription_model_migration_service()
            await migration_service.migrate_model_usage(
                from_model_id=source_id,
                to_model_id=target_id,
                user=admin_user,
                confirm_migration=True,
            )
            # Soft-delete the target *after* migration, so it is a lifecycle
            # candidate but still referenced by the migrated source.
            target_row = (
                await session.execute(
                    select(TranscriptionModels).where(
                        TranscriptionModels.id == target_id
                    )
                )
            ).scalar_one()
            target_row.deleted_at = datetime.now(timezone.utc)
            await session.flush()

        async with db_container() as container:
            result = await cleanup_orphaned_transcription_models(container)
            session = container.session()

            removed = [m["id"] for m in result["removed_models"]]
            assert str(source_id) in removed
            # Target excluded from candidacy (incoming ref) → never even attempted.
            assert str(target_id) not in removed
            assert (
                await session.execute(
                    select(TranscriptionModels).where(
                        TranscriptionModels.id == source_id
                    )
                )
            ).scalar_one_or_none() is None
            assert (
                await session.execute(
                    select(TranscriptionModels).where(
                        TranscriptionModels.id == target_id
                    )
                )
            ).scalar_one_or_none() is not None

    async def test_cleanup_handles_multiple_migrations_in_one_pass(
        self, db_container, transcription_model_factory, admin_user
    ):
        # Two independent migrations → the incoming-reference subquery returns
        # multiple rows. Both sources must be removed and both targets protected
        # (guards against the multi-row NOT IN regressing to a scalar comparison).
        async with db_container() as container:
            session = container.session()
            a = await transcription_model_factory(session, "whisper-a")
            b = await transcription_model_factory(session, "whisper-b")
            c = await transcription_model_factory(session, "whisper-c")
            d = await transcription_model_factory(session, "whisper-d")
            a_id, b_id, c_id, d_id = a.id, b.id, c.id, d.id

            migration_service = container.transcription_model_migration_service()
            await migration_service.migrate_model_usage(
                from_model_id=a_id,
                to_model_id=b_id,
                user=admin_user,
                confirm_migration=True,
            )
            await migration_service.migrate_model_usage(
                from_model_id=c_id,
                to_model_id=d_id,
                user=admin_user,
                confirm_migration=True,
            )

        async with db_container() as container:
            await cleanup_orphaned_transcription_models(container)
            session = container.session()

            present = {
                row.id
                for row in (
                    await session.execute(
                        select(TranscriptionModels).where(
                            TranscriptionModels.id.in_([a_id, b_id, c_id, d_id])
                        )
                    )
                ).scalars()
            }
            assert a_id not in present and c_id not in present  # sources removed
            assert b_id in present and d_id in present  # targets protected

    async def test_cleanup_never_touches_active_models(
        self, db_container, transcription_model_factory, admin_user
    ):
        # Safety net against an over-broad candidate predicate: a live model
        # (no deleted_at, no migrated_to) must never be selected for deletion.
        async with db_container() as container:
            session = container.session()
            active = await transcription_model_factory(session, "whisper-active")
            active_id = active.id

        async with db_container() as container:
            result = await cleanup_orphaned_transcription_models(container)
            session = container.session()

            assert str(active_id) not in [m["id"] for m in result["removed_models"]]
            assert (
                await session.execute(
                    select(TranscriptionModels).where(
                        TranscriptionModels.id == active_id
                    )
                )
            ).scalar_one_or_none() is not None

    async def test_migration_history_survives_source_cleanup(
        self, db_container, transcription_model_factory, admin_user
    ):
        # After the migrated source is hard-deleted, its history row must remain
        # readable: from_model_id is SET NULL but the denormalized name persists.
        async with db_container() as container:
            session = container.session()
            old_model = await transcription_model_factory(session, "whisper-hist-old")
            new_model = await transcription_model_factory(session, "whisper-hist-new")
            old_id, new_id = old_model.id, new_model.id

            migration_service = container.transcription_model_migration_service()
            await migration_service.migrate_model_usage(
                from_model_id=old_id,
                to_model_id=new_id,
                user=admin_user,
                confirm_migration=True,
            )

        async with db_container() as container:
            await cleanup_orphaned_transcription_models(container)
            session = container.session()

            history = (
                await session.execute(
                    select(TranscriptionModelMigrationHistory).where(
                        TranscriptionModelMigrationHistory.to_model_id == new_id
                    )
                )
            ).scalar_one()
            assert history.from_model_id is None  # SET NULL after source delete
            assert history.from_model_name == "whisper-hist-old"  # name preserved
            assert history.to_model_name == "whisper-hist-new"
