from io import BytesIO
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import UploadFile

from eneo.icons.icon_service import (
    ICON_ALLOWED_MIMETYPES,
    ICON_MAX_SIZE,
    IconService,
)
from eneo.main.exceptions import BadRequestException, FileTooLargeException


@pytest.fixture
def service():
    return IconService(
        icon_repo=AsyncMock(),
        file_size_service=MagicMock(),
        object_content=AsyncMock(),
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
    service.file_size_service.get_file_size.return_value = ICON_MAX_SIZE + 1

    upload_file = UploadFile(
        file=BytesIO(b"x" * (ICON_MAX_SIZE + 1)),
        filename="large.png",
        headers={"content-type": "image/png"},
    )

    with pytest.raises(FileTooLargeException):
        await service.create_icon(
            upload_file,
            tenant_id=uuid4(),
            created_by_user_id=uuid4(),
        )
