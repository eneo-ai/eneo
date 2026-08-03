from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from hashlib import sha256
from io import BytesIO
from uuid import UUID

import pytest
import sqlalchemy as sa
from fastapi import UploadFile
from sqlalchemy import select

from eneo.database.database import AsyncSession, DatabaseSessionManager
from eneo.database.tables.object_content_table import (
    FileContentReferences,
    IconContentReferences,
    ObjectContents,
)
from eneo.database.tables.users_table import Users
from eneo.files.file_models import FileContentVariant, FileType
from eneo.files.file_protocol import (
    FileProtocol,
    PendingFileContent,
    PreparedFileUpload,
)
from eneo.files.file_repo import FileRepository
from eneo.files.file_service import FileService
from eneo.files.file_size_service import FileSizeService
from eneo.files.image import ImageExtractor
from eneo.files.text import TextExtractor
from eneo.icons.icon_repo import IconRepository
from eneo.icons.icon_service import IconService
from eneo.main.exceptions import NotFoundException
from eneo.object_content.configuration import ObjectContentCoreSettings
from eneo.object_content.content import StorageKind
from eneo.object_content.content_service import ObjectContentService
from eneo.object_content.deployment_policy import UploadAdmissionSnapshot
from eneo.users.user import UserInDB


def _content_service(
    database: DatabaseSessionManager,
    *,
    inline_maximum_bytes: int = 10 * 1024 * 1024,
) -> ObjectContentService:
    return ObjectContentService(
        ObjectContentCoreSettings(
            _env_file=None,
            inline_maximum_bytes=inline_maximum_bytes,
            inline_io_chunk_bytes=64 * 1024,
        ),
        database,
    )


async def _bytes_source(payload: bytes) -> AsyncGenerator[bytes]:
    yield payload


def _inline_upload_admission() -> UploadAdmissionSnapshot:
    maximum_bytes = 20 * 1024 * 1024
    return UploadAdmissionSnapshot(
        policy_revision=1,
        new_write_storage_target=StorageKind.POSTGRES_INLINE,
        session_file_maximum_bytes=maximum_bytes,
        session_image_maximum_bytes=maximum_bytes,
        session_audio_maximum_bytes=maximum_bytes,
        knowledge_file_maximum_bytes=maximum_bytes,
        knowledge_audio_maximum_bytes=maximum_bytes,
    )


class _PreparedFileProtocol(FileProtocol):
    def __init__(self, prepared: PreparedFileUpload) -> None:
        self._prepared = prepared

    @asynccontextmanager
    async def prepare_upload(
        self,
        upload_file: UploadFile,
        *,
        upload_admission_snapshot: UploadAdmissionSnapshot | None = None,
        max_size: int | None = None,
        limit_name: str | None = None,
    ) -> AsyncGenerator[PreparedFileUpload]:
        del upload_file, upload_admission_snapshot, max_size, limit_name
        yield self._prepared


async def _user(session) -> UserInDB:
    row = (await session.scalars(select(Users))).first()
    assert row is not None
    return UserInDB.model_construct(id=row.id, tenant_id=row.tenant_id)


class _PausingLockFileRepository(FileRepository):
    def __init__(
        self,
        session: AsyncSession,
        *,
        locked: asyncio.Event,
        release: asyncio.Event,
    ) -> None:
        super().__init__(session)
        self._locked = locked
        self._release = release

    async def get_by_id_for_update(self, file_id: UUID):
        metadata = await super().get_by_id_for_update(file_id)
        self._locked.set()
        await self._release.wait()
        return metadata


