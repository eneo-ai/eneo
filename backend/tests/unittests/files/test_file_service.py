from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.files.file_models import FileType
from eneo.files.file_service import FileService
from eneo.object_content.content import StorageKind
from eneo.object_content.deployment_policy import UploadAdmissionSnapshot


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


@pytest.mark.asyncio
async def test_object_store_save_rejects_ambient_transaction_before_external_work() -> (
    None
):
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    repo = MagicMock()
    repo.session.in_transaction.return_value = True
    protocol = MagicMock()
    object_content = MagicMock()
    object_content.ensure_target_ready = AsyncMock(
        side_effect=AssertionError("readiness must not start")
    )
    service = FileService(
        user=user,
        repo=repo,
        protocol=protocol,
        object_content=object_content,
        upload_admission=UploadAdmissionSnapshot(
            policy_revision=7,
            session_storage_target=StorageKind.OBJECT_STORE,
            session_operator_ceiling_bytes=10_000,
            session_file_maximum_bytes=10_000,
            session_image_maximum_bytes=10_000,
            session_audio_maximum_bytes=10_000,
            knowledge_file_maximum_bytes=10_000,
            knowledge_audio_maximum_bytes=10_000,
        ),
    )

    with pytest.raises(
        RuntimeError,
        match="requires a non-ambient transaction",
    ):
        await service.save_file(MagicMock())

    object_content.ensure_target_ready.assert_not_awaited()
    protocol.prepare_upload.assert_not_called()
    object_content.capture_for_target.assert_not_called()
    object_content.upload_for_publication.assert_not_called()
