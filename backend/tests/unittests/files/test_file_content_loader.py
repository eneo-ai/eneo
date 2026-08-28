from datetime import UTC, datetime
from hashlib import sha256
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from eneo.authentication.principal_types import PrincipalType
from eneo.files.file_content_loader import FileAttachmentGroup, FileContentLoader
from eneo.files.file_models import FileContentVariant, FileMetadata, FileType
from eneo.files.file_repo import (
    FileContentReferenceRecord,
    LegacyFileContentRecord,
    LegacyFileInfoRecord,
)
from eneo.object_content.content import ContentAccessClass, ContentState


@pytest.mark.asyncio
async def test_loader_falls_back_to_frozen_legacy_variants() -> None:
    file_id = uuid4()
    tenant_id = uuid4()
    metadata = FileMetadata(
        id=file_id,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        name="legacy.pdf",
        mimetype="application/pdf",
        file_type=FileType.TEXT,
        owner_type=PrincipalType.USER,
        owner_user_id=uuid4(),
        tenant_id=tenant_id,
        parent_file_id=None,
    )
    extracted = b"legacy extracted text"
    transcription = b"legacy transcription"
    repository = AsyncMock()
    repository.get_content_references.return_value = []
    repository.get_legacy_infos.return_value = [
        LegacyFileInfoRecord(
            file_id=file_id,
            variant=FileContentVariant.EXTRACTED_TEXT,
            checksum=sha256(extracted).hexdigest(),
            size_bytes=len(extracted),
            media_type="text/plain",
            original_available=True,
            transcription_available=True,
        )
    ]
    repository.get_legacy_content.return_value = [
        LegacyFileContentRecord(
            file_id=file_id,
            variant=FileContentVariant.EXTRACTED_TEXT,
            payload=extracted,
            media_type="text/plain",
        ),
        LegacyFileContentRecord(
            file_id=file_id,
            variant=FileContentVariant.TRANSCRIPTION,
            payload=transcription,
            media_type="text/plain",
        ),
    ]
    object_content = AsyncMock()
    object_content.read_content_bytes.return_value = {}

    loaded = (await FileContentLoader(repository, object_content).load([metadata]))[
        file_id
    ]

    assert loaded.text == extracted.decode()
    assert loaded.blob is None
    assert loaded.transcription == transcription.decode()
    assert loaded.checksum == sha256(extracted).hexdigest()
    assert loaded.size == len(extracted)
    assert loaded.mimetype == "application/pdf"
    assert loaded.original_available is True
    repository.get_legacy_content.assert_awaited_once_with(
        {
            file_id: {
                FileContentVariant.EXTRACTED_TEXT,
                FileContentVariant.TRANSCRIPTION,
            }
        }
    )
    object_content.read_content_bytes.assert_awaited_once_with([])


@pytest.mark.asyncio
async def test_loader_prefers_object_content_over_legacy_for_same_variant() -> None:
    file_id = uuid4()
    content_id = uuid4()
    tenant_id = uuid4()
    metadata = FileMetadata(
        id=file_id,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        name="image.png",
        mimetype="image/png",
        file_type=FileType.IMAGE,
        owner_type=PrincipalType.USER,
        owner_user_id=uuid4(),
        tenant_id=tenant_id,
        parent_file_id=None,
    )
    payload = b"object-content"
    reference = FileContentReferenceRecord(
        file_id=file_id,
        content_id=content_id,
        variant=FileContentVariant.LEGACY_IMAGE,
        ordinal=0,
        page_number=None,
        width=None,
        height=None,
        duration_ms=None,
        sha256=sha256(payload).digest(),
        size_bytes=len(payload),
        media_type="image/png",
        access_class=ContentAccessClass.PRIVATE_RESOURCE,
        state=ContentState.AVAILABLE,
    )
    repository = AsyncMock()
    repository.get_content_references.return_value = [reference]
    repository.get_legacy_infos.return_value = []
    repository.get_legacy_content.return_value = []
    object_content = AsyncMock()
    object_content.read_content_bytes.return_value = {content_id: payload}

    loaded = (await FileContentLoader(repository, object_content).load([metadata]))[
        file_id
    ]

    assert loaded.blob == payload
    assert loaded.checksum == sha256(payload).hexdigest()
    repository.get_legacy_content.assert_not_awaited()


