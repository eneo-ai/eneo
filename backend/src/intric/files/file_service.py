import hashlib
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from fastapi import UploadFile

from intric.authentication.principal_types import PrincipalType
from intric.files.file_models import (
    File,
    FileBaseWithContent,
    FileCreate,
    FileInfo,
    FileType,
)
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
    async def _write_transaction(self) -> AsyncGenerator[None, None]:
        """Open a short write transaction only when one is not already active."""
        session = self.repo.session
        if session.in_transaction():
            yield
            return

        async with session.begin():
            yield

    async def save_file(
        self, upload_file: UploadFile, max_size: int | None = None
    ) -> File:
        if max_size is None:
            file = await self.protocol.to_domain(upload_file)
        else:
            file = await self.protocol.to_domain(upload_file, max_size=max_size)

        return await self.save_file_content(file)

    async def document_from_upload(
        self,
        upload_file: UploadFile,
        max_size: int | None = None,
    ) -> FileBaseWithContent:
        if max_size is None:
            return await self.protocol.document_to_domain(upload_file)
        return await self.protocol.document_to_domain(upload_file, max_size=max_size)

    async def save_file_content(self, file: FileBaseWithContent) -> File:
        return await self._save_file_record(file)

    async def _save_file_record(self, file: FileBaseWithContent) -> File:
        async with self._write_transaction():
            saved_file = await self.repo.add(
                FileCreate.model_validate(
                    {
                        **file.model_dump(mode="python"),
                        **self._owner_fields(),
                        "tenant_id": self.user.tenant_id,
                    }
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
                FileCreate.model_validate(
                    {
                        **file_base.model_dump(mode="python"),
                        **self._owner_fields(),
                        "tenant_id": self.user.tenant_id,
                    }
                )
            )

    async def get_file_by_id(self, file_id: UUID):
        file = await self.repo.get_by_id(file_id=file_id)

        if not self._owns_file(file):
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
        return await self.repo.get_list_by_id_for_owner(
            ids=file_ids,
            owner_type=self._owner_type().value,
            owner_user_id=self._owner_user_id(),
            owner_api_key_id=self._owner_api_key_id(),
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

    async def get_files(self) -> list[File]:
        if self._owner_type() == PrincipalType.USER:
            return await self.repo.get_list_by_user(user_id=self.user.id)
        return await self.repo.get_list_by_owner_principal(
            owner_type=self._owner_type().value,
            owner_api_key_id=self._owner_api_key_id(),
        )

    async def get_file_infos(self, file_ids: list[UUID]):
        files = await self.repo.get_file_infos(file_ids)

        for file in files:
            if not self._owns_file(file):
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
        file_deleted = await self.repo.delete_by_owner_principal(
            id=id,
            owner_type=self._owner_type().value,
            owner_user_id=self._owner_user_id(),
            owner_api_key_id=self._owner_api_key_id(),
        )

        if file_deleted is None:
            raise NotFoundException()

        return file_deleted

    async def update_file(self, file: File) -> File:
        if not self._owns_file(file):
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

        if not self._owns_file(file):
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

    def _owner_type(self) -> PrincipalType:
        key = getattr(self.user, "active_api_key", None)
        if key is not None:
            ownership = getattr(key, "ownership", "user")
            ownership_value = str(getattr(ownership, "value", ownership))
            if ownership_value == "service":
                return PrincipalType.SERVICE_KEY
        return PrincipalType.USER

    def _owner_api_key_id(self) -> UUID | None:
        if self._owner_type() == PrincipalType.SERVICE_KEY:
            key = getattr(self.user, "active_api_key", None)
            return getattr(key, "id", None)
        return None

    def _owner_user_id(self) -> UUID | None:
        if self._owner_type() == PrincipalType.USER:
            return self.user.id
        return None

    def _owner_fields(self) -> dict[str, Any]:
        return {
            "owner_type": self._owner_type(),
            "owner_user_id": self._owner_user_id(),
            "owner_api_key_id": self._owner_api_key_id(),
            "user_id": self._owner_user_id(),
        }

    def _owns_file(self, file: File | FileInfo) -> bool:
        owner_type = file.owner_type
        if owner_type is None:
            return file.user_id == self.user.id
        if owner_type == PrincipalType.USER:
            return file.owner_user_id == self.user.id
        return file.owner_api_key_id == self._owner_api_key_id()

    async def get_file_content_no_auth(self, file_id: UUID):
        """Get file content without checking user authorization.

        This method should only be used by endpoints that verify authorization
        through other means, such as signed URLs.
        """
        file = await self.repo.get_by_id(file_id=file_id)

        if file.text is None and file.blob is None:
            raise NotFoundException("File content not found")

        return file
