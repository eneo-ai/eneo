"""Integration tests for the embedding model lifecycle.

Embedding models are never migrated (switching embedding model means
re-embedding, not repointing), so the lifecycle is soft-delete only:
- tenant delete soft-deletes (keeps the row as a tombstone) and hides it from
  read paths
- the weekly cleanup worker hard-deletes a tombstone only once nothing
  references it — info_blobs (the historical chunk → model link, FK SET NULL)
  are the blocker that keeps a tombstone alive until the knowledge is gone
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from eneo.database.tables.ai_models_table import EmbeddingModels
from eneo.database.tables.info_blobs_table import InfoBlobs
from eneo.database.tables.model_providers_table import ModelProviders
from eneo.database.tables.spaces_table import SpacesEmbeddingModels
from eneo.embedding_models.domain.embedding_model_repo import (
    EmbeddingModelRepository,
)
from eneo.embedding_models.infrastructure.embedding_model_cleanup_worker import (
    cleanup_orphaned_embedding_models,
)
from eneo.embedding_models.presentation.tenant_embedding_models_router import (
    TenantEmbeddingModelUpdate,
)
from eneo.main.exceptions import NotFoundException
from eneo.tenant_models.application.tenant_model_service import (
    TenantEmbeddingModelService,
)


async def _make_embedding_model(session, admin_user, name, *, deleted=False):
    provider = (
        await session.execute(
            select(ModelProviders).where(
                ModelProviders.tenant_id == admin_user.tenant_id,
                ModelProviders.provider_type == "openai",
            )
        )
    ).scalar_one_or_none()
    if provider is None:
        provider = ModelProviders(
            tenant_id=admin_user.tenant_id,
            name="Openai",
            provider_type="openai",
            credentials={"api_key": "test-key"},
            config={},
            is_active=True,
        )
        session.add(provider)
        await session.flush()

    model = EmbeddingModels(
        tenant_id=admin_user.tenant_id,
        provider_id=provider.id,
        name=name,
        open_source=False,
        family="openai",
        stability="stable",
        hosting="usa",
    )
    session.add(model)
    await session.flush()
    if deleted:
        model.deleted_at = datetime.now(timezone.utc)
        await session.flush()
    return model


@pytest.mark.integration
@pytest.mark.asyncio
class TestEmbeddingModelSoftDelete:
    async def test_delete_soft_deletes_and_hides_from_reads(
        self, db_container, admin_user
    ):
        async with db_container() as container:
            session = container.session()
            model = await _make_embedding_model(session, admin_user, "embed-del")
            model_id = model.id

            service = TenantEmbeddingModelService(session=session, user=admin_user)
            await service.delete(model_id)

            row = (
                await session.execute(
                    select(EmbeddingModels).where(EmbeddingModels.id == model_id)
                )
            ).scalar_one()
            assert row.deleted_at is not None

            repo = EmbeddingModelRepository(session, admin_user)
            assert all(m.id != model_id for m in await repo.all())
            assert await repo.one_or_none(model_id) is None

    async def test_update_rejects_soft_deleted_model(self, db_container, admin_user):
        async with db_container() as container:
            session = container.session()
            model = await _make_embedding_model(
                session, admin_user, "embed-update-deleted", deleted=True
            )

            service = TenantEmbeddingModelService(session=session, user=admin_user)
            with pytest.raises(NotFoundException):
                await service.update(
                    model.id,
                    TenantEmbeddingModelUpdate(description="should not update"),
                )

    async def test_sysadmin_delete_soft_deletes_and_preserves_info_blob_model_link(
        self, client, super_admin_token, db_container, admin_user, space_factory
    ):
        async with db_container() as container:
            session = container.session()
            model = await _make_embedding_model(session, admin_user, "embed-admin-del")
            model_id = model.id
            space = await space_factory(session, "Embedding model admin delete")
            session.add(
                SpacesEmbeddingModels(space_id=space.id, embedding_model_id=model_id)
            )
            info_blob = InfoBlobs(
                text="historical chunk",
                size=10,
                user_id=admin_user.id,
                tenant_id=admin_user.tenant_id,
                embedding_model_id=model_id,
            )
            session.add(info_blob)
            await session.flush()
            info_blob_id = info_blob.id

        response = await client.delete(
            f"/api/v1/sysadmin/embedding-models/{model_id}",
            headers={"X-API-Key": super_admin_token},
        )
        assert response.status_code == 200

        async with db_container() as container:
            session = container.session()

            row = (
                await session.execute(
                    select(EmbeddingModels).where(EmbeddingModels.id == model_id)
                )
            ).scalar_one()
            assert row.deleted_at is not None

            blob = (
                await session.execute(
                    select(InfoBlobs).where(InfoBlobs.id == info_blob_id)
                )
            ).scalar_one()
            assert blob.embedding_model_id == model_id

            link = (
                await session.execute(
                    select(SpacesEmbeddingModels).where(
                        SpacesEmbeddingModels.embedding_model_id == model_id
                    )
                )
            ).scalar_one_or_none()
            assert link is None


@pytest.mark.integration
@pytest.mark.asyncio
class TestEmbeddingModelCleanupWorker:
    async def test_cleanup_removes_soft_deleted_without_references(
        self, db_container, admin_user
    ):
        async with db_container() as container:
            session = container.session()
            model = await _make_embedding_model(
                session, admin_user, "embed-tomb", deleted=True
            )
            model_id = model.id

        async with db_container() as container:
            result = await cleanup_orphaned_embedding_models(container)
            session = container.session()

            assert str(model_id) in [m["id"] for m in result["removed_models"]]
            assert (
                await session.execute(
                    select(EmbeddingModels).where(EmbeddingModels.id == model_id)
                )
            ).scalar_one_or_none() is None

    async def test_cleanup_never_touches_active_models(self, db_container, admin_user):
        # An embedding model with no deleted_at is not a tombstone and must never
        # be selected — embedding has no migration, so deleted_at is the *only*
        # lifecycle signal.
        async with db_container() as container:
            session = container.session()
            active = await _make_embedding_model(session, admin_user, "embed-active")
            active_id = active.id

        async with db_container() as container:
            result = await cleanup_orphaned_embedding_models(container)
            session = container.session()

            assert str(active_id) not in [m["id"] for m in result["removed_models"]]
            assert (
                await session.execute(
                    select(EmbeddingModels).where(EmbeddingModels.id == active_id)
                )
            ).scalar_one_or_none() is not None

    async def test_cleanup_skips_tombstone_with_info_blob_reference(
        self, db_container, admin_user
    ):
        async with db_container() as container:
            session = container.session()
            model = await _make_embedding_model(
                session, admin_user, "embed-stuck", deleted=True
            )
            model_id = model.id
            session.add(
                InfoBlobs(
                    text="historical chunk",
                    size=10,
                    user_id=admin_user.id,
                    tenant_id=admin_user.tenant_id,
                    embedding_model_id=model_id,
                )
            )
            await session.flush()

        async with db_container() as container:
            result = await cleanup_orphaned_embedding_models(container)
            session = container.session()

            assert str(model_id) in [m["id"] for m in result["skipped_models"]]
            assert (
                await session.execute(
                    select(EmbeddingModels).where(EmbeddingModels.id == model_id)
                )
            ).scalar_one_or_none() is not None
