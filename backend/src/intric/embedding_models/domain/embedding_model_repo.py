from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from intric.database.tables.ai_models_table import (
    EmbeddingModels,
    EmbeddingModelSettings,
)
from intric.database.tables.security_classifications_table import SecurityClassification
from intric.embedding_models.domain.embedding_model import EmbeddingModel
from intric.main.exceptions import NotFoundException

if TYPE_CHECKING:
    from uuid import UUID

    from intric.database.database import AsyncSession
    from intric.users.user import UserInDB


class EmbeddingModelRepository:
    def __init__(self, session: "AsyncSession", user: "UserInDB"):
        self.session = session
        self.user = user

    async def all(self, with_deprecated: bool = False):
        from intric.main.config import get_settings
        app_settings = get_settings()
        tenant_models_enabled = app_settings.tenant_models_enabled

        stmt = (
            sa.select(EmbeddingModels, EmbeddingModelSettings)
            .outerjoin(
                EmbeddingModelSettings,
                sa.and_(
                    EmbeddingModelSettings.embedding_model_id == EmbeddingModels.id,
                    EmbeddingModelSettings.tenant_id == self.user.tenant_id,
                ),
            )
            .options(
                selectinload(EmbeddingModelSettings.security_classification),
                selectinload(EmbeddingModelSettings.security_classification).options(
                    selectinload(SecurityClassification.tenant)
                ),
            )
            .where(
                # When tenant_models_enabled, return both global and tenant models
                # This allows existing collections with global models to continue working
                # UI filtering happens at the presentation layer
                sa.or_(
                    EmbeddingModels.tenant_id.is_(None),
                    EmbeddingModels.tenant_id == self.user.tenant_id
                ) if tenant_models_enabled
                else EmbeddingModels.tenant_id.is_(None)
            )
            .order_by(
                EmbeddingModels.org,
                EmbeddingModels.created_at,
                EmbeddingModels.name,
            )
        )

        if not with_deprecated:
            stmt = stmt.where(EmbeddingModels.is_deprecated == False)  # noqa

        result = await self.session.execute(stmt)
        embedding_models = result.all()

        return [
            EmbeddingModel.to_domain(
                db_model=embedding_model,
                embedding_model_settings=embedding_model_settings,
                user=self.user,
            )
            for embedding_model, embedding_model_settings in embedding_models
        ]

    async def one_or_none(self, model_id: "UUID") -> Optional["EmbeddingModel"]:
        # When fetching by ID, return ANY model (global or tenant) that the user can access
        stmt = (
            sa.select(EmbeddingModels, EmbeddingModelSettings)
            .outerjoin(
                EmbeddingModelSettings,
                sa.and_(
                    EmbeddingModelSettings.embedding_model_id == EmbeddingModels.id,
                    EmbeddingModelSettings.tenant_id == self.user.tenant_id,
                ),
            )
            .options(
                selectinload(EmbeddingModelSettings.security_classification),
                selectinload(EmbeddingModelSettings.security_classification).options(
                    selectinload(SecurityClassification.tenant)
                ),
            )
            .where(
                EmbeddingModels.id == model_id,
                # Allow both global models (tenant_id IS NULL) and tenant models (tenant_id = user.tenant_id)
                sa.or_(
                    EmbeddingModels.tenant_id.is_(None),
                    EmbeddingModels.tenant_id == self.user.tenant_id
                )
            )
        )

        result = await self.session.execute(stmt)
        one_or_none = result.one_or_none()

        if one_or_none is None:
            return

        embedding_model, embedding_model_settings = one_or_none

        return EmbeddingModel.to_domain(
            db_model=embedding_model,
            embedding_model_settings=embedding_model_settings,
            user=self.user,
        )

    async def one(self, model_id: "UUID") -> "EmbeddingModel":
        embedding_model = await self.one_or_none(model_id=model_id)

        if embedding_model is None:
            raise NotFoundException()

        return embedding_model

    async def update(self, embedding_model: "EmbeddingModel"):
        stmt = sa.select(EmbeddingModelSettings).where(
            EmbeddingModelSettings.embedding_model_id == embedding_model.id,
            EmbeddingModelSettings.tenant_id == self.user.tenant_id,
        )
        result = await self.session.execute(stmt)
        existing_settings = result.scalars().one_or_none()

        # Extract security classification ID
        security_classification_id = (
            embedding_model.security_classification.id
            if embedding_model.security_classification
            else None
        )

        if existing_settings is None:
            stmt = sa.insert(EmbeddingModelSettings).values(
                embedding_model_id=embedding_model.id,
                tenant_id=self.user.tenant_id,
                is_org_enabled=embedding_model.is_org_enabled,
                security_classification_id=security_classification_id,
            )
            await self.session.execute(stmt)
        else:
            stmt = (
                sa.update(EmbeddingModelSettings)
                .values(
                    is_org_enabled=embedding_model.is_org_enabled,
                    security_classification_id=security_classification_id,
                )
                .where(
                    EmbeddingModelSettings.embedding_model_id == embedding_model.id,
                    EmbeddingModelSettings.tenant_id == self.user.tenant_id,
                )
            )
            await self.session.execute(stmt)

        return await self.one(model_id=embedding_model.id)
