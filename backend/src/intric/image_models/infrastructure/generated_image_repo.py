# Copyright (c) 2025 Sundsvalls Kommun
#
# Licensed under the MIT License.

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID

import sqlalchemy as sa

from intric.database.tables.image_models_table import GeneratedImages

if TYPE_CHECKING:
    from intric.database.database import AsyncSession


@dataclass
class GeneratedImage:
    """Domain object for a generated image."""

    id: UUID
    created_at: datetime
    tenant_id: UUID
    user_id: Optional[UUID]
    image_model_id: Optional[UUID]
    prompt: str
    revised_prompt: Optional[str]
    size: Optional[str]
    quality: Optional[str]
    blob: bytes
    mimetype: str
    file_size: int
    metadata: Optional[dict]


class GeneratedImageRepository:
    """Repository for storing and retrieving generated images."""

    def __init__(self, session: "AsyncSession"):
        self.session = session

    async def save(
        self,
        tenant_id: UUID,
        prompt: str,
        blob: bytes,
        mimetype: str,
        user_id: Optional[UUID] = None,
        image_model_id: Optional[UUID] = None,
        revised_prompt: Optional[str] = None,
        size: Optional[str] = None,
        quality: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> GeneratedImage:
        """Save a generated image to the database."""
        file_size = len(blob)

        stmt = (
            sa.insert(GeneratedImages)
            .values(
                tenant_id=tenant_id,
                user_id=user_id,
                image_model_id=image_model_id,
                prompt=prompt,
                revised_prompt=revised_prompt,
                size=size,
                quality=quality,
                blob=blob,
                mimetype=mimetype,
                file_size=file_size,
                metadata=metadata,
            )
            .returning(GeneratedImages)
        )

        result = await self.session.execute(stmt)
        db_image = result.scalar_one()

        return GeneratedImage(
            id=db_image.id,
            created_at=db_image.created_at,
            tenant_id=db_image.tenant_id,
            user_id=db_image.user_id,
            image_model_id=db_image.image_model_id,
            prompt=db_image.prompt,
            revised_prompt=db_image.revised_prompt,
            size=db_image.size,
            quality=db_image.quality,
            blob=db_image.blob,
            mimetype=db_image.mimetype,
            file_size=db_image.file_size,
            metadata=db_image.metadata,
        )

    async def get_by_id(self, image_id: UUID) -> Optional[GeneratedImage]:
        """Get a generated image by ID."""
        stmt = sa.select(GeneratedImages).where(GeneratedImages.id == image_id)
        result = await self.session.execute(stmt)
        db_image = result.scalar_one_or_none()

        if db_image is None:
            return None

        return GeneratedImage(
            id=db_image.id,
            created_at=db_image.created_at,
            tenant_id=db_image.tenant_id,
            user_id=db_image.user_id,
            image_model_id=db_image.image_model_id,
            prompt=db_image.prompt,
            revised_prompt=db_image.revised_prompt,
            size=db_image.size,
            quality=db_image.quality,
            blob=db_image.blob,
            mimetype=db_image.mimetype,
            file_size=db_image.file_size,
            metadata=db_image.metadata,
        )

    async def list_by_tenant(
        self,
        tenant_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[GeneratedImage]:
        """List generated images for a tenant."""
        stmt = (
            sa.select(GeneratedImages)
            .where(GeneratedImages.tenant_id == tenant_id)
            .order_by(GeneratedImages.created_at.desc())
            .limit(limit)
            .offset(offset)
        )

        result = await self.session.execute(stmt)
        db_images = result.scalars().all()

        return [
            GeneratedImage(
                id=db_image.id,
                created_at=db_image.created_at,
                tenant_id=db_image.tenant_id,
                user_id=db_image.user_id,
                image_model_id=db_image.image_model_id,
                prompt=db_image.prompt,
                revised_prompt=db_image.revised_prompt,
                size=db_image.size,
                quality=db_image.quality,
                blob=db_image.blob,
                mimetype=db_image.mimetype,
                file_size=db_image.file_size,
                metadata=db_image.metadata,
            )
            for db_image in db_images
        ]

    async def delete(self, image_id: UUID) -> None:
        """Delete a generated image."""
        stmt = sa.delete(GeneratedImages).where(GeneratedImages.id == image_id)
        await self.session.execute(stmt)
