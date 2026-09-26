from typing import TYPE_CHECKING, Optional
from uuid import UUID

import sqlalchemy as sa

from eneo.database.affected_rows import affected_row_count
from eneo.database.tables.model_providers_table import ModelProviders
from eneo.main.exceptions import NotFoundException
from eneo.model_providers.domain.connection_check import ConnectionCheck
from eneo.model_providers.domain.model_provider import ModelProvider

if TYPE_CHECKING:
    from eneo.database.database import AsyncSession


class ModelProviderRepository:
    """Repository for managing model providers."""

    def __init__(self, session: "AsyncSession", tenant_id: UUID):
        super().__init__()
        self.session = session
        self.tenant_id = tenant_id

    async def all(self, active_only: bool = False) -> list[ModelProvider]:
        """Get all providers for the tenant."""
        stmt = sa.select(ModelProviders).where(
            ModelProviders.tenant_id == self.tenant_id
        )

        if active_only:
            stmt = stmt.where(ModelProviders.is_active == True)  # noqa

        stmt = stmt.order_by(ModelProviders.name)

        result = await self.session.execute(stmt)
        providers_db = result.scalars().all()

        return [
            ModelProvider.create_from_db(provider_db) for provider_db in providers_db
        ]

    async def get_by_id(self, provider_id: UUID) -> ModelProvider:
        """Get a provider by ID."""
        stmt = sa.select(ModelProviders).where(
            ModelProviders.id == provider_id, ModelProviders.tenant_id == self.tenant_id
        )

        result = await self.session.execute(stmt)
        provider_db = result.scalar_one_or_none()

        if provider_db is None:
            raise NotFoundException("ModelProvider", provider_id)

        return ModelProvider.create_from_db(provider_db)

    async def get_by_name(self, name: str) -> Optional[ModelProvider]:
        """Get a provider by name."""
        stmt = sa.select(ModelProviders).where(
            ModelProviders.name == name, ModelProviders.tenant_id == self.tenant_id
        )

        result = await self.session.execute(stmt)
        provider_db = result.scalar_one_or_none()

        if provider_db is None:
            return None

        return ModelProvider.create_from_db(provider_db)

    async def create(self, provider: ModelProvider) -> ModelProvider:
        """Create a new provider."""
        provider_db = ModelProviders(
            **dict(  # type: ignore[arg-type]
                tenant_id=provider.tenant_id,
                name=provider.name,
                provider_type=provider.provider_type,
                credentials=provider.credentials,
                config=provider.config,
                is_active=provider.is_active,
                key_expires_on=provider.key_expires_on,
            )
        )

        self.session.add(provider_db)
        await self.session.flush()
        await self.session.refresh(provider_db)

        return ModelProvider.create_from_db(provider_db)

    async def update(
        self, provider: ModelProvider, *, clear_connection_check: bool = False
    ) -> ModelProvider:
        """Update an existing provider.

        The connection check is written only by ``record_connection_check``,
        or cleared here, so an edit never overwrites a newer result.
        """
        stmt = sa.select(ModelProviders).where(
            ModelProviders.id == provider.id, ModelProviders.tenant_id == self.tenant_id
        )

        result = await self.session.execute(stmt)
        provider_db = result.scalar_one_or_none()

        if provider_db is None:
            raise NotFoundException("ModelProvider", provider.id)

        provider_db.name = provider.name
        provider_db.provider_type = provider.provider_type
        provider_db.credentials = provider.credentials
        provider_db.config = provider.config
        provider_db.is_active = provider.is_active
        provider_db.key_expires_on = provider.key_expires_on
        if clear_connection_check:
            provider_db.connection_status = None
            provider_db.connection_error = None
            provider_db.connection_checked_at = None

        await self.session.flush()
        await self.session.refresh(provider_db)

        return ModelProvider.create_from_db(provider_db)

    async def record_connection_check(
        self, tested: ModelProvider, check: ConnectionCheck
    ) -> ModelProvider:
        """Store ``check`` as the provider's latest result and return the provider.

        The check ran without a lock. If the credentials or endpoint changed
        meanwhile, the result describes settings the provider no longer has
        and is dropped; the row lock keeps an edit from slipping in between
        this comparison and the write.
        """
        stmt = (
            sa.select(ModelProviders)
            .where(
                ModelProviders.id == tested.id,
                ModelProviders.tenant_id == self.tenant_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        provider_db = (await self.session.execute(stmt)).scalar_one_or_none()
        if provider_db is None:
            raise NotFoundException("ModelProvider", tested.id)

        if (
            provider_db.credentials == tested.credentials
            and provider_db.config == tested.config
        ):
            provider_db.connection_status = check.status.value
            provider_db.connection_error = check.error.value if check.error else None
            provider_db.connection_checked_at = check.checked_at
            await self.session.flush()
            await self.session.refresh(provider_db)

        return ModelProvider.create_from_db(provider_db)

    async def delete(self, provider_id: UUID) -> None:
        """Delete a provider."""
        stmt = sa.delete(ModelProviders).where(
            ModelProviders.id == provider_id, ModelProviders.tenant_id == self.tenant_id
        )

        result = await self.session.execute(stmt)

        if affected_row_count(result) == 0:
            raise NotFoundException("ModelProvider", provider_id)

    async def count_models_for_provider(self, provider_id: UUID) -> int:
        """Count how many models are using this provider."""
        from eneo.database.tables.ai_models_table import (
            CompletionModels,
            EmbeddingModels,
            ImageModels,
            TranscriptionModels,
        )

        # Count completion models
        completion_count = await self.session.scalar(
            sa.select(sa.func.count())
            .select_from(CompletionModels)
            .where(CompletionModels.provider_id == provider_id)
        )

        # Count embedding models
        embedding_count = await self.session.scalar(
            sa.select(sa.func.count())
            .select_from(EmbeddingModels)
            .where(EmbeddingModels.provider_id == provider_id)
        )

        # Count transcription models
        transcription_count = await self.session.scalar(
            sa.select(sa.func.count())
            .select_from(TranscriptionModels)
            .where(TranscriptionModels.provider_id == provider_id)
        )

        image_count = await self.session.scalar(
            sa.select(sa.func.count())
            .select_from(ImageModels)
            .where(ImageModels.provider_id == provider_id)
        )

        return (
            (completion_count or 0)
            + (embedding_count or 0)
            + (transcription_count or 0)
            + (image_count or 0)
        )
