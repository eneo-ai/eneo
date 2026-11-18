"""A provider is only held back by models an admin can still see and remove."""

from datetime import datetime, timezone

from sqlalchemy import func, select, update

from eneo.database.tables.ai_models_table import CompletionModels
from eneo.model_providers.infrastructure.model_provider_repository import (
    ModelProviderRepository,
)


async def _repo(container, admin_user) -> ModelProviderRepository:
    return ModelProviderRepository(
        session=container.session(), tenant_id=admin_user.tenant_id
    )


async def test_an_active_model_holds_its_provider_back(
    db_container, completion_model_factory, admin_user
):
    async with db_container() as container:
        session = container.session()
        repo = await _repo(container, admin_user)
        first = await completion_model_factory(session, "first")
        before = await repo.count_models_for_provider(first.provider_id)

        await completion_model_factory(session, "second")

        assert await repo.count_models_for_provider(first.provider_id) == before + 1


async def test_a_deleted_model_does_not(
    db_container, completion_model_factory, admin_user
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "deleted")
        repo = await _repo(container, admin_user)
        before = await repo.count_models_for_provider(model.provider_id)

        await session.execute(
            update(CompletionModels)
            .where(CompletionModels.id == model.id)
            .values(deleted_at=datetime.now(timezone.utc))
        )

        assert await repo.count_models_for_provider(model.provider_id) == before - 1


async def test_a_migrated_model_does_not(
    db_container, completion_model_factory, admin_user
):
    async with db_container() as container:
        session = container.session()
        old = await completion_model_factory(session, "old")
        new = await completion_model_factory(session, "new")
        repo = await _repo(container, admin_user)
        before = await repo.count_models_for_provider(old.provider_id)

        await session.execute(
            update(CompletionModels)
            .where(CompletionModels.id == old.id)
            .values(migrated_to_model_id=new.id)
        )

        assert await repo.count_models_for_provider(old.provider_id) == before - 1


async def test_a_provider_with_only_hidden_models_can_be_deleted(
    db_container, completion_model_factory, admin_user
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gone")
        await session.execute(
            update(CompletionModels)
            .where(CompletionModels.id == model.id)
            .values(deleted_at=datetime.now(timezone.utc))
        )
        repo = await _repo(container, admin_user)

        await repo.delete(model.provider_id)

        assert await repo.count_models_for_provider(model.provider_id) == 0


async def test_a_provider_whose_model_was_migrated_away_can_be_deleted(
    db_container, completion_model_factory, admin_user
):
    async with db_container() as container:
        session = container.session()
        old = await completion_model_factory(session, "old")
        new = await completion_model_factory(session, "new")
        await session.execute(
            update(CompletionModels)
            .where(CompletionModels.id == old.id)
            .values(migrated_to_model_id=new.id)
        )
        repo = await _repo(container, admin_user)

        await repo.delete(old.provider_id)

        remaining = await session.scalar(
            select(func.count())
            .select_from(CompletionModels)
            .where(CompletionModels.id.in_([old.id, new.id]))
        )
        assert remaining == 0
