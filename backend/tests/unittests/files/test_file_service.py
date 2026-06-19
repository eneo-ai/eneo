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
    assert create_arg.owner_type.value == "user"
    assert create_arg.owner_user_id == user.id
    assert create_arg.owner_service_id is None
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
    assert create_arg.owner_type.value == "user"
    assert create_arg.owner_user_id == user.id
    assert create_arg.owner_service_id is None
    assert create_arg.tenant_id == user.tenant_id


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
    assert child_create.owner_type.value == "user"
    assert child_create.owner_user_id == user.id
    assert child_create.owner_service_id is None
    assert child_create.tenant_id == user.tenant_id


@pytest.mark.asyncio
async def test_with_derived_images_appends_and_dedupes(service, repo, user):
    parent = MagicMock(id=uuid4(), file_type=FileType.TEXT)
    already_attached = MagicMock(id=uuid4(), file_type=FileType.IMAGE)
    new_derived = MagicMock(id=uuid4(), file_type=FileType.IMAGE)
    repo.get_by_parent_ids.return_value = [already_attached, new_derived]

    result = await service.with_derived_images([parent, already_attached])

    assert result == [parent, already_attached, new_derived]
    repo.get_by_parent_ids.assert_awaited_once_with(
        parent_ids=[parent.id],
        owner_type="user",
        owner_user_id=user.id,
        owner_service_id=None,
        tenant_id=user.tenant_id,
    )


@pytest.mark.asyncio
async def test_with_derived_images_skips_lookup_without_text_files(service, repo):
    image = MagicMock(id=uuid4(), file_type=FileType.IMAGE)

    result = await service.with_derived_images([image])

    assert result == [image]
    repo.get_by_parent_ids.assert_not_awaited()
