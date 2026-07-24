import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import BinaryIO
from uuid import UUID

from fastapi import UploadFile

from eneo.files.file_size_service import FileSizeService
from eneo.icons.icon import Icon, IconMetadataCreate
from eneo.icons.icon_repo import IconRepository
from eneo.main.exceptions import (
    BadRequestException,
    FileTooLargeException,
    NotFoundException,
)
from eneo.object_content.content import (
    ContentAccessClass,
    ContentIntent,
    ContentReadGrant,
    StorageKind,
)
from eneo.object_content.content_service import ObjectContentService

ICON_MAX_SIZE = 262144
ICON_ALLOWED_MIMETYPES = (
    "image/jpeg",
    "image/png",
    "image/webp",
)
_ICON_STREAM_CHUNK_BYTES = 64 * 1024


async def _upload_chunks(upload_file: UploadFile) -> AsyncGenerator[bytes]:
    while chunk := await upload_file.read(_ICON_STREAM_CHUNK_BYTES):
        yield chunk


def _read_captured(file: BinaryIO) -> bytes:
    position = file.tell()
    try:
        file.seek(0)
        return file.read()
    finally:
        file.seek(position)


class IconService:
    """Own Icon policy while delegating durable primary bytes."""

    def __init__(
        self,
        icon_repo: IconRepository,
        file_size_service: FileSizeService,
        object_content: ObjectContentService,
    ) -> None:
        self.icon_repo = icon_repo
        self.file_size_service = file_size_service
        self.object_content = object_content

    @staticmethod
    def validate_mimetype(mimetype: str | None) -> None:
        if mimetype not in ICON_ALLOWED_MIMETYPES:
            raise BadRequestException(
                f"Invalid icon format '{mimetype}'. Allowed formats: PNG, JPEG, WebP"
            )

    @asynccontextmanager
    async def _write_transaction(self) -> AsyncGenerator[None]:
        session = self.icon_repo.session
        if session.in_transaction():
            yield
            return
        async with session.begin():
            yield

    async def create_icon(
        self,
        upload_file: UploadFile,
        *,
        tenant_id: UUID,
        created_by_user_id: UUID,
    ) -> Icon:
        self.validate_mimetype(upload_file.content_type)
        file_size = self.file_size_service.get_file_size(upload_file.file)
        if file_size > ICON_MAX_SIZE:
            raise FileTooLargeException(
                file_size=file_size,
                max_size=ICON_MAX_SIZE,
            )
        media_type = upload_file.content_type
        assert media_type is not None

        async with self._write_transaction():
            metadata = await self.icon_repo.add_metadata(
                IconMetadataCreate(tenant_id=tenant_id)
            )
            async with self.object_content.capture_inline(
                _upload_chunks(upload_file),
                declared_media_type=media_type,
                verified_media_type=media_type,
                business_maximum_bytes=ICON_MAX_SIZE,
            ) as captured:
                prepared = await self.object_content.prepare_in_transaction(
                    self.icon_repo.session,
                    intent=ContentIntent(
                        tenant_id=tenant_id,
                        created_by_user_id=created_by_user_id,
                        access_class=ContentAccessClass.PUBLIC_IMMUTABLE,
                        idempotency_key=f"icon:{metadata.id}:primary",
                        producer_receipt=f"icon:{metadata.id}:primary",
                    ),
                    content=captured,
                    storage_kind=StorageKind.POSTGRES_INLINE,
                )
                await self.icon_repo.add_primary_reference(
                    icon_id=metadata.id,
                    content_id=prepared.id,
                )
                payload = await asyncio.to_thread(_read_captured, captured.file)
        return Icon(
            id=metadata.id,
            created_at=metadata.created_at,
            updated_at=metadata.updated_at,
            tenant_id=metadata.tenant_id,
            blob=payload,
            mimetype=captured.verified_media_type,
            size=captured.size_bytes,
        )

    async def get_icon(self, icon_id: UUID) -> Icon:
        metadata = await self.icon_repo.get(icon_id)
        if metadata is None:
            raise NotFoundException(f"Icon with id {icon_id} not found")
        reference = await self.icon_repo.get_primary_reference(icon_id)
        if reference is None:
            raise NotFoundException(f"Icon with id {icon_id} has no durable content")

        async with self.object_content.open_content(
            ContentReadGrant(
                content_id=reference.content_id,
                tenant_id=metadata.tenant_id,
                access_class=reference.access_class,
            )
        ) as opened:
            payload = b"".join([chunk async for chunk in opened.chunks])

        return Icon(
            id=metadata.id,
            created_at=metadata.created_at,
            updated_at=metadata.updated_at,
            tenant_id=metadata.tenant_id,
            blob=payload,
            mimetype=reference.media_type,
            size=reference.size_bytes,
        )

    async def delete_icon(self, icon_id: UUID, tenant_id: UUID) -> None:
        if await self.icon_repo.get(icon_id) is None:
            raise NotFoundException(f"Icon with id {icon_id} not found")
        if not await self.icon_repo.delete_by_tenant(icon_id, tenant_id):
            raise BadRequestException("Cannot delete icon from another tenant")
