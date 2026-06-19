from __future__ import annotations

import hashlib
import io
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from docx import Document
from fastapi import UploadFile

from intric.files.file_models import File, FileCreate, FileType
from intric.files.file_protocol import FileProtocol
from intric.files.file_service import FileService
from intric.flows.domain.flow import Flow, FlowTemplateAsset
from intric.flows.domain.flow_invariant_exceptions import FlowPersistedIdMissingError
from intric.flows.flow_template_asset_service import FlowTemplateAssetService
from intric.main.exceptions import BadRequestException, FileTooLargeException

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class _OpenSession:
    def in_transaction(self) -> bool:
        return True


class _TemplateFileSizeService:
    def __init__(self, tmp_path: Path, forced_size: int | None = None):
        self.tmp_path = tmp_path
        self.forced_size = forced_size

    def get_file_size(self, file: io.BytesIO) -> int:
        if self.forced_size is not None:
            return self.forced_size
        position = file.tell()
        file.seek(0, io.SEEK_END)
        size = file.tell()
        file.seek(position)
        return size

    async def save_file_to_disk(self, file: io.BytesIO) -> str:
        destination = self.tmp_path / uuid4().hex
        position = file.tell()
        file.seek(0)
        destination.write_bytes(file.read())
        file.seek(position)
        return str(destination)

    def get_file_checksum(self, filepath: Path) -> str:
        return hashlib.sha256(filepath.read_bytes()).hexdigest()


class _ReadGuard(io.BytesIO):
    def read(self, *args, **kwargs):
        raise AssertionError("upload body was read before size validation")


def _build_template_bytes() -> bytes:
    document = Document()
    document.add_paragraph("{{Body}}")
    payload = io.BytesIO()
    document.save(payload)
    return payload.getvalue()


def _upload(filename: str, content: bytes) -> UploadFile:
    return UploadFile(
        file=io.BytesIO(content),
        filename=filename,
        headers={"content-type": DOCX_MIME},
    )


def _flow_for_user(user) -> Flow:
    now = datetime.now(timezone.utc)
    return Flow(
        id=uuid4(),
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        name="Template flow",
        description=None,
        created_by_user_id=user.id,
        owner_user_id=user.id,
        published_version=None,
        metadata_json=None,
        data_retention_days=None,
        created_at=now,
        updated_at=now,
        steps=[],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["list", "upload", "get"])
async def test_template_asset_operations_require_persisted_parent_flow_id(
    user,
    operation: str,
) -> None:
    flow = _flow_for_user(user).model_copy(update={"id": None})
    flow_repo = AsyncMock()
    flow_repo.get.return_value = flow
    file_repo = AsyncMock()
    file_service = AsyncMock()
    template_asset_repo = AsyncMock()
    service = FlowTemplateAssetService(
        user=user,
        flow_repo=flow_repo,
        file_repo=file_repo,
        file_service=file_service,
        template_asset_repo=template_asset_repo,
    )

    with pytest.raises(FlowPersistedIdMissingError):
        if operation == "list":
            await service.list_assets(
                flow_id=uuid4(),
                can_edit=True,
                can_download=True,
            )
        elif operation == "upload":
            await service.upload_asset(
                flow_id=uuid4(),
                upload_file=_upload("template.docx", _build_template_bytes()),
            )
        else:
            await service.get_asset_with_file(flow_id=uuid4(), asset_id=uuid4())

    template_asset_repo.list_for_flow.assert_not_awaited()
    template_asset_repo.create.assert_not_awaited()
    template_asset_repo.get.assert_not_awaited()
    file_service.document_from_upload.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_asset_persists_docx_template_bytes_and_body_placeholder(
    user,
    tmp_path: Path,
) -> None:
    template_bytes = _build_template_bytes()
    flow = _flow_for_user(user)
    text_extractor = MagicMock()
    image_extractor = MagicMock()
    protocol = FileProtocol(
        file_size_service=_TemplateFileSizeService(tmp_path),
        text_extractor=text_extractor,
        image_extractor=image_extractor,
    )
    file_repo = AsyncMock()
    file_repo.session = _OpenSession()
    now = datetime.now(timezone.utc)

    async def add_file(file_create: FileCreate) -> File:
        return File(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            **file_create.model_dump(mode="python"),
        )

    file_repo.add.side_effect = add_file
    flow_repo = AsyncMock()
    flow_repo.get.return_value = flow
    template_asset_repo = AsyncMock()

    async def create_asset(**kwargs) -> FlowTemplateAsset:
        return FlowTemplateAsset(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            **kwargs,
        )

    template_asset_repo.create.side_effect = create_asset
    file_service = FileService(user=user, repo=file_repo, protocol=protocol)
    service = FlowTemplateAssetService(
        user=user,
        flow_repo=flow_repo,
        file_repo=file_repo,
        file_service=file_service,
        template_asset_repo=template_asset_repo,
    )

    asset = await service.upload_asset(
        flow_id=flow.id,
        upload_file=_upload("template.docx", template_bytes),
    )

    file_repo.add.assert_awaited_once()
    saved_file_create = file_repo.add.await_args.args[0]
    assert saved_file_create.file_type == FileType.DOCUMENT
    assert saved_file_create.blob == template_bytes
    assert saved_file_create.text is None
    assert saved_file_create.name == "template.docx"
    assert saved_file_create.mimetype == DOCX_MIME
    template_asset_repo.create.assert_awaited_once()
    assert template_asset_repo.create.await_args.kwargs["placeholders"] == ["Body"]
    assert asset.placeholders == ["Body"]
    assert asset.can_edit is True
    assert asset.can_download is True
    text_extractor.extract.assert_not_called()


