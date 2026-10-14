"""Integration tests for the rerank model lifecycle.

Rerank models follow the catalog contract of the other model types:
- tenant create/update honour the unique display name and single default
- org settings (enabled, default, classification) are updated through the
  CRUD service, which also keeps a single default
- tenant delete soft-deletes (keeps a tombstone) and hides it from reads
- the weekly cleanup worker hard-deletes tombstones
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from eneo.database.tables.ai_models_table import RerankModels
from eneo.main.exceptions import NameCollisionException, NotFoundException
from eneo.rerank_models.application.rerank_model_crud_service import (
    RerankModelCRUDService,
)
from eneo.rerank_models.domain.rerank_model_repo import RerankModelRepository
from eneo.rerank_models.infrastructure.rerank_model_cleanup_worker import (
    cleanup_orphaned_rerank_models,
)
from eneo.rerank_models.presentation.tenant_rerank_models_router import (
    TenantRerankModelCreate,
    TenantRerankModelUpdate,
)
from eneo.tenant_models.application.tenant_model_service import (
    TenantRerankModelService,
)


class TestTenantRerankModelService:
    async def test_create_and_read_back(
        self, db_container, rerank_model_factory, admin_user
    ):
        async with db_container() as container:
            session = container.session()
            seed = await rerank_model_factory(session, "seed")
            service = TenantRerankModelService(session=session, user=admin_user)

            created = await service.create(
                TenantRerankModelCreate(
                    provider_id=seed.provider_id,
                    name="rerank-v3.5",
                    display_name="Cohere rerank",
                    is_default=True,
                )
            )

            assert created.name == "rerank-v3.5"
            assert created.nickname == "Cohere rerank"
            assert created.is_org_enabled is True
            assert created.is_org_default is True
            assert (created.provider_name or "").lower() == "cohere"
            assert created.provider_type == "cohere"

            listed = await RerankModelRepository(session, admin_user).all()
            assert {m.id for m in listed} >= {seed.id, created.id}

    async def test_display_name_is_unique_per_provider(
        self, db_container, rerank_model_factory, admin_user
    ):
        async with db_container() as container:
            session = container.session()
            existing = await rerank_model_factory(session, "one", nickname="Taken")
            service = TenantRerankModelService(session=session, user=admin_user)

            with pytest.raises(NameCollisionException):
                await service.create(
                    TenantRerankModelCreate(
                        provider_id=existing.provider_id,
                        name="two",
                        display_name="taken",
                    )
                )

    async def test_promoting_a_default_unsets_the_previous_one(
        self, db_container, rerank_model_factory, admin_user
    ):
        async with db_container() as container:
            session = container.session()
            first = await rerank_model_factory(session, "first", is_default=True)
            second = await rerank_model_factory(session, "second")
            service = TenantRerankModelService(session=session, user=admin_user)

            await service.update(second.id, TenantRerankModelUpdate(is_default=True))

            rows = (
                await session.execute(
                    select(RerankModels.id, RerankModels.is_default).where(
                        RerankModels.id.in_([first.id, second.id])
                    )
                )
            ).all()
            assert dict(rows) == {first.id: False, second.id: True}

    async def test_update_renames_and_describes(
        self, db_container, rerank_model_factory, admin_user
    ):
        async with db_container() as container:
            session = container.session()
            model = await rerank_model_factory(session, "editable")
            service = TenantRerankModelService(session=session, user=admin_user)

            updated = await service.update(
                model.id,
                TenantRerankModelUpdate(
                    display_name="Renamed", description="Swedish-capable reranker"
                ),
            )

            assert updated.nickname == "Renamed"
            assert updated.name == "editable"
            assert updated.description == "Swedish-capable reranker"

    async def test_update_rejects_soft_deleted_model(
        self, db_container, rerank_model_factory, admin_user
    ):
        async with db_container() as container:
            session = container.session()
            model = await rerank_model_factory(session, "gone")
            model.deleted_at = datetime.now(timezone.utc)
            await session.flush()

            service = TenantRerankModelService(session=session, user=admin_user)
            with pytest.raises(NotFoundException):
                await service.update(
                    model.id, TenantRerankModelUpdate(description="should not update")
                )


class TestRerankModelOrgSettings:
    async def test_disable_and_enable_without_restart(
        self, db_container, rerank_model_factory, admin_user
    ):
        async with db_container() as container:
            session = container.session()
            model = await rerank_model_factory(session, "toggle")
            repo = RerankModelRepository(session, admin_user)
            service = RerankModelCRUDService(user=admin_user, rerank_model_repo=repo)

            disabled = await service.update_rerank_model(
                model_id=model.id, is_org_enabled=False, is_org_default=None
            )
            assert disabled.is_org_enabled is False
            assert (await repo.one(model.id)).can_access is False

            enabled = await service.update_rerank_model(
                model_id=model.id, is_org_enabled=True, is_org_default=None
            )
            assert enabled.is_org_enabled is True
            assert (await repo.one(model.id)).can_access is True

    async def test_org_default_is_single(
        self, db_container, rerank_model_factory, admin_user
    ):
        async with db_container() as container:
            session = container.session()
            first = await rerank_model_factory(session, "first", is_default=True)
            second = await rerank_model_factory(session, "second")
            repo = RerankModelRepository(session, admin_user)
            service = RerankModelCRUDService(user=admin_user, rerank_model_repo=repo)

            await service.update_rerank_model(
                model_id=second.id, is_org_enabled=None, is_org_default=True
            )

            defaults = {m.id: m.is_org_default for m in await repo.all()}
            assert defaults[first.id] is False
            assert defaults[second.id] is True


class TestRerankModelSoftDelete:
    async def test_delete_soft_deletes_and_hides_from_reads(
        self, db_container, rerank_model_factory, admin_user
    ):
        async with db_container() as container:
            session = container.session()
            model = await rerank_model_factory(session, "to-delete")
            model_id = model.id

            service = TenantRerankModelService(session=session, user=admin_user)
            await service.delete(model_id)

            row = (
                await session.execute(
                    select(RerankModels).where(RerankModels.id == model_id)
                )
            ).scalar_one()
            assert row.deleted_at is not None

            repo = RerankModelRepository(session, admin_user)
            assert all(m.id != model_id for m in await repo.all())
            assert await repo.one_or_none(model_id) is None


class TestRerankModelCleanupWorker:
    async def test_cleanup_removes_soft_deleted_models(
        self, db_container, rerank_model_factory, admin_user
    ):
        async with db_container() as container:
            session = container.session()
            model = await rerank_model_factory(session, "tombstone")
            model_id = model.id
            service = TenantRerankModelService(session=session, user=admin_user)
            await service.delete(model_id)

        async with db_container() as container:
            result = await cleanup_orphaned_rerank_models(container)

        assert str(model_id) in [m["id"] for m in result["removed_models"]]
        async with db_container() as container:
            session = container.session()
            row = (
                await session.execute(
                    select(RerankModels).where(RerankModels.id == model_id)
                )
            ).scalar_one_or_none()
            assert row is None
