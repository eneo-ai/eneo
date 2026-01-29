from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from intric.ai_models.embedding_models.embedding_model import (
    EmbeddingModelCreate,
    EmbeddingModelLegacy,
    EmbeddingModelUpdate,
)
from intric.database.database import AsyncSession
from intric.database.repositories.base import BaseRepositoryDelegate
from intric.database.tables.ai_models_table import EmbeddingModels
from intric.main.exceptions import UniqueException
from intric.main.models import IdAndName


class AdminEmbeddingModelsService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.delegate = BaseRepositoryDelegate(session, EmbeddingModels, EmbeddingModelLegacy)

    async def get_model(self, id: UUID, tenant_id: UUID) -> EmbeddingModelLegacy:
        # Query the model with tenant filtering
        stmt = sa.select(EmbeddingModels).where(
            EmbeddingModels.id == id,
            sa.or_(
                EmbeddingModels.tenant_id.is_(None),
                EmbeddingModels.tenant_id == tenant_id
            )
        )
        result = await self.session.execute(stmt)
        db_model = result.scalar_one_or_none()

        if db_model is None:
            from intric.main.exceptions import NotFoundException
            raise NotFoundException()

        model = EmbeddingModelLegacy.model_validate(db_model)
        model.is_org_enabled = db_model.is_enabled
        return model

    async def get_model_by_name(self, name: str) -> EmbeddingModelLegacy:
        return await self.delegate.get_by(conditions={EmbeddingModels.name: name})

    async def create_model(self, model: EmbeddingModelCreate) -> EmbeddingModelLegacy:
        return await self.delegate.add(model)

    async def update_model(self, model: EmbeddingModelUpdate) -> EmbeddingModelLegacy:
        return await self.delegate.update(model)

    async def delete_model(self, id: UUID) -> EmbeddingModelLegacy:
        return await self.delegate.delete(id)

    async def get_models(
        self,
        tenant_id: UUID = None,
        with_deprecated: bool = False,
        id_list: list[UUID] = None,
    ):
        stmt = sa.select(EmbeddingModels).order_by(EmbeddingModels.created_at)

        if not with_deprecated:
            stmt = stmt.where(EmbeddingModels.is_deprecated == False)  # noqa

        if id_list is not None:
            stmt = stmt.where(EmbeddingModels.id.in_(id_list))

        # Filter to tenant's models
        if tenant_id is not None:
            stmt = stmt.where(
                sa.or_(
                    EmbeddingModels.tenant_id.is_(None),
                    EmbeddingModels.tenant_id == tenant_id
                )
            )

        result = await self.session.execute(stmt)
        db_models = result.scalars().all()

        models = []
        for db_model in db_models:
            model = EmbeddingModelLegacy.model_validate(db_model)
            model.is_org_enabled = db_model.is_enabled
            models.append(model)

        return models

    async def get_ids_and_names(self) -> list[(UUID, str)]:
        stmt = sa.select(EmbeddingModels)

        models = await self.delegate.get_records_from_query(stmt)

        return [IdAndName(id=model.id, name=model.name) for model in models.all()]

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
