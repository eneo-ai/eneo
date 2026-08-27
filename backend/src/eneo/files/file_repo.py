from collections import defaultdict
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import TypeVar
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
from eneo.object_content.content import ByteRange, ContentAccessClass, ContentState


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


@dataclass(frozen=True, slots=True)
class LegacyFileContentRecord:
    """Frozen Release A payload used until its object-content reference exists."""

    file_id: UUID
    variant: FileContentVariant
    payload: bytes
    media_type: str

    @property
    def sha256(self) -> bytes:
        return sha256(self.payload).digest()

    @property
    def size_bytes(self) -> int:
        return len(self.payload)


@dataclass(frozen=True, slots=True)
class LegacyFileInfoRecord:
    """Legacy integrity facts that do not require detoasting payload bytes."""

    file_id: UUID
    variant: FileContentVariant
    checksum: str
    size_bytes: int
    media_type: str
    original_available: bool
    transcription_available: bool

    @property
    def sha256(self) -> bytes:
        return bytes.fromhex(self.checksum)


@dataclass(frozen=True, slots=True)
class LegacyAudioSlice:
    payload: bytes
    media_type: str


LegacyContentT = TypeVar(
    "LegacyContentT",
    bound=LegacyFileContentRecord | LegacyFileInfoRecord,
)


@dataclass(frozen=True, slots=True)
class AttachedDerivedImageProjection:
    derived_images: tuple[FileMetadata, ...]
    unstable_parent_ids: frozenset[UUID]


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


def primary_file_variants(file_type: FileType) -> tuple[FileContentVariant, ...]:
    if file_type is FileType.TEXT:
        variants = (
            FileContentVariant.EXTRACTED_TEXT,
            FileContentVariant.ORIGINAL,
        )
    elif file_type is FileType.IMAGE:
        variants = _IMAGE_INPUT_VARIANTS
    else:
        variants = (FileContentVariant.ORIGINAL,)
    return tuple(dict.fromkeys((*variants, *_PRIMARY_VARIANTS)))


def binary_file_variants(file_type: FileType) -> tuple[FileContentVariant, ...]:
    return (
        _IMAGE_INPUT_VARIANTS
        if file_type is FileType.IMAGE
        else (FileContentVariant.ORIGINAL,)
    )


def legacy_primary_file_variant(
    file_type: FileType,
    *,
    parent_file_id: UUID | None,
) -> FileContentVariant:
    if file_type is FileType.TEXT:
        return FileContentVariant.EXTRACTED_TEXT
    if file_type is FileType.AUDIO:
        return FileContentVariant.ORIGINAL
    if parent_file_id is not None:
        return FileContentVariant.DERIVED_PAGE
    return FileContentVariant.LEGACY_IMAGE


def select_primary_file_reference(
    file_type: FileType,
    references: list[FileContentReferenceRecord],
) -> FileContentReferenceRecord | None:
    for variant in primary_file_variants(file_type):
        reference = next(
            (candidate for candidate in references if candidate.variant is variant),
            None,
        )
        if reference is not None:
            return reference
    return None


def select_file_content_variant(
    references: list[FileContentReferenceRecord],
    legacy_content: Sequence[LegacyContentT],
    variant: FileContentVariant,
) -> FileContentReferenceRecord | LegacyContentT | None:
    reference = next(
        (candidate for candidate in references if candidate.variant is variant),
        None,
    )
    if reference is not None:
        return reference
    return next(
        (candidate for candidate in legacy_content if candidate.variant is variant),
        None,
    )


def select_primary_file_content(
    file_type: FileType,
    references: list[FileContentReferenceRecord],
    legacy_content: Sequence[LegacyContentT],
) -> FileContentReferenceRecord | LegacyContentT | None:
    for variant in primary_file_variants(file_type):
        content = select_file_content_variant(references, legacy_content, variant)
        if content is not None:
            return content
    return None


