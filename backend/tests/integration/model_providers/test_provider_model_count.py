"""A provider is only held back by models an admin can still see and remove."""

from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select, update

from eneo.database.tables.ai_models_table import CompletionModels, EmbeddingModels
from eneo.database.tables.info_blobs_table import InfoBlobs, InfoBlobVersionState
from eneo.database.tables.model_providers_table import ModelProviders
from eneo.database.tables.questions_table import Questions
from eneo.main.exceptions import BadRequestException
from eneo.model_providers.domain.model_provider_service import ModelProviderService
from eneo.model_providers.infrastructure.model_provider_repository import (
    ModelProviderRepository,
)
from eneo.settings.encryption_service import EncryptionService


async def _repo(container, admin_user) -> ModelProviderRepository:
    return ModelProviderRepository(
        session=container.session(), tenant_id=admin_user.tenant_id
    )


def _service(session, admin_user) -> ModelProviderService:
    return ModelProviderService(
        repository=ModelProviderRepository(session, admin_user.tenant_id),
        encryption=EncryptionService(Fernet.generate_key().decode()),
    )


async def _provider(session, admin_user) -> ModelProviders:
    provider = ModelProviders(
        tenant_id=admin_user.tenant_id,
        name=f"provider-{uuid4().hex[:8]}",
        provider_type="anthropic",
        credentials={"api_key": "test-key"},
        config={},
        is_active=True,
    )
    session.add(provider)
    await session.flush()
    return provider


async def _move(session, model_id, provider_id, **values) -> None:
    await session.execute(
        update(CompletionModels)
        .where(CompletionModels.id == model_id)
        .values(provider_id=provider_id, **values)
    )


async def _exists(session, provider_id) -> bool:
    return (
        await session.scalar(
            select(ModelProviders.id).where(ModelProviders.id == provider_id)
        )
    ) is not None


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


async def test_an_active_model_keeps_its_provider_from_being_deleted(
    db_container, completion_model_factory, admin_user
):
    async with db_container() as container:
        session = container.session()
        provider = await _provider(session, admin_user)
        model = await completion_model_factory(session, "active")
        await _move(session, model.id, provider.id)

        with pytest.raises(BadRequestException):
            await _service(session, admin_user).delete(provider.id)

        assert await _exists(session, provider.id)


async def test_a_migrated_model_keeps_its_history_when_its_provider_is_deleted(
    db_container, completion_model_factory, admin_user
):
    async with db_container() as container:
        session = container.session()
        old_provider = await _provider(session, admin_user)
        new_provider = await _provider(session, admin_user)
        old = await completion_model_factory(session, "old")
        new = await completion_model_factory(session, "new")
        await _move(session, new.id, new_provider.id)
        await _move(session, old.id, old_provider.id, migrated_to_model_id=new.id)
        question = Questions(
            question="Which day is it?",
            answer="Monday.",
            num_tokens_question=4,
            num_tokens_answer=2,
            tenant_id=admin_user.tenant_id,
            completion_model_id=old.id,
        )
        session.add(question)
        await session.flush()

        await _service(session, admin_user).delete(old_provider.id)

        assert not await _exists(session, old_provider.id)
        assert (
            await session.scalar(
                select(Questions.completion_model_id).where(Questions.id == question.id)
            )
        ) == old.id
        providers = dict(
            (
                await session.execute(
                    select(CompletionModels.id, CompletionModels.provider_id).where(
                        CompletionModels.id.in_([old.id, new.id])
                    )
                )
            ).all()
        )
        assert providers == {old.id: None, new.id: new_provider.id}


async def test_a_deleted_embedding_model_keeps_its_vectors_when_its_provider_is_deleted(
    db_container, admin_user
):
    async with db_container() as container:
        session = container.session()
        provider = await _provider(session, admin_user)
        model = EmbeddingModels(
            tenant_id=admin_user.tenant_id,
            provider_id=provider.id,
            name=f"embedding-{uuid4().hex[:8]}",
            open_source=False,
            family="openai",
            stability="stable",
            hosting="usa",
            deleted_at=datetime.now(timezone.utc),
        )
        session.add(model)
        await session.flush()
        blob = InfoBlobs(
            text="Retained knowledge",
            size=18,
            content_hash=sha256(b"Retained knowledge").digest(),
            source_id=uuid4(),
            version_state=InfoBlobVersionState.SUPERSEDED.value,
            user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            embedding_model_id=model.id,
        )
        session.add(blob)
        await session.flush()

        await _service(session, admin_user).delete(provider.id)

        assert not await _exists(session, provider.id)
        assert (
            await session.scalar(
                select(InfoBlobs.embedding_model_id).where(InfoBlobs.id == blob.id)
            )
        ) == model.id


async def test_the_name_of_a_deleted_provider_can_be_used_again(
    db_container, completion_model_factory, admin_user
):
    async with db_container() as container:
        session = container.session()
        provider = await _provider(session, admin_user)
        model = await completion_model_factory(session, "gone")
        await _move(
            session, model.id, provider.id, deleted_at=datetime.now(timezone.utc)
        )
        service = _service(session, admin_user)

        await service.delete(provider.id)
        again = await service.create(
            tenant_id=admin_user.tenant_id,
            name=provider.name,
            provider_type="anthropic",
            credentials={"api_key": "test-key"},
            config={},
        )

        assert again.name == provider.name
        assert again.id != provider.id
