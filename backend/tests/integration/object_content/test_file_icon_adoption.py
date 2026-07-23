from __future__ import annotations

import asyncio
from io import BytesIO
from uuid import UUID

import pytest
from fastapi import UploadFile
from sqlalchemy import select

from eneo.database.database import AsyncSession, DatabaseSessionManager
from eneo.database.tables.object_content_table import (
    FileContentReferences,
    IconContentReferences,
    ObjectContents,
)
from eneo.database.tables.users_table import Users
from eneo.files.file_protocol import FileProtocol
from eneo.files.file_repo import FileRepository
from eneo.files.file_service import FileService
from eneo.files.file_size_service import FileSizeService
from eneo.files.image import ImageExtractor
from eneo.files.text import TextExtractor
from eneo.icons.icon_repo import IconRepository
from eneo.icons.icon_service import IconService
from eneo.object_content.configuration import ObjectContentCoreSettings
from eneo.object_content.content_service import ObjectContentService
from eneo.users.user import UserInDB


def _content_service(
    database: DatabaseSessionManager,
) -> ObjectContentService:
    return ObjectContentService(
        ObjectContentCoreSettings(
            _env_file=None,
            inline_maximum_bytes=10 * 1024 * 1024,
            inline_io_chunk_bytes=64 * 1024,
        ),
        database,
    )


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
        hydrated = await service.get_file_content(file_id)
        download = await service.get_download_no_auth(file_id)
        downloaded = b"".join([chunk async for chunk in download.chunks])

    assert hydrated.text == payload.decode()
    assert hydrated.blob is None
    assert downloaded == payload
    assert download.media_type == "text/plain"


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
        assert saved_icon.blob == icon
        assert saved_icon.mimetype == "image/png"
        assert saved_icon.size == len(icon)

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

    assert audio_id is not None
    async with object_content_database.session() as session, session.begin():
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
