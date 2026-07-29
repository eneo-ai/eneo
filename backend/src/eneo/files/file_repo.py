from dataclasses import dataclass
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import Select
from sqlalchemy.orm import aliased

from eneo.database.database import AsyncSession
from eneo.database.tables.files_table import Files
from eneo.database.tables.object_content_table import (
    FileContentReferences,
    ObjectContents,
)
from eneo.files.file_models import (
    FileContentVariant,
    FileInfo,
    FileMetadata,
    FileMetadataCreate,
    FileType,
)
from eneo.main.exceptions import NotFoundException
from eneo.object_content.content import ContentAccessClass, ContentState


@dataclass(frozen=True, slots=True)
class FileContentReferenceRecord:
    file_id: UUID
    content_id: UUID
    variant: FileContentVariant
    ordinal: int
    page_number: int | None
    width: int | None
    height: int | None
    duration_ms: int | None
    sha256: bytes
    size_bytes: int
    media_type: str
    access_class: ContentAccessClass


_PRIMARY_VARIANTS = (
    FileContentVariant.ORIGINAL,
    FileContentVariant.GENERATED_ARTIFACT,
    FileContentVariant.DERIVED_PAGE,
    FileContentVariant.MODEL_INPUT,
    FileContentVariant.EXTRACTED_TEXT,
)
_IMAGE_INPUT_VARIANTS = (
    FileContentVariant.MODEL_INPUT,
    FileContentVariant.DERIVED_PAGE,
    FileContentVariant.GENERATED_ARTIFACT,
    FileContentVariant.ORIGINAL,
    FileContentVariant.LEGACY_IMAGE,
)


def select_primary_file_reference(
    file_type: FileType,
    references: list[FileContentReferenceRecord],
) -> FileContentReferenceRecord | None:
    if file_type is FileType.TEXT:
        variants = (
            FileContentVariant.EXTRACTED_TEXT,
            FileContentVariant.ORIGINAL,
        )
    elif file_type is FileType.IMAGE:
        variants = _IMAGE_INPUT_VARIANTS
    else:
        variants = (FileContentVariant.ORIGINAL,)

    for variant in (*variants, *_PRIMARY_VARIANTS):
        reference = next(
            (candidate for candidate in references if candidate.variant is variant),
            None,
        )
        if reference is not None:
            return reference
    return None


def select_binary_file_reference(
    file_type: FileType,
    references: list[FileContentReferenceRecord],
) -> FileContentReferenceRecord | None:
    variants = (
        _IMAGE_INPUT_VARIANTS
        if file_type is FileType.IMAGE
        else (FileContentVariant.ORIGINAL,)
    )
    for variant in variants:
        reference = next(
            (candidate for candidate in references if candidate.variant is variant),
            None,
        )
        if reference is not None:
            return reference
    return None


def project_file_info(
    file: FileMetadata,
    references: list[FileContentReferenceRecord],
) -> FileInfo:
    primary = select_primary_file_reference(file.file_type, references)
    if primary is None:
        raise NotFoundException(f"File {file.id} has no durable content")
    return FileInfo(
        id=file.id,
        created_at=file.created_at,
        updated_at=file.updated_at,
        name=file.name,
        checksum=primary.sha256.hex(),
        size=primary.size_bytes,
        mimetype=project_file_media_type(file, primary),
        file_type=file.file_type,
        user_id=file.user_id,
        tenant_id=file.tenant_id,
    )


def project_file_media_type(
    file: FileMetadata,
    reference: FileContentReferenceRecord,
) -> str:
    """Project the media type users supplied, except for transformed images."""
    if file.file_type is FileType.IMAGE:
        return reference.media_type
    return file.mimetype or reference.media_type


