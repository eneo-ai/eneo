"""Integration tests for files attached to records removed by data retention.

Retention removes a Question or AppRun together with the files it used, as long
as nothing else still uses them. The stored bytes, including audio originals and
transcriptions, are released for the object-content reconciler.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.infrastructure.data_retention_service import (
    DataRetentionService,
)
from eneo.database.tables.app_table import AppRuns, AppRunsFiles, Apps
from eneo.database.tables.assistant_table import Assistants, AssistantsFiles
from eneo.database.tables.files_table import Files
from eneo.database.tables.object_content_table import (
    FileContentReferences,
    ObjectContents,
)
from eneo.database.tables.questions_table import Questions, QuestionsFiles
from eneo.database.tables.sessions_table import Sessions
from eneo.files.file_models import FileType
from eneo.object_content.configuration import ObjectContentCoreSettings
from eneo.object_content.content import (
    ContentAccessClass,
    ContentIntent,
    ContentState,
    StorageKind,
    capture_content,
)
from eneo.object_content.content_service import ObjectContentService


async def _payload_source(payload: bytes) -> AsyncIterator[bytes]:
    yield payload


@pytest.fixture
async def completion_model(async_session: AsyncSession, completion_model_factory):
    return await completion_model_factory(async_session, "gpt-4")


@pytest.fixture
async def retention_app(
    async_session: AsyncSession,
    completion_model,
    app_factory,
) -> Apps:
    return await app_factory(
        async_session,
        "Transcription App",
        completion_model.id,
        data_retention_days=1,
    )


@pytest.fixture
async def retention_assistant(
    async_session: AsyncSession,
    completion_model,
    assistant_factory,
    space_factory,
) -> Assistants:
    space = await space_factory(async_session, "Retention Files Space")
    return await assistant_factory(
        async_session,
        "Retention Files Assistant",
        completion_model.id,
        space_id=space.id,
        data_retention_days=1,
    )


async def _create_file(
    session: AsyncSession,
    admin_user,
    *,
    name: str = "recording.mp3",
    parent_file_id: UUID | None = None,
) -> Files:
    file = Files(
        name=name,
        mimetype="audio/mpeg",
        file_type=FileType.AUDIO.value,
        tenant_id=admin_user.tenant_id,
        user_id=admin_user.id,
        parent_file_id=parent_file_id,
    )
    session.add(file)
    await session.flush()
    return file


async def _add_transcription(
    session: AsyncSession,
    admin_user,
    file: Files,
) -> UUID:
    payload = b"Transcribed meeting notes"
    settings = ObjectContentCoreSettings(
        _env_file=None,
        inline_maximum_bytes=len(payload),
        inline_io_chunk_bytes=len(payload),
    )
    async with capture_content(
        _payload_source(payload),
        declared_media_type="text/plain",
        verified_media_type="text/plain",
        maximum_size_bytes=len(payload),
        spool_memory_bytes=len(payload),
        multipart_part_bytes=len(payload),
    ) as captured:
        prepared = await ObjectContentService(settings).prepare_in_transaction(
            session,
            intent=ContentIntent(
                tenant_id=admin_user.tenant_id,
                created_by_user_id=admin_user.id,
                access_class=ContentAccessClass.PRIVATE_RESOURCE,
                idempotency_key=f"file:{file.id}:transcription:0",
                producer_receipt=f"file:{file.id}:transcription:0",
            ),
            content=captured,
            storage_kind=StorageKind.POSTGRES_INLINE,
        )
    session.add(
        FileContentReferences(
            file_id=file.id,
            content_id=prepared.id,
            variant="transcription",
            ordinal=0,
        )
    )
    await session.flush()
    return prepared.id


async def _create_app_run(
    session: AsyncSession,
    app: Apps,
    *,
    days_old: int,
    file: Files,
) -> AppRuns:
    created_at = datetime.now(timezone.utc) - timedelta(days=days_old)
    app_run = AppRuns(
        tenant_id=app.tenant_id,
        app_id=app.id,
        user_id=app.user_id,
        completion_model_id=app.completion_model_id,
        input_text="",
        output_text="Summary",
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(app_run)
    await session.flush()
    session.add(AppRunsFiles(app_run_id=app_run.id, file_id=file.id))
    await session.flush()
    return app_run


async def _create_question(
    session: AsyncSession,
    assistant: Assistants,
    admin_user,
    *,
    days_old: int,
    file: Files,
) -> Questions:
    created_at = datetime.now(timezone.utc) - timedelta(days=days_old)
    chat_session = Sessions(
        user_id=admin_user.id,
        name="Retention chat",
        assistant_id=assistant.id,
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(chat_session)
    await session.flush()
    question = Questions(
        question="Summarise the attachment",
        answer="Summary",
        num_tokens_question=1,
        num_tokens_answer=1,
        tenant_id=admin_user.tenant_id,
        assistant_id=assistant.id,
        session_id=chat_session.id,
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(question)
    await session.flush()
    session.add(QuestionsFiles(question_id=question.id, file_id=file.id, type="user"))
    await session.flush()
    return question


async def _file_exists(session: AsyncSession, file_id: UUID) -> bool:
    return (
        await session.scalar(select(Files.id).where(Files.id == file_id))
    ) is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_app_run_retention_deletes_recording_and_releases_transcription(
    async_session: AsyncSession,
    admin_user,
    retention_app: Apps,
) -> None:
    recording = await _create_file(async_session, admin_user)
    transcription_id = await _add_transcription(async_session, admin_user, recording)
    app_run = await _create_app_run(
        async_session, retention_app, days_old=2, file=recording
    )

    deleted = await DataRetentionService(async_session).delete_old_app_runs()

    assert deleted == 1
    assert await async_session.get(AppRuns, app_run.id) is None
    assert not await _file_exists(async_session, recording.id)
    content = (
        await async_session.execute(
            select(ObjectContents.reference_count, ObjectContents.state).where(
                ObjectContents.id == transcription_id
            )
        )
    ).one()
    assert content.reference_count == 0
    assert content.state == ContentState.DELETE_PENDING.value


@pytest.mark.integration
@pytest.mark.asyncio
async def test_question_retention_deletes_chat_attachment(
    async_session: AsyncSession,
    admin_user,
    retention_assistant: Assistants,
) -> None:
    attachment = await _create_file(async_session, admin_user, name="notes.mp3")
    await _create_question(
        async_session, retention_assistant, admin_user, days_old=2, file=attachment
    )

    deleted = await DataRetentionService(async_session).delete_old_questions()

    assert deleted == 1
    assert not await _file_exists(async_session, attachment.id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_retention_keeps_file_still_used_by_a_recent_app_run(
    async_session: AsyncSession,
    admin_user,
    retention_app: Apps,
) -> None:
    shared = await _create_file(async_session, admin_user)
    await _create_app_run(async_session, retention_app, days_old=2, file=shared)
    recent_run = await _create_app_run(
        async_session, retention_app, days_old=0, file=shared
    )

    deleted = await DataRetentionService(async_session).delete_old_app_runs()

    assert deleted == 1
    assert await async_session.get(AppRuns, recent_run.id) is not None
    assert await _file_exists(async_session, shared.id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_retention_keeps_file_attached_to_an_assistant(
    async_session: AsyncSession,
    admin_user,
    retention_app: Apps,
    retention_assistant: Assistants,
) -> None:
    knowledge = await _create_file(async_session, admin_user, name="policy.mp3")
    async_session.add(
        AssistantsFiles(assistant_id=retention_assistant.id, file_id=knowledge.id)
    )
    await _create_app_run(async_session, retention_app, days_old=2, file=knowledge)

    await DataRetentionService(async_session).delete_old_app_runs()

    assert await _file_exists(async_session, knowledge.id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_retention_deletes_derived_files_with_their_root(
    async_session: AsyncSession,
    admin_user,
    retention_app: Apps,
) -> None:
    root = await _create_file(async_session, admin_user, name="slides.pdf")
    derived = await _create_file(
        async_session, admin_user, name="page-1.png", parent_file_id=root.id
    )
    await _create_app_run(async_session, retention_app, days_old=2, file=root)

    await DataRetentionService(async_session).delete_old_app_runs()

    assert not await _file_exists(async_session, root.id)
    assert not await _file_exists(async_session, derived.id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_retention_keeps_root_when_a_derived_file_is_still_used(
    async_session: AsyncSession,
    admin_user,
    retention_app: Apps,
) -> None:
    root = await _create_file(async_session, admin_user, name="slides.pdf")
    derived = await _create_file(
        async_session, admin_user, name="page-1.png", parent_file_id=root.id
    )
    await _create_app_run(async_session, retention_app, days_old=2, file=root)
    await _create_app_run(async_session, retention_app, days_old=0, file=derived)

    await DataRetentionService(async_session).delete_old_app_runs()

    assert await _file_exists(async_session, root.id)
    assert await _file_exists(async_session, derived.id)