def select_binary_file_reference(
    file_type: FileType,
    references: list[FileContentReferenceRecord],
) -> FileContentReferenceRecord | None:
    for variant in binary_file_variants(file_type):
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
    legacy_content: Sequence[LegacyFileContentRecord | LegacyFileInfoRecord]
    | None = None,
) -> FileInfo:
    primary = select_primary_file_content(
        file.file_type,
        references,
        legacy_content or [],
    )
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
    reference: (
        FileContentReferenceRecord | LegacyFileContentRecord | LegacyFileInfoRecord
    ),
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
    def _family_has_content_state(
        file: type[Files],
        *,
        state: ContentState,
        matches: bool,
    ):
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
        referenced_content_state = (
            sa.select(ObjectContents.state)
            .where(ObjectContents.id == family_reference.content_id)
            .correlate(family_reference)
            .scalar_subquery()
        )
        state_condition = (
            referenced_content_state == state.value
            if matches
            else referenced_content_state != state.value
        )
        return (
            sa.exists()
            .where(
                family_reference.file_id.in_(family_ids),
                state_condition,
            )
            .correlate(file)
        )

    @staticmethod
    def _family_has_unavailable_content(file: type[Files] = Files):
        return FileRepository._family_has_content_state(
            file,
            state=ContentState.AVAILABLE,
            matches=False,
        )

    @staticmethod
    def _family_has_pending_content(file: type[Files] = Files):
        return FileRepository._family_has_content_state(
            file,
            state=ContentState.PENDING,
            matches=True,
        )

    @staticmethod
    def _visible_family(file: type[Files] = Files):
        root_id = sa.case(
            (file.parent_file_id.is_(None), file.id),
            else_=file.parent_file_id,
        )
        root_has_content = sa.exists().where(FileContentReferences.file_id == root_id)
        legacy_root = aliased(Files)
        root_has_legacy = sa.exists().where(
            legacy_root.id == root_id,
            sa.or_(
                legacy_root.legacy_text.is_not(None),
                legacy_root.legacy_blob.is_not(None),
            ),
        )
        return sa.and_(
            sa.or_(
                root_has_content.correlate(file),
                root_has_legacy.correlate(file),
            ),
            ~FileRepository._family_has_unavailable_content(file),
        )

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

    async def project_derived_images_for_attached_roots(
        self,
        *,
        parent_ids: list[UUID],
        tenant_id: UUID,
    ) -> AttachedDerivedImageProjection:
        if not parent_ids:
            return AttachedDerivedImageProjection(
                derived_images=(),
                unstable_parent_ids=frozenset(),
            )
        parent = aliased(Files)
        child = aliased(Files)
        family_unavailable = self._family_has_unavailable_content(parent)
        family_pending = self._family_has_pending_content(parent)
        rows = (
            await self.session.execute(
                sa.select(parent.id, child, family_unavailable, family_pending)
                .select_from(parent)
                .outerjoin(
                    child,
                    sa.and_(
                        child.parent_file_id == parent.id,
                        child.user_id == parent.user_id,
                        child.tenant_id == parent.tenant_id,
                        child.file_type == FileType.IMAGE.value,
                    ),
                )
                .where(
                    parent.id.in_(parent_ids),
                    parent.tenant_id == tenant_id,
                )
                .order_by(parent.id, child.created_at, child.id)
            )
        ).all()
        unavailable_parent_ids = frozenset(
            parent_id
            for parent_id, _child, unavailable, _pending in rows
            if unavailable
        )
        unstable_parent_ids = frozenset(
            parent_id for parent_id, _child, _unavailable, pending in rows if pending
        )
        return AttachedDerivedImageProjection(
            derived_images=tuple(
                FileMetadata.model_validate(child_row)
                for parent_id, child_row, _unavailable, _pending in rows
                if child_row is not None and parent_id not in unavailable_parent_ids
            ),
            unstable_parent_ids=unstable_parent_ids,
        )

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

    async def get_legacy_content(
        self,
        requests: Mapping[UUID, Collection[FileContentVariant]],
    ) -> list[LegacyFileContentRecord]:
        """Load only the frozen variants whose object references are missing."""
        ids_by_variant: defaultdict[FileContentVariant, list[UUID]] = defaultdict(list)
        for file_id, variants in requests.items():
            for variant in variants:
                ids_by_variant[variant].append(file_id)

        records: list[LegacyFileContentRecord] = []
        for variant in (
            FileContentVariant.EXTRACTED_TEXT,
            FileContentVariant.ORIGINAL,
            FileContentVariant.DERIVED_PAGE,
            FileContentVariant.LEGACY_IMAGE,
            FileContentVariant.TRANSCRIPTION,
        ):
            file_ids = ids_by_variant[variant]
            if not file_ids:
                continue
            payload_column = (
                Files.legacy_text
                if variant is FileContentVariant.EXTRACTED_TEXT
                else (
                    Files.legacy_transcription
                    if variant is FileContentVariant.TRANSCRIPTION
                    else Files.legacy_blob
                )
            )
            query = sa.select(Files.id, Files.mimetype, payload_column).where(
                Files.id.in_(file_ids),
                payload_column.is_not(None),
            )
            if variant is FileContentVariant.ORIGINAL:
                query = query.where(
                    Files.file_type.in_((FileType.TEXT.value, FileType.AUDIO.value))
                )
            rows = (await self.session.execute(query)).all()
            for file_id, mimetype, payload in rows:
                is_text = variant in (
                    FileContentVariant.EXTRACTED_TEXT,
                    FileContentVariant.TRANSCRIPTION,
                )
                records.append(
                    LegacyFileContentRecord(
                        file_id=file_id,
                        variant=variant,
                        payload=(
                            payload.encode("utf-8")
                            if isinstance(payload, str)
                            else bytes(payload)
                        ),
                        media_type=(
                            "text/plain"
                            if is_text
                            else mimetype or "application/octet-stream"
                        ),
                    )
                )
        return records

    async def get_legacy_infos(
        self,
        file_ids: list[UUID],
    ) -> list[LegacyFileInfoRecord]:
        """Read legacy integrity metadata without materializing TOAST payloads."""
        if not file_ids:
            return []
        rows = (
            await self.session.execute(
                sa.select(
                    Files.id,
                    Files.file_type,
                    Files.parent_file_id,
                    Files.mimetype,
                    Files.legacy_checksum,
                    Files.legacy_size,
                    Files.legacy_blob.is_not(None).label("original_available"),
                    Files.legacy_transcription.is_not(None).label(
                        "transcription_available"
                    ),
                ).where(
                    Files.id.in_(file_ids),
                    Files.legacy_checksum.is_not(None),
                    Files.legacy_size.is_not(None),
                )
            )
        ).all()
        return [
            LegacyFileInfoRecord(
                file_id=row.id,
                variant=legacy_primary_file_variant(
                    FileType(row.file_type),
                    parent_file_id=row.parent_file_id,
                ),
                checksum=row.legacy_checksum,
                size_bytes=row.legacy_size,
                media_type=(
                    "text/plain"
                    if FileType(row.file_type) is FileType.TEXT
                    else row.mimetype or "application/octet-stream"
                ),
                original_available=(
                    FileType(row.file_type) is FileType.TEXT and row.original_available
                ),
                transcription_available=row.transcription_available,
            )
            for row in rows
        ]

    async def get_legacy_audio_slice(
        self,
        file_id: UUID,
        selected_range: ByteRange | None,
    ) -> LegacyAudioSlice | None:
        payload = (
            Files.legacy_blob
            if selected_range is None
            else sa.func.substring(
                Files.legacy_blob,
                selected_range.start + 1,
                selected_range.content_length,
            )
        )
        row = (
            await self.session.execute(
                sa.select(
                    payload.label("payload"),
                    Files.mimetype,
                ).where(
                    Files.id == file_id,
                    Files.file_type == FileType.AUDIO.value,
                    Files.legacy_blob.is_not(None),
                )
            )
        ).one_or_none()
        if row is None:
            return None
        return LegacyAudioSlice(
            payload=bytes(row.payload),
            media_type=row.mimetype or "application/octet-stream",
        )

    async def get_infos_by_ids(self, file_ids: list[UUID]) -> list[FileInfo]:
        metadata = await self.get_by_ids(file_ids)
        references = await self.get_content_references([file.id for file in metadata])
        legacy_infos = await self.get_legacy_infos([file.id for file in metadata])
        by_file: dict[UUID, list[FileContentReferenceRecord]] = {
            file.id: [] for file in metadata
        }
        legacy_by_file: dict[UUID, list[LegacyFileInfoRecord]] = {
            file.id: [] for file in metadata
        }
        for reference in references:
            by_file[reference.file_id].append(reference)
        for content in legacy_infos:
            legacy_by_file[content.file_id].append(content)
        return [
            project_file_info(file, by_file[file.id], legacy_by_file[file.id])
            for file in metadata
        ]

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
