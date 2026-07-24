from collections import defaultdict
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from uuid import UUID

from fastapi import UploadFile

from eneo.files.file_content_loader import FileContentLoader
from eneo.files.file_models import (
    File,
    FileContentVariant,
    FileDeletionPreview,
    FileInfo,
    FileInUseError,
    FileMetadata,
    FileMetadataCreate,
    FilePublic,
    FileType,
    FileUsageKind,
    FileUsageSummary,
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
    select_primary_file_reference,
)
from eneo.files.file_usage import FileUsageRepository
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
    _close: Callable[[], Awaitable[None]] = field(repr=False)

    async def aclose(self) -> None:
        await self._close()


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
        self._object_content = object_content
        self._content_loader = FileContentLoader(repo, object_content)
        self._usage = FileUsageRepository(repo.session)

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
            async with self._object_content.capture_inline(
                pending.chunks,
                declared_media_type=pending.declared_media_type,
                verified_media_type=pending.verified_media_type,
            ) as captured:
                stored = await self._object_content.prepare_in_transaction(
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

    async def get_public_file_by_id(self, file_id: UUID) -> FilePublic:
        metadata = await self.repo.get_by_id(file_id=file_id)
        self._require_owner(metadata, action="read")
        return (await self._project_public_files([metadata]))[0]

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

    async def get_public_files(self) -> list[FilePublic]:
        metadata = await self.repo.get_list_by_user(
            user_id=self._authenticated_user().id
        )
        return await self._project_public_files(metadata)

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

    async def get_deletion_preview(self, file_id: UUID) -> FileDeletionPreview:
        user = self._authenticated_user()
        metadata = await self.repo.get_by_id_and_owner(
            file_id=file_id,
            user_id=user.id,
            tenant_id=user.tenant_id,
        )
        if metadata is None:
            raise NotFoundException()
        family_ids = await self._usage.list_family(
            root_file_id=file_id,
            tenant_id=user.tenant_id,
        )
        if not family_ids:
            raise NotFoundException()
        return await self._deletion_preview(
            file_id=file_id,
            family_ids=family_ids,
        )

    async def delete_file(self, id: UUID) -> FileInfo:
        user = self._authenticated_user()
        async with self._write_transaction():
            metadata = await self.repo.get_by_id_and_owner(
                file_id=id,
                user_id=user.id,
                tenant_id=user.tenant_id,
            )
            if metadata is None:
                raise NotFoundException()
            family_ids = await self._usage.lock_family(
                root_file_id=id,
                tenant_id=user.tenant_id,
            )
            if not family_ids:
                raise NotFoundException()
            preview = await self._deletion_preview(
                file_id=id,
                family_ids=family_ids,
            )
            if not preview.can_delete:
                raise FileInUseError(preview)

            info = await self._file_info(metadata)
            deleted = await self.repo.delete_by_owner(
                id=id,
                user_id=user.id,
                tenant_id=user.tenant_id,
            )
            if deleted is None:
                raise NotFoundException()
            return info

    async def _deletion_preview(
        self,
        *,
        file_id: UUID,
        family_ids: list[UUID],
    ) -> FileDeletionPreview:
        usage = {
            item.kind: item.count
            for item in await self._usage.count_product_usage(family_ids)
        }
        blockers = [
            FileUsageSummary(kind=kind, count=usage[kind])
            for kind in FileUsageKind
            if kind in usage
        ]
        return FileDeletionPreview(
            file_id=file_id,
            can_delete=not blockers,
            affected_file_count=len(family_ids),
            blockers=blockers,
        )

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

            async with self._object_content.capture_inline(
                _bytes_source(payload),
                declared_media_type="text/plain",
                verified_media_type="text/plain",
            ) as captured:
                prepared = await self._object_content.prepare_in_transaction(
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

        if range_header is not None:
            ByteRange.parse(range_header, size_bytes=reference.size_bytes)
        grant = ContentReadGrant(
            content_id=reference.content_id,
            tenant_id=metadata.tenant_id,
            access_class=reference.access_class,
        )

        read_context = self._object_content.open_content(
            grant,
            range_header=range_header,
        )
        opened = await read_context.__aenter__()
        closed = False

        async def exit_read_context(
            error: BaseException | None = None,
        ) -> bool | None:
            nonlocal closed
            if closed:
                return None
            closed = True
            if error is None:
                return await read_context.__aexit__(None, None, None)
            return await read_context.__aexit__(
                type(error),
                error,
                error.__traceback__,
            )

        async def stream() -> AsyncGenerator[bytes]:
            try:
                async for chunk in opened.chunks:
                    yield chunk
            except BaseException as error:
                if not await exit_read_context(error):
                    raise
            else:
                await exit_read_context()

        async def close() -> None:
            await exit_read_context()

        return FileDownload(
            chunks=stream(),
            content_length=opened.content_length,
            media_type=opened.media_type,
            filename=(
                self._legacy_text_filename(metadata.name)
                if reference.variant is FileContentVariant.EXTRACTED_TEXT
                else metadata.name
            ),
            content_range=opened.content_range,
            _close=close,
        )

    @staticmethod
    def _legacy_text_filename(filename: str) -> str:
        stem, separator, _extension = filename.rpartition(".")
        return f"{stem}.txt" if separator else f"{filename}.txt"

    async def _file_info(self, metadata: FileMetadata) -> FileInfo:
        references = await self.repo.get_content_references([metadata.id])
        return project_file_info(metadata, references)

    async def _project_public_files(
        self,
        metadata: list[FileMetadata],
    ) -> list[FilePublic]:
        references = await self.repo.get_content_references(
            [file.id for file in metadata]
        )
        by_file = self._references_by_file(references)
        transcription_by_file: dict[UUID, FileContentReferenceRecord] = {}
        grants: list[ContentReadGrant] = []
        for file in metadata:
            transcription_reference = self._first_reference(
                by_file[file.id],
                FileContentVariant.TRANSCRIPTION,
            )
            if transcription_reference is None:
                continue
            transcription_by_file[file.id] = transcription_reference
            grants.append(
                ContentReadGrant(
                    content_id=transcription_reference.content_id,
                    tenant_id=file.tenant_id,
                    access_class=transcription_reference.access_class,
                )
            )
        payloads = await self._object_content.read_content_bytes(grants)

        projected: list[FilePublic] = []
        for file in metadata:
            file_references = by_file[file.id]
            info = project_file_info(file, file_references)
            transcription_reference = transcription_by_file.get(file.id)
            transcription = (
                None
                if transcription_reference is None
                else payloads[transcription_reference.content_id].decode("utf-8")
            )
            projected.append(
                FilePublic(
                    **info.model_dump(),
                    transcription=transcription,
                )
            )
        return projected

    async def _hydrate_files(
        self,
        metadata: list[FileMetadata],
        *,
        include_transcription: bool = True,
    ) -> list[File]:
        loaded = await self._content_loader.load(
            metadata,
            include_transcription=include_transcription,
        )
        return [loaded[file.id] for file in metadata]

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
        async with self._object_content.open_content(grant) as opened:
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
