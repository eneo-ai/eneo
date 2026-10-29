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
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.security_classifications_table import (
    SecurityClassification,
)
from eneo.main.exceptions import NameCollisionException, NotFoundException
from eneo.model_providers.infrastructure.model_provider_repository import (
    ModelProviderRepository,
)
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
from eneo.security_classifications.domain.repositories.security_classification_repo_impl import (  # noqa: E501
    SecurityClassificationRepoImpl,
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

    async def test_candidate_factor_and_cap_default_and_change(
        self, db_container, rerank_model_factory, admin_user
    ):
        async with db_container() as container:
            session = container.session()
            seed = await rerank_model_factory(session, "seed")
            service = TenantRerankModelService(session=session, user=admin_user)

            defaulted = await service.create(
                TenantRerankModelCreate(
                    provider_id=seed.provider_id, name="a", display_name="A"
                )
            )
            chosen = await service.create(
                TenantRerankModelCreate(
                    provider_id=seed.provider_id,
                    name="b",
                    display_name="B",
                    candidate_factor=3,
                    max_candidates=250,
                )
            )
            assert (defaulted.candidate_factor, defaulted.max_candidates) == (5, 100)
            assert (chosen.candidate_factor, chosen.max_candidates) == (3, 250)

            capped = await service.update(
                chosen.id, TenantRerankModelUpdate(max_candidates=30)
            )
            assert (capped.candidate_factor, capped.max_candidates) == (3, 30)

            renamed = await service.update(
                chosen.id, TenantRerankModelUpdate(display_name="B2")
            )
            assert (renamed.candidate_factor, renamed.max_candidates) == (3, 30)

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


class TestRerankModelReferenceGuards:
    """Rerank rows count where the other model types count, so an admin cannot
    delete a provider or a classification out from under a rerank model."""

    async def test_provider_deletion_counts_rerank_models(
        self, db_container, rerank_model_factory, admin_user
    ):
        async with db_container() as container:
            session = container.session()
            model = await rerank_model_factory(session, "guarded")
            repo = ModelProviderRepository(
                session=session, tenant_id=admin_user.tenant_id
            )

            assert await repo.count_models_for_provider(model.provider_id) == 1

    async def test_classification_usage_counts_live_rerank_models_only(
        self, db_container, rerank_model_factory, admin_user
    ):
        async with db_container() as container:
            session = container.session()
            classification = SecurityClassification(
                tenant_id=admin_user.tenant_id, name="Confidential", security_level=2
            )
            session.add(classification)
            await session.flush()
            live = await rerank_model_factory(
                session, "live", security_classification_id=classification.id
            )
            gone = await rerank_model_factory(
                session, "gone", security_classification_id=classification.id
            )
            gone.deleted_at = datetime.now(timezone.utc)
            await session.flush()

            usages = await SecurityClassificationRepoImpl(
                session, admin_user
            ).count_usages(classification.id)

            assert usages["rerank_models"] == 1
            assert live.security_classification_id == classification.id


class TestAssistantReference:
    async def test_assistant_falls_back_when_its_reranker_is_removed(
        self,
        db_container,
        rerank_model_factory,
        completion_model_factory,
        assistant_factory,
        admin_user,
    ):
        """B9: a reranker can be removed while assistants point at it. The
        tombstone keeps the reference until the cleanup worker hard-deletes
        it, and the FK's SET NULL then clears the assistant's choice."""
        async with db_container() as container:
            session = container.session()
            reranker = await rerank_model_factory(session, "chosen")
            completion = await completion_model_factory(session, "gpt-4")
            assistant = await assistant_factory(
                session, "Uses reranker", completion.id, rerank_model_id=reranker.id
            )
            reranker_id, assistant_id = reranker.id, assistant.id
            await TenantRerankModelService(session=session, user=admin_user).delete(
                reranker_id
            )
            await session.refresh(assistant)
            assert assistant.rerank_model_id == reranker_id

        async with db_container() as container:
            await cleanup_orphaned_rerank_models(container)

        async with db_container() as container:
            session = container.session()
            row = (
                await session.execute(
                    select(Assistants.rerank_model_id).where(
                        Assistants.id == assistant_id
                    )
                )
            ).scalar_one()
            assert row is None
