from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from intric.ai_models.completion_models.completion_model import (
    CompletionModel,
    CompletionModelCreate,
    CompletionModelUpdate,
)
from intric.database.database import AsyncSession
from intric.database.repositories.base import BaseRepositoryDelegate
from intric.database.tables.ai_models_table import CompletionModels
from intric.main.exceptions import UniqueException
from intric.main.models import IdAndName


class CompletionModelsRepository:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.delegate = BaseRepositoryDelegate(
            session, CompletionModels, CompletionModel
        )

    async def get_model(self, id: UUID, tenant_id: UUID) -> CompletionModel:
        # Query the model with tenant filtering
        stmt = sa.select(CompletionModels).where(
            CompletionModels.id == id,
            sa.or_(
                CompletionModels.tenant_id.is_(None),
                CompletionModels.tenant_id == tenant_id
            )
        )
        result = await self.session.execute(stmt)
        db_model = result.scalar_one_or_none()

        if db_model is None:
            from intric.main.exceptions import NotFoundException
            raise NotFoundException()

        model = CompletionModel.model_validate(db_model)
        model.is_org_enabled = db_model.is_enabled
        return model

    async def get_model_by_name(self, name: str) -> CompletionModel:
        return await self.delegate.get_by(conditions={CompletionModels.name: name})

    async def create_model(self, model: CompletionModelCreate) -> CompletionModel:
        return await self.delegate.add(model)

    async def enable_completion_model(
        self,
        is_org_enabled: bool,
        completion_model_id: UUID,
        tenant_id: UUID,
    ):
        try:
            # Settings are now stored directly on the model table
            query = (
                sa.update(CompletionModels)
                .values(is_enabled=is_org_enabled)
                .where(
                    CompletionModels.id == completion_model_id,
                    CompletionModels.tenant_id == tenant_id,
                )
                .returning(CompletionModels)
            )
            return await self.session.scalar(query)
        except IntegrityError as e:
            raise UniqueException("Default completion model already exists.") from e

    async def update_model(self, model: CompletionModelUpdate) -> CompletionModel:
        return await self.delegate.update(model)

    async def delete_model(self, id: UUID) -> CompletionModel:
        stmt = (
            sa.delete(CompletionModels)
            .where(CompletionModels.id == id)
            .returning(CompletionModels)
        )

        await self.delegate.get_record_from_query(stmt)

    async def get_models(
        self,
        tenant_id: UUID = None,
        is_deprecated: bool = False,
        id_list: list[UUID] = None,
    ) -> list[CompletionModel]:
        query = (
            sa.select(CompletionModels)
            .where(CompletionModels.is_deprecated == is_deprecated)
            .order_by(CompletionModels.created_at)
        )

        if id_list is not None:
            query = query.where(CompletionModels.id.in_(id_list))

        # Filter to tenant's models
        if tenant_id is not None:
            query = query.where(
                sa.or_(
                    CompletionModels.tenant_id.is_(None),
                    CompletionModels.tenant_id == tenant_id
                )
            )

        result = await self.session.execute(query)
        db_models = result.scalars().all()

        models = []
        for db_model in db_models:
            model = CompletionModel.model_validate(db_model)
            model.is_org_enabled = db_model.is_enabled
            models.append(model)

        return models

    async def get_ids_and_names(self) -> list[(UUID, str)]:
        stmt = sa.select(CompletionModels)

        models = await self.delegate.get_records_from_query(stmt)

        return [IdAndName(id=model.id, name=model.name) for model in models.all()]
