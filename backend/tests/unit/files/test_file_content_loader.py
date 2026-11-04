"""``original_available`` follows the per-type original-download variants."""

from datetime import UTC, datetime
from hashlib import sha256
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.authentication.principal_types import PrincipalType
from eneo.files.file_content_loader import FileContentLoader
from eneo.files.file_models import (
    FileContentNotLoadedError,
    FileContentVariant,
    FileMetadata,
    FileType,
    FileWithoutContent,
)
from eneo.files.file_repo import (
    FileContentReferenceRecord,
    original_download_variants,
)
from eneo.object_content.content import (
    ContentAccessClass,
    ContentState,
    StorageKind,
)


def _metadata(file_type: FileType, *, parent_file_id=None) -> FileMetadata:
    now = datetime.now(UTC)
    return FileMetadata(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        name="file",
        mimetype="image/png" if file_type is FileType.IMAGE else "text/plain",
        file_type=file_type,
        owner_type=PrincipalType.USER,
        owner_user_id=uuid4(),
        tenant_id=uuid4(),
        parent_file_id=parent_file_id,
    )


def _reference(
    metadata: FileMetadata,
    variant: FileContentVariant,
    payload: bytes,
    storage_kind: StorageKind = StorageKind.POSTGRES_INLINE,
) -> FileContentReferenceRecord:
    return FileContentReferenceRecord(
        file_id=metadata.id,
        content_id=uuid4(),
        variant=variant,
        ordinal=0,
        page_number=None,
        width=None,
        height=None,
        duration_ms=None,
        sha256=sha256(payload).digest(),
        size_bytes=len(payload),
        media_type=metadata.mimetype,
        access_class=ContentAccessClass.PRIVATE_RESOURCE,
        state=ContentState.AVAILABLE,
        storage_kind=storage_kind,
    )


async def _load(
    metadata: FileMetadata,
    *references: FileContentReferenceRecord,
    object_store_configured: bool = False,
):
    repository = AsyncMock()
    repository.get_content_references.return_value = list(references)
    repository.get_legacy_infos.return_value = []
    repository.get_legacy_content.return_value = []
    object_content = AsyncMock()
    object_content.object_store_configured = object_store_configured
    object_content.read_content_bytes.return_value = {
        reference.content_id: b"payload" for reference in references
    }
    loader = FileContentLoader(repository, object_content)
    return (await loader.load([metadata], include_transcription=False))[metadata.id]


def test_image_originals_include_the_generated_artifact():
    assert original_download_variants(FileType.IMAGE) == (
        FileContentVariant.ORIGINAL,
        FileContentVariant.GENERATED_ARTIFACT,
    )
    assert original_download_variants(FileType.TEXT) == (FileContentVariant.ORIGINAL,)
    assert original_download_variants(FileType.AUDIO) == (FileContentVariant.ORIGINAL,)


async def test_generated_image_is_original_available():
    metadata = _metadata(FileType.IMAGE)
    loaded = await _load(
        metadata,
        _reference(metadata, FileContentVariant.GENERATED_ARTIFACT, b"payload"),
    )
    assert loaded.original_available is True
    assert loaded.blob == b"payload"


async def test_derived_page_image_is_not_original_available():
    metadata = _metadata(FileType.IMAGE, parent_file_id=uuid4())
    loaded = await _load(
        metadata,
        _reference(metadata, FileContentVariant.DERIVED_PAGE, b"payload"),
    )
    assert loaded.original_available is False


async def test_text_file_needs_a_stored_original():
    metadata = _metadata(FileType.TEXT)
    loaded = await _load(
        metadata,
        _reference(metadata, FileContentVariant.EXTRACTED_TEXT, b"payload"),
    )
    assert loaded.original_available is False


async def test_inline_original_is_available_without_an_object_store():
    """An original stored in PostgreSQL is served by the same download path
    whether or not an object store exists, so it is advertised as available."""
    metadata = _metadata(FileType.TEXT)
    loaded = await _load(
        metadata,
        _reference(metadata, FileContentVariant.EXTRACTED_TEXT, b"text"),
        _reference(metadata, FileContentVariant.ORIGINAL, b"%PDF"),
        object_store_configured=False,
    )
    assert loaded.original_available is True


