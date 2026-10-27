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

# Every column that shows an icon. Their foreign keys are ON DELETE SET NULL and
# icon ids are public, so an icon is only deleted once none of them references it.
ICON_REFERENCES = (
    Assistants.icon_id,
    Apps.icon_id,
    Spaces.icon_id,
    GroupChatsTable.icon_id,
)


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

    async def get_for_lifecycle(
        self, icon_id: UUID, *, lock: bool = False
    ) -> IconMetadata | None:
        """With ``lock``, wait for a concurrent delete, so a deleted icon reads as gone."""
        if lock:
            row = await self.session.scalar(
                sa.select(Icons)
                .where(Icons.id == icon_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        else:
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

    async def delete_if_unreferenced(self, icon_id: UUID) -> bool:
        """Delete the icon unless a resource still shows it; returns whether it did.

        Must run inside a transaction.
        """
        # Lock first, then check in a separate statement. Under READ COMMITTED a
        # single DELETE … WHERE NOT EXISTS evaluates the check on its starting
        # snapshot even after waiting for a concurrent attach to commit, and the
        # SET NULL cascade would then clear that attach. With the lock, an attach
        # either commits before the check reads, or waits and fails its FK check.
        await self.session.execute(
            sa.select(Icons.id).where(Icons.id == icon_id).with_for_update()
        )
        deleted_id = (
            await self.session.execute(
                sa.delete(Icons)
                .where(
                    Icons.id == icon_id,
                    *(
                        ~sa.exists().where(column == Icons.id)
                        for column in ICON_REFERENCES
                    ),
                )
                .returning(Icons.id)
            )
        ).scalar_one_or_none()
        return deleted_id is not None
