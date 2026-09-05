"""Integration tests for the image model lifecycle.

Image models follow the catalog contract of the other model types:
- tenant create/update honour the unique display name and single default
- tenant delete soft-deletes (keeps a tombstone) and hides it from reads
- deletion is refused while a built-in capability provider runs on the model
- the weekly cleanup worker hard-deletes tombstones nothing references
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from eneo.database.tables.ai_models_table import ImageModels
from eneo.database.tables.mcp_server_table import MCPServers
from eneo.image_models.domain.image_model_repo import ImageModelRepository
from eneo.image_models.infrastructure.image_model_cleanup_worker import (
    cleanup_orphaned_image_models,
)
from eneo.image_models.presentation.tenant_image_models_router import (
    TenantImageModelCreate,
    TenantImageModelUpdate,
)
from eneo.main.exceptions import (
    ModelInUseException,
    NameCollisionException,
    NotFoundException,
)
from eneo.tenant_models.application.tenant_model_service import (
    TenantImageModelService,
)


async def _builtin_provider(session, tenant_id, image_model_id) -> MCPServers:
    server = MCPServers(
        tenant_id=tenant_id,
        name="Built-in images",
        purpose="image_generation",
        http_url="http://localhost:8123/internal-mcp/image_generation/mcp",
        http_auth_type="internal",
        image_model_id=image_model_id,
        is_enabled=False,
    )
    session.add(server)
    await session.flush()
    return server


class TestTenantImageModelService:
    async def test_create_and_read_back(
        self, db_container, image_model_factory, admin_user
    ):
        async with db_container() as container:
            session = container.session()
            seed = await image_model_factory(session, "seed")
            service = TenantImageModelService(session=session, user=admin_user)

            created = await service.create(
                TenantImageModelCreate(
                    provider_id=seed.provider_id,
                    name="gpt-image-1",
                    display_name="GPT Image",
                    cost_per_image=Decimal("0.04"),
                    default_size="1536x1024",
                    default_quality="high",
                    is_default=True,
                )
            )

            assert created.name == "gpt-image-1"
            assert created.nickname == "GPT Image"
            assert created.default_size == "1536x1024"
            assert created.default_quality == "high"
            assert created.cost_per_image == Decimal("0.04")
            assert created.is_org_default is True
            assert (created.provider_name or "").lower() == "openai"

            listed = await ImageModelRepository(session, admin_user).all()
            assert {m.id for m in listed} >= {seed.id, created.id}

    async def test_display_name_is_unique_per_provider(
        self, db_container, image_model_factory, admin_user
    ):
        async with db_container() as container:
            session = container.session()
            existing = await image_model_factory(session, "one", nickname="Taken")
            service = TenantImageModelService(session=session, user=admin_user)

            with pytest.raises(NameCollisionException):
                await service.create(
                    TenantImageModelCreate(
                        provider_id=existing.provider_id,
                        name="two",
                        display_name="taken",
                    )
                )

    async def test_promoting_a_default_unsets_the_previous_one(
        self, db_container, image_model_factory, admin_user
    ):
        async with db_container() as container:
            session = container.session()
            first = await image_model_factory(session, "first", is_default=True)
            second = await image_model_factory(session, "second")
            service = TenantImageModelService(session=session, user=admin_user)

            await service.update(second.id, TenantImageModelUpdate(is_default=True))

            rows = (
                await session.execute(
                    select(ImageModels.id, ImageModels.is_default).where(
                        ImageModels.id.in_([first.id, second.id])
                    )
                )
            ).all()
            assert dict(rows) == {first.id: False, second.id: True}

    async def test_update_changes_defaults_and_cost(
        self, db_container, image_model_factory, admin_user
    ):
        async with db_container() as container:
            session = container.session()
            model = await image_model_factory(session, "editable")
            service = TenantImageModelService(session=session, user=admin_user)

            updated = await service.update(
                model.id,
                TenantImageModelUpdate(
                    display_name="Renamed",
                    default_size="1024x1536",
                    default_quality="low",
                    cost_per_image=Decimal("0.01"),
                ),
            )

            assert updated.nickname == "Renamed"
            assert updated.name == "editable"
            assert updated.default_size == "1024x1536"
            assert updated.default_quality == "low"
            assert updated.cost_per_image == Decimal("0.01")

    async def test_update_rejects_soft_deleted_model(
        self, db_container, image_model_factory, admin_user
    ):
        async with db_container() as container:
            session = container.session()
            model = await image_model_factory(session, "gone")
            model.deleted_at = datetime.now(timezone.utc)
            await session.flush()

            service = TenantImageModelService(session=session, user=admin_user)
            with pytest.raises(NotFoundException):
                await service.update(
                    model.id, TenantImageModelUpdate(description="should not update")
                )


class TestImageModelSoftDelete:
    async def test_delete_soft_deletes_and_hides_from_reads(
        self, db_container, image_model_factory, admin_user
    ):
        async with db_container() as container:
            session = container.session()
            model = await image_model_factory(session, "to-delete")
            model_id = model.id

            service = TenantImageModelService(session=session, user=admin_user)
            await service.delete(model_id)

            row = (
                await session.execute(
                    select(ImageModels).where(ImageModels.id == model_id)
                )
            ).scalar_one()
            assert row.deleted_at is not None

            repo = ImageModelRepository(session, admin_user)
            assert all(m.id != model_id for m in await repo.all())
            assert await repo.one_or_none(model_id) is None

    async def test_delete_blocked_while_builtin_provider_references_model(
        self, db_container, image_model_factory, admin_user
    ):
        async with db_container() as container:
            session = container.session()
            model = await image_model_factory(session, "in-use")
            await _builtin_provider(session, admin_user.tenant_id, model.id)

            service = TenantImageModelService(session=session, user=admin_user)
            with pytest.raises(ModelInUseException):
                await service.delete(model.id)

            row = (
                await session.execute(
                    select(ImageModels).where(ImageModels.id == model.id)
                )
            ).scalar_one()
            assert row.deleted_at is None


class TestImageModelCleanupWorker:
    async def test_cleanup_removes_soft_deleted_without_references(
        self, db_container, image_model_factory, admin_user
    ):
        async with db_container() as container:
            session = container.session()
            model = await image_model_factory(session, "tombstone")
            model_id = model.id
            service = TenantImageModelService(session=session, user=admin_user)
            await service.delete(model_id)

        async with db_container() as container:
            result = await cleanup_orphaned_image_models(container)

        assert str(model_id) in [m["id"] for m in result["removed_models"]]
        async with db_container() as container:
            session = container.session()
            row = (
                await session.execute(
                    select(ImageModels).where(ImageModels.id == model_id)
                )
            ).scalar_one_or_none()
            assert row is None

    async def test_cleanup_keeps_referenced_tombstones(
        self, db_container, image_model_factory, admin_user
    ):
        # A tombstone that is still referenced can only arise from a manual
        # edit (the service refuses the delete); the worker must skip it and
        # leave the RESTRICT FK untouched.
        async with db_container() as container:
            session = container.session()
            model = await image_model_factory(session, "referenced-tombstone")
            model_id = model.id
            await _builtin_provider(session, admin_user.tenant_id, model_id)
            model.deleted_at = datetime.now(timezone.utc)
            await session.flush()

        async with db_container() as container:
            await cleanup_orphaned_image_models(container)

        async with db_container() as container:
            session = container.session()
            row = (
                await session.execute(
                    select(ImageModels).where(ImageModels.id == model_id)
                )
            ).scalar_one_or_none()
            assert row is not None
