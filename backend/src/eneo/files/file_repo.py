from collections.abc import Iterable
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
    FileOwner,
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
    state: ContentState


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


def _primary_file_content_variants(
    file_type: FileType,
) -> tuple[FileContentVariant, ...]:
    if file_type is FileType.TEXT:
        preferred_variants = (
            FileContentVariant.EXTRACTED_TEXT,
            FileContentVariant.ORIGINAL,
        )
    elif file_type is FileType.IMAGE:
        preferred_variants = _IMAGE_INPUT_VARIANTS
    else:
        preferred_variants = (FileContentVariant.ORIGINAL,)
    return tuple(dict.fromkeys((*preferred_variants, *_PRIMARY_VARIANTS)))


def select_primary_file_reference(
    file_type: FileType,
    references: list[FileContentReferenceRecord],
) -> FileContentReferenceRecord | None:
    for variant in _primary_file_content_variants(file_type):
        reference = next(
            (candidate for candidate in references if candidate.variant is variant),
            None,
        )
        if reference is not None:
            return reference
    return None


def primary_file_content_size_expression() -> sa.ColumnElement[int]:
    """Project the same durable-content size used by ``FileInfo.size``."""

    ranked_variants = [
        (
            sa.and_(
                Files.file_type == file_type.value,
                FileContentReferences.variant == variant.value,
            ),
            priority,
        )
        for file_type in FileType
        for priority, variant in enumerate(_primary_file_content_variants(file_type))
    ]
    return (
        sa.select(ObjectContents.size_bytes)
        .select_from(FileContentReferences)
        .join(ObjectContents, ObjectContents.id == FileContentReferences.content_id)
        .where(
            FileContentReferences.file_id == Files.id,
            sa.or_(*(condition for condition, _ in ranked_variants)),
        )
        .order_by(
            sa.case(*ranked_variants, else_=len(ranked_variants)),
            FileContentReferences.ordinal,
        )
        .limit(1)
        .correlate(Files)
        .scalar_subquery()
    )


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
        owner_type=file.owner_type,
        owner_user_id=file.owner_user_id,
        owner_service_id=file.owner_service_id,
        tenant_id=file.tenant_id,
    )


def _metadata_in_requested_order(
    rows: Iterable[Files],
    requested_ids: list[UUID],
) -> list[FileMetadata]:
    metadata_by_id = {row.id: FileMetadata.model_validate(row) for row in rows}
    return [
        metadata_by_id[file_id]
        for file_id in dict.fromkeys(requested_ids)
        if file_id in metadata_by_id
    ]


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
    def _owned_by(file: type[Files], owner: FileOwner):
        return sa.and_(
            file.tenant_id == owner.tenant_id,
            file.owner_type == owner.owner_type.value,
            file.owner_user_id.is_not_distinct_from(owner.owner_user_id),
            file.owner_service_id.is_not_distinct_from(owner.owner_service_id),
        )

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
        return sa.and_(
            root_has_content.correlate(file),
            ~FileRepository._family_has_unavailable_content(file),
        )

    def _visible_children_query(
        self,
        *,
        parent_ids: list[UUID],
        owner: FileOwner | None = None,
        tenant_id: UUID | None = None,
        file_type: FileType | None = None,
    ) -> Select[tuple[Files]]:
        parent = aliased(Files)
        query = (
            sa.select(Files)
            .join(parent, Files.parent_file_id == parent.id)
            .where(
                Files.parent_file_id.in_(parent_ids),
                Files.tenant_id == parent.tenant_id,
                Files.owner_type == parent.owner_type,
                Files.owner_user_id.is_not_distinct_from(parent.owner_user_id),
                Files.owner_service_id.is_not_distinct_from(parent.owner_service_id),
                self._visible_family(),
            )
        )
        if owner is not None:
            query = query.where(self._owned_by(parent, owner))
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

    async def get_list_by_id_and_owner(
        self,
        ids: list[UUID],
        owner: FileOwner,
    ) -> list[FileMetadata]:
        if not ids:
            return []
        rows = await self.session.scalars(
            sa.select(Files).where(
                Files.id.in_(ids),
                self._owned_by(Files, owner),
                self._visible_family(),
            )
        )
        return _metadata_in_requested_order(rows, ids)

    async def get_by_ids(self, ids: list[UUID]) -> list[FileMetadata]:
        if not ids:
            return []
        rows = await self.session.scalars(
            sa.select(Files).where(Files.id.in_(ids), self._visible_family())
        )
        return _metadata_in_requested_order(rows, ids)

    async def get_by_parent_ids(
        self,
        parent_ids: list[UUID],
        owner: FileOwner,
    ) -> list[FileMetadata]:
        if not parent_ids:
            return []
        rows = await self.session.scalars(
            self._visible_children_query(
                parent_ids=parent_ids,
                owner=owner,
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
                        child.tenant_id == parent.tenant_id,
                        child.owner_type == parent.owner_type,
                        child.owner_user_id.is_not_distinct_from(parent.owner_user_id),
                        child.owner_service_id.is_not_distinct_from(
                            parent.owner_service_id
                        ),
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

    async def get_by_id(
        self,
        file_id: UUID,
        *,
        tenant_id: UUID | None = None,
    ) -> FileMetadata:
        query = sa.select(Files).where(Files.id == file_id, self._visible_family())
        if tenant_id is not None:
            query = query.where(Files.tenant_id == tenant_id)
        row = await self.session.scalar(query)
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
        owner: FileOwner,
    ) -> FileMetadata | None:
        row = await self.session.scalar(
            sa.select(Files).where(
                Files.id == file_id,
                self._owned_by(Files, owner),
            )
        )
        return None if row is None else FileMetadata.model_validate(row)

    async def get_by_id_and_owner_for_key_share(
        self,
        *,
        file_id: UUID,
        owner: FileOwner,
    ) -> FileMetadata | None:
        """Fence deletion while an owned File is adopted by another resource."""

        row = await self.session.scalar(
            sa.select(Files)
            .where(
                Files.id == file_id,
                self._owned_by(Files, owner),
                self._visible_family(),
            )
            .with_for_update(read=True, key_share=True)
        )
        return None if row is None else FileMetadata.model_validate(row)

    async def get_list_by_owner(self, owner: FileOwner) -> list[FileMetadata]:
        rows = await self.session.scalars(
            sa.select(Files)
            .where(
                self._owned_by(Files, owner),
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
                ObjectContents.state,
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
                state=ContentState(row.state),
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
        owner: FileOwner,
    ) -> FileMetadata | None:
        row = (
            await self.session.execute(
                sa.delete(Files)
                .where(
                    Files.id == id,
                    self._owned_by(Files, owner),
                )
                .returning(Files)
            )
        ).scalar_one_or_none()
        return None if row is None else FileMetadata.model_validate(row)
