from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from intric.database.tables.ai_models_table import EmbeddingModels
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
        stmt = (
            sa.select(EmbeddingModels)
            .options(
                selectinload(EmbeddingModels.security_classification),
                selectinload(EmbeddingModels.security_classification).options(
                    selectinload(SecurityClassification.tenant)
                ),
            )
            .where(
                # Return both global and tenant models
                # This allows existing collections with global models to continue working
                # UI filtering happens at the presentation layer
                sa.or_(
                    EmbeddingModels.tenant_id.is_(None),
                    EmbeddingModels.tenant_id == self.user.tenant_id
                )
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
        embedding_models = result.scalars().all()

        return [
            EmbeddingModel.to_domain(
                db_model=embedding_model,
                user=self.user,
            )
            for embedding_model in embedding_models
        ]

    async def one_or_none(self, model_id: "UUID") -> Optional["EmbeddingModel"]:
        # When fetching by ID, return ANY model (global or tenant) that the user can access
        stmt = (
            sa.select(EmbeddingModels)
            .options(
                selectinload(EmbeddingModels.security_classification),
                selectinload(EmbeddingModels.security_classification).options(
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
        embedding_model = result.scalars().one_or_none()

        if embedding_model is None:
            return

        return EmbeddingModel.to_domain(
            db_model=embedding_model,
            user=self.user,
        )

    async def one(self, model_id: "UUID") -> "EmbeddingModel":
        embedding_model = await self.one_or_none(model_id=model_id)

        if embedding_model is None:
            raise NotFoundException()

        return embedding_model

    async def update(self, embedding_model: "EmbeddingModel"):
        # Update settings directly on the model table
        security_classification_id = (
            embedding_model.security_classification.id
            if embedding_model.security_classification
            else None
        )

        stmt = (
            sa.update(EmbeddingModels)
            .values(
                is_enabled=embedding_model.is_org_enabled,
                security_classification_id=security_classification_id,
            )
            .where(
                EmbeddingModels.id == embedding_model.id,
                EmbeddingModels.tenant_id == self.user.tenant_id,
            )
        )
        await self.session.execute(stmt)

        return await self.one(model_id=embedding_model.id)
