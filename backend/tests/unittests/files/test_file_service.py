from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import UploadFile

from eneo.files.file_models import FileBaseWithContent, FileType
from eneo.files.file_service import FileService


@pytest.fixture
def user():
    return MagicMock(id=uuid4(), tenant_id=uuid4())


@pytest.fixture
def protocol():
    return AsyncMock()


@pytest.fixture
def repo():
    mock = AsyncMock()
    # session.in_transaction() is sync — keep it a MagicMock so it doesn't return a coroutine
    mock.session = MagicMock()
    return mock


@pytest.fixture
def service(user, repo, protocol):
    return FileService(user=user, repo=repo, protocol=protocol)


@pytest.mark.asyncio
async def test_save_file_delegates_to_protocol_without_max_size(service, protocol):
    """save_file() must NOT pass explicit max_size so each type handler uses its own default."""
    upload = MagicMock(spec=UploadFile)
    protocol.to_domain_with_derivatives.return_value = (
        FileBaseWithContent(
            name="test.mp3",
            checksum="abc123",
            size=100,
            file_type=FileType.AUDIO,
            blob=b"audio-data",
        ),
        [],
    )

    await service.save_file(upload)

    protocol.to_domain_with_derivatives.assert_called_once_with(upload)


@pytest.mark.asyncio
async def test_save_file_passes_result_to_repo(service, protocol, repo, user):
    """save_file() passes the domain object from protocol to repo.add()."""
    upload = MagicMock(spec=UploadFile)
    protocol.to_domain_with_derivatives.return_value = (
        FileBaseWithContent(
            name="test.txt",
            checksum="abc123",
            size=50,
            file_type=FileType.TEXT,
            text="hello",
        ),
        [],
    )

    await service.save_file(upload)

    repo.add.assert_called_once()
    create_arg = repo.add.call_args[0][0]
    assert create_arg.user_id == user.id
    assert create_arg.tenant_id == user.tenant_id
    assert create_arg.name == "test.txt"


@pytest.mark.asyncio
async def test_save_file_persists_pdf_derived_images_with_parent_id(
    service, protocol, repo, user
):
    upload = MagicMock(spec=UploadFile)
    protocol.to_domain_with_derivatives.return_value = (
        FileBaseWithContent(
            name="report.pdf",
            checksum="abc123",
            size=1000,
            file_type=FileType.TEXT,
            text="report text",
        ),
        [
            FileBaseWithContent(
                name="report.pdf (image 1)",
                checksum="img1",
                size=10,
                file_type=FileType.IMAGE,
                mimetype="image/jpeg",
                blob=b"jpeg-bytes",
            )
        ],
    )
    parent_id = uuid4()
    repo.add.side_effect = [MagicMock(id=parent_id), MagicMock(id=uuid4())]

    await service.save_file(upload)

    assert repo.add.call_count == 2
    child_create = repo.add.call_args_list[1][0][0]
    assert child_create.parent_file_id == parent_id
    assert child_create.file_type == FileType.IMAGE
    assert child_create.name == "report.pdf (image 1)"


@pytest.mark.asyncio
async def test_with_derived_images_appends_and_dedupes(service, repo, user):
    parent = MagicMock(id=uuid4(), file_type=FileType.TEXT)
    already_attached = MagicMock(id=uuid4(), file_type=FileType.IMAGE)
    new_derived = MagicMock(id=uuid4(), file_type=FileType.IMAGE)
    repo.get_by_parent_ids.return_value = [already_attached, new_derived]

    result = await service.with_derived_images([parent, already_attached])

    assert result == [parent, already_attached, new_derived]
    repo.get_by_parent_ids.assert_awaited_once_with(
        parent_ids=[parent.id], user_id=user.id
    )


@pytest.mark.asyncio
async def test_with_derived_images_skips_lookup_without_text_files(service, repo):
    image = MagicMock(id=uuid4(), file_type=FileType.IMAGE)

    result = await service.with_derived_images([image])

    assert result == [image]
    repo.get_by_parent_ids.assert_not_awaited()