@pytest.mark.asyncio
async def test_file_upload_reads_exact_bytes_without_an_object_store(
    object_content_database: DatabaseSessionManager,
) -> None:
    payload = "Exact original café".encode()
    file_id = None
    async with object_content_database.session() as session, session.begin():
        user = await _user(session)
        service = FileService(
            user=user,
            repo=FileRepository(session),
            protocol=FileProtocol(
                file_size_service=FileSizeService(),
                text_extractor=TextExtractor(),
                image_extractor=ImageExtractor(),
            ),
            object_content=_content_service(object_content_database),
            upload_admission=_inline_upload_admission(),
        )
        saved = await service.save_file(
            UploadFile(
                file=BytesIO(payload),
                filename="../../safe.txt",
                headers={"content-type": "text/plain"},
            )
        )
        file_id = saved.id
        assert saved.name == "safe.txt"

        references = (
            await session.execute(
                select(
                    FileContentReferences.variant,
                    FileContentReferences.content_id,
                ).where(FileContentReferences.file_id == saved.id)
            )
        ).all()
        assert {row.variant for row in references} == {
            "original",
            "extracted_text",
        }
        assert len({row.content_id for row in references}) == 2

    assert file_id is not None
    async with object_content_database.session() as session:
        async with session.begin():
            user = await _user(session)
            service = FileService(
                user=user,
                repo=FileRepository(session),
                protocol=FileProtocol(
                    file_size_service=FileSizeService(),
                    text_extractor=TextExtractor(),
                    image_extractor=ImageExtractor(),
                ),
                object_content=_content_service(object_content_database),
                upload_admission=_inline_upload_admission(),
            )
            hydrated = await service.get_file_content(file_id)
        download = await service.get_download_no_auth(file_id)
        downloaded = b"".join([chunk async for chunk in download.chunks])

    assert hydrated.text == payload.decode()
    assert hydrated.blob is None
    assert downloaded == payload
    assert download.media_type == "text/plain"


