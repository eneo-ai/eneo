from dataclasses import dataclass
from uuid import UUID

import sqlalchemy as sa

from eneo.database.database import AsyncSession
from eneo.database.tables.app_table import Apps
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.group_chats_table import GroupChatsTable
from eneo.database.tables.icons_table import Icons
from eneo.database.tables.object_content_table import (
    IconContentReferences,
    ObjectContents,
)
from eneo.database.tables.spaces_table import Spaces
from eneo.icons.icon import IconMetadata, IconMetadataCreate
from eneo.object_content.content import ContentAccessClass, ContentState
from eneo.object_content.file_icon_cleanup import file_icon_legacy_is_cleaned


@dataclass(frozen=True, slots=True)
class IconContentReferenceRecord:
    content_id: UUID
    sha256: bytes
    size_bytes: int
    media_type: str
    access_class: ContentAccessClass


@dataclass(frozen=True, slots=True)
class LegacyIconContentRecord:
    payload: bytes
    media_type: str


# Every column through which a resource uses an icon. Icon content references
# belong to the icon itself and go with it.
ICON_USER_COLUMNS = (
    Apps.icon_id,
    Assistants.icon_id,
    GroupChatsTable.icon_id,
    Spaces.icon_id,
)


class IconRepository:
    """Persist Icon identity and its primary durable-content reference."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_metadata(self, icon: IconMetadataCreate) -> IconMetadata:
        row = (
            await self.session.execute(
                sa.insert(Icons)
                .values(**icon.model_dump())
                .returning(
                    Icons.id,
                    Icons.created_at,
                    Icons.updated_at,
                    Icons.tenant_id,
                )
            )
        ).one()
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
        available_reference = sa.exists(
            sa.select(1)
            .select_from(IconContentReferences)
            .join(
                ObjectContents,
                ObjectContents.id == IconContentReferences.content_id,
            )
            .where(
                IconContentReferences.icon_id == Icons.id,
                IconContentReferences.variant == "primary",
                ObjectContents.state == ContentState.AVAILABLE.value,
            )
        )
        visible = available_reference
        if not await file_icon_legacy_is_cleaned(self.session):
            visible = sa.or_(visible, Icons.legacy_blob.is_not(None))
        row = await self.session.scalar(
            sa.select(Icons).where(
                Icons.id == icon_id,
                visible,
            )
        )
        return None if row is None else IconMetadata.model_validate(row)

    async def get_for_lifecycle(self, icon_id: UUID) -> IconMetadata | None:
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

    async def get_legacy_primary(
        self,
        icon_id: UUID,
    ) -> LegacyIconContentRecord | None:
        if await file_icon_legacy_is_cleaned(self.session):
            return None
        row = (
            await self.session.execute(
                sa.select(
                    Icons.legacy_blob,
                    Icons.legacy_mimetype,
                ).where(Icons.id == icon_id)
            )
        ).one_or_none()
        if row is None or row.legacy_blob is None or row.legacy_mimetype is None:
            return None
        return LegacyIconContentRecord(
            payload=bytes(row.legacy_blob),
            media_type=row.legacy_mimetype,
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

    async def delete_unused(self, icon_id: UUID, *, tenant_id: UUID) -> None:
        """Delete an icon of ``tenant_id`` that no resource uses any more.

        A resource's icon_id can name any icon, including another tenant's or
        one a space still shows, so removing the resource deletes the icon only
        when it is the tenant's own and nothing else uses it.
        """
        await self.session.execute(
            sa.delete(Icons)
            .where(Icons.id == icon_id, Icons.tenant_id == tenant_id)
            .where(
                *(~sa.exists().where(column == icon_id) for column in ICON_USER_COLUMNS)
            )
        )
