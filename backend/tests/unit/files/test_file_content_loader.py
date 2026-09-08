"""``original_available`` follows the per-type original-download variants."""

from datetime import UTC, datetime
from hashlib import sha256
from unittest.mock import AsyncMock
from uuid import uuid4

from eneo.files.file_content_loader import FileContentLoader
from eneo.files.file_models import FileContentVariant, FileMetadata, FileType
from eneo.files.file_repo import (
    FileContentReferenceRecord,
    original_download_variants,
)
from eneo.object_content.content import ContentAccessClass


def _metadata(file_type: FileType, *, parent_file_id=None) -> FileMetadata:
    now = datetime.now(UTC)
    return FileMetadata(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        name="file",
        mimetype="image/png" if file_type is FileType.IMAGE else "text/plain",
        file_type=file_type,
        user_id=uuid4(),
        tenant_id=uuid4(),
        parent_file_id=parent_file_id,
    )


def _reference(
    metadata: FileMetadata, variant: FileContentVariant, payload: bytes
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
    )


async def _load(metadata: FileMetadata, *references: FileContentReferenceRecord):
    repository = AsyncMock()
    repository.get_content_references.return_value = list(references)
    object_content = AsyncMock()
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
