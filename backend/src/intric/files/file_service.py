import hashlib
from contextlib import asynccontextmanager
from typing import AsyncIterator
from uuid import UUID

from fastapi import UploadFile

from intric.files.file_models import File, FileBaseWithContent, FileCreate, FileType
from intric.files.file_protocol import FileProtocol
from intric.files.file_repo import FileRepository
from intric.main.exceptions import NotFoundException, UnauthorizedException
from intric.users.user import UserInDB


class FileService:
    def __init__(self, user: UserInDB, repo: FileRepository, protocol: FileProtocol):
        super().__init__()
        self.user = user
        self.repo = repo
        self.protocol = protocol

    @asynccontextmanager
    async def _write_transaction(self) -> AsyncIterator[None]:
        """Open a short write transaction only when one is not already active."""
        session = self.repo.session
        if session.in_transaction():
            yield
            return

        async with session.begin():
            yield

    async def save_file(self, upload_file: UploadFile):
        file, derived_images = await self.protocol.to_domain_with_derivatives(
            upload_file
        )

        async with self._write_transaction():
            saved_file = await self.repo.add(
                FileCreate(
                    **file.model_dump(),
                    user_id=self.user.id,
                    tenant_id=self.user.tenant_id,
                )
            )
            for derived in derived_images:
                await self.repo.add(
                    FileCreate(
                        **derived.model_dump(),
                        user_id=self.user.id,
                        tenant_id=self.user.tenant_id,
                        parent_file_id=saved_file.id,
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

        async with self._write_transaction():
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
            raise UnauthorizedException(
                "You can only access files you own.",
                code="forbidden_action",
                context={
                    "resource_type": "file",
                    "action": "read",
                    "auth_layer": "domain_policy",
                },
            )

        return file

    async def get_files_by_ids(
        self, file_ids: list[UUID], include_transcription: bool = True
    ):
        return await self.repo.get_list_by_id_and_user(
            ids=file_ids,
            user_id=self.user.id,
            include_transcription=include_transcription,
        )

    async def get_files(self) -> list[File]:
        return await self.repo.get_list_by_user(user_id=self.user.id)

    async def get_derived_images(self, parent_ids: list[UUID]) -> list[File]:
        """Get image files derived from the given files (e.g. PDF-extracted)."""
        files = await self.repo.get_by_parent_ids(
            parent_ids=parent_ids, user_id=self.user.id
        )
        return [file for file in files if file.file_type == FileType.IMAGE]

    async def with_derived_images(self, files: list[File]) -> list[File]:
        """The given files plus the stored images derived from them.

        Callers gate on model vision support — derived images exist solely
        as vision input for the completion payload.
        """
        parent_ids = [file.id for file in files if file.file_type == FileType.TEXT]
        if not parent_ids:
            return files

        derived = await self.get_derived_images(parent_ids=parent_ids)
        present = {file.id for file in files}
        return files + [file for file in derived if file.id not in present]

    async def get_file_infos(self, file_ids: list[UUID]):
        files = await self.repo.get_file_infos(file_ids)

        for file in files:
            if file.user_id != self.user.id:
                raise UnauthorizedException(
                    "You can only access files you own.",
                    code="forbidden_action",
                    context={
                        "resource_type": "file",
                        "action": "read",
                        "auth_layer": "domain_policy",
                    },
                )

        return files

    async def delete_file(self, id: UUID):
        file_deleted = await self.repo.delete_by_owner(
            id=id,
            user_id=self.user.id,
            tenant_id=self.user.tenant_id,
        )

        if file_deleted is None:
            raise NotFoundException()

        return file_deleted

    async def update_file(self, file: File) -> File:
        if file.user_id != self.user.id:
            raise UnauthorizedException(
                "You can only update files you own.",
                code="forbidden_action",
                context={
                    "resource_type": "file",
                    "action": "update",
                    "auth_layer": "domain_policy",
                },
            )

        return await self.repo.update(file)

    async def get_file_content(self, file_id: UUID):
        file = await self.repo.get_by_id(file_id=file_id)

        if file.user_id != self.user.id:
            raise UnauthorizedException(
                "You can only access files you own.",
                code="forbidden_action",
                context={
                    "resource_type": "file",
                    "action": "read_content",
                    "auth_layer": "domain_policy",
                },
            )

        if file.text is None and file.blob is None:
            raise NotFoundException("File content not found")

        return file

    async def get_file_content_no_auth(self, file_id: UUID):
        """Get file content without checking user authorization.

        This method should only be used by endpoints that verify authorization
        through other means, such as signed URLs.
        """
        file = await self.repo.get_by_id(file_id=file_id)

        if file.text is None and file.blob is None:
            raise NotFoundException("File content not found")

        return file
