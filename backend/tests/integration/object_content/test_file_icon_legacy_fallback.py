from collections.abc import AsyncIterator
from hashlib import sha256
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.database import AsyncSession, DatabaseSessionManager
from eneo.database.tables.files_table import Files
from eneo.database.tables.icons_table import Icons
from eneo.database.tables.users_table import Users
from eneo.files.file_content_loader import FileContentLoader
from eneo.files.file_repo import FileRepository
from eneo.files.file_service import FileService
from eneo.files.file_size_service import FileSizeService
from eneo.icons.icon_repo import IconRepository
from eneo.icons.icon_service import IconService


async def _read_chunks(chunks: AsyncIterator[bytes]) -> bytes:
    return b"".join([chunk async for chunk in chunks])


async def _seed_legacy_rows(
    session: AsyncSession,
) -> tuple[UUID, UUID, UUID, UUID, UUID, bytes, bytes, bytes, bytes, bytes]:
    tenant_id, user_id = (
        await session.execute(
            sa.select(Users.tenant_id, Users.id).where(
                Users.email == "object-content@example.test"
            )
        )
    ).one()
    text_id = uuid4()
    image_id = uuid4()
    audio_id = uuid4()
    icon_id = uuid4()
    extracted = b"legacy extracted text"
    original = b"legacy original pdf"
    transcription = b"legacy transcription"
    image = b"legacy-image"
    audio = b"0123456789legacy-audio"

    await session.execute(sa.text("SET LOCAL session_replication_role = replica"))
    await session.execute(
        sa.text(
            """
            INSERT INTO files (
                id, name, text, blob, checksum, size, mimetype, file_type,
                transcription, user_id, tenant_id, parent_file_id
            ) VALUES (
                :text_id, 'legacy.pdf', :extracted, :original, :text_checksum,
                :text_size, 'application/pdf', 'text', :transcription,
                :user_id, :tenant_id, NULL
            ), (
                :image_id, 'legacy.png', NULL, :image, :image_checksum,
                :image_size, 'image/png', 'image', NULL,
                :user_id, :tenant_id, NULL
            ), (
                :audio_id, 'legacy.mp3', NULL, :audio, :audio_checksum,
                :audio_size, 'audio/mpeg', 'audio', NULL,
                :user_id, :tenant_id, NULL
            )
            """
        ),
        {
            "text_id": text_id,
            "extracted": extracted.decode(),
            "original": original,
            # v2.1 stored the upload digest but the extracted-text logical size.
            "text_checksum": sha256(original).hexdigest(),
            "text_size": len(extracted),
            "transcription": transcription.decode(),
            "image_id": image_id,
            "image": image,
            "image_checksum": sha256(image).hexdigest(),
            "image_size": len(image),
            "audio_id": audio_id,
            "audio": audio,
            "audio_checksum": sha256(audio).hexdigest(),
            "audio_size": len(audio),
            "user_id": user_id,
            "tenant_id": tenant_id,
        },
    )
    await session.execute(
        sa.text(
            """
            INSERT INTO icons (id, blob, mimetype, size, tenant_id)
            VALUES (:icon_id, :payload, 'image/png', :size, :tenant_id)
            """
        ),
        {
            "icon_id": icon_id,
            "payload": b"legacy-icon",
            "size": len(b"legacy-icon"),
            "tenant_id": tenant_id,
        },
    )
    return (
        tenant_id,
        text_id,
        image_id,
        audio_id,
        icon_id,
        extracted,
        original,
        transcription,
        image,
        audio,
    )


@pytest.mark.asyncio
async def test_file_and_icon_legacy_fallbacks_execute_against_postgres(
    object_content_database: DatabaseSessionManager,
) -> None:
    async with object_content_database.session() as session, session.begin():
        (
            tenant_id,
            text_id,
            image_id,
            audio_id,
            icon_id,
            extracted,
            original,
            transcription,
            image,
            audio,
        ) = await _seed_legacy_rows(session)

    try:
        object_content = AsyncMock()
        object_content.read_content_bytes.return_value = {}
        async with object_content_database.session() as session, session.begin():
            repository = FileRepository(session)
            text_metadata = await repository.get_by_id(text_id)
            image_metadata = await repository.get_by_id(image_id)
            loaded = await FileContentLoader(repository, object_content).load(
                [text_metadata, image_metadata]
            )
            info = (await repository.get_infos_by_ids([text_id]))[0]

        loaded_text = loaded[text_id]
        assert loaded_text.text == extracted.decode()
        assert loaded_text.blob is None
        assert loaded_text.transcription == transcription.decode()
        assert loaded_text.checksum == sha256(extracted).hexdigest()
        assert loaded_text.size == len(extracted)
        assert loaded_text.original_available is True
        assert loaded[image_id].blob == image
        assert loaded[image_id].checksum == sha256(image).hexdigest()
        assert info.checksum == sha256(original).hexdigest()
        assert info.size == len(extracted)
        object_content.open_content.assert_not_called()

        async with object_content_database.session() as session:
            audio_service = FileService(
                user=None,
                repo=FileRepository(session),
                protocol=AsyncMock(),
                object_content=object_content,
            )
            download = await audio_service.get_download_no_auth(
                audio_id,
                range_header="bytes=2-7",
                expected_tenant_id=tenant_id,
            )
            try:
                assert await _read_chunks(download.chunks) == audio[2:8]
                assert download.content_length == 6
                assert download.content_range == f"bytes 2-7/{len(audio)}"
                assert download.sha256 == sha256(audio).digest()
            finally:
                await download.aclose()

        async with object_content_database.session() as session:
            icon_service = IconService(
                IconRepository(session),
                FileSizeService(),
                object_content,
            )
            icon_download = await icon_service.open_icon(icon_id)
            try:
                assert await _read_chunks(icon_download.chunks) == b"legacy-icon"
                assert icon_download.content_length == len(b"legacy-icon")
                assert icon_download.media_type == "image/png"
            finally:
                await icon_download.aclose()
        object_content.open_content.assert_not_called()
    finally:
        async with object_content_database.session() as session, session.begin():
            await session.execute(
                sa.delete(Files).where(Files.id.in_([text_id, image_id, audio_id]))
            )
            await session.execute(sa.delete(Icons).where(Icons.id == icon_id))
