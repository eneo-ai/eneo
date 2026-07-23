from collections import defaultdict
from collections.abc import Sequence
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
    project_file_media_type,
    select_binary_file_reference,
    select_primary_file_reference,
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
        by_file: defaultdict[UUID, list[FileContentReferenceRecord]] = defaultdict(list)
        for reference in references:
            by_file[reference.file_id].append(reference)

        payloads: dict[UUID, bytes] = {}
        hydrated: dict[UUID, File] = {}
        for file in unique_metadata.values():
            file_references = by_file[file.id]
            primary = self._primary_reference(file, file_references)
            text: str | None = None
            blob: bytes | None = None
            transcription: str | None = None
            hydrated_reference = primary

            if file.file_type is FileType.TEXT:
                text_reference = self._first_reference(
                    file_references,
                    FileContentVariant.EXTRACTED_TEXT,
                )
                if text_reference is None and primary.media_type.startswith("text/"):
                    text_reference = primary
                if text_reference is None:
                    raise NotFoundException(
                        f"File {file.id} has no readable text content"
                    )
                text = (await self._read_bytes(file, text_reference, payloads)).decode(
                    "utf-8"
                )
                hydrated_reference = text_reference
            else:
                content_reference = self._preferred_binary_reference(
                    file,
                    file_references,
                )
                blob = await self._read_bytes(file, content_reference, payloads)
                hydrated_reference = content_reference

            if include_transcription:
                transcription_reference = self._first_reference(
                    file_references,
                    FileContentVariant.TRANSCRIPTION,
                )
                if transcription_reference is not None:
                    transcription = (
                        await self._read_bytes(
                            file,
                            transcription_reference,
                            payloads,
                        )
                    ).decode("utf-8")

            hydrated[file.id] = File(
                id=file.id,
                created_at=file.created_at,
                updated_at=file.updated_at,
                name=file.name,
                checksum=hydrated_reference.sha256.hex(),
                size=hydrated_reference.size_bytes,
                mimetype=project_file_media_type(file, hydrated_reference),
                file_type=file.file_type,
                text=text,
                blob=blob,
                transcription=transcription,
                user_id=file.user_id,
                tenant_id=file.tenant_id,
                parent_file_id=file.parent_file_id,
            )
        return hydrated

    async def load_attachment_groups(
        self,
        groups: Sequence[FileAttachmentGroup],
        *,
        include_transcription: bool = True,
    ) -> dict[tuple[str, UUID], list[File]]:
        """Validate, deduplicate, hydrate, and regroup concrete attachments."""
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

        loaded = await self.load(
            list(metadata_by_id.values()),
            include_transcription=include_transcription,
        )
        return {
            key: [loaded[file_id] for file_id in file_ids]
            for key, file_ids in ids_by_group.items()
        }

    async def _read_bytes(
        self,
        file: FileMetadata,
        reference: FileContentReferenceRecord,
        payloads: dict[UUID, bytes],
    ) -> bytes:
        cached = payloads.get(reference.content_id)
        if cached is not None:
            return cached

        grant = ContentReadGrant(
            content_id=reference.content_id,
            tenant_id=file.tenant_id,
            access_class=reference.access_class,
        )
        async with self._object_content.open_content(grant) as opened:
            payload = b"".join([chunk async for chunk in opened.chunks])
        payloads[reference.content_id] = payload
        return payload

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
    def _primary_reference(
        file: FileMetadata,
        references: list[FileContentReferenceRecord],
    ) -> FileContentReferenceRecord:
        reference = select_primary_file_reference(file.file_type, references)
        if reference is not None:
            return reference
        raise NotFoundException(f"File {file.id} has no durable content")

    @staticmethod
    def _preferred_binary_reference(
        file: FileMetadata,
        references: list[FileContentReferenceRecord],
    ) -> FileContentReferenceRecord:
        reference = select_binary_file_reference(file.file_type, references)
        if reference is not None:
            return reference
        raise NotFoundException(f"File {file.id} has no readable binary content")
