from collections import defaultdict
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID

from fastapi import UploadFile

from eneo.files.file_models import (
    File,
    FileContentVariant,
    FileInfo,
    FileMetadata,
    FileMetadataCreate,
    FileType,
)
from eneo.files.file_protocol import (
    FileProtocol,
    PendingFileContent,
    PreparedFileUpload,
)
from eneo.files.file_repo import (
    FileContentReferenceRecord,
    FileRepository,
    project_file_info,
    select_binary_file_reference,
    select_primary_file_reference,
)
from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from eneo.object_content.content import (
    ByteRange,
    ContentAccessClass,
    ContentIntent,
    ContentReadGrant,
    StorageKind,
)
from eneo.object_content.content_service import ObjectContentService
from eneo.users.user import UserInDB


@dataclass(frozen=True, slots=True)
class FileDownload:
    chunks: AsyncGenerator[bytes]
    content_length: int
    media_type: str
    filename: str
    content_range: str | None


async def _bytes_source(payload: bytes) -> AsyncGenerator[bytes]:
    yield payload


class FileService:
    """Own File identity and authorization while delegating durable bytes."""

    def __init__(
        self,
        user: UserInDB | None,
        repo: FileRepository,
        protocol: FileProtocol,
        object_content: ObjectContentService,
    ):
        self.user = user
        self.repo = repo
        self.protocol = protocol
        self.object_content = object_content

    @asynccontextmanager
    async def _write_transaction(self) -> AsyncGenerator[None]:
        session = self.repo.session
        if session.in_transaction():
            yield
            return
        async with session.begin():
            yield

    async def save_file(self, upload_file: UploadFile) -> FileInfo:
        self._authenticated_user()
        async with self.protocol.prepare_upload(upload_file) as prepared:
            async with self._write_transaction():
                file_id = await self._persist_prepared_file(prepared)
                for derivative in prepared.derivatives:
                    await self._persist_prepared_file(
                        derivative,
                        parent_file_id=file_id,
                    )
        return await self.get_file_by_id(file_id)

    async def save_image_from_bytes(
        self,
        image_data: bytes,
        name: str = "generated_image.jpeg",
        mimetype: str = "image/jpeg",
    ) -> File:
        self._authenticated_user()
        prepared = PreparedFileUpload(
            name=name,
            file_type=FileType.IMAGE,
            display_media_type=mimetype,
            contents=(
                PendingFileContent(
                    variant=FileContentVariant.GENERATED_ARTIFACT,
                    chunks=_bytes_source(image_data),
                    declared_media_type=mimetype,
                    verified_media_type=mimetype,
                ),
            ),
        )
        async with self._write_transaction():
            file_id = await self._persist_prepared_file(prepared)
        info = await self.get_file_by_id(file_id)
        return File(
            **info.model_dump(),
            blob=image_data,
            text=None,
            transcription=None,
        )

    async def _persist_prepared_file(
        self,
        prepared: PreparedFileUpload,
        *,
        parent_file_id: UUID | None = None,
    ) -> UUID:
        user = self._authenticated_user()
        metadata = await self.repo.add_metadata(
            FileMetadataCreate(
                name=prepared.name,
                file_type=prepared.file_type,
                mimetype=prepared.display_media_type,
                user_id=user.id,
                tenant_id=user.tenant_id,
                parent_file_id=parent_file_id,
            )
        )
        for pending in prepared.contents:
            async with self.object_content.capture_inline(
                pending.chunks,
                declared_media_type=pending.declared_media_type,
                verified_media_type=pending.verified_media_type,
            ) as captured:
                stored = await self.object_content.prepare_in_transaction(
                    self.repo.session,
                    intent=ContentIntent(
                        tenant_id=user.tenant_id,
                        created_by_user_id=user.id,
                        access_class=ContentAccessClass.PRIVATE_RESOURCE,
                        idempotency_key=(
                            f"file:{metadata.id}:{pending.variant.value}:"
                            f"{pending.ordinal}"
                        ),
                        producer_receipt=(
                            f"file:{metadata.id}:{pending.variant.value}:"
                            f"{pending.ordinal}"
                        ),
                    ),
                    content=captured,
                    storage_kind=StorageKind.POSTGRES_INLINE,
                )

                await self.repo.add_content_reference(
                    file_id=metadata.id,
                    content_id=stored.id,
                    variant=pending.variant,
                    ordinal=pending.ordinal,
                    page_number=pending.page_number,
                    width=pending.width,
                    height=pending.height,
                    duration_ms=pending.duration_ms,
                )

        return metadata.id

    async def get_file_by_id(self, file_id: UUID) -> FileInfo:
        metadata = await self.repo.get_by_id(file_id=file_id)
        self._require_owner(metadata, action="read")
        return await self._file_info(metadata)

    async def get_files_by_ids(
        self,
        file_ids: list[UUID],
        include_transcription: bool = True,
    ) -> list[File]:
        metadata = await self.repo.get_list_by_id_and_user(
            ids=file_ids,
            user_id=self._authenticated_user().id,
        )
        return await self._hydrate_files(
            metadata,
            include_transcription=include_transcription,
        )

    async def get_files(self) -> list[FileInfo]:
        metadata = await self.repo.get_list_by_user(
            user_id=self._authenticated_user().id
        )
        references = await self.repo.get_content_references(
            [file.id for file in metadata]
        )
        by_file = self._references_by_file(references)
        return [project_file_info(file, by_file[file.id]) for file in metadata]

    async def get_derived_images(self, parent_ids: list[UUID]) -> list[File]:
        metadata = await self.repo.get_by_parent_ids(
            parent_ids=parent_ids,
            user_id=self._authenticated_user().id,
        )
        files = await self._hydrate_files(metadata)
        return [file for file in files if file.file_type == FileType.IMAGE]

    async def with_derived_images(self, files: list[File]) -> list[File]:
        parent_ids = [file.id for file in files if file.file_type == FileType.TEXT]
        if not parent_ids:
            return files
        derived = await self.get_derived_images(parent_ids=parent_ids)
        present = {file.id for file in files}
        return files + [file for file in derived if file.id not in present]

    async def get_file_infos(self, file_ids: list[UUID]) -> list[FileInfo]:
        metadata = await self.repo.get_by_ids(file_ids)
        for file in metadata:
            self._require_owner(file, action="read")
        references = await self.repo.get_content_references(
            [file.id for file in metadata]
        )
        by_file = self._references_by_file(references)
        return [project_file_info(file, by_file[file.id]) for file in metadata]

    async def delete_file(self, id: UUID) -> FileInfo:
        user = self._authenticated_user()
        metadata = await self.repo.get_by_id_and_owner(
            file_id=id,
            user_id=user.id,
            tenant_id=user.tenant_id,
        )
        if metadata is None:
            raise NotFoundException()
        info = await self._file_info(metadata)
        deleted = await self.repo.delete_by_owner(
            id=id,
            user_id=user.id,
            tenant_id=user.tenant_id,
        )
        if deleted is None:
            raise NotFoundException()
        return info

    async def get_file_content(self, file_id: UUID) -> File:
        metadata = await self.repo.get_by_id(file_id=file_id)
        self._require_owner(metadata, action="read_content")
        return (await self._hydrate_files([metadata]))[0]

    async def save_transcription(self, file_id: UUID, transcription: str) -> str:
        payload = transcription.encode("utf-8")
        user = self._authenticated_user()
        async with self._write_transaction():
            metadata = await self.repo.get_by_id_for_update(file_id)
            self._require_owner(metadata, action="update")
            if metadata.file_type is not FileType.AUDIO:
                raise ValueError("Only audio files can own a transcription")

            references = await self.repo.get_content_references([file_id])
            existing = self._first_reference(
                references,
                FileContentVariant.TRANSCRIPTION,
            )
            if existing is not None:
                return (await self._read_bytes(metadata, existing)).decode("utf-8")

            async with self.object_content.capture_inline(
                _bytes_source(payload),
                declared_media_type="text/plain",
                verified_media_type="text/plain",
            ) as captured:
                prepared = await self.object_content.prepare_in_transaction(
                    self.repo.session,
                    intent=ContentIntent(
                        tenant_id=metadata.tenant_id,
                        created_by_user_id=user.id,
                        access_class=ContentAccessClass.PRIVATE_RESOURCE,
                        idempotency_key=f"file:{metadata.id}:transcription:0",
                        producer_receipt=f"file:{metadata.id}:transcription:0",
                    ),
                    content=captured,
                    storage_kind=StorageKind.POSTGRES_INLINE,
                )
                await self.repo.add_content_reference(
                    file_id=metadata.id,
                    content_id=prepared.id,
                    variant=FileContentVariant.TRANSCRIPTION,
                )
        return transcription

    async def get_download_no_auth(
        self,
        file_id: UUID,
        *,
        range_header: str | None = None,
    ) -> FileDownload:
        metadata = await self.repo.get_by_id(file_id=file_id)
        references = await self.repo.get_content_references([file_id])
        reference = self._primary_reference(metadata, references)

        if range_header is not None and metadata.file_type is not FileType.AUDIO:
            raise BadRequestException("Range is only supported for audio files")

        byte_range = (
            None
            if range_header is None
            else ByteRange.parse(range_header, size_bytes=reference.size_bytes)
        )
        grant = ContentReadGrant(
            content_id=reference.content_id,
            tenant_id=metadata.tenant_id,
            access_class=reference.access_class,
        )

        async def stream() -> AsyncGenerator[bytes]:
            async with self.object_content.open_content(
                grant,
                range_header=range_header,
            ) as opened:
                async for chunk in opened.chunks:
                    yield chunk

        return FileDownload(
            chunks=stream(),
            content_length=(
                reference.size_bytes
                if byte_range is None
                else byte_range.content_length
            ),
            media_type=reference.media_type,
            filename=(
                self._legacy_text_filename(metadata.name)
                if reference.variant is FileContentVariant.EXTRACTED_TEXT
                else metadata.name
            ),
            content_range=(None if byte_range is None else byte_range.response_header),
        )

    @staticmethod
    def _legacy_text_filename(filename: str) -> str:
        stem, separator, _extension = filename.rpartition(".")
        return f"{stem}.txt" if separator else f"{filename}.txt"

    async def _file_info(self, metadata: FileMetadata) -> FileInfo:
        references = await self.repo.get_content_references([metadata.id])
        return project_file_info(metadata, references)

    async def _hydrate_files(
        self,
        metadata: list[FileMetadata],
        *,
        include_transcription: bool = True,
    ) -> list[File]:
        references = await self.repo.get_content_references(
            [file.id for file in metadata]
        )
        by_file = self._references_by_file(references)
        hydrated: list[File] = []
        for file in metadata:
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
                if text_reference is not None:
                    text = (await self._read_bytes(file, text_reference)).decode(
                        "utf-8"
                    )
                    hydrated_reference = text_reference
            else:
                content_reference = self._preferred_binary_reference(
                    file,
                    file_references,
                )
                blob = await self._read_bytes(file, content_reference)
                hydrated_reference = content_reference

            if include_transcription:
                transcription_reference = self._first_reference(
                    file_references,
                    FileContentVariant.TRANSCRIPTION,
                )
                if transcription_reference is not None:
                    transcription = (
                        await self._read_bytes(file, transcription_reference)
                    ).decode("utf-8")

            hydrated.append(
                File(
                    id=file.id,
                    created_at=file.created_at,
                    updated_at=file.updated_at,
                    name=file.name,
                    checksum=hydrated_reference.sha256.hex(),
                    size=hydrated_reference.size_bytes,
                    mimetype=hydrated_reference.media_type,
                    file_type=file.file_type,
                    text=text,
                    blob=blob,
                    transcription=transcription,
                    user_id=file.user_id,
                    tenant_id=file.tenant_id,
                    parent_file_id=file.parent_file_id,
                )
            )
        return hydrated

    async def _read_bytes(
        self,
        file: FileMetadata,
        reference: FileContentReferenceRecord,
    ) -> bytes:
        grant = ContentReadGrant(
            content_id=reference.content_id,
            tenant_id=file.tenant_id,
            access_class=reference.access_class,
        )
        async with self.object_content.open_content(grant) as opened:
            return b"".join([chunk async for chunk in opened.chunks])

    @staticmethod
    def _references_by_file(
        references: list[FileContentReferenceRecord],
    ) -> defaultdict[UUID, list[FileContentReferenceRecord]]:
        by_file: defaultdict[UUID, list[FileContentReferenceRecord]] = defaultdict(list)
        for reference in references:
            by_file[reference.file_id].append(reference)
        return by_file

    @staticmethod
    def _first_reference(
        references: list[FileContentReferenceRecord],
        variant: FileContentVariant,
    ) -> FileContentReferenceRecord | None:
        return next(
            (reference for reference in references if reference.variant is variant),
            None,
        )

    def _primary_reference(
        self,
        file: FileMetadata,
        references: list[FileContentReferenceRecord],
    ) -> FileContentReferenceRecord:
        reference = select_primary_file_reference(file.file_type, references)
        if reference is not None:
            return reference
        raise NotFoundException(f"File {file.id} has no durable content")

    def _preferred_binary_reference(
        self,
        file: FileMetadata,
        references: list[FileContentReferenceRecord],
    ) -> FileContentReferenceRecord:
        reference = select_binary_file_reference(file.file_type, references)
        if reference is not None:
            return reference
        raise NotFoundException(f"File {file.id} has no readable binary content")

    def _require_owner(self, file: FileMetadata, *, action: str) -> None:
        if file.user_id == self._authenticated_user().id:
            return
        raise UnauthorizedException(
            "You can only access files you own.",
            code="forbidden_action",
            context={
                "resource_type": "file",
                "action": action,
                "auth_layer": "domain_policy",
            },
        )

    def _authenticated_user(self) -> UserInDB:
        if self.user is None:
            raise UnauthorizedException("Authentication is required")
        return self.user
