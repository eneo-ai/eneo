# Copyright (c) 2025 Sundsvalls Kommun
#
# Licensed under the MIT License.

from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from intric.database.tables.image_models_table import (
    ImageModels,
    ImageModelSettings,
)
from intric.database.tables.security_classifications_table import (
    SecurityClassification as SecurityClassificationDBModel,
)
from intric.image_models.domain.image_model import ImageModel
from intric.main.exceptions import NotFoundException

if TYPE_CHECKING:
    from uuid import UUID

    from intric.database.database import AsyncSession
    from intric.users.user import UserInDB


class ImageModelRepository:
    """Repository for image generation models."""

    def __init__(self, session: "AsyncSession", user: "UserInDB"):
        self.session = session
        self.user = user

    async def all(self, with_deprecated: bool = False) -> list[ImageModel]:
        """Get all image models with tenant-specific settings."""
        stmt = (
            sa.select(ImageModels, ImageModelSettings)
            .outerjoin(
                ImageModelSettings,
                sa.and_(
                    ImageModelSettings.image_model_id == ImageModels.id,
                    ImageModelSettings.tenant_id == self.user.tenant_id,
                ),
            )
            .options(
                selectinload(ImageModelSettings.security_classification),
                selectinload(
                    ImageModelSettings.security_classification
                ).options(selectinload(SecurityClassificationDBModel.tenant)),
            )
            .order_by(
                ImageModels.org,
                ImageModels.created_at,
                ImageModels.name,
            )
        )

        if not with_deprecated:
            stmt = stmt.where(ImageModels.is_deprecated == False)  # noqa

        result = await self.session.execute(stmt)
        image_models = result.all()

        return [
            ImageModel.create_from_db(
                image_model_db=image_model,
                image_model_settings=image_model_settings,
                user=self.user,
            )
            for image_model, image_model_settings in image_models
        ]

    async def one_or_none(self, model_id: "UUID") -> Optional[ImageModel]:
        """Get a single image model by ID, or None if not found."""
        stmt = (
            sa.select(ImageModels, ImageModelSettings)
            .outerjoin(
                ImageModelSettings,
                sa.and_(
                    ImageModelSettings.image_model_id == ImageModels.id,
                    ImageModelSettings.tenant_id == self.user.tenant_id,
                ),
            )
            .options(
                selectinload(ImageModelSettings.security_classification),
                selectinload(
                    ImageModelSettings.security_classification
                ).options(selectinload(SecurityClassificationDBModel.tenant)),
            )
            .where(ImageModels.id == model_id)
        )

        result = await self.session.execute(stmt)
        one_or_none = result.one_or_none()

        if one_or_none is None:
            return None

        image_model, image_model_settings = one_or_none

        return ImageModel.create_from_db(
            image_model_db=image_model,
            image_model_settings=image_model_settings,
            user=self.user,
        )

    async def one(self, model_id: "UUID") -> ImageModel:
        """Get a single image model by ID, raising NotFoundException if not found."""
        image_model = await self.one_or_none(model_id=model_id)

        if image_model is None:
            raise NotFoundException(f"Image model with ID {model_id} not found")

        return image_model

    async def update(self, image_model: ImageModel) -> None:
        """Update tenant-specific settings for an image model."""
        stmt = sa.select(ImageModelSettings).where(
            ImageModelSettings.image_model_id == image_model.id,
            ImageModelSettings.tenant_id == self.user.tenant_id,
        )
        result = await self.session.execute(stmt)
        existing_settings = result.scalars().one_or_none()

        if existing_settings is None:
            # Create new settings for this tenant
            stmt = sa.insert(ImageModelSettings).values(
                image_model_id=image_model.id,
                tenant_id=self.user.tenant_id,
                is_org_enabled=image_model.is_org_enabled,
                is_org_default=image_model.is_org_default,
                security_classification_id=(
                    image_model.security_classification.id
                    if image_model.security_classification
                    else None
                ),
            )
            await self.session.execute(stmt)

        else:
            # Update existing settings
            stmt = (
                sa.update(ImageModelSettings)
                .values(
                    is_org_enabled=image_model.is_org_enabled,
                    is_org_default=image_model.is_org_default,
                    security_classification_id=(
                        image_model.security_classification.id
                        if image_model.security_classification
                        else None
                    ),
                )
                .where(
                    ImageModelSettings.image_model_id == image_model.id,
                    ImageModelSettings.tenant_id == self.user.tenant_id,
                )
            )
            await self.session.execute(stmt)

        # If this model is set as default, unset all other models
        if image_model.is_org_default:
            stmt = (
                sa.update(ImageModelSettings)
                .values(is_org_default=False)
                .where(
                    ImageModelSettings.image_model_id != image_model.id,
                    ImageModelSettings.tenant_id == self.user.tenant_id,
                )
            )
            await self.session.execute(stmt)
