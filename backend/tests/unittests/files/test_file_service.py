from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.authentication.principal_types import PrincipalType
from eneo.files.file_models import (
    FileContentVariant,
    FileMetadata,
    FileOwner,
    FileType,
)
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
async def test_get_derived_images_uses_the_typed_file_owner(
    service: FileService,
) -> None:
    parent_id = uuid4()
    service.repo.get_by_parent_ids.return_value = []

    assert await service.get_derived_images([parent_id]) == []

    service.repo.get_by_parent_ids.assert_awaited_once_with(
        parent_ids=[parent_id],
        owner=FileOwner(
            tenant_id=service.user.tenant_id,
            owner_type=PrincipalType.USER,
            owner_user_id=service.user.id,
        ),
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
            new_write_storage_target=StorageKind.OBJECT_STORE,
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


@pytest.mark.asyncio
async def test_get_owned_file_infos_filters_by_owner_and_reads_no_bytes(
    service: FileService,
) -> None:
    """Audio steps identify files here, so this must never hydrate payloads."""

    owned_id, unowned_id = uuid4(), uuid4()
    owned = FileMetadata(
        id=owned_id,
        created_at=datetime(2026, 8, 16, tzinfo=timezone.utc),
        updated_at=datetime(2026, 8, 16, tzinfo=timezone.utc),
        name="meeting.wav",
        file_type=FileType.AUDIO,
        mimetype="audio/wav",
        owner_type=PrincipalType.USER,
        owner_user_id=service.user.id,
        tenant_id=service.user.tenant_id,
    )
    # The repository already excludes what this owner may not read; an unowned
    # id must come back absent, not as an error that fails the whole step.
    service.repo.get_list_by_id_and_owner.return_value = [owned]
    service.repo.get_content_references.return_value = [
        SimpleNamespace(
            file_id=owned_id,
            variant=FileContentVariant.ORIGINAL,
            sha256=b"\x01" * 32,
            size_bytes=105_289_648,
            media_type="audio/wav",
            content_id=uuid4(),
            access_class=None,
        )
    ]
    loader = AsyncMock()
    service._content_loader = loader  # pyright: ignore[reportPrivateUsage]

    infos = await service.get_owned_file_infos([owned_id, unowned_id])

    service.repo.get_list_by_id_and_owner.assert_awaited_once_with(
        ids=[owned_id, unowned_id],
        owner=FileOwner(
            tenant_id=service.user.tenant_id,
            owner_type=PrincipalType.USER,
            owner_user_id=service.user.id,
        ),
    )
    assert [info.id for info in infos] == [owned_id]
    assert infos[0].size == 105_289_648
    assert infos[0].checksum == (b"\x01" * 32).hex()
    assert not hasattr(infos[0], "blob")
    loader.load.assert_not_awaited()
