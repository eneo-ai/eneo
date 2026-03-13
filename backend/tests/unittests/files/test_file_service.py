from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import UploadFile

from intric.files.file_models import FileBaseWithContent, FileType
from intric.files.file_service import FileService


@pytest.fixture
def user():
    return MagicMock(id=uuid4(), tenant_id=uuid4())


@pytest.fixture
def protocol():
    return AsyncMock()


@pytest.fixture
def repo():
    return AsyncMock()


@pytest.fixture
def service(user, repo, protocol):
    return FileService(user=user, repo=repo, protocol=protocol)


@pytest.mark.asyncio
async def test_save_file_delegates_to_protocol_without_max_size(service, protocol):
    """save_file() must NOT pass explicit max_size so each type handler uses its own default."""
    upload = MagicMock(spec=UploadFile)
    protocol.to_domain.return_value = FileBaseWithContent(
        name="test.mp3",
        checksum="abc123",
        size=100,
        file_type=FileType.AUDIO,
        blob=b"audio-data",
    )

    await service.save_file(upload)

    protocol.to_domain.assert_called_once_with(upload)


@pytest.mark.asyncio
async def test_save_file_passes_result_to_repo(service, protocol, repo, user):
    """save_file() passes the domain object from protocol to repo.add()."""
    upload = MagicMock(spec=UploadFile)
    protocol.to_domain.return_value = FileBaseWithContent(
        name="test.txt",
        checksum="abc123",
        size=50,
        file_type=FileType.TEXT,
        text="hello",
    )

    await service.save_file(upload)

    repo.add.assert_called_once()
    create_arg = repo.add.call_args[0][0]
    assert create_arg.user_id == user.id
    assert create_arg.tenant_id == user.tenant_id
    assert create_arg.name == "test.txt"
