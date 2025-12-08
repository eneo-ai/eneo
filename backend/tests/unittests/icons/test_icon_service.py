from io import BytesIO
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import UploadFile

from intric.icons.icon_service import (
    ICON_ALLOWED_MIMETYPES,
    ICON_MAX_SIZE,
    IconService,
)
from intric.main.exceptions import BadRequestException, FileTooLargeException


@pytest.fixture
def service():
    return IconService(
        icon_repo=AsyncMock(),
        file_size_service=MagicMock(),
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

def test_validate_size_under_limit_ok():
    data = b"x" * (ICON_MAX_SIZE - 1)
    IconService.validate_size(data)


def test_validate_size_at_limit_ok():
    data = b"x" * ICON_MAX_SIZE
    IconService.validate_size(data)


def test_validate_size_over_limit_raises():
    data = b"x" * (ICON_MAX_SIZE + 1)
    with pytest.raises(FileTooLargeException):
        IconService.validate_size(data)

async def test_create_icon_rejects_invalid_mimetype(service: IconService):
    upload_file = UploadFile(
        file=BytesIO(b"test"),
        filename="test.gif",
        headers={"content-type": "image/gif"},
    )

    with pytest.raises(BadRequestException):
        await service.create_icon(upload_file, tenant_id=uuid4())


async def test_create_icon_rejects_oversized_file(service: IconService):
    service.file_size_service.is_too_large.return_value = True

    upload_file = UploadFile(
        file=BytesIO(b"x" * (ICON_MAX_SIZE + 1)),
        filename="large.png",
        headers={"content-type": "image/png"},
    )

    with pytest.raises(FileTooLargeException):
        await service.create_icon(upload_file, tenant_id=uuid4())