@pytest.mark.asyncio
async def test_file_hydration_batches_multiple_inline_payloads_in_one_query(
    object_content_database: DatabaseSessionManager,
) -> None:
    file_ids: list[UUID] = []
    async with object_content_database.session() as session, session.begin():
        user = await _user(session)
        service = FileService(
            user=user,
            repo=FileRepository(session),
            protocol=FileProtocol(
                file_size_service=FileSizeService(),
                text_extractor=TextExtractor(),
                image_extractor=ImageExtractor(),
            ),
            object_content=_content_service(object_content_database),
            upload_admission=_inline_upload_admission(),
        )
        for index in range(3):
            saved = await service.save_file(
                UploadFile(
                    file=BytesIO(f"policy {index}".encode()),
                    filename=f"policy-{index}.txt",
                    headers={"content-type": "text/plain"},
                )
            )
            file_ids.append(saved.id)

    inline_payload_queries: list[str] = []

    def capture_inline_payload_query(
        _connection,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        if "inline_content_payloads" in statement.lower():
            inline_payload_queries.append(statement)

    async with object_content_database.session() as session, session.begin():
        user = await _user(session)
        service = FileService(
            user=user,
            repo=FileRepository(session),
            protocol=FileProtocol(
                file_size_service=FileSizeService(),
                text_extractor=TextExtractor(),
                image_extractor=ImageExtractor(),
            ),
            object_content=_content_service(object_content_database),
        )
        assert session.bind is not None
        sync_engine = session.bind.sync_engine
        sa.event.listen(
            sync_engine,
            "before_cursor_execute",
            capture_inline_payload_query,
        )
        try:
            hydrated = await service.get_files_by_ids(file_ids)
        finally:
            sa.event.remove(
                sync_engine,
                "before_cursor_execute",
                capture_inline_payload_query,
            )

    assert [file.text for file in hydrated] == ["policy 0", "policy 1", "policy 2"]
    assert len(inline_payload_queries) == 1


@pytest.mark.asyncio
async def test_file_capture_persists_payload_above_the_old_inline_default(
    object_content_database: DatabaseSessionManager,
) -> None:
    payload = b"a" * (10 * 1024 * 1024 + 1)
    prepared = PreparedFileUpload(
        name="long-recording.mp3",
        file_type=FileType.AUDIO,
        display_media_type="audio/mpeg",
        contents=(
            PendingFileContent(
                variant=FileContentVariant.ORIGINAL,
                chunks=_bytes_source(payload),
                declared_media_type="audio/mpeg",
                verified_media_type="audio/mpeg",
            ),
        ),
    )

    async with object_content_database.session() as session, session.begin():
        user = await _user(session)
        service = FileService(
            user=user,
            repo=FileRepository(session),
            protocol=_PreparedFileProtocol(prepared),
            object_content=_content_service(
                object_content_database,
                inline_maximum_bytes=len(payload),
            ),
            upload_admission=_inline_upload_admission(),
        )
        saved = await service.save_file(
            UploadFile(
                file=BytesIO(),
                filename=prepared.name,
                headers={"content-type": prepared.display_media_type},
            )
        )

        control = await session.scalar(
            select(ObjectContents)
            .join(
                FileContentReferences,
                FileContentReferences.content_id == ObjectContents.id,
            )
            .where(FileContentReferences.file_id == saved.id)
        )
        assert control is not None
        assert control.size_bytes == len(payload)
        assert control.storage_kind == "postgres_inline"


@pytest.mark.asyncio
async def test_signed_download_preserves_the_established_text_and_image_variants(
    object_content_database: DatabaseSessionManager,
) -> None:
    cases = (
        (
            PreparedFileUpload(
                name="report.pdf",
                file_type=FileType.TEXT,
                display_media_type="application/pdf",
                contents=(
                    PendingFileContent(
                        variant=FileContentVariant.ORIGINAL,
                        chunks=_bytes_source(b"%PDF exact original"),
                        declared_media_type="application/pdf",
                        verified_media_type="application/pdf",
                    ),
                    PendingFileContent(
                        variant=FileContentVariant.EXTRACTED_TEXT,
                        chunks=_bytes_source(b"extracted report"),
                        declared_media_type="text/plain",
                        verified_media_type="text/plain",
                    ),
                ),
            ),
            b"extracted report",
            "text/plain",
            "report.txt",
        ),
        (
            PreparedFileUpload(
                name="legacy-report.pdf",
                file_type=FileType.TEXT,
                display_media_type="application/pdf",
                contents=(
                    PendingFileContent(
                        variant=FileContentVariant.EXTRACTED_TEXT,
                        chunks=_bytes_source(b"migrated report"),
                        declared_media_type="text/plain",
                        verified_media_type="text/plain",
                    ),
                ),
            ),
            b"migrated report",
            "text/plain",
            "legacy-report.txt",
        ),
        (
            PreparedFileUpload(
                name="photo.png",
                file_type=FileType.IMAGE,
                display_media_type="image/png",
                contents=(
                    PendingFileContent(
                        variant=FileContentVariant.ORIGINAL,
                        chunks=_bytes_source(b"large original image"),
                        declared_media_type="image/png",
                        verified_media_type="image/png",
                    ),
                    PendingFileContent(
                        variant=FileContentVariant.MODEL_INPUT,
                        chunks=_bytes_source(b"bounded image"),
                        declared_media_type="image/jpeg",
                        verified_media_type="image/jpeg",
                    ),
                ),
            ),
            b"bounded image",
            "image/jpeg",
            "photo.png",
        ),
        (
            PreparedFileUpload(
                name="legacy-photo.png",
                file_type=FileType.IMAGE,
                display_media_type="image/png",
                contents=(
                    PendingFileContent(
                        variant=FileContentVariant.LEGACY_IMAGE,
                        chunks=_bytes_source(b"migrated bounded image"),
                        declared_media_type="image/jpeg",
                        verified_media_type="image/jpeg",
                    ),
                ),
            ),
            b"migrated bounded image",
            "image/jpeg",
            "legacy-photo.png",
        ),
    )

    saved_cases: list[tuple[UUID, bytes, str, str, str]] = []
    async with object_content_database.session() as session, session.begin():
        user = await _user(session)
        for prepared, expected_bytes, expected_media_type, expected_name in cases:
            service = FileService(
                user=user,
                repo=FileRepository(session),
                protocol=_PreparedFileProtocol(prepared),
                object_content=_content_service(object_content_database),
                upload_admission=_inline_upload_admission(),
            )
            saved = await service.save_file(
                UploadFile(
                    file=BytesIO(),
                    filename=prepared.name,
                    headers={"content-type": prepared.display_media_type},
                )
            )
            assert saved.checksum == sha256(expected_bytes).hexdigest()
            assert saved.size == len(expected_bytes)
            expected_file_media_type = (
                expected_media_type
                if prepared.file_type is FileType.IMAGE
                else prepared.display_media_type
            )
            assert saved.mimetype == expected_file_media_type
            saved_cases.append(
                (
                    saved.id,
                    expected_bytes,
                    expected_media_type,
                    expected_name,
                    expected_file_media_type,
                )
            )

    async with object_content_database.session() as session:
        async with session.begin():
            user = await _user(session)
            service = FileService(
                user=user,
                repo=FileRepository(session),
                protocol=_PreparedFileProtocol(cases[0][0]),
                object_content=_content_service(object_content_database),
            )
            for (
                file_id,
                _expected_bytes,
                _expected_media_type,
                _expected_name,
                expected_file_media_type,
            ) in saved_cases:
                hydrated = await service.get_file_content(file_id)
                assert hydrated.mimetype == expected_file_media_type
        for (
            file_id,
            expected_bytes,
            expected_media_type,
            expected_name,
            _expected_file_media_type,
        ) in saved_cases:
            download = await service.get_download_no_auth(file_id)
            downloaded = b"".join([chunk async for chunk in download.chunks])
            assert downloaded == expected_bytes
            assert download.media_type == expected_media_type
            assert download.filename == expected_name


@pytest.mark.asyncio
async def test_text_hydration_without_readable_text_returns_typed_not_found(
    object_content_database: DatabaseSessionManager,
) -> None:
    prepared = PreparedFileUpload(
        name="unextracted.pdf",
        file_type=FileType.TEXT,
        display_media_type="application/pdf",
        contents=(
            PendingFileContent(
                variant=FileContentVariant.ORIGINAL,
                chunks=_bytes_source(b"%PDF exact original"),
                declared_media_type="application/pdf",
                verified_media_type="application/pdf",
            ),
        ),
    )

    async with object_content_database.session() as session, session.begin():
        user = await _user(session)
        service = FileService(
            user=user,
            repo=FileRepository(session),
            protocol=_PreparedFileProtocol(prepared),
            object_content=_content_service(object_content_database),
            upload_admission=_inline_upload_admission(),
        )
        saved = await service.save_file(
            UploadFile(
                file=BytesIO(),
                filename=prepared.name,
                headers={"content-type": prepared.display_media_type},
            )
        )

    async with object_content_database.session() as session, session.begin():
        service = FileService(
            user=user,
            repo=FileRepository(session),
            protocol=_PreparedFileProtocol(prepared),
            object_content=_content_service(object_content_database),
            upload_admission=_inline_upload_admission(),
        )
        with pytest.raises(NotFoundException, match="no readable text content"):
            await service.get_file_content(saved.id)


@pytest.mark.asyncio
async def test_audio_range_and_icon_primary_use_the_same_inline_owner(
    object_content_database: DatabaseSessionManager,
) -> None:
    audio = b"0123456789audio"
    icon = b"\x89PNG\r\n\x1a\nicon"
    audio_id = None
    async with object_content_database.session() as session, session.begin():
        user = await _user(session)
        content_service = _content_service(object_content_database)
        file_service = FileService(
            user=user,
            repo=FileRepository(session),
            protocol=FileProtocol(
                file_size_service=FileSizeService(),
                text_extractor=TextExtractor(),
                image_extractor=ImageExtractor(),
            ),
            object_content=content_service,
            upload_admission=_inline_upload_admission(),
        )
        saved_audio = await file_service.save_file(
            UploadFile(
                file=BytesIO(audio),
                filename="meeting.mp3",
                headers={"content-type": "audio/mpeg"},
            )
        )
        audio_id = saved_audio.id

        icon_service = IconService(
            icon_repo=IconRepository(session),
            file_size_service=FileSizeService(),
            object_content=content_service,
            upload_admission=UploadAdmissionSnapshot(
                policy_revision=1,
                new_write_storage_target=StorageKind.POSTGRES_INLINE,
                session_file_maximum_bytes=10 * 1024 * 1024,
                session_image_maximum_bytes=10 * 1024 * 1024,
                session_audio_maximum_bytes=10 * 1024 * 1024,
                knowledge_file_maximum_bytes=10 * 1024 * 1024,
                knowledge_audio_maximum_bytes=10 * 1024 * 1024,
            ),
        )
        saved_icon = await icon_service.create_icon(
            UploadFile(
                file=BytesIO(icon),
                filename="icon.png",
                headers={"content-type": "image/png"},
            ),
            tenant_id=user.tenant_id,
            created_by_user_id=user.id,
        )

        icon_reference = await session.scalar(
            select(IconContentReferences).where(
                IconContentReferences.icon_id == saved_icon.id
            )
        )
        assert icon_reference is not None
        control = await session.get(ObjectContents, icon_reference.content_id)
        assert control is not None
        assert control.storage_kind == "postgres_inline"
        assert control.access_class == "public_immutable"
        assert control.verified_media_type == "image/png"
        assert control.size_bytes == len(icon)

    async with object_content_database.session() as session:
        opened_icon = await IconService(
            icon_repo=IconRepository(session),
            file_size_service=FileSizeService(),
            object_content=content_service,
        ).open_icon(saved_icon.id)
        try:
            assert b"".join([chunk async for chunk in opened_icon.chunks]) == icon
        finally:
            await opened_icon.aclose()

    assert audio_id is not None
    async with object_content_database.session() as session:
        async with session.begin():
            user = await _user(session)
        file_service = FileService(
            user=user,
            repo=FileRepository(session),
            protocol=FileProtocol(
                file_size_service=FileSizeService(),
                text_extractor=TextExtractor(),
                image_extractor=ImageExtractor(),
            ),
            object_content=_content_service(object_content_database),
            upload_admission=_inline_upload_admission(),
        )
        ranged = await file_service.get_download_no_auth(
            audio_id,
            range_header="bytes=3-8",
        )
        ranged_bytes = b"".join([chunk async for chunk in ranged.chunks])

    assert ranged_bytes == audio[3:9]
    assert ranged.content_range == f"bytes 3-8/{len(audio)}"


@pytest.mark.asyncio
async def test_concurrent_transcription_writes_converge_on_one_reference(
    object_content_database: DatabaseSessionManager,
) -> None:
    async with (
        object_content_database.session() as setup_session,
        setup_session.begin(),
    ):
        user = await _user(setup_session)
        setup_service = FileService(
            user=user,
            repo=FileRepository(setup_session),
            protocol=FileProtocol(
                file_size_service=FileSizeService(),
                text_extractor=TextExtractor(),
                image_extractor=ImageExtractor(),
            ),
            object_content=_content_service(object_content_database),
            upload_admission=_inline_upload_admission(),
        )
        audio = await setup_service.save_file(
            UploadFile(
                file=BytesIO(b"audio"),
                filename="meeting.mp3",
                headers={"content-type": "audio/mpeg"},
            )
        )

    locked = asyncio.Event()
    release = asyncio.Event()
    async with (
        object_content_database.session() as first_session,
        object_content_database.session() as second_session,
    ):
        first_service = FileService(
            user=user,
            repo=_PausingLockFileRepository(
                first_session,
                locked=locked,
                release=release,
            ),
            protocol=FileProtocol(
                file_size_service=FileSizeService(),
                text_extractor=TextExtractor(),
                image_extractor=ImageExtractor(),
            ),
            object_content=_content_service(object_content_database),
        )
        second_service = FileService(
            user=user,
            repo=FileRepository(second_session),
            protocol=FileProtocol(
                file_size_service=FileSizeService(),
                text_extractor=TextExtractor(),
                image_extractor=ImageExtractor(),
            ),
            object_content=_content_service(object_content_database),
        )

        first = asyncio.create_task(
            first_service.save_transcription(audio.id, "first result")
        )
        await asyncio.wait_for(locked.wait(), timeout=2)
        second = asyncio.create_task(
            second_service.save_transcription(audio.id, "racing result")
        )
        await asyncio.sleep(0.05)
        assert not second.done()

        release.set()
        assert await asyncio.gather(first, second) == [
            "first result",
            "first result",
        ]

    async with (
        object_content_database.session() as verify_session,
        verify_session.begin(),
    ):
        references = (
            await verify_session.scalars(
                select(FileContentReferences).where(
                    FileContentReferences.file_id == audio.id,
                    FileContentReferences.variant == "transcription",
                )
            )
        ).all()
    assert len(references) == 1
