"""Integration tests for deleting uploaded files nothing uses anymore.

Retention and manual deletion remove a Question or AppRun together with the
files it used, as long as nothing else still uses them; the daily sweep removes
every other unused file family. The stored bytes, including audio originals and
transcriptions, are released for the object-content reconciler.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.audit.domain.action_types import ActionType
from eneo.data_retention.application.retention_runner import is_lock_wait_timeout
from eneo.data_retention.domain.retention import RetentionJobOutcome, RetentionKeyset
from eneo.data_retention.infrastructure.retention_job_run_repo import (
    RetentionJobRunRepository,
)
from eneo.database.database import sessionmanager
from eneo.database.tables.app_table import AppRuns, AppRunsFiles, Apps, AppsFiles
from eneo.database.tables.assistant_table import Assistants, AssistantsFiles
from eneo.database.tables.audit_log_table import AuditLog
from eneo.database.tables.files_table import Files
from eneo.database.tables.object_content_table import (
    FileContentReferences,
    ObjectContents,
)
from eneo.database.tables.questions_table import Questions, QuestionsFiles
from eneo.database.tables.sessions_table import Sessions
from eneo.files.file_models import FileType
from eneo.files.file_retention import FileRetentionReason
from eneo.files.unused_file_cleanup import preview_unused_files
from eneo.main.config import get_settings
from eneo.object_content.configuration import ObjectContentCoreSettings
from eneo.object_content.content import (
    ContentAccessClass,
    ContentIntent,
    ContentState,
    StorageKind,
    capture_content,
)
from eneo.object_content.content_service import ObjectContentService
from tests.integration.data_retention.retention_support import (
    run_registered_retention,
    step_batches,
)


async def _payload_source(payload: bytes) -> AsyncIterator[bytes]:
    yield payload


@pytest.fixture
async def completion_model(retention_session: AsyncSession, completion_model_factory):
    return await completion_model_factory(retention_session, "gpt-4")


@pytest.fixture
async def retention_app(
    retention_session: AsyncSession,
    completion_model,
    app_factory,
) -> Apps:
    return await app_factory(
        retention_session,
        "Transcription App",
        completion_model.id,
        data_retention_days=1,
    )


@pytest.fixture
async def retention_assistant(
    retention_session: AsyncSession,
    completion_model,
    assistant_factory,
    space_factory,
) -> Assistants:
    space = await space_factory(retention_session, "Retention Files Space")
    return await assistant_factory(
        retention_session,
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


async def _sweep():
    async with sessionmanager.session() as session:
        return await run_registered_retention(session, task_name="files.unused")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_question_retention_deletes_chat_attachment(
    retention_session: AsyncSession,
    admin_user,
    retention_assistant: Assistants,
) -> None:
    attachment = await _create_file(retention_session, admin_user, name="notes.mp3")
    await _create_question(
        retention_session, retention_assistant, admin_user, days_old=2, file=attachment
    )

    report = await run_registered_retention(retention_session)
    deleted = report.counts.get("questions.questions_deleted", 0)

    assert deleted == 1
    assert not await _file_exists(retention_session, attachment.id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_retention_keeps_file_attached_to_an_assistant(
    retention_session: AsyncSession,
    admin_user,
    retention_app: Apps,
    retention_assistant: Assistants,
) -> None:
    knowledge = await _create_file(retention_session, admin_user, name="policy.mp3")
    retention_session.add(
        AssistantsFiles(assistant_id=retention_assistant.id, file_id=knowledge.id)
    )
    await _create_app_run(retention_session, retention_app, days_old=2, file=knowledge)

    await run_registered_retention(retention_session)

    assert await _file_exists(retention_session, knowledge.id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_retention_deletes_derived_files_with_their_root(
    retention_session: AsyncSession,
    admin_user,
    retention_app: Apps,
) -> None:
    root = await _create_file(retention_session, admin_user, name="slides.pdf")
    # Kills truncating a family below the product's configured extraction limit.
    derived = [
        await _create_file(
            retention_session,
            admin_user,
            name=f"page-{index}.png",
            parent_file_id=root.id,
        )
        for index in range(get_settings().attachment_max_extracted_images)
    ]
    await _create_app_run(retention_session, retention_app, days_old=2, file=root)

    await run_registered_retention(retention_session)

    assert not await _file_exists(retention_session, root.id)
    for page in derived:
        assert not await _file_exists(retention_session, page.id)


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rows,files,unit,chunk,family,locked,block",
    [
        pytest.param(
            200,
            20,
            32,
            64,
            5,
            None,
            FileRetentionReason.FAMILY_EXCEEDS_BUDGET,
            id="kills-partial-family-cap-delete",
        ),
        # The first run spends 2 discovery + 5 on the smaller run's unit, so a
        # 14-row chunk leaves 7: the proof (1 row) and the root DELETE fit,
        # the two-member family does not.
        pytest.param(
            22, 20, 12, 14, 12, None, None, id="kills-row-shortage-cursor-skip"
        ),
        pytest.param(
            100, 2, 12, 40, 12, None, None, id="kills-file-shortage-cursor-skip"
        ),
        pytest.param(
            200,
            20,
            32,
            64,
            32,
            0,
            FileRetentionReason.LOCKED,
            id="kills-held-root-conversation-delete",
        ),
        pytest.param(
            200,
            20,
            32,
            64,
            32,
            1,
            FileRetentionReason.LOCKED,
            id="kills-held-child-partial-delete",
        ),
    ],
)
async def test_conversation_file_refusal_is_atomic_and_resumable(
    retention_session: AsyncSession,
    admin_user,
    retention_app: Apps,
    rows: int,
    files: int,
    unit: int,
    chunk: int,
    family: int,
    locked: int | None,
    block: FileRetentionReason | None,
) -> None:
    settings = get_settings().model_copy(
        update={
            "retention_conversations_max_rows_per_run": rows,
            "retention_max_files_per_run": files,
            "retention_conversations_max_unit_rows": unit,
            "retention_chunk_rows": chunk,
            "retention_max_family_rows": family,
            "retention_chunk_lock_timeout_ms": 200,
        }
    )
    root = await _create_file(retention_session, admin_user)
    child = await _create_file(retention_session, admin_user, parent_file_id=root.id)
    content_id = await _add_transcription(retention_session, admin_user, root)
    retained = await _create_app_run(
        retention_session, retention_app, days_old=2 if block is None else 3, file=root
    )
    smaller = await _create_file(retention_session, admin_user)
    progressed = await _create_app_run(
        retention_session,
        retention_app,
        days_old=3 if block is None else 2,
        file=smaller,
    )
    await retention_session.commit()
    async with sessionmanager.session() as holder, holder.begin():
        if locked is not None:
            await holder.execute(
                select(Files.id)
                .where(Files.id == (root.id, child.id)[locked])
                .with_for_update()
            )
        report = await run_registered_retention(retention_session, settings=settings)

    assert report.outcome is (
        RetentionJobOutcome.PARTIAL if block is None else RetentionJobOutcome.SUCCEEDED
    )
    assert report.job_run_id is not None
    assert report.counts["app_runs.app_runs_deleted"] == 1
    assert report.counts["app_runs.files_deleted"] == 1
    assert await retention_session.get(AppRuns, retained.id) is not None
    assert await retention_session.get(AppRunsFiles, (retained.id, root.id)) is not None
    assert await retention_session.get(AppRuns, progressed.id) is None
    assert not await _file_exists(retention_session, smaller.id)
    for identifier in (root.id, child.id):
        assert await _file_exists(retention_session, identifier)
    assert (
        await retention_session.scalar(
            select(ObjectContents.reference_count).where(
                ObjectContents.id == content_id
            )
        )
        == 1
    )
    audits = (
        select(AuditLog.log_metadata)
        .where(
            AuditLog.action == ActionType.DATA_RETENTION_BATCH.value,
            AuditLog.log_metadata["job_run_id"].astext == str(report.job_run_id),
            AuditLog.log_metadata["step"].astext == "app_runs",
        )
        .subquery()
    )
    assert (
        await retention_session.scalar(
            select(
                func.sum(
                    audits.c.log_metadata["counts"]["app_runs_deleted"].as_integer()
                )
            )
        )
        == 1
    )
    cursors = await RetentionJobRunRepository(retention_session).cursors(
        report.job_run_id
    )
    if block is not None:
        assert report.blocked[f"app_runs.{block.key}"] == 1
        assert (
            await retention_session.scalar(
                select(
                    func.sum(audits.c.log_metadata["blocked"][block.key].as_integer())
                )
            )
            == 1
        )
        assert cursors == {}
    else:
        # The step stops on the shortage with no refusal; the next chunk lacks
        # a fresh unit's allowance and defers.
        assert not [key for key in report.blocked if key.startswith("app_runs.")]
        assert report.counts["app_runs.deferred"] == 1
        assert cursors["app_runs"] == RetentionKeyset(
            at=progressed.created_at, id=progressed.id, group=retention_app.id
        )
        retry = await run_registered_retention(retention_session, settings=settings)
        assert retry.outcome in {
            RetentionJobOutcome.SUCCEEDED,
            RetentionJobOutcome.PARTIAL,
        }
        assert retry.counts["app_runs.app_runs_deleted"] == 1
        assert retry.counts["app_runs.files_deleted"] == 2
        assert await retention_session.get(AppRuns, retained.id) is None
        for identifier in (root.id, child.id):
            assert not await _file_exists(retention_session, identifier)
        assert (
            await retention_session.scalar(
                select(ObjectContents.state).where(ObjectContents.id == content_id)
            )
            == ContentState.DELETE_PENDING.value
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_held_stored_content_keeps_its_question_and_the_open_chunk_goes_on(
    retention_session: AsyncSession,
    admin_user,
    retention_assistant: Assistants,
) -> None:
    """The File release's reference trigger waits on the stored content another
    transaction holds. Mutants: the lock wait fails the whole chunk; it charges
    the unit's whole row allowance (5000 rows by default), so the later
    question is deleted in a second batch."""
    held_file = await _create_file(retention_session, admin_user)
    content_id = await _add_transcription(retention_session, admin_user, held_file)
    held = await _create_question(
        retention_session, retention_assistant, admin_user, days_old=3, file=held_file
    )
    later = await _create_question(
        retention_session,
        retention_assistant,
        admin_user,
        days_old=2,
        file=await _create_file(retention_session, admin_user, name="later.mp3"),
    )
    held_id, held_file_id, later_id = held.id, held_file.id, later.id
    await retention_session.commit()
    # The default unit and chunk rows; a family cap that leaves the chunk room,
    # and a gather window that outlasts the lock wait on a cold database.
    settings = get_settings().model_copy(
        update={
            "retention_chunk_lock_timeout_ms": 200,
            "retention_chunk_gather_seconds": 60.0,
            "retention_max_family_rows": 32,
        }
    )

    async with sessionmanager.session() as holder, holder.begin():
        await holder.execute(
            select(ObjectContents.id)
            .where(ObjectContents.id == content_id)
            .with_for_update()
        )
        report = await run_registered_retention(retention_session, settings=settings)

    assert report.blocked["questions.cascade_locked"] == 1
    assert report.counts["questions.questions_deleted"] == 1
    assert await retention_session.get(Questions, held_id) is not None
    assert await _file_exists(retention_session, held_file_id)
    assert await retention_session.get(Questions, later_id) is None
    [batch] = await step_batches(retention_session, report.job_run_id, "questions")
    assert batch["blocked"] == {"cascade_locked": 1}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_retention_keeps_root_when_a_derived_file_is_still_used(
    retention_session: AsyncSession,
    admin_user,
    retention_app: Apps,
) -> None:
    root = await _create_file(retention_session, admin_user, name="slides.pdf")
    derived = await _create_file(
        retention_session, admin_user, name="page-1.png", parent_file_id=root.id
    )
    await _create_app_run(retention_session, retention_app, days_old=2, file=root)
    await _create_app_run(retention_session, retention_app, days_old=0, file=derived)

    await run_registered_retention(retention_session)

    assert await _file_exists(retention_session, root.id)
    assert await _file_exists(retention_session, derived.id)


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

    assert result.counts["families.roots_deleted"] == 1
    assert result.counts["families.files_deleted"] == 2
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
    """Mutants: omit kept outcomes; filter referenced roots before admission;
    lock and prove a root whose own use the page shows (3 rows instead of 1,
    so the budget ends before the unused root); report a File in use as
    blocked."""
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
        unused = await _create_file(session, admin_user, days_old=29)
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
        unused_id = unused.id

    # Four roots in use by themselves cost 1 row each; the root kept by its
    # child is proved under lock (5 rows); the unused singleton needs 4.
    settings = get_settings().model_copy(
        update={
            "retention_max_rows_per_run": 14,
            "retention_chunk_rows": 14,
            "retention_max_family_rows": 6,
        }
    )
    async with sessionmanager.session() as session:
        result = await run_registered_retention(
            session, task_name="files.unused", settings=settings
        )

    assert result.outcome is RetentionJobOutcome.SUCCEEDED
    assert result.counts["families.files_in_use"] == 5
    assert result.counts["families.roots_deleted"] == 1
    assert result.blocked == {}
    for file_id in file_ids:
        assert await _committed_file_exists(file_id)
    assert not await _committed_file_exists(unused_id)


async def _preview(session: AsyncSession, *, lock_timeout_ms: int):
    return await preview_unused_files(
        session,
        older_than=timedelta(days=1),
        page_size=2,
        statement_timeout_ms=30_000,
        lock_timeout_ms=lock_timeout_ms,
    )


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

    async with sessionmanager.session() as session:
        preview = await _preview(session, lock_timeout_ms=2_000)

    assert preview.dry_run is True
    assert preview.families == 3
    for orphan_id in orphan_ids:
        assert await _committed_file_exists(orphan_id)

    result = await _sweep()

    assert result.counts["families.roots_deleted"] == 3
    for orphan_id in orphan_ids:
        assert not await _committed_file_exists(orphan_id)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sweep_preview_ends_at_a_held_file_instead_of_waiting(
    admin_user,
) -> None:
    """Mutants: the preview transaction sets no lock timeout, so a File a user
    holds keeps the preview, and every user queued behind it, waiting; the
    preview is bounded by its statement timeout alone (57014, not 55P03)."""
    async with sessionmanager.session() as session, session.begin():
        held_id = (await _create_file(session, admin_user, days_old=30)).id

    async with sessionmanager.session() as holder, holder.begin():
        await holder.execute(
            select(Files.id).where(Files.id == held_id).with_for_update()
        )
        async with sessionmanager.session() as session:
            with pytest.raises(DBAPIError) as raised:
                async with asyncio.timeout(10):
                    await _preview(session, lock_timeout_ms=100)
    assert is_lock_wait_timeout(raised.value)
