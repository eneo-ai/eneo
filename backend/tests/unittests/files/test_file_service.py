from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import UploadFile

from intric.files.file_models import FileBaseWithContent, FileType
from intric.files.file_service import FileService


class _OpenSession:
    def in_transaction(self) -> bool:
        return True


@pytest.fixture
def user():
    return MagicMock(id=uuid4(), tenant_id=uuid4())


@pytest.fixture
def protocol():
    return AsyncMock()


@pytest.fixture
def repo():
    repo = AsyncMock()
    repo.session = _OpenSession()
    return repo


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


@pytest.mark.asyncio
async def test_document_from_upload_uses_document_path(service, protocol, repo):
    upload = MagicMock(spec=UploadFile)
    protocol.document_to_domain.return_value = FileBaseWithContent(
        name="template.docx",
        checksum="abc123",
        size=100,
        file_type=FileType.DOCUMENT,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        blob=b"docx-bytes",
    )

    result = await service.document_from_upload(upload, max_size=2048)

    protocol.document_to_domain.assert_awaited_once_with(upload, max_size=2048)
    protocol.to_domain.assert_not_called()
    repo.add.assert_not_called()
    assert result.file_type == FileType.DOCUMENT
    assert result.blob == b"docx-bytes"


@pytest.mark.asyncio
async def test_save_file_content_persists_blob(service, repo, user):
    file_content = FileBaseWithContent(
        name="template.docx",
        checksum="abc123",
        size=100,
        file_type=FileType.DOCUMENT,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        blob=b"docx-bytes",
    )

    await service.save_file_content(file_content)

    repo.add.assert_called_once()
    create_arg = repo.add.call_args[0][0]
    assert create_arg.file_type == FileType.DOCUMENT
    assert create_arg.blob == b"docx-bytes"
    assert create_arg.text is None
    assert create_arg.user_id == user.id
    assert create_arg.tenant_id == user.tenant_id
