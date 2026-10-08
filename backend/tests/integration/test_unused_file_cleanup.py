"""Integration tests for deleting uploaded files nothing uses anymore.

Retention and manual deletion remove a Question or AppRun together with the
files it used, as long as nothing else still uses them; the daily sweep removes
every other unused file family. The stored bytes, including audio originals and
transcriptions, are released for the object-content reconciler.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.infrastructure import (
    data_retention_service as retention_module,
)
from eneo.data_retention.infrastructure.data_retention_service import (
    DataRetentionService,
)
from eneo.database.database import sessionmanager
from eneo.database.tables.app_table import AppRuns, AppRunsFiles, Apps, AppsFiles
from eneo.database.tables.assistant_table import Assistants, AssistantsFiles
from eneo.database.tables.files_table import Files
from eneo.database.tables.object_content_table import (
    FileContentReferences,
    ObjectContents,
)
from eneo.database.tables.questions_table import Questions, QuestionsFiles
from eneo.database.tables.sessions_table import Sessions
from eneo.files.file_models import FileType
from eneo.files.unused_file_cleanup import sweep_unused_files
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
    days_old: int = 0,
) -> Files:
    created_at = datetime.now(timezone.utc) - timedelta(days=days_old)
    file = Files(
        name=name,
        mimetype="audio/mpeg",
        file_type=FileType.AUDIO.value,
        tenant_id=admin_user.tenant_id,
        user_id=admin_user.id,
        parent_file_id=parent_file_id,
        created_at=created_at,
        updated_at=created_at,
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


async def _committed_file_exists(file_id: UUID) -> bool:
    async with sessionmanager.session() as session, session.begin():
        return await _file_exists(session, file_id)


async def _sweep(*, dry_run: bool = False, page_size: int = 1000):
    async with sessionmanager.session() as session:
        return await sweep_unused_files(session, dry_run=dry_run, page_size=page_size)


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


@pytest.mark.integration
@pytest.mark.asyncio
async def test_deleting_an_app_run_deletes_its_unused_input_files(
    db_container,
    admin_user,
    completion_model_factory,
    app_factory,
) -> None:
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4")
        app = await app_factory(session, "Transcription App", model.id)
        recording = await _create_file(session, admin_user)
        shared = await _create_file(session, admin_user, name="shared.mp3")
        run = await _create_app_run(session, app, days_old=0, file=recording)
        session.add(AppRunsFiles(app_run_id=run.id, file_id=shared.id))
        await _create_app_run(session, app, days_old=0, file=shared)
        run_id, recording_id, shared_id = run.id, recording.id, shared.id

    async with db_container() as container:
        await container.app_run_repo().delete(run_id)

    assert not await _committed_file_exists(recording_id)
    assert await _committed_file_exists(shared_id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sweep_deletes_old_unused_families_and_releases_content(
    admin_user,
) -> None:
    async with sessionmanager.session() as session, session.begin():
        orphan = await _create_file(session, admin_user, days_old=30)
        transcription_id = await _add_transcription(session, admin_user, orphan)
        derived = await _create_file(
            session, admin_user, name="page-1.png", parent_file_id=orphan.id
        )
        fresh = await _create_file(session, admin_user, name="fresh.mp3")
        orphan_id, derived_id, fresh_id = orphan.id, derived.id, fresh.id

    result = await _sweep()

    assert result.files == 1
    assert result.files_by_tenant == {str(admin_user.tenant_id): 1}
    assert result.managed_bytes == len(b"Transcribed meeting notes")
    assert not await _committed_file_exists(orphan_id)
    assert not await _committed_file_exists(derived_id)
    # Younger than the minimum age: may still be on its way to a chat or run.
    assert await _committed_file_exists(fresh_id)
    async with sessionmanager.session() as session, session.begin():
        state = await session.scalar(
            select(ObjectContents.state).where(ObjectContents.id == transcription_id)
        )
    assert state == ContentState.DELETE_PENDING.value


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sweep_keeps_every_file_family_still_in_use(
    admin_user,
    completion_model_factory,
    app_factory,
    assistant_factory,
    space_factory,
) -> None:
    async with sessionmanager.session() as session, session.begin():
        model = await completion_model_factory(session, "gpt-4")
        app = await app_factory(session, "Sweep App", model.id)
        space = await space_factory(session, "Sweep Space")
        assistant = await assistant_factory(
            session, "Sweep Assistant", model.id, space_id=space.id
        )
        in_chat = await _create_file(session, admin_user, days_old=30)
        in_assistant = await _create_file(session, admin_user, days_old=30)
        in_app = await _create_file(session, admin_user, days_old=30)
        in_run = await _create_file(session, admin_user, days_old=30)
        with_used_child = await _create_file(session, admin_user, days_old=30)
        used_child = await _create_file(
            session, admin_user, parent_file_id=with_used_child.id, days_old=30
        )
        await _create_question(session, assistant, admin_user, days_old=0, file=in_chat)
        session.add_all(
            [
                AssistantsFiles(assistant_id=assistant.id, file_id=in_assistant.id),
                AppsFiles(app_id=app.id, file_id=in_app.id),
            ]
        )
        await _create_app_run(session, app, days_old=0, file=in_run)
        await _create_app_run(session, app, days_old=0, file=used_child)
        file_ids = [
            file.id
            for file in (
                in_chat,
                in_assistant,
                in_app,
                in_run,
                with_used_child,
                used_child,
            )
        ]

    result = await _sweep()

    assert result.files == 0
    for file_id in file_ids:
        assert await _committed_file_exists(file_id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sweep_preview_counts_without_deleting(admin_user) -> None:
    async with sessionmanager.session() as session, session.begin():
        orphan_ids = [
            (
                await _create_file(
                    session, admin_user, name=f"{index}.mp3", days_old=30
                )
            ).id
            for index in range(3)
        ]

    preview = await _sweep(dry_run=True, page_size=2)

    assert preview.dry_run is True
    assert preview.files == 3
    for orphan_id in orphan_ids:
        assert await _committed_file_exists(orphan_id)

    result = await _sweep(page_size=2)

    assert result.files == 3
    for orphan_id in orphan_ids:
        assert not await _committed_file_exists(orphan_id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_retention_commits_each_batch_on_its_own(
    db_container,
    admin_user,
    completion_model_factory,
    app_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The nightly job releases each batch's locks before taking the next.

    Files a batch keeps because something else still uses them are locked
    too, so one transaction over the whole run would block every attach of
    those Files until the run ends.
    """
    monkeypatch.setattr(retention_module, "RETENTION_BATCH_SIZE", 1)
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4")
        app = await app_factory(
            session, "Transcription App", model.id, data_retention_days=1
        )
        file_ids: list[UUID] = []
        for index in range(3):
            recording = await _create_file(session, admin_user, name=f"{index}.mp3")
            await _create_app_run(session, app, days_old=2, file=recording)
            file_ids.append(recording.id)

    commits: list[None] = []
    async with sessionmanager.session() as session:
        sa.event.listen(
            session.sync_session, "after_commit", lambda _session: commits.append(None)
        )
        deleted = await DataRetentionService(session).delete_old_app_runs(
            commit_each_batch=True
        )
        assert not session.in_transaction()

    assert deleted == 3
    # One commit per batch of one run; the final empty page may add another.
    assert len(commits) >= 3
    for file_id in file_ids:
        assert not await _committed_file_exists(file_id)
