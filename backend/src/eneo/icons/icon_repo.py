from dataclasses import dataclass
from uuid import UUID

import sqlalchemy as sa

from eneo.database.database import AsyncSession
from eneo.database.tables.icons_table import Icons
from eneo.database.tables.object_content_table import (
    IconContentReferences,
    ObjectContents,
)
from eneo.icons.icon import IconMetadata, IconMetadataCreate
from eneo.object_content.content import ContentAccessClass


@dataclass(frozen=True, slots=True)
class IconContentReferenceRecord:
    content_id: UUID
    sha256: bytes
    size_bytes: int
    media_type: str
    access_class: ContentAccessClass


class IconRepository:
    """Persist Icon identity and its primary durable-content reference."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_metadata(self, icon: IconMetadataCreate) -> IconMetadata:
        row = Icons(**icon.model_dump())
        self.session.add(row)
        await self.session.flush()
        return IconMetadata.model_validate(row)

    async def add_primary_reference(
        self,
        *,
        icon_id: UUID,
        content_id: UUID,
    ) -> None:
        reference = IconContentReferences()
        reference.icon_id = icon_id
        reference.content_id = content_id
        reference.variant = "primary"
        self.session.add(reference)
        await self.session.flush()

    async def get(self, icon_id: UUID) -> IconMetadata | None:
        row = await self.session.get(Icons, icon_id)
        return None if row is None else IconMetadata.model_validate(row)

    async def get_primary_reference(
        self,
        icon_id: UUID,
    ) -> IconContentReferenceRecord | None:
        row = (
            await self.session.execute(
                sa.select(
                    IconContentReferences.content_id,
                    ObjectContents.sha256,
                    ObjectContents.size_bytes,
                    ObjectContents.verified_media_type,
                    ObjectContents.access_class,
                )
                .join(
                    ObjectContents,
                    ObjectContents.id == IconContentReferences.content_id,
                )
                .where(
                    IconContentReferences.icon_id == icon_id,
                    IconContentReferences.variant == "primary",
                )
            )
        ).one_or_none()
        if row is None:
            return None
        return IconContentReferenceRecord(
            content_id=row.content_id,
            sha256=row.sha256,
            size_bytes=row.size_bytes,
            media_type=row.verified_media_type,
            access_class=ContentAccessClass(row.access_class),
        )

    async def delete_by_tenant(self, icon_id: UUID, tenant_id: UUID) -> bool:
        deleted_id = (
            await self.session.execute(
                sa.delete(Icons)
                .where(Icons.id == icon_id, Icons.tenant_id == tenant_id)
                .returning(Icons.id)
            )
        ).scalar_one_or_none()
        return deleted_id is not None

    async def delete(self, icon_id: UUID) -> None:
        """Delete an icon after its owning aggregate has authorized removal."""
        await self.session.execute(sa.delete(Icons).where(Icons.id == icon_id))
