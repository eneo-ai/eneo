from collections import defaultdict
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from uuid import UUID

from eneo.files.file_models import (
    File,
    FileContentVariant,
    FileMetadata,
    FileType,
)
from eneo.files.file_repo import (
    FileContentReferenceRecord,
    FileRepository,
    LegacyFileContentRecord,
    LegacyFileInfoRecord,
    binary_file_variants,
    legacy_primary_file_variant,
    primary_file_variants,
    project_file_media_type,
    select_binary_file_reference,
)
from eneo.main.exceptions import NotFoundException
from eneo.object_content.content import ContentReadGrant
from eneo.object_content.content_service import ObjectContentService


@dataclass(frozen=True, slots=True)
class FileAttachmentGroup:
    """One authorized owner's ordered File attachments."""

    owner_kind: str
    owner_id: UUID
    tenant_id: UUID
    files: tuple[FileMetadata, ...]

    @property
    def key(self) -> tuple[str, UUID]:
        return self.owner_kind, self.owner_id


class FileContentTenantMismatchError(RuntimeError):
    """A concrete File relationship crossed its owner's tenant boundary."""

    def __init__(self, *, group: FileAttachmentGroup, file_id: UUID) -> None:
        super().__init__(
            f"{group.owner_kind} {group.owner_id} attachment {file_id} "
            "crosses a tenant boundary"
        )


@dataclass(frozen=True, slots=True)
class _FileContentSelection:
    hydrated_reference: FileContentReferenceRecord | LegacyFileContentRecord
    text_reference: FileContentReferenceRecord | LegacyFileContentRecord | None
    blob_reference: FileContentReferenceRecord | LegacyFileContentRecord | None
    transcription_reference: FileContentReferenceRecord | LegacyFileContentRecord | None
    original_available: bool

    @property
    def readable_references(self) -> tuple[FileContentReferenceRecord, ...]:
        return tuple(
            reference
            for reference in (
                self.text_reference,
                self.blob_reference,
                self.transcription_reference,
            )
            if isinstance(reference, FileContentReferenceRecord)
        )


