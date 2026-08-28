from contextlib import asynccontextmanager
from datetime import UTC, datetime
from hashlib import sha256
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
from eneo.files.file_repo import (
    FileContentReferenceRecord,
    LegacyAudioSlice,
    LegacyFileContentRecord,
    LegacyFileInfoRecord,
)
from eneo.files.file_service import FileService
from eneo.object_content.content import ContentAccessClass, ContentState, StorageKind
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
        created_at=datetime(2026, 8, 16, tzinfo=UTC),
        updated_at=datetime(2026, 8, 16, tzinfo=UTC),
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
    service.repo.get_legacy_infos.return_value = []
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


def _legacy_metadata(*, file_type: FileType = FileType.TEXT) -> FileMetadata:
    return FileMetadata(
        id=uuid4(),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        name="legacy.pdf" if file_type is FileType.TEXT else "legacy.mp3",
        mimetype=("application/pdf" if file_type is FileType.TEXT else "audio/mpeg"),
        file_type=file_type,
        owner_type=PrincipalType.USER,
        owner_user_id=uuid4(),
        tenant_id=uuid4(),
        parent_file_id=None,
    )


@pytest.mark.asyncio
async def test_file_info_and_original_availability_fall_back_to_legacy() -> None:
    metadata = _legacy_metadata()
    user = SimpleNamespace(id=metadata.owner_user_id, tenant_id=metadata.tenant_id)
    extracted = LegacyFileContentRecord(
        file_id=metadata.id,
        variant=FileContentVariant.EXTRACTED_TEXT,
        payload=b"legacy text",
        media_type="text/plain",
    )
    original = LegacyFileContentRecord(
        file_id=metadata.id,
        variant=FileContentVariant.ORIGINAL,
        payload=b"%PDF legacy",
        media_type="application/pdf",
    )
    repository = AsyncMock()
    repository.session = MagicMock()
    repository.get_by_id.return_value = metadata
    repository.get_content_references.return_value = []
    repository.get_legacy_infos.return_value = [
        LegacyFileInfoRecord(
            file_id=metadata.id,
            variant=FileContentVariant.EXTRACTED_TEXT,
            checksum=sha256(extracted.payload).hexdigest(),
            size_bytes=len(extracted.payload),
            media_type="text/plain",
            original_available=True,
            transcription_available=False,
        )
    ]
    repository.get_legacy_content.return_value = [original]
    service = FileService(
        user=user,
        repo=repository,
        protocol=AsyncMock(),
        object_content=AsyncMock(),
    )

    info = await service.get_file_by_id(metadata.id)
    available = await service.ensure_original_available(metadata.id)

    assert available == metadata
    assert info.checksum == sha256(extracted.payload).hexdigest()
    assert info.size == len(extracted.payload)
    assert info.mimetype == "application/pdf"


@pytest.mark.asyncio
async def test_file_info_does_not_load_legacy_payload_bytes() -> None:
    metadata = _legacy_metadata()
    user = SimpleNamespace(id=metadata.owner_user_id, tenant_id=metadata.tenant_id)
    repository = AsyncMock()
    repository.session = MagicMock()
    repository.get_by_id.return_value = metadata
    repository.get_content_references.return_value = []
    repository.get_legacy_infos.return_value = [
        LegacyFileInfoRecord(
            file_id=metadata.id,
            variant=FileContentVariant.EXTRACTED_TEXT,
            checksum=sha256(b"legacy text").hexdigest(),
            size_bytes=len(b"legacy text"),
            media_type="text/plain",
            original_available=True,
            transcription_available=False,
        )
    ]
    service = FileService(
        user=user,
        repo=repository,
        protocol=AsyncMock(),
        object_content=AsyncMock(),
    )

    info = await service.get_file_by_id(metadata.id)

    assert info.size == len(b"legacy text")
    repository.get_legacy_content.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_download_streams_without_opening_object_content() -> None:
    metadata = _legacy_metadata(file_type=FileType.AUDIO)
    payload = b"legacy audio"
    legacy_info = LegacyFileInfoRecord(
        file_id=metadata.id,
        variant=FileContentVariant.ORIGINAL,
        checksum=sha256(payload).hexdigest(),
        size_bytes=len(payload),
        media_type="audio/mpeg",
        original_available=False,
        transcription_available=False,
    )
    legacy_slice = LegacyAudioSlice(
        payload=payload,
        media_type="audio/mpeg",
    )

    class Session:
        def in_transaction(self) -> bool:
            return False

        @asynccontextmanager
        async def begin(self):
            yield

    repository = AsyncMock()
    repository.session = Session()
    repository.get_by_id.return_value = metadata
    repository.get_content_references.return_value = []
    repository.get_legacy_infos.return_value = [legacy_info]
    repository.get_legacy_audio_slice.return_value = legacy_slice
    object_content = MagicMock()
    service = FileService(
        user=None,
        repo=repository,
        protocol=AsyncMock(),
        object_content=object_content,
    )

    opened = await service.get_download_no_auth(
        metadata.id,
        tenant_id=metadata.tenant_id,
    )

    assert b"".join([chunk async for chunk in opened.chunks]) == payload
    assert opened.content_length == len(payload)
    assert opened.sha256 == sha256(payload).digest()
    assert opened.range_supported is True
    repository.get_legacy_audio_slice.assert_awaited_once_with(metadata.id, None)
    repository.get_legacy_content.assert_not_awaited()
    object_content.open_content.assert_not_called()


