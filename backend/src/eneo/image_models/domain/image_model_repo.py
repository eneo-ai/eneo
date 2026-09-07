from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from eneo.database.tables.ai_models_table import ImageModels
from eneo.database.tables.model_providers_table import ModelProviders
from eneo.database.tables.security_classifications_table import (
    SecurityClassification as SecurityClassificationDBModel,
)
from eneo.image_models.domain.image_model import ImageModel
from eneo.main.exceptions import NotFoundException

if TYPE_CHECKING:
    from uuid import UUID

    from eneo.database.database import AsyncSession
    from eneo.users.user import UserInDB


class ImageModelRepository:
    def __init__(self, session: "AsyncSession", user: "UserInDB") -> None:
        super().__init__()
        self.session = session
        self.user = user

    def _base_query(self):
        return (
            sa.select(ImageModels, ModelProviders.name, ModelProviders.provider_type)
            .outerjoin(ModelProviders, ImageModels.provider_id == ModelProviders.id)
            .options(
                selectinload(ImageModels.security_classification).options(
                    selectinload(SecurityClassificationDBModel.tenant)
                ),
            )
            .where(
                # Global and tenant models alike; UI filtering happens at the
                # presentation layer.
                sa.or_(
                    ImageModels.tenant_id.is_(None),
                    ImageModels.tenant_id == self.user.tenant_id,
                ),
                # Soft-deleted models are tombstones; never surface them.
                ImageModels.deleted_at.is_(None),
            )
        )

    async def all(self, with_deprecated: bool = False) -> list[ImageModel]:
        stmt = self._base_query().order_by(
            ImageModels.org, ImageModels.created_at, ImageModels.name
        )
        if not with_deprecated:
            stmt = stmt.where(ImageModels.is_deprecated == False)  # noqa: E712

        result = await self.session.execute(stmt)
        return [
            ImageModel.create_from_db(
                image_model_db=image_model,
                user=self.user,
                provider_name=provider_name,
                provider_type=provider_type,
            )
            for image_model, provider_name, provider_type in result.all()
        ]

    async def one_or_none(self, model_id: "UUID") -> Optional[ImageModel]:
        stmt = self._base_query().where(ImageModels.id == model_id)
        result = await self.session.execute(stmt)
        row = result.one_or_none()
        if row is None:
            return None

        image_model, provider_name, provider_type = row
        return ImageModel.create_from_db(
            image_model_db=image_model,
            user=self.user,
            provider_name=provider_name,
            provider_type=provider_type,
        )

    async def one(self, model_id: "UUID") -> ImageModel:
        image_model = await self.one_or_none(model_id=model_id)
        if image_model is None:
            raise NotFoundException()
        return image_model

    async def update(self, image_model: ImageModel) -> None:
        stmt = (
            sa.update(ImageModels)
            .values(
                is_enabled=image_model.is_org_enabled,
                is_default=image_model.is_org_default,
                security_classification_id=(
                    image_model.security_classification.id
                    if image_model.security_classification
                    else None
                ),
            )
            .where(
                ImageModels.id == image_model.id,
                ImageModels.tenant_id == self.user.tenant_id,
            )
        )
        await self.session.execute(stmt)

        if image_model.is_org_default:
            stmt = (
                sa.update(ImageModels)
                .values(is_default=False)
                .where(
                    ImageModels.id != image_model.id,
                    ImageModels.tenant_id == self.user.tenant_id,
                )
            )
            await self.session.execute(stmt)
