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
from eneo.icons.icon import IconMetadata, IconMetadataCreate, IconNotAttachableError
from eneo.main.models import NotProvided, is_provided
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

    async def delete_if_unreferenced(
        self, icon_id: UUID, *, tenant_id: UUID | None = None
    ) -> bool:
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
                    *([Icons.tenant_id == tenant_id] if tenant_id is not None else []),
                    *(
                        ~sa.exists().where(column == Icons.id)
                        for column in ICON_REFERENCES
                    ),
                )
                .returning(Icons.id)
            )
        ).scalar_one_or_none()
        return deleted_id is not None

    async def lock_for_change(
        self, previous: UUID | None, requested: UUID | None
    ) -> None:
        """Lock the icons an update swaps, in id order, so two updates swapping
        icons cannot deadlock. The previous icon is locked FOR UPDATE, as its
        release may delete it; the requested one FOR KEY SHARE, as the foreign
        key check would, so a concurrent delete either commits first or waits.

        Callers lock the resource row first and read ``previous`` under that lock.
        """
        for icon_id in sorted(i for i in (previous, requested) if i is not None):
            shared = icon_id != previous
            await self.session.execute(
                sa.select(Icons.id)
                .where(Icons.id == icon_id)
                .with_for_update(read=shared, key_share=shared)
            )

    async def ensure_attachable(
        self,
        previous: UUID | None,
        requested: UUID | None | NotProvided,
        *,
        tenant_id: UUID,
        user_id: UUID,
    ) -> None:
        """Lock the icons of an icon change, then refuse it if the user did not
        upload the new icon in their tenant. Icon ids are public, so showing
        someone else's icon would also keep it from being deleted. Sending the
        current icon again is fine. Call after locking the resource row."""
        if not is_provided(requested) or requested == previous:
            return
        await self.lock_for_change(previous, requested)
        if requested is None:
            return
        uploaded = await self.session.scalar(
            sa.select(Icons.id)
            .join(
                IconContentReferences,
                sa.and_(
                    IconContentReferences.icon_id == Icons.id,
                    IconContentReferences.variant == "primary",
                ),
            )
            .join(ObjectContents, ObjectContents.id == IconContentReferences.content_id)
            .where(
                Icons.id == requested,
                Icons.tenant_id == tenant_id,
                ObjectContents.created_by_user_id == user_id,
            )
        )
        if uploaded is None:
            raise IconNotAttachableError()

    async def release_replaced(
        self, previous: UUID | None, requested: UUID | None | NotProvided
    ) -> None:
        """Delete the icon an update replaced or cleared, unless another resource
        still shows it. Call after the update is written."""
        if previous is None or not is_provided(requested) or requested == previous:
            return
        await self.delete_if_unreferenced(previous)

    async def lock_shown_in_space(self, space_id: UUID) -> list[UUID]:
        """Lock the space, then the assistants, apps and group chats in it, as
        deleting the space would, and return the icons they show in id order.
        Their icons cannot change until the delete commits."""
        icon_ids: set[UUID | None] = set()
        for shown in (
            sa.select(Spaces.icon_id).where(Spaces.id == space_id),
            sa.select(Assistants.icon_id).where(Assistants.space_id == space_id),
            sa.select(Apps.icon_id).where(Apps.space_id == space_id),
            sa.select(GroupChatsTable.icon_id).where(
                GroupChatsTable.space_id == space_id
            ),
        ):
            icon_ids.update(await self.session.scalars(shown.with_for_update()))
        return sorted(icon_id for icon_id in icon_ids if icon_id is not None)
