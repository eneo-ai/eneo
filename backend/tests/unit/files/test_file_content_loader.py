"""``original_available`` follows the per-type original-download variants."""

from datetime import UTC, datetime
from hashlib import sha256
from unittest.mock import AsyncMock
from uuid import uuid4

from eneo.authentication.principal_types import PrincipalType
from eneo.files.file_content_loader import FileContentLoader
from eneo.files.file_models import FileContentVariant, FileMetadata, FileType
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
