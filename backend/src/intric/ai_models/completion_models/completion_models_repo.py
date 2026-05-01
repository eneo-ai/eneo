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
from intric.database.tables.app_table import Apps
from intric.database.tables.app_template_table import AppTemplates
from intric.database.tables.assistant_table import Assistants
from intric.database.tables.assistant_template_table import AssistantTemplates
from intric.database.tables.model_providers_table import ModelProviders
from intric.database.tables.service_table import Services
from intric.database.tables.spaces_table import SpacesCompletionModels
from intric.database.tables.users_table import Users
from intric.main.exceptions import UniqueException
from intric.main.models import IdAndName

COMPLETION_MODEL_DB_WRITE_EXCLUDE = {"token_limit", "supported_model_kwargs"}


class CompletionModelsRepository:
    def __init__(self, session: AsyncSession) -> None:
        super().__init__()
        self.session = session
        self.delegate: BaseRepositoryDelegate[CompletionModel] = BaseRepositoryDelegate(
            session, CompletionModels, CompletionModel
        )

    async def get_model(self, id: UUID, tenant_id: UUID) -> CompletionModel:
        # Query the model with tenant filtering
        stmt = (
            sa.select(CompletionModels, ModelProviders.provider_type)
            .outerjoin(
                ModelProviders, CompletionModels.provider_id == ModelProviders.id
            )
            .where(
                CompletionModels.id == id,
                CompletionModels.deleted_at.is_(None),
                sa.or_(
                    CompletionModels.tenant_id.is_(None),
                    CompletionModels.tenant_id == tenant_id,
                ),
            )
        )
        result = await self.session.execute(stmt)
        row = result.one_or_none()

        if row is None:
            from intric.main.exceptions import NotFoundException

            raise NotFoundException()

        db_model, provider_type = row
        model = CompletionModel.model_validate(db_model)
        model.is_org_enabled = db_model.is_enabled
        model.provider_type = provider_type
        return model

    async def get_model_by_name(self, name: str) -> CompletionModel | None:
        return await self.delegate.get_by(conditions={CompletionModels.name: name})

    async def create_model(self, model: CompletionModelCreate) -> CompletionModel:
        return await self.delegate.add(model, exclude=COMPLETION_MODEL_DB_WRITE_EXCLUDE)

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

    async def update_model(
        self, model: CompletionModelUpdate
    ) -> CompletionModel | None:
        return await self.delegate.update(
            model, exclude=COMPLETION_MODEL_DB_WRITE_EXCLUDE
        )

    async def delete_model(self, id: UUID) -> None:
        # Spaces are containers — a model "enabled" on a space without any
        # resource using it is configuration, not active usage. Drop the
        # cross-reference rows first so the soft-deleted model doesn't
        # dangle in space-aware reads (`Spaces.completion_models`).
        await self.session.execute(
            sa.delete(SpacesCompletionModels).where(
                SpacesCompletionModels.completion_model_id == id
            )
        )

        stmt = (
            sa.update(CompletionModels)
            .where(CompletionModels.id == id)
            .values(deleted_at=sa.func.now())
        )

        await self.session.execute(stmt)

    async def get_models(
        self,
        tenant_id: UUID | None = None,
        is_deprecated: bool = False,
        id_list: list[UUID] | None = None,
    ) -> list[CompletionModel]:
        query = (
            sa.select(CompletionModels, ModelProviders.provider_type)
            .outerjoin(
                ModelProviders, CompletionModels.provider_id == ModelProviders.id
            )
            .where(CompletionModels.is_deprecated == is_deprecated)
            .where(CompletionModels.deleted_at.is_(None))
            .order_by(CompletionModels.created_at)
        )

        if id_list is not None:
            query = query.where(CompletionModels.id.in_(id_list))

        # Filter to tenant's models
        if tenant_id is not None:
            query = query.where(
                sa.or_(
                    CompletionModels.tenant_id.is_(None),
                    CompletionModels.tenant_id == tenant_id,
                )
            )

        result = await self.session.execute(query)
        rows = result.all()

        models: list[CompletionModel] = []
        for db_model, provider_type in rows:
            model = CompletionModel.model_validate(db_model)
            model.is_org_enabled = db_model.is_enabled
            model.provider_type = provider_type
            models.append(model)

        return models

    async def get_ids_and_names(self) -> list[tuple[UUID, str]]:  # type: ignore[type-arg]
        stmt = sa.select(CompletionModels)

        models = await self.delegate.get_records_from_query(stmt)

        return [IdAndName(id=model.id, name=model.name) for model in models.all()]  # type: ignore[return-value]

    async def has_active_references(
        self, model_id: UUID, tenant_id: UUID | None = None
    ) -> bool:
        # Note: spaces are intentionally NOT counted here. Spaces are
        # containers for resources (assistants, apps, services); a model
        # "enabled" on a space without any resource using it is just
        # configuration. The cross-reference rows are cleaned up in
        # `delete_model`.
        assistant_stmt = (
            sa.select(sa.func.count())
            .select_from(Assistants)
            .where(Assistants.completion_model_id == model_id)
        )
        service_stmt = (
            sa.select(sa.func.count())
            .select_from(Services)
            .where(Services.completion_model_id == model_id)
        )
        app_stmt = (
            sa.select(sa.func.count())
            .select_from(Apps)
            .where(Apps.completion_model_id == model_id)
        )
        assistant_template_stmt = (
            sa.select(sa.func.count())
            .select_from(AssistantTemplates)
            .where(
                AssistantTemplates.completion_model_id == model_id,
                AssistantTemplates.deleted_at.is_(None),
            )
        )
        app_template_stmt = (
            sa.select(sa.func.count())
            .select_from(AppTemplates)
            .where(
                AppTemplates.completion_model_id == model_id,
                AppTemplates.deleted_at.is_(None),
            )
        )

        if tenant_id is not None:
            tenant_user_ids = sa.select(Users.id).where(Users.tenant_id == tenant_id)
            assistant_stmt = assistant_stmt.where(
                Assistants.user_id.in_(tenant_user_ids)
            )
            service_stmt = service_stmt.where(Services.user_id.in_(tenant_user_ids))
            app_stmt = app_stmt.where(Apps.tenant_id == tenant_id)

        for stmt in (
            assistant_stmt,
            service_stmt,
            app_stmt,
            assistant_template_stmt,
            app_template_stmt,
        ):
            result = await self.session.execute(stmt)
            if (result.scalar_one() or 0) > 0:
                return True

        return False
