from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from eneo.ai_models.embedding_models.embedding_model import (
    EmbeddingModelCreate,
    EmbeddingModelLegacy,
    EmbeddingModelUpdate,
)
from eneo.database.database import AsyncSession
from eneo.database.repositories.base import BaseRepositoryDelegate
from eneo.database.tables.ai_models_table import EmbeddingModels
from eneo.main.exceptions import UniqueException
from eneo.main.models import IdAndName


class AdminEmbeddingModelsService:
    def __init__(self, session: AsyncSession) -> None:
        super().__init__()
        self.session = session
        self.delegate: BaseRepositoryDelegate[EmbeddingModelLegacy] = (
            BaseRepositoryDelegate(session, EmbeddingModels, EmbeddingModelLegacy)
        )

    async def get_model(self, id: UUID, tenant_id: UUID) -> EmbeddingModelLegacy:
        # Query the model with tenant filtering
        stmt = sa.select(EmbeddingModels).where(
            EmbeddingModels.id == id,
            sa.or_(
                EmbeddingModels.tenant_id.is_(None),
                EmbeddingModels.tenant_id == tenant_id,
            ),
            EmbeddingModels.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        db_model = result.scalar_one_or_none()

        if db_model is None:
            from eneo.main.exceptions import NotFoundException

            raise NotFoundException()

        model = EmbeddingModelLegacy.model_validate(db_model)
        model.is_org_enabled = db_model.is_enabled
        return model

    async def get_model_by_name(self, name: str) -> EmbeddingModelLegacy | None:
        return await self.delegate.get_by(conditions={EmbeddingModels.name: name})

    async def create_model(self, model: EmbeddingModelCreate) -> EmbeddingModelLegacy:
        return await self.delegate.add(model)

    async def update_model(
        self, model: EmbeddingModelUpdate
    ) -> EmbeddingModelLegacy | None:
        return await self.delegate.update(model)

    async def delete_model(self, id: UUID) -> EmbeddingModelLegacy | None:
        return await self.delegate.delete(id)

    async def get_models(
        self,
        tenant_id: UUID | None = None,
        with_deprecated: bool = False,
        id_list: list[UUID] | None = None,
    ) -> list[EmbeddingModelLegacy]:
        stmt = (
            sa.select(EmbeddingModels)
            .where(EmbeddingModels.deleted_at.is_(None))
            .order_by(EmbeddingModels.created_at)
        )

        if not with_deprecated:
            stmt = stmt.where(EmbeddingModels.is_deprecated == False)  # noqa

        if id_list is not None:
            stmt = stmt.where(EmbeddingModels.id.in_(id_list))

        # Filter to tenant's models
        if tenant_id is not None:
            stmt = stmt.where(
                sa.or_(
                    EmbeddingModels.tenant_id.is_(None),
                    EmbeddingModels.tenant_id == tenant_id,
                )
            )

        result = await self.session.execute(stmt)
        db_models = result.scalars().all()

        models: list[EmbeddingModelLegacy] = []
        for db_model in db_models:
            model = EmbeddingModelLegacy.model_validate(db_model)
            model.is_org_enabled = db_model.is_enabled
            models.append(model)

        return models

    async def get_ids_and_names(self) -> list[tuple[UUID, str]]:  # type: ignore[type-arg]
        stmt = sa.select(EmbeddingModels)

        models = await self.delegate.get_records_from_query(stmt)

        return [IdAndName(id=model.id, name=model.name) for model in models.all()]  # type: ignore[return-value]

    async def enable_embedding_model(
        self,
        is_org_enabled: bool,
        embedding_model_id: UUID,
        tenant_id: UUID,
    ):
        try:
            # Settings are now stored directly on the model table
            query = (
                sa.update(EmbeddingModels)
                .values(is_enabled=is_org_enabled)
                .where(
                    EmbeddingModels.id == embedding_model_id,
                    EmbeddingModels.tenant_id == tenant_id,
                )
                .returning(EmbeddingModels)
            )
            return await self.session.scalar(query)
        except IntegrityError as e:
            raise UniqueException("Default embedding model already exists.") from e
