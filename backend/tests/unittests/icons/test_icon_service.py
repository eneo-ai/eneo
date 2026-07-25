from io import BytesIO
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import UploadFile

from eneo.icons.icon_service import (
    ICON_ALLOWED_MIMETYPES,
    IconService,
)
from eneo.main.exceptions import BadRequestException, FileTooLargeException
from eneo.object_content.content import StorageKind
from eneo.object_content.deployment_policy import (
    UploadAdmissionSnapshot,
    UploadLimitUseCase,
)


@pytest.fixture
def service():
    return IconService(
        icon_repo=AsyncMock(),
        file_size_service=MagicMock(),
        object_content=AsyncMock(),
        upload_admission=UploadAdmissionSnapshot(
            policy_revision=7,
            session_storage_target=StorageKind.POSTGRES_INLINE,
            session_operator_ceiling_bytes=4,
            session_file_maximum_bytes=4,
            session_image_maximum_bytes=4,
            session_audio_maximum_bytes=4,
            knowledge_file_maximum_bytes=4,
            knowledge_audio_maximum_bytes=4,
        ),
    )


@pytest.mark.parametrize("mimetype", sorted(ICON_ALLOWED_MIMETYPES))
def test_validate_mimetype_allowed_ok(mimetype: str):
    IconService.validate_mimetype(mimetype)


def test_validate_mimetype_gif_raises():
    with pytest.raises(BadRequestException):
        IconService.validate_mimetype("image/gif")


def test_validate_mimetype_none_raises():
    with pytest.raises(BadRequestException):
        IconService.validate_mimetype(None)


def test_validate_mimetype_invalid_raises():
    with pytest.raises(BadRequestException):
        IconService.validate_mimetype("application/pdf")


async def test_create_icon_rejects_invalid_mimetype(service: IconService):
    upload_file = UploadFile(
        file=BytesIO(b"test"),
        filename="test.gif",
        headers={"content-type": "image/gif"},
    )

    with pytest.raises(BadRequestException):
        await service.create_icon(
            upload_file,
            tenant_id=uuid4(),
            created_by_user_id=uuid4(),
        )


async def test_create_icon_rejects_oversized_file(service: IconService):
    service.file_size_service.get_file_size.return_value = 5

    upload_file = UploadFile(
        file=BytesIO(b"x" * 5),
        filename="large.png",
        headers={"content-type": "image/png"},
    )

    with pytest.raises(FileTooLargeException) as error:
        await service.create_icon(
            upload_file,
            tenant_id=uuid4(),
            created_by_user_id=uuid4(),
        )
    assert error.value.max_size == 4
    assert error.value.limit_name == UploadLimitUseCase.SESSION_IMAGE.value