class FileRepository:
    """Persist File identity and its typed durable-content references."""

    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _visible_family(file: type[Files] = Files):
        root_id = sa.case(
            (file.parent_file_id.is_(None), file.id),
            else_=file.parent_file_id,
        )
        family_member = aliased(Files)
        family_reference = aliased(FileContentReferences)
        family_ids = (
            sa.select(family_member.id)
            .where(
                sa.or_(
                    family_member.id == root_id,
                    family_member.parent_file_id == root_id,
                )
            )
            .correlate(file)
        )
        root_has_content = sa.exists().where(FileContentReferences.file_id == root_id)
        referenced_content_state = (
            sa.select(ObjectContents.state)
            .where(ObjectContents.id == family_reference.content_id)
            .correlate(family_reference)
            .scalar_subquery()
        )
        unavailable_content = (
            sa.exists()
            .where(
                family_reference.file_id.in_(family_ids),
                referenced_content_state != ContentState.AVAILABLE.value,
            )
            .correlate(file)
        )
        return sa.and_(root_has_content.correlate(file), ~unavailable_content)

    def _visible_children_query(
        self,
        *,
        parent_ids: list[UUID],
        user_id: UUID | None = None,
        tenant_id: UUID | None = None,
        file_type: FileType | None = None,
    ) -> Select[tuple[Files]]:
        parent = aliased(Files)
        query = (
            sa.select(Files)
            .join(parent, Files.parent_file_id == parent.id)
            .where(
                Files.parent_file_id.in_(parent_ids),
                Files.user_id == parent.user_id,
                Files.tenant_id == parent.tenant_id,
                self._visible_family(),
            )
        )
        if user_id is not None:
            query = query.where(parent.user_id == user_id)
        if tenant_id is not None:
            query = query.where(parent.tenant_id == tenant_id)
        if file_type is not None:
            query = query.where(Files.file_type == file_type.value)
        return query.order_by(Files.created_at, Files.id)

    async def add_metadata(self, file: FileMetadataCreate) -> FileMetadata:
        row = Files(**file.model_dump())
        self.session.add(row)
        await self.session.flush()
        return FileMetadata.model_validate(row)

    async def add_content_reference(
        self,
        *,
        file_id: UUID,
        content_id: UUID,
        variant: FileContentVariant,
        ordinal: int = 0,
        page_number: int | None = None,
        width: int | None = None,
        height: int | None = None,
        duration_ms: int | None = None,
    ) -> None:
        reference = FileContentReferences()
        reference.file_id = file_id
        reference.content_id = content_id
        reference.variant = variant.value
        reference.ordinal = ordinal
        reference.page_number = page_number
        reference.width = width
        reference.height = height
        reference.duration_ms = duration_ms
        self.session.add(reference)
        await self.session.flush()

    async def get_list_by_id_and_user(
        self,
        ids: list[UUID],
        user_id: UUID,
    ) -> list[FileMetadata]:
        if not ids:
            return []
        rows = await self.session.scalars(
            sa.select(Files)
            .where(
                Files.id.in_(ids),
                Files.user_id == user_id,
                self._visible_family(),
            )
            .order_by(Files.created_at)
        )
        return [FileMetadata.model_validate(row) for row in rows]

    async def get_by_ids(self, ids: list[UUID]) -> list[FileMetadata]:
        if not ids:
            return []
        rows = await self.session.scalars(
            sa.select(Files)
            .where(Files.id.in_(ids), self._visible_family())
            .order_by(Files.created_at)
        )
        return [FileMetadata.model_validate(row) for row in rows]

    async def get_by_parent_ids(
        self,
        parent_ids: list[UUID],
        user_id: UUID,
    ) -> list[FileMetadata]:
        if not parent_ids:
            return []
        rows = await self.session.scalars(
            self._visible_children_query(
                parent_ids=parent_ids,
                user_id=user_id,
            )
        )
        return [FileMetadata.model_validate(row) for row in rows]

    async def get_visible_derived_images_for_attached_roots(
        self,
        *,
        parent_ids: list[UUID],
        tenant_id: UUID,
    ) -> list[FileMetadata]:
        if not parent_ids:
            return []
        rows = await self.session.scalars(
            self._visible_children_query(
                parent_ids=parent_ids,
                tenant_id=tenant_id,
                file_type=FileType.IMAGE,
            )
        )
        return [FileMetadata.model_validate(row) for row in rows]

    async def get_by_id(self, file_id: UUID) -> FileMetadata:
        row = await self.session.scalar(
            sa.select(Files).where(Files.id == file_id, self._visible_family())
        )
        if row is None:
            raise NotFoundException()
        return FileMetadata.model_validate(row)

    async def get_by_id_for_update(self, file_id: UUID) -> FileMetadata:
        row = await self.session.scalar(
            sa.select(Files)
            .where(Files.id == file_id, self._visible_family())
            .with_for_update()
        )
        if row is None:
            raise NotFoundException()
        return FileMetadata.model_validate(row)

    async def get_by_id_and_owner_for_lifecycle(
        self,
        *,
        file_id: UUID,
        user_id: UUID,
        tenant_id: UUID,
    ) -> FileMetadata | None:
        row = await self.session.scalar(
            sa.select(Files).where(
                Files.id == file_id,
                Files.user_id == user_id,
                Files.tenant_id == tenant_id,
            )
        )
        return None if row is None else FileMetadata.model_validate(row)

    async def get_list_by_user(self, user_id: UUID) -> list[FileMetadata]:
        rows = await self.session.scalars(
            sa.select(Files)
            .where(
                Files.user_id == user_id,
                Files.parent_file_id.is_(None),
                self._visible_family(),
            )
            .order_by(Files.created_at)
        )
        return [FileMetadata.model_validate(row) for row in rows]

    async def get_by_id_for_lifecycle(self, file_id: UUID) -> FileMetadata | None:
        row = await self.session.get(Files, file_id)
        return None if row is None else FileMetadata.model_validate(row)

    async def get_content_references(
        self,
        file_ids: list[UUID],
    ) -> list[FileContentReferenceRecord]:
        if not file_ids:
            return []
        rows = await self.session.execute(
            sa.select(
                FileContentReferences.file_id,
                FileContentReferences.content_id,
                FileContentReferences.variant,
                FileContentReferences.ordinal,
                FileContentReferences.page_number,
                FileContentReferences.width,
                FileContentReferences.height,
                FileContentReferences.duration_ms,
                ObjectContents.sha256,
                ObjectContents.size_bytes,
                ObjectContents.verified_media_type,
                ObjectContents.access_class,
            )
            .join(
                ObjectContents,
                ObjectContents.id == FileContentReferences.content_id,
            )
            .where(FileContentReferences.file_id.in_(file_ids))
            .order_by(
                FileContentReferences.file_id,
                FileContentReferences.variant,
                FileContentReferences.ordinal,
            )
        )
        return [
            FileContentReferenceRecord(
                file_id=row.file_id,
                content_id=row.content_id,
                variant=FileContentVariant(row.variant),
                ordinal=row.ordinal,
                page_number=row.page_number,
                width=row.width,
                height=row.height,
                duration_ms=row.duration_ms,
                sha256=row.sha256,
                size_bytes=row.size_bytes,
                media_type=row.verified_media_type,
                access_class=ContentAccessClass(row.access_class),
            )
            for row in rows
        ]

    async def get_infos_by_ids(self, file_ids: list[UUID]) -> list[FileInfo]:
        metadata = await self.get_by_ids(file_ids)
        references = await self.get_content_references([file.id for file in metadata])
        by_file: dict[UUID, list[FileContentReferenceRecord]] = {
            file.id: [] for file in metadata
        }
        for reference in references:
            by_file[reference.file_id].append(reference)
        return [project_file_info(file, by_file[file.id]) for file in metadata]

    async def delete_by_owner_for_lifecycle(
        self,
        id: UUID,
        user_id: UUID,
        tenant_id: UUID,
    ) -> FileMetadata | None:
        row = (
            await self.session.execute(
                sa.delete(Files)
                .where(
                    Files.id == id,
                    Files.user_id == user_id,
                    Files.tenant_id == tenant_id,
                )
                .returning(Files)
            )
        ).scalar_one_or_none()
        return None if row is None else FileMetadata.model_validate(row)
