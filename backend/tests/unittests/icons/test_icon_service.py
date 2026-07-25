from contextlib import asynccontextmanager
from datetime import UTC, datetime
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import UploadFile

from eneo.icons.icon import IconMetadata
from eneo.icons.icon_service import (
    ICON_ALLOWED_MIMETYPES,
    IconService,
)
from eneo.main.exceptions import BadRequestException, FileTooLargeException
from eneo.object_content.content import (
    CapturedContent,
    ContentAccessClass,
    ContentRead,
    StorageKind,
)
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


async def test_create_icon_returns_metadata_without_reading_captured_payload() -> None:
    class ReadForbidden(BytesIO):
        def read(self, size: int = -1) -> bytes:
            raise AssertionError("icon creation must not hydrate captured bytes")

    tenant_id = uuid4()
    metadata = IconMetadata(
        id=uuid4(),
        tenant_id=tenant_id,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    captured = CapturedContent(
        file=ReadForbidden(b"captured"),
        sha256=b"digest",
        size_bytes=8,
        declared_media_type="image/png",
        verified_media_type="image/png",
        part_sha256=(),
    )

    @asynccontextmanager
    async def capture_for_target(*_args, **_kwargs):
        yield captured

    repository = MagicMock()
    repository.session.in_transaction.return_value = True
    repository.add_metadata = AsyncMock(return_value=metadata)
    repository.add_primary_reference = AsyncMock()
    object_content = MagicMock()
    object_content.ensure_target_ready = AsyncMock()
    object_content.capture_for_target.side_effect = capture_for_target
    object_content.prepare_in_transaction = AsyncMock(
        return_value=SimpleNamespace(id=uuid4())
    )
    service = IconService(
        icon_repo=repository,
        file_size_service=MagicMock(
            get_file_size=MagicMock(return_value=captured.size_bytes)
        ),
        object_content=object_content,
        upload_admission=UploadAdmissionSnapshot(
            policy_revision=7,
            session_storage_target=StorageKind.POSTGRES_INLINE,
            session_operator_ceiling_bytes=20,
            session_file_maximum_bytes=20,
            session_image_maximum_bytes=20,
            session_audio_maximum_bytes=20,
            knowledge_file_maximum_bytes=20,
            knowledge_audio_maximum_bytes=20,
        ),
    )

    created = await service.create_icon(
        UploadFile(
            file=BytesIO(b"captured"),
            filename="icon.png",
            headers={"content-type": "image/png"},
        ),
        tenant_id=tenant_id,
        created_by_user_id=uuid4(),
    )

    assert created == metadata


async def test_open_icon_exposes_the_content_stream_incrementally() -> None:
    icon_id = uuid4()
    tenant_id = uuid4()
    metadata = IconMetadata(
        id=icon_id,
        tenant_id=tenant_id,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    reference = SimpleNamespace(
        content_id=uuid4(),
        access_class=ContentAccessClass.PUBLIC_IMMUTABLE,
        media_type="image/png",
        size_bytes=6,
    )
    pulls: list[bytes] = []
    closed = False

    async def source():
        for chunk in (b"abc", b"def"):
            pulls.append(chunk)
            yield chunk

    @asynccontextmanager
    async def open_content(_grant):
        nonlocal closed
        try:
            yield ContentRead(
                chunks=source(),
                content_length=6,
                media_type="image/png",
                content_range=None,
            )
        finally:
            closed = True

    repository = MagicMock()
    repository.get = AsyncMock(return_value=metadata)
    repository.get_primary_reference = AsyncMock(return_value=reference)
    object_content = MagicMock()
    object_content.open_content.side_effect = open_content
    service = IconService(
        icon_repo=repository,
        file_size_service=MagicMock(),
        object_content=object_content,
    )

    opened = await service.open_icon(icon_id)
    assert await anext(opened.chunks) == b"abc"
    assert pulls == [b"abc"]

    await opened.aclose()
    assert closed
