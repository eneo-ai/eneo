import hashlib
from uuid import UUID

from fastapi import UploadFile

from intric.files.file_models import File, FileBaseWithContent, FileCreate, FileType
from intric.files.file_protocol import FileProtocol
from intric.files.file_repo import FileRepository
from intric.main.exceptions import NotFoundException, UnauthorizedException
from intric.users.user import UserInDB


class FileService:
    def __init__(self, user: UserInDB, repo: FileRepository, protocol: FileProtocol):
        self.user = user
        self.repo = repo
        self.protocol = protocol

    async def save_file(self, upload_file: UploadFile):
        file = await self.protocol.to_domain(upload_file)

        saved_file = await self.repo.add(
            FileCreate(
                **file.model_dump(),
                user_id=self.user.id,
                tenant_id=self.user.tenant_id,
            )
        )

        # Don't calculate token count here - we don't know which model will be used
        # Token counting will happen when the file is used in an assistant context
        return saved_file

    async def save_image_from_bytes(
        self,
        image_data: bytes,
        name: str = "generated_image.jpeg",
        mimetype: str = "image/jpeg",
    ):
        """Create a file from raw image bytes returned by an AI model."""
        checksum = hashlib.md5(image_data).hexdigest()
        size = len(image_data)

        file_base = FileBaseWithContent(
            name=name,
            checksum=checksum,
            size=size,
            file_type=FileType.IMAGE,
            mimetype=mimetype,
            blob=image_data,
        )

        return await self.repo.add(
            FileCreate(
                **file_base.model_dump(),
                user_id=self.user.id,
                tenant_id=self.user.tenant_id,
            )
        )

    async def get_file_by_id(self, file_id: UUID):
        file = await self.repo.get_by_id(file_id=file_id)

        if file.user_id != self.user.id:
            raise UnauthorizedException()

        return file

    async def get_files_by_ids(
        self, file_ids: list[UUID], include_transcription: bool = True
    ):
        return await self.repo.get_list_by_id_and_user(
            ids=file_ids,
            user_id=self.user.id,
            include_transcription=include_transcription,
        )

    async def get_files_for_token_estimate(
        self, file_ids: list[UUID], include_transcription: bool = True
    ):
        return await self.repo.get_list_by_id_and_tenant(
            ids=file_ids,
            tenant_id=self.user.tenant_id,
            include_transcription=include_transcription,
        )

    async def get_files(self):
        return await self.repo.get_list_by_user(user_id=self.user.id)

    async def get_file_infos(self, file_ids: list[UUID]):
        files = await self.repo.get_file_infos(file_ids)

        for file in files:
            if file.user_id != self.user.id:
                raise UnauthorizedException()

        return files

    async def delete_file(self, id: UUID):
        file_deleted = await self.repo.delete(id)

        if file_deleted.user_id != self.user.id:
            raise UnauthorizedException()

        return file_deleted

    async def update_file(self, file: File) -> File:
        if file.user_id != self.user.id:
            raise UnauthorizedException()

        return await self.repo.update(file)

    async def get_file_content(self, file_id: UUID):
        file = await self.repo.get_by_id(file_id=file_id)

        if file.user_id != self.user.id:
            raise UnauthorizedException()

        if file.text is None and file.blob is None:
            raise NotFoundException(detail="File content not found")

        return file

    async def get_file_content_no_auth(self, file_id: UUID):
        """Get file content without checking user authorization.

        This method should only be used by endpoints that verify authorization
        through other means, such as signed URLs.
        """
        file = await self.repo.get_by_id(file_id=file_id)

        if file.text is None and file.blob is None:
            raise NotFoundException(detail="File content not found")

        return file
