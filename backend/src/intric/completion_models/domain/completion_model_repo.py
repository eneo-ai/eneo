from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from intric.completion_models.domain import CompletionModel
from intric.database.tables.ai_models_table import (
    CompletionModels,
    CompletionModelSettings,
)
from intric.database.tables.security_classifications_table import (
    SecurityClassification as SecurityClassificationDBModel,
)
from intric.main.exceptions import NotFoundException

if TYPE_CHECKING:
    from uuid import UUID

    from intric.database.database import AsyncSession
    from intric.users.user import UserInDB


class CompletionModelRepository:
    def __init__(self, session: "AsyncSession", user: "UserInDB"):
        self.session = session
        self.user = user

    async def all(self, with_deprecated: bool = False):
        from intric.main.config import get_settings
        app_settings = get_settings()
        tenant_models_enabled = app_settings.tenant_models_enabled

        stmt = (
            sa.select(CompletionModels, CompletionModelSettings)
            .outerjoin(
                CompletionModelSettings,
                sa.and_(
                    CompletionModelSettings.completion_model_id == CompletionModels.id,
                    CompletionModelSettings.tenant_id == self.user.tenant_id,
                ),
            )
            .options(
                selectinload(CompletionModelSettings.security_classification),
                selectinload(CompletionModelSettings.security_classification).options(
                    selectinload(SecurityClassificationDBModel.tenant)
                ),
            )
            .where(
                # When tenant_models_enabled, return both global and tenant models
                # This allows existing assistants with global models to continue working
                # UI filtering happens at the presentation layer
                sa.or_(
                    CompletionModels.tenant_id.is_(None),
                    CompletionModels.tenant_id == self.user.tenant_id
                ) if tenant_models_enabled
                else CompletionModels.tenant_id.is_(None)
            )
            .order_by(
                CompletionModels.org,
                CompletionModels.created_at,
                CompletionModels.nickname,
            )
        )

        if not with_deprecated:
            stmt = stmt.where(CompletionModels.is_deprecated == False)  # noqa

        result = await self.session.execute(stmt)
        completion_models = result.all()

        return [
            CompletionModel.create_from_db(
                completion_model_db=completion_model,
                completion_model_settings=completion_model_settings,
                user=self.user,
            )
            for completion_model, completion_model_settings in completion_models
        ]

    async def one_or_none(self, model_id: "UUID") -> Optional["CompletionModel"]:
        # When fetching by ID, return ANY model (global or tenant) that the user can access
        # This ensures existing assistants continue working when tenant_models_enabled is toggled
        stmt = (
            sa.select(CompletionModels, CompletionModelSettings)
            .outerjoin(
                CompletionModelSettings,
                sa.and_(
                    CompletionModelSettings.completion_model_id == CompletionModels.id,
                    CompletionModelSettings.tenant_id == self.user.tenant_id,
                ),
            )
            .options(
                selectinload(CompletionModelSettings.security_classification),
                selectinload(CompletionModelSettings.security_classification).options(
                    selectinload(SecurityClassificationDBModel.tenant)
                ),
            )
            .where(
                CompletionModels.id == model_id,
                # Allow both global models (tenant_id IS NULL) and tenant models (tenant_id = user.tenant_id)
                sa.or_(
                    CompletionModels.tenant_id.is_(None),
                    CompletionModels.tenant_id == self.user.tenant_id
                )
            )
        )

        result = await self.session.execute(stmt)
        one_or_none = result.one_or_none()

        if one_or_none is None:
            return

        completion_model, completion_model_settings = one_or_none

        return CompletionModel.create_from_db(
            completion_model_db=completion_model,
            completion_model_settings=completion_model_settings,
            user=self.user,
        )

    async def one(self, model_id: "UUID") -> "CompletionModel":
        completion_model = await self.one_or_none(model_id=model_id)

        if completion_model is None:
            raise NotFoundException()

        return completion_model

    async def update(self, completion_model: "CompletionModel"):
        stmt = sa.select(CompletionModelSettings).where(
            CompletionModelSettings.completion_model_id == completion_model.id,
            CompletionModelSettings.tenant_id == self.user.tenant_id,
        )
        result = await self.session.execute(stmt)
        existing_settings = result.scalars().one_or_none()

        if existing_settings is None:
            stmt = sa.insert(CompletionModelSettings).values(
                completion_model_id=completion_model.id,
                tenant_id=self.user.tenant_id,
                is_org_enabled=completion_model.is_org_enabled,
                is_org_default=completion_model.is_org_default,
                security_classification_id=(
                    completion_model.security_classification.id
                    if completion_model.security_classification
                    else None
                ),
            )
            await self.session.execute(stmt)

        else:
            stmt = (
                sa.update(CompletionModelSettings)
                .values(
                    is_org_enabled=completion_model.is_org_enabled,
                    is_org_default=completion_model.is_org_default,
                    security_classification_id=(
                        completion_model.security_classification.id
                        if completion_model.security_classification
                        else None
                    ),
                )
                .where(
                    CompletionModelSettings.completion_model_id == completion_model.id,
                    CompletionModelSettings.tenant_id == self.user.tenant_id,
                )
            )
            await self.session.execute(stmt)

        if completion_model.is_org_default:
            # Set all other models to not default
            stmt = (
                sa.update(CompletionModelSettings)
                .values(is_org_default=False)
                .where(
                    CompletionModelSettings.completion_model_id != completion_model.id,
                    CompletionModelSettings.tenant_id == self.user.tenant_id,
                )
            )
            await self.session.execute(stmt)