@pytest.mark.asyncio
async def test_text_download_prefers_exact_legacy_text_over_object_original() -> None:
    metadata = _legacy_metadata()
    extracted = LegacyFileContentRecord(
        file_id=metadata.id,
        variant=FileContentVariant.EXTRACTED_TEXT,
        payload=b"legacy extracted text",
        media_type="text/plain",
    )
    original = FileContentReferenceRecord(
        file_id=metadata.id,
        content_id=uuid4(),
        variant=FileContentVariant.ORIGINAL,
        ordinal=0,
        page_number=None,
        width=None,
        height=None,
        duration_ms=None,
        sha256=sha256(b"original pdf").digest(),
        size_bytes=len(b"original pdf"),
        media_type="application/pdf",
        access_class=ContentAccessClass.PRIVATE_RESOURCE,
        state=ContentState.AVAILABLE,
    )

    class Session:
        def in_transaction(self) -> bool:
            return False

        @asynccontextmanager
        async def begin(self):
            yield

    repository = AsyncMock()
    repository.session = Session()
    repository.get_by_id.return_value = metadata
    repository.get_content_references.return_value = [original]
    repository.get_legacy_content.return_value = [extracted]
    object_content = MagicMock()
    service = FileService(
        user=None,
        repo=repository,
        protocol=AsyncMock(),
        object_content=object_content,
    )

    opened = await service.get_download_no_auth(
        metadata.id,
        tenant_id=metadata.tenant_id,
    )

    assert b"".join([chunk async for chunk in opened.chunks]) == extracted.payload
    assert opened.filename == "legacy.txt"
    repository.get_legacy_content.assert_awaited_once_with(
        {metadata.id: {FileContentVariant.EXTRACTED_TEXT}}
    )
    object_content.open_content.assert_not_called()


@pytest.mark.asyncio
async def test_legacy_audio_range_fetches_only_the_selected_slice() -> None:
    metadata = _legacy_metadata(file_type=FileType.AUDIO)
    payload = b"legacy audio payload"
    selected_payload = payload[2:5]

    class Session:
        def in_transaction(self) -> bool:
            return False

        @asynccontextmanager
        async def begin(self):
            yield

    repository = AsyncMock()
    repository.session = Session()
    repository.get_by_id.return_value = metadata
    repository.get_content_references.return_value = []
    repository.get_legacy_infos.return_value = [
        LegacyFileInfoRecord(
            file_id=metadata.id,
            variant=FileContentVariant.ORIGINAL,
            checksum=sha256(payload).hexdigest(),
            size_bytes=len(payload),
            media_type="audio/mpeg",
            original_available=False,
            transcription_available=False,
        )
    ]
    repository.get_legacy_audio_slice.return_value = LegacyAudioSlice(
        payload=selected_payload,
        media_type="audio/mpeg",
    )
    service = FileService(
        user=None,
        repo=repository,
        protocol=AsyncMock(),
        object_content=MagicMock(),
    )

    opened = await service.get_download_no_auth(
        metadata.id,
        range_header="bytes=2-4",
        tenant_id=metadata.tenant_id,
    )

    assert b"".join([chunk async for chunk in opened.chunks]) == selected_payload
    assert opened.content_length == len(selected_payload)
    assert opened.content_range == f"bytes 2-4/{len(payload)}"
    selected_range = repository.get_legacy_audio_slice.await_args.args[1]
    assert selected_range.start == 2
    assert selected_range.end == 4