async def test_object_store_original_needs_a_connected_store():
    """Rows written while a store was connected must not be promised once it
    is gone: the file falls back to inlining rather than getting a dead link."""
    metadata = _metadata(FileType.TEXT)
    references = (
        _reference(metadata, FileContentVariant.EXTRACTED_TEXT, b"text"),
        _reference(
            metadata,
            FileContentVariant.ORIGINAL,
            b"%PDF",
            storage_kind=StorageKind.OBJECT_STORE,
        ),
    )

    disconnected = await _load(metadata, *references, object_store_configured=False)
    connected = await _load(metadata, *references, object_store_configured=True)

    assert disconnected.original_available is False
    assert connected.original_available is True


async def test_hydrated_file_carries_the_original_size():
    """A download delivers the original; a picked file is recognised by its bytes."""
    metadata = _metadata(FileType.TEXT)
    original = b"the exact uploaded bytes"
    loaded = await _load(
        metadata,
        _reference(metadata, FileContentVariant.ORIGINAL, original),
        _reference(metadata, FileContentVariant.EXTRACTED_TEXT, b"the extracted text"),
    )
    assert loaded.size == len(b"the extracted text")
    assert loaded.original_size == len(original)


async def test_hydrated_file_without_an_original_has_no_original_size():
    metadata = _metadata(FileType.TEXT)
    loaded = await _load(
        metadata,
        _reference(metadata, FileContentVariant.EXTRACTED_TEXT, b"text only"),
    )
    assert loaded.original_size is None


async def test_a_file_outside_content_of_keeps_its_facts_and_reads_no_bytes():
    wanted = _metadata(FileType.TEXT)
    other = _metadata(FileType.TEXT)
    wanted_text = _reference(wanted, FileContentVariant.EXTRACTED_TEXT, b"wanted")
    other_original = _reference(other, FileContentVariant.ORIGINAL, b"the upload")
    other_text = _reference(other, FileContentVariant.EXTRACTED_TEXT, b"other text")
    repository = AsyncMock()
    repository.get_content_references.return_value = [
        wanted_text,
        other_original,
        other_text,
    ]
    repository.get_legacy_infos.return_value = []
    object_content = AsyncMock()
    object_content.object_store_configured = False
    object_content.read_content_bytes.return_value = {wanted_text.content_id: b"wanted"}

    loaded = await FileContentLoader(repository, object_content).load(
        [wanted, other], content_of={wanted.id}
    )

    grants = object_content.read_content_bytes.await_args.args[0]
    assert [grant.content_id for grant in grants] == [wanted_text.content_id]
    assert loaded[wanted.id].text == "wanted"
    assert isinstance(loaded[other.id], FileWithoutContent)
    assert loaded[other.id].size == len(b"other text")
    assert loaded[other.id].original_size == len(b"the upload")
    assert loaded[other.id].original_available is True


async def test_a_file_without_content_still_reads_its_transcription():
    metadata = _metadata(FileType.AUDIO)
    audio = _reference(metadata, FileContentVariant.ORIGINAL, b"audio")
    transcription = _reference(metadata, FileContentVariant.TRANSCRIPTION, b"said")
    repository = AsyncMock()
    repository.get_content_references.return_value = [audio, transcription]
    repository.get_legacy_infos.return_value = []
    object_content = AsyncMock()
    object_content.object_store_configured = False
    object_content.read_content_bytes.return_value = {transcription.content_id: b"said"}

    loaded = await FileContentLoader(repository, object_content).load(
        [metadata], content_of=()
    )

    grants = object_content.read_content_bytes.await_args.args[0]
    assert [grant.content_id for grant in grants] == [transcription.content_id]
    assert loaded[metadata.id].transcription == "said"


def test_reading_the_content_of_a_file_without_content_raises():
    now = datetime.now(UTC)
    file = FileWithoutContent(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        name="policy.txt",
        checksum="00",
        size=5,
        mimetype="text/plain",
        file_type=FileType.TEXT,
        user_id=uuid4(),
        tenant_id=uuid4(),
        owner_type=PrincipalType.USER,
    )

    with pytest.raises(FileContentNotLoadedError):
        _ = file.text
    with pytest.raises(FileContentNotLoadedError):
        _ = file.blob
    assert file.model_dump()["name"] == "policy.txt"
    assert "policy.txt" in repr(file)