@pytest.mark.asyncio
async def test_upload_asset_rejects_invalid_docx_before_file_persistence(
    user,
    tmp_path: Path,
) -> None:
    flow = _flow_for_user(user)
    protocol = FileProtocol(
        file_size_service=_TemplateFileSizeService(tmp_path),
        text_extractor=MagicMock(),
        image_extractor=MagicMock(),
    )
    file_repo = AsyncMock()
    file_repo.session = _OpenSession()
    flow_repo = AsyncMock()
    flow_repo.get.return_value = flow
    template_asset_repo = AsyncMock()
    file_service = FileService(user=user, repo=file_repo, protocol=protocol)
    service = FlowTemplateAssetService(
        user=user,
        flow_repo=flow_repo,
        file_repo=file_repo,
        file_service=file_service,
        template_asset_repo=template_asset_repo,
    )

    with pytest.raises(BadRequestException) as exc_info:
        await service.upload_asset(
            flow_id=flow.id,
            upload_file=_upload("template.docx", b"not-a-docx"),
        )

    assert exc_info.value.code == "flow_template_invalid_archive"
    file_repo.add.assert_not_awaited()
    template_asset_repo.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_asset_rejects_oversized_docx_before_reading_body(
    user,
    tmp_path: Path,
) -> None:
    flow = _flow_for_user(user)
    protocol = FileProtocol(
        file_size_service=_TemplateFileSizeService(tmp_path, forced_size=10**12),
        text_extractor=MagicMock(),
        image_extractor=MagicMock(),
    )
    file_repo = AsyncMock()
    file_repo.session = _OpenSession()
    flow_repo = AsyncMock()
    flow_repo.get.return_value = flow
    template_asset_repo = AsyncMock()
    file_service = FileService(user=user, repo=file_repo, protocol=protocol)
    service = FlowTemplateAssetService(
        user=user,
        flow_repo=flow_repo,
        file_repo=file_repo,
        file_service=file_service,
        template_asset_repo=template_asset_repo,
    )
    upload = UploadFile(
        file=_ReadGuard(b"body-must-not-be-read"),
        filename="oversized.docx",
        headers={"content-type": DOCX_MIME},
    )

    with pytest.raises(FileTooLargeException):
        await service.upload_asset(flow_id=flow.id, upload_file=upload)

    file_repo.add.assert_not_awaited()
    template_asset_repo.create.assert_not_awaited()