@pytest.mark.asyncio
async def test_loader_resolves_each_variant_independently_during_backfill() -> None:
    file_id = uuid4()
    content_id = uuid4()
    tenant_id = uuid4()
    metadata = FileMetadata(
        id=file_id,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        name="mixed.pdf",
        mimetype="application/pdf",
        file_type=FileType.TEXT,
        owner_type=PrincipalType.USER,
        owner_user_id=uuid4(),
        tenant_id=tenant_id,
        parent_file_id=None,
    )
    original = b"%PDF object original"
    extracted = b"legacy extracted text"
    repository = AsyncMock()
    repository.get_content_references.return_value = [
        FileContentReferenceRecord(
            file_id=file_id,
            content_id=content_id,
            variant=FileContentVariant.ORIGINAL,
            ordinal=0,
            page_number=None,
            width=None,
            height=None,
            duration_ms=None,
            sha256=sha256(original).digest(),
            size_bytes=len(original),
            media_type="application/pdf",
            access_class=ContentAccessClass.PRIVATE_RESOURCE,
            state=ContentState.AVAILABLE,
        )
    ]
    repository.get_legacy_infos.return_value = [
        LegacyFileInfoRecord(
            file_id=file_id,
            variant=FileContentVariant.EXTRACTED_TEXT,
            checksum=sha256(extracted).hexdigest(),
            size_bytes=len(extracted),
            media_type="text/plain",
            original_available=True,
            transcription_available=False,
        )
    ]
    repository.get_legacy_content.return_value = [
        LegacyFileContentRecord(
            file_id=file_id,
            variant=FileContentVariant.EXTRACTED_TEXT,
            payload=extracted,
            media_type="text/plain",
        )
    ]
    object_content = AsyncMock()
    object_content.read_content_bytes.return_value = {}

    loaded = (
        await FileContentLoader(repository, object_content).load(
            [metadata],
            include_transcription=False,
        )
    )[file_id]

    assert loaded.text == extracted.decode()
    assert loaded.original_available is True
    repository.get_legacy_content.assert_awaited_once_with(
        {file_id: {FileContentVariant.EXTRACTED_TEXT}}
    )
    object_content.read_content_bytes.assert_awaited_once_with([])