class FileContentLoader:
    """Hydrate already-authorized File metadata through object content."""

    def __init__(
        self,
        repo: FileRepository,
        object_content: ObjectContentService,
    ) -> None:
        self._repo = repo
        self._object_content = object_content

    async def load(
        self,
        metadata: Sequence[FileMetadata],
        *,
        include_transcription: bool = True,
    ) -> dict[UUID, File]:
        """Load each referenced content object at most once.

        Callers must obtain ``metadata`` through an already-authorized concrete
        File relationship or FileService ownership check. This loader owns byte
        projection only; it deliberately does not invent a second authorization
        policy.
        """
        if not metadata:
            return {}

        unique_metadata = {file.id: file for file in metadata}
        references = await self._repo.get_content_references(list(unique_metadata))
        legacy_infos = await self._repo.get_legacy_infos(list(unique_metadata))
        return await self._load_from_facts(
            unique_metadata,
            references,
            legacy_infos,
            include_transcription=include_transcription,
        )

    async def _load_from_facts(
        self,
        metadata: dict[UUID, FileMetadata],
        references: list[FileContentReferenceRecord],
        legacy_infos: list[LegacyFileInfoRecord],
        *,
        include_transcription: bool,
    ) -> dict[UUID, File]:
        selections = await self._select_content_from_facts(
            metadata,
            references,
            legacy_infos,
            include_transcription=include_transcription,
        )
        return await self._hydrate_selected_files(metadata, selections)

    async def _select_content_from_facts(
        self,
        metadata: dict[UUID, FileMetadata],
        references: list[FileContentReferenceRecord],
        legacy_infos: list[LegacyFileInfoRecord],
        *,
        include_transcription: bool,
    ) -> dict[UUID, _FileContentSelection]:
        by_file: defaultdict[UUID, list[FileContentReferenceRecord]] = defaultdict(list)
        for reference in references:
            by_file[reference.file_id].append(reference)
        legacy_info_by_file = {info.file_id: info for info in legacy_infos}
        legacy_requests: dict[UUID, set[FileContentVariant]] = {}
        for file in metadata.values():
            file_references = by_file[file.id]
            requested = self._legacy_requests(
                file,
                file_references,
                legacy_info_by_file.get(file.id),
                include_transcription=include_transcription,
            )
            if requested:
                legacy_requests[file.id] = requested
        legacy_content = (
            await self._repo.get_legacy_content(legacy_requests)
            if legacy_requests
            else []
        )
        legacy_by_file: defaultdict[UUID, list[LegacyFileContentRecord]] = defaultdict(
            list
        )
        for content in legacy_content:
            legacy_by_file[content.file_id].append(content)

        selections: dict[UUID, _FileContentSelection] = {}
        for file in metadata.values():
            file_references = by_file[file.id]
            file_legacy_content = legacy_by_file[file.id]
            primary = self._primary_content(
                file,
                file_references,
                file_legacy_content,
            )
            if file.file_type is FileType.TEXT:
                text_reference = self._first_content(
                    file_references,
                    file_legacy_content,
                    FileContentVariant.EXTRACTED_TEXT,
                )
                if text_reference is None and primary.media_type.startswith("text/"):
                    text_reference = primary
                if text_reference is None:
                    raise NotFoundException(
                        f"File {file.id} has no readable text content"
                    )
                hydrated_reference = text_reference
                blob_reference = None
            else:
                text_reference = None
                blob_reference = self._preferred_binary_reference(
                    file,
                    file_references,
                    file_legacy_content,
                )
                hydrated_reference = blob_reference

            transcription_reference = (
                self._first_content(
                    file_references,
                    file_legacy_content,
                    FileContentVariant.TRANSCRIPTION,
                )
                if include_transcription
                else None
            )
            selection = _FileContentSelection(
                hydrated_reference=hydrated_reference,
                text_reference=text_reference,
                blob_reference=blob_reference,
                transcription_reference=transcription_reference,
                original_available=self._first_content(
                    file_references,
                    [],
                    FileContentVariant.ORIGINAL,
                )
                is not None
                or self._legacy_original_available(legacy_info_by_file.get(file.id)),
            )
            selections[file.id] = selection
        return selections

    async def _hydrate_selected_files(
        self,
        metadata: dict[UUID, FileMetadata],
        selections: dict[UUID, _FileContentSelection],
    ) -> dict[UUID, File]:
        grants: list[ContentReadGrant] = []
        for file in metadata.values():
            selection = selections[file.id]
            grants.extend(
                ContentReadGrant(
                    content_id=reference.content_id,
                    tenant_id=file.tenant_id,
                    access_class=reference.access_class,
                )
                for reference in selection.readable_references
            )

        payloads = await self._object_content.read_content_bytes(grants)
        hydrated: dict[UUID, File] = {}
        for file in metadata.values():
            selection = selections[file.id]
            text = (
                None
                if selection.text_reference is None
                else self._payload(selection.text_reference, payloads).decode("utf-8")
            )
            blob = (
                None
                if selection.blob_reference is None
                else self._payload(selection.blob_reference, payloads)
            )
            transcription = (
                None
                if selection.transcription_reference is None
                else self._payload(
                    selection.transcription_reference,
                    payloads,
                ).decode("utf-8")
            )
            hydrated[file.id] = File(
                id=file.id,
                created_at=file.created_at,
                updated_at=file.updated_at,
                name=file.name,
                checksum=selection.hydrated_reference.sha256.hex(),
                size=selection.hydrated_reference.size_bytes,
                mimetype=project_file_media_type(
                    file,
                    selection.hydrated_reference,
                ),
                file_type=file.file_type,
                text=text,
                blob=blob,
                transcription=transcription,
                user_id=file.user_id,
                tenant_id=file.tenant_id,
                parent_file_id=file.parent_file_id,
                original_available=selection.original_available,
            )
        return hydrated

    async def load_attachment_groups(
        self,
        groups: Sequence[FileAttachmentGroup],
        *,
        include_transcription: bool = True,
    ) -> dict[tuple[str, UUID], list[File]]:
        """Validate, deduplicate, hydrate, and regroup concrete attachments."""
        metadata_by_id, ids_by_group = self._index_attachment_groups(groups)
        loaded = await self.load(
            list(metadata_by_id.values()),
            include_transcription=include_transcription,
        )
        return {
            key: [loaded[file_id] for file_id in file_ids]
            for key, file_ids in ids_by_group.items()
        }

    async def load_attachment_groups_in_payload_batches(
        self,
        groups: Sequence[FileAttachmentGroup],
        *,
        max_batch_bytes: int,
        include_transcription: bool = True,
    ) -> AsyncIterator[dict[tuple[str, UUID], list[File]]]:
        """Hydrate groups incrementally after one content-reference lookup.

        A group is never split, so one unusually large owner has the same peak
        payload as the single-owner loader. Shared content counts once within a
        batch and may keep several groups below the byte limit.
        """
        if max_batch_bytes <= 0:
            raise ValueError("max_batch_bytes must be positive")

        metadata_by_id, ids_by_group = self._index_attachment_groups(groups)
        references = await self._repo.get_content_references(list(metadata_by_id))
        legacy_infos = await self._repo.get_legacy_infos(list(metadata_by_id))
        legacy_info_by_file = {info.file_id: info for info in legacy_infos}
        by_file: defaultdict[UUID, list[FileContentReferenceRecord]] = defaultdict(list)
        for reference in references:
            by_file[reference.file_id].append(reference)
        legacy_requests_by_file = {
            file.id: requests
            for file in metadata_by_id.values()
            if (
                requests := self._legacy_requests(
                    file,
                    by_file[file.id],
                    legacy_info_by_file.get(file.id),
                    include_transcription=include_transcription,
                )
            )
        }
        legacy_size_by_key = {
            (file_id, variant): (
                info.size_bytes if variant is info.variant else max_batch_bytes + 1
            )
            for file_id, variants in legacy_requests_by_file.items()
            if (info := legacy_info_by_file.get(file_id)) is not None
            for variant in variants
        }

        batch_groups: list[FileAttachmentGroup] = []
        batch_content_ids: set[UUID] = set()
        batch_legacy_keys: set[tuple[UUID, FileContentVariant]] = set()
        batch_bytes = 0

        async def load_known_groups(
            selected_groups: Sequence[FileAttachmentGroup],
        ) -> dict[tuple[str, UUID], list[File]]:
            selected_file_ids = list(
                dict.fromkeys(
                    file_id
                    for selected_group in selected_groups
                    for file_id in ids_by_group[selected_group.key]
                )
            )
            selected_metadata = {
                file_id: metadata_by_id[file_id] for file_id in selected_file_ids
            }
            loaded = await self._load_from_facts(
                selected_metadata,
                [
                    reference
                    for file_id in selected_file_ids
                    for reference in by_file[file_id]
                ],
                [
                    legacy_info_by_file[file_id]
                    for file_id in selected_file_ids
                    if file_id in legacy_info_by_file
                ],
                include_transcription=include_transcription,
            )
            return {
                selected_group.key: [
                    loaded[file_id] for file_id in ids_by_group[selected_group.key]
                ]
                for selected_group in selected_groups
            }

        for group in groups:
            file_ids = ids_by_group[group.key]
            group_content_sizes: dict[UUID, int] = {}
            group_legacy_sizes: dict[tuple[UUID, FileContentVariant], int] = {}
            for file_id in file_ids:
                file = metadata_by_id[file_id]
                for reference in self._readable_object_references(
                    file,
                    by_file[file_id],
                    include_transcription=include_transcription,
                ):
                    group_content_sizes[reference.content_id] = reference.size_bytes
                for variant in legacy_requests_by_file.get(file_id, set()):
                    key = (file_id, variant)
                    group_legacy_sizes[key] = legacy_size_by_key.get(
                        key,
                        max_batch_bytes + 1,
                    )
            additional_bytes = sum(
                size
                for content_id, size in group_content_sizes.items()
                if content_id not in batch_content_ids
            ) + sum(
                size
                for key, size in group_legacy_sizes.items()
                if key not in batch_legacy_keys
            )
            if (
                batch_groups
                and additional_bytes > 0
                and batch_bytes + additional_bytes > max_batch_bytes
            ):
                yield await load_known_groups(batch_groups)
                batch_groups = []
                batch_content_ids = set()
                batch_legacy_keys = set()
                batch_bytes = 0

            batch_groups.append(group)
            for content_id, size in group_content_sizes.items():
                if content_id not in batch_content_ids:
                    batch_content_ids.add(content_id)
                    batch_bytes += size
            for key, size in group_legacy_sizes.items():
                if key not in batch_legacy_keys:
                    batch_legacy_keys.add(key)
                    batch_bytes += size

        if batch_groups:
            yield await load_known_groups(batch_groups)

    @staticmethod
    def _index_attachment_groups(
        groups: Sequence[FileAttachmentGroup],
    ) -> tuple[
        dict[UUID, FileMetadata],
        dict[tuple[str, UUID], list[UUID]],
    ]:
        metadata_by_id: dict[UUID, FileMetadata] = {}
        ids_by_group: dict[tuple[str, UUID], list[UUID]] = {}
        for group in groups:
            file_ids: list[UUID] = []
            for metadata in group.files:
                if metadata.tenant_id != group.tenant_id:
                    raise FileContentTenantMismatchError(
                        group=group,
                        file_id=metadata.id,
                    )
                metadata_by_id[metadata.id] = metadata
                file_ids.append(metadata.id)
            ids_by_group[group.key] = file_ids
        return metadata_by_id, ids_by_group

    @staticmethod
    def _first_reference(
        references: Sequence[FileContentReferenceRecord],
        variant: FileContentVariant,
    ) -> FileContentReferenceRecord | None:
        return next(
            (reference for reference in references if reference.variant is variant),
            None,
        )

    @staticmethod
    def _legacy_requests(
        file: FileMetadata,
        references: list[FileContentReferenceRecord],
        legacy_info: LegacyFileInfoRecord | None,
        *,
        include_transcription: bool,
    ) -> set[FileContentVariant]:
        requested: set[FileContentVariant] = set()
        if legacy_info is None:
            return requested
        if file.file_type is FileType.TEXT:
            if (
                FileContentLoader._first_reference(
                    references,
                    FileContentVariant.EXTRACTED_TEXT,
                )
                is None
            ):
                requested.add(FileContentVariant.EXTRACTED_TEXT)
        elif select_binary_file_reference(file.file_type, references) is None:
            requested.add(
                legacy_primary_file_variant(
                    file.file_type,
                    parent_file_id=file.parent_file_id,
                )
            )
        if (
            include_transcription
            and legacy_info.transcription_available
            and FileContentLoader._first_reference(
                references,
                FileContentVariant.TRANSCRIPTION,
            )
            is None
        ):
            requested.add(FileContentVariant.TRANSCRIPTION)
        return requested

    @staticmethod
    def _readable_object_references(
        file: FileMetadata,
        references: list[FileContentReferenceRecord],
        *,
        include_transcription: bool,
    ) -> tuple[FileContentReferenceRecord, ...]:
        readable: list[FileContentReferenceRecord] = []
        if file.file_type is FileType.TEXT:
            text_reference = FileContentLoader._first_reference(
                references,
                FileContentVariant.EXTRACTED_TEXT,
            )
            if text_reference is not None:
                readable.append(text_reference)
        else:
            binary_reference = select_binary_file_reference(
                file.file_type,
                references,
            )
            if binary_reference is not None:
                readable.append(binary_reference)
        if include_transcription:
            transcription = FileContentLoader._first_reference(
                references,
                FileContentVariant.TRANSCRIPTION,
            )
            if transcription is not None:
                readable.append(transcription)
        return tuple(readable)

    @staticmethod
    def _legacy_original_available(info: LegacyFileInfoRecord | None) -> bool:
        return info is not None and info.original_available

    @classmethod
    def _first_content(
        cls,
        references: Sequence[FileContentReferenceRecord],
        legacy_content: Sequence[LegacyFileContentRecord],
        variant: FileContentVariant,
    ) -> FileContentReferenceRecord | LegacyFileContentRecord | None:
        reference = cls._first_reference(references, variant)
        if reference is not None:
            return reference
        return next(
            (content for content in legacy_content if content.variant is variant),
            None,
        )

    @staticmethod
    def _primary_content(
        file: FileMetadata,
        references: list[FileContentReferenceRecord],
        legacy_content: list[LegacyFileContentRecord],
    ) -> FileContentReferenceRecord | LegacyFileContentRecord:
        for variant in primary_file_variants(file.file_type):
            content = FileContentLoader._first_content(
                references,
                legacy_content,
                variant,
            )
            if content is not None:
                return content
        raise NotFoundException(f"File {file.id} has no durable content")

    @staticmethod
    def _preferred_binary_reference(
        file: FileMetadata,
        references: list[FileContentReferenceRecord],
        legacy_content: list[LegacyFileContentRecord],
    ) -> FileContentReferenceRecord | LegacyFileContentRecord:
        for variant in binary_file_variants(file.file_type):
            content = FileContentLoader._first_content(
                references,
                legacy_content,
                variant,
            )
            if content is not None:
                return content
        raise NotFoundException(f"File {file.id} has no readable binary content")

    @staticmethod
    def _payload(
        content: FileContentReferenceRecord | LegacyFileContentRecord,
        payloads: dict[UUID, bytes],
    ) -> bytes:
        if isinstance(content, LegacyFileContentRecord):
            return content.payload
        return payloads[content.content_id]
