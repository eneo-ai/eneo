from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from intric.completion_models.domain import CompletionModel
from intric.database.tables.ai_models_table import CompletionModels
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
        stmt = (
            sa.select(CompletionModels)
            .options(
                selectinload(CompletionModels.security_classification),
                selectinload(CompletionModels.security_classification).options(
                    selectinload(SecurityClassificationDBModel.tenant)
                ),
            )
            .where(
                # Return both global and tenant models
                # This allows existing assistants with global models to continue working
                # UI filtering happens at the presentation layer
                sa.or_(
                    CompletionModels.tenant_id.is_(None),
                    CompletionModels.tenant_id == self.user.tenant_id
                )
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
        completion_models = result.scalars().all()

        return [
            CompletionModel.create_from_db(
                completion_model_db=completion_model,
                user=self.user,
            )
            for completion_model in completion_models
        ]

    async def one_or_none(self, model_id: "UUID") -> Optional["CompletionModel"]:
        # When fetching by ID, return ANY model (global or tenant) that the user can access
        stmt = (
            sa.select(CompletionModels)
            .options(
                selectinload(CompletionModels.security_classification),
                selectinload(CompletionModels.security_classification).options(
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
        completion_model = result.scalars().one_or_none()

        if completion_model is None:
            return

        return CompletionModel.create_from_db(
            completion_model_db=completion_model,
            user=self.user,
        )

    async def one(self, model_id: "UUID") -> "CompletionModel":
        completion_model = await self.one_or_none(model_id=model_id)

        if completion_model is None:
            raise NotFoundException()

        return completion_model

    async def update(self, completion_model: "CompletionModel"):
        # Update settings directly on the model table
        stmt = (
            sa.update(CompletionModels)
            .values(
                is_enabled=completion_model.is_org_enabled,
                is_default=completion_model.is_org_default,
                security_classification_id=(
                    completion_model.security_classification.id
                    if completion_model.security_classification
                    else None
                ),
            )
            .where(
                CompletionModels.id == completion_model.id,
                CompletionModels.tenant_id == self.user.tenant_id,
            )
        )
        await self.session.execute(stmt)

        if completion_model.is_org_default:
            # Set all other models to not default (for this tenant)
            stmt = (
                sa.update(CompletionModels)
                .values(is_default=False)
                .where(
                    CompletionModels.id != completion_model.id,
                    CompletionModels.tenant_id == self.user.tenant_id,
                )
            )
            await self.session.execute(stmt)