@pytest.mark.asyncio
async def test_legacy_text_original_bytes_are_loaded_only_when_requested() -> None:
    file_id = uuid4()
    tenant_id = uuid4()
    metadata = FileMetadata(
        id=file_id,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        name="template.docx",
        mimetype=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        file_type=FileType.TEXT,
        owner_type=PrincipalType.USER,
        owner_user_id=uuid4(),
        tenant_id=tenant_id,
        parent_file_id=None,
    )
    extracted = b"legacy extracted text"
    original = b"PK\x03\x04exact docx bytes"
    repository = AsyncMock()
    repository.get_content_references.return_value = []
    repository.get_legacy_infos.return_value = [
        LegacyFileInfoRecord(
            file_id=file_id,
            variant=FileContentVariant.EXTRACTED_TEXT,
            checksum=sha256(extracted).hexdigest(),
            size_bytes=len(extracted),
            media_type="text/plain",
            original_available=True,
            transcription_available=False,
        )
    ]
    payloads = {
        FileContentVariant.EXTRACTED_TEXT: extracted,
        FileContentVariant.ORIGINAL: original,
    }

    async def load_requested_legacy(
        requests: dict[UUID, set[FileContentVariant]],
    ) -> list[LegacyFileContentRecord]:
        return [
            LegacyFileContentRecord(
                file_id=file_id,
                variant=variant,
                payload=payloads[variant],
                media_type=(
                    "text/plain"
                    if variant is FileContentVariant.EXTRACTED_TEXT
                    else metadata.mimetype or "application/octet-stream"
                ),
            )
            for variant in requests[file_id]
        ]

    repository.get_legacy_content.side_effect = load_requested_legacy
    object_content = AsyncMock()
    object_content.read_content_bytes.return_value = {}
    loader = FileContentLoader(repository, object_content)

    default = (await loader.load([metadata], include_transcription=False))[file_id]
    with_original = (
        await loader.load(
            [metadata],
            include_transcription=False,
            include_text_original_bytes=True,
        )
    )[file_id]

    assert default.text == extracted.decode()
    assert default.blob is None
    assert with_original.text == extracted.decode()
    assert with_original.blob == original
    assert [call.args[0] for call in repository.get_legacy_content.await_args_list] == [
        {file_id: {FileContentVariant.EXTRACTED_TEXT}},
        {
            file_id: {
                FileContentVariant.EXTRACTED_TEXT,
                FileContentVariant.ORIGINAL,
            }
        },
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("max_batch_bytes", "expected_request_groups"),
    [
        (9, ((0,), (1,))),
        (18, ((0, 1),)),
    ],
)
async def test_legacy_payload_batches_bound_distinct_legacy_files(
    max_batch_bytes: int,
    expected_request_groups: tuple[tuple[int, ...], ...],
) -> None:
    tenant_id = uuid4()
    files = [
        FileMetadata(
            id=uuid4(),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            name=f"legacy-{index}.png",
            mimetype="image/png",
            file_type=FileType.IMAGE,
            owner_type=PrincipalType.USER,
            owner_user_id=uuid4(),
            tenant_id=tenant_id,
            parent_file_id=None,
        )
        for index in range(2)
    ]
    payloads = {
        file.id: f"payload-{index}".encode() for index, file in enumerate(files)
    }
    repository = AsyncMock()
    repository.get_content_references.return_value = []
    repository.get_legacy_infos.return_value = [
        LegacyFileInfoRecord(
            file_id=file.id,
            variant=FileContentVariant.LEGACY_IMAGE,
            checksum=sha256(payloads[file.id]).hexdigest(),
            size_bytes=len(payloads[file.id]),
            media_type="image/png",
            original_available=False,
            transcription_available=False,
        )
        for file in files
    ]

    async def load_requested_legacy(
        requests: dict[UUID, set[FileContentVariant]],
    ) -> list[LegacyFileContentRecord]:
        return [
            LegacyFileContentRecord(
                file_id=file_id,
                variant=variant,
                payload=payloads[file_id],
                media_type="image/png",
            )
            for file_id, variants in requests.items()
            for variant in variants
        ]

    repository.get_legacy_content.side_effect = load_requested_legacy
    object_content = AsyncMock()
    object_content.read_content_bytes.return_value = {}
    groups = [
        FileAttachmentGroup(
            owner_kind="assistant",
            owner_id=uuid4(),
            tenant_id=tenant_id,
            files=(file,),
        )
        for file in files
    ]

    batches = [
        batch
        async for batch in FileContentLoader(
            repository,
            object_content,
        ).load_attachment_groups_in_payload_batches(
            groups,
            max_batch_bytes=max_batch_bytes,
            include_transcription=False,
        )
    ]

    assert len(batches) == len(expected_request_groups)
    assert [set(batch) for batch in batches] == [
        {groups[index].key for index in request_group}
        for request_group in expected_request_groups
    ]
    assert [call.args[0] for call in repository.get_legacy_content.await_args_list] == [
        {files[index].id: {FileContentVariant.LEGACY_IMAGE} for index in request_group}
        for request_group in expected_request_groups
    ]
    repository.get_content_references.assert_awaited_once()
    repository.get_legacy_infos.assert_awaited_once()


@pytest.mark.asyncio
async def test_legacy_payload_batches_fetch_one_shared_file_once() -> None:
    tenant_id = uuid4()
    file = FileMetadata(
        id=uuid4(),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        name="shared-legacy.png",
        mimetype="image/png",
        file_type=FileType.IMAGE,
        owner_type=PrincipalType.USER,
        owner_user_id=uuid4(),
        tenant_id=tenant_id,
        parent_file_id=None,
    )
    payload = b"shared legacy payload"
    repository = AsyncMock()
    repository.get_content_references.return_value = []
    repository.get_legacy_infos.return_value = [
        LegacyFileInfoRecord(
            file_id=file.id,
            variant=FileContentVariant.LEGACY_IMAGE,
            checksum=sha256(payload).hexdigest(),
            size_bytes=len(payload),
            media_type="image/png",
            original_available=False,
            transcription_available=False,
        )
    ]
    repository.get_legacy_content.return_value = [
        LegacyFileContentRecord(
            file_id=file.id,
            variant=FileContentVariant.LEGACY_IMAGE,
            payload=payload,
            media_type="image/png",
        )
    ]
    object_content = AsyncMock()
    object_content.read_content_bytes.return_value = {}
    groups = [
        FileAttachmentGroup(
            owner_kind="assistant",
            owner_id=uuid4(),
            tenant_id=tenant_id,
            files=(file,),
        )
        for _ in range(3)
    ]

    batches = [
        batch
        async for batch in FileContentLoader(
            repository,
            object_content,
        ).load_attachment_groups_in_payload_batches(
            groups,
            max_batch_bytes=1,
            include_transcription=False,
        )
    ]

    assert len(batches) == 1
    assert set(batches[0]) == {group.key for group in groups}
    repository.get_legacy_content.assert_awaited_once_with(
        {file.id: {FileContentVariant.LEGACY_IMAGE}}
    )
