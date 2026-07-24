from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.files.file_models import FileType
from eneo.files.file_service import FileService


@pytest.fixture
def service() -> FileService:
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    repo = AsyncMock()
    repo.session = MagicMock()
    return FileService(
        user=user,
        repo=repo,
        protocol=AsyncMock(),
        object_content=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_with_derived_images_appends_new_images_once(
    service: FileService,
) -> None:
    parent = MagicMock(id=uuid4(), file_type=FileType.TEXT)
    already_attached = MagicMock(id=uuid4(), file_type=FileType.IMAGE)
    new_derived = MagicMock(id=uuid4(), file_type=FileType.IMAGE)
    service.get_derived_images = AsyncMock(return_value=[already_attached, new_derived])

    result = await service.with_derived_images([parent, already_attached])

    assert result == [parent, already_attached, new_derived]
    service.get_derived_images.assert_awaited_once_with(parent_ids=[parent.id])


@pytest.mark.asyncio
async def test_with_derived_images_skips_lookup_without_text_files(
    service: FileService,
) -> None:
    image = MagicMock(id=uuid4(), file_type=FileType.IMAGE)
    service.get_derived_images = AsyncMock()

    result = await service.with_derived_images([image])

    assert result == [image]
    service.get_derived_images.assert_not_awaited()
