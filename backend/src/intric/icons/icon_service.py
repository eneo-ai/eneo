from uuid import UUID

from fastapi import UploadFile

from intric.files.file_size_service import FileSizeService
from intric.icons.icon import Icon, IconCreate
from intric.icons.icon_repo import IconRepository
from intric.main.exceptions import BadRequestException, FileTooLargeException, NotFoundException

ICON_MAX_SIZE = 262144  # 256 KB
ICON_ALLOWED_MIMETYPES = {"image/png", "image/jpeg", "image/webp"}


class IconService:
    def __init__(
        self,
        icon_repo: IconRepository,
        file_size_service: FileSizeService,
    ):
        self.icon_repo = icon_repo
        self.file_size_service = file_size_service

    @staticmethod
    def validate_mimetype(mimetype: str | None) -> None:
        if mimetype not in ICON_ALLOWED_MIMETYPES:
            raise BadRequestException(
                f"Invalid icon format '{mimetype}'. Allowed formats: PNG, JPEG, WebP"
            )

    @staticmethod
    def validate_size(data: bytes) -> None:
        if len(data) > ICON_MAX_SIZE:
            raise FileTooLargeException(
                f"Icon exceeds maximum size of 256 KB (got {len(data)} bytes)"
            )

    async def create_icon(self, upload_file: UploadFile, tenant_id: UUID) -> Icon:
        """Validates and stores an icon. Raises BadRequestException or FileTooLargeException."""
        self.validate_mimetype(upload_file.content_type)

        if self.file_size_service.is_too_large(upload_file.file, ICON_MAX_SIZE):
            raise FileTooLargeException("Icon exceeds maximum size of 256 KB")

        content = await upload_file.read()
        self.validate_size(content)

        icon_create = IconCreate(
            blob=content,
            mimetype=upload_file.content_type,
            size=len(content),
            tenant_id=tenant_id,
        )

        return await self.icon_repo.add(icon_create)

    async def get_icon(self, icon_id: UUID) -> Icon:
        icon = await self.icon_repo.get(icon_id)
        if icon is None:
            raise NotFoundException(f"Icon with id {icon_id} not found")
        return icon

    async def delete_icon(self, icon_id: UUID, tenant_id: UUID) -> None:
        icon = await self.icon_repo.get(icon_id)
        if icon is None:
            raise NotFoundException(f"Icon with id {icon_id} not found")

        if icon.tenant_id != tenant_id:
            raise BadRequestException("Cannot delete icon from another tenant")

        await self.icon_repo.delete(icon_id)
