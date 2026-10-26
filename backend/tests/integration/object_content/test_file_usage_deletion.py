from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.database import DatabaseSessionManager, sessionmanager
from eneo.database.tables.ai_models_table import CompletionModels
from eneo.database.tables.app_table import AppRuns, Apps
from eneo.database.tables.files_table import Files
from eneo.database.tables.object_content_table import (
    FileContentReferences,
    InlineContentPayloads,
    ObjectContents,
    ObjectStoreObjects,
)
from eneo.database.tables.questions_table import Questions, QuestionsFiles
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.users_table import Users
from eneo.files.file_models import (
    FileContentVariant,
    FileInUseError,
    FileType,
    FileUsageKind,
)
from eneo.files.file_repo import FileRepository
from eneo.files.file_retention import FileRetentionReason
from eneo.files.file_service import FileService
from eneo.files.file_usage import FileUsageRepository
from eneo.object_content.content import (
    ContentAccessClass,
    ContentIntent,
    ContentReadGrant,
    ContentState,
    StorageKind,
    capture_content,
)
from eneo.object_content.content_service import ObjectContentService
from eneo.object_content.object_store_provider import ObjectStoreProvider
from eneo.object_content.reconciliation import ObjectContentReconciler
from eneo.object_content.s3_object_store import ObjectStoreNotFoundError
from eneo.users.user import UserInDB
from tests.integration.data_retention.retention_support import run_registered_retention
from tests.integration.object_content.conftest import RealObjectStore
from tests.integration.object_content.test_file_family_visibility import (
    _add_pending_reference,
)
from tests.integration.test_unused_file_cleanup import _create_app_run, _payload_source


async def _owner_ids(database: DatabaseSessionManager) -> tuple[UUID, UUID]:
    async with database.session() as session, session.begin():
        row = (await session.execute(sa.select(Users.tenant_id, Users.id))).one()
        return row.tenant_id, row.id


async def _add_file(
    session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    name: str,
    parent_file_id: UUID | None = None,
) -> Files:
    file = Files(
        name=name,
        mimetype="text/plain",
        file_type=FileType.TEXT.value,
        tenant_id=tenant_id,
        user_id=user_id,
        parent_file_id=parent_file_id,
    )
    session.add(file)
    await session.flush()
    return file


async def _add_question_file(
    session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    file_id: UUID,
) -> QuestionsFiles:
    chat_session = Sessions(user_id=user_id, name="File usage test")
    session.add(chat_session)
    await session.flush()
    question = Questions(
        question="Use this attachment",
        answer="",
        num_tokens_question=0,
        num_tokens_answer=0,
        tenant_id=tenant_id,
        session_id=chat_session.id,
    )
    session.add(question)
    await session.flush()
    relation = QuestionsFiles(
        question_id=question.id,
        file_id=file_id,
        type="user",
    )
    session.add(relation)
    await session.flush()
    return relation


def _service(
    *,
    session,
    tenant_id: UUID,
    user_id: UUID,
) -> FileService:
    return FileService(
        user=UserInDB.model_construct(id=user_id, tenant_id=tenant_id),
        repo=FileRepository(session),
        protocol=AsyncMock(),
        object_content=AsyncMock(),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "storage_kind",
    [
        pytest.param(
            StorageKind.POSTGRES_INLINE, id="inline-shared-file-then-active-removal"
        ),
        pytest.param(StorageKind.OBJECT_STORE, id="s3-shared-file-then-active-removal"),
    ],
)
async def test_app_run_retention_releases_shared_file_before_active_store_removal(
    retention_session: AsyncSession,
    admin_user: UserInDB,
    completion_model_factory: Callable[
        [AsyncSession, str], Awaitable[CompletionModels]
    ],
    app_factory: Callable[[AsyncSession, str, UUID], Awaitable[Apps]],
    real_object_store: RealObjectStore,
    storage_kind: StorageKind,
) -> None:
    """Kills deleting a still-used File and bypassing OC's active-store cleanup."""
    session = retention_session
    model = await completion_model_factory(session, "gpt-4")
    app = await app_factory(session, "Retention content ownership", model.id)
    app.data_retention_days = 1
    shared = await _add_file(
        session,
        tenant_id=admin_user.tenant_id,
        user_id=admin_user.id,
        name="shared.txt",
    )
    old_run = await _create_app_run(session, app, days_old=2, file=shared)
    recent_run = await _create_app_run(session, app, days_old=0, file=shared)
    settings = real_object_store.settings
    provider = (
        ObjectStoreProvider.fixed(settings, real_object_store.store)
        if storage_kind is StorageKind.OBJECT_STORE
        else None
    )
    service = ObjectContentService(
        settings, sessionmanager, object_store_provider=provider
    )
    reconciler = ObjectContentReconciler(
        settings, sessionmanager, object_store_provider=provider
    )
    payload = b"One file used by two independently retained app runs"
    async with capture_content(
        _payload_source(payload),
        declared_media_type="text/plain",
        verified_media_type="text/plain",
        maximum_size_bytes=len(payload),
        spool_memory_bytes=len(payload),
        multipart_part_bytes=len(payload),
    ) as captured:
        content = await service.prepare_in_transaction(
            session,
            intent=ContentIntent(
                tenant_id=admin_user.tenant_id,
                created_by_user_id=admin_user.id,
                access_class=ContentAccessClass.PRIVATE_RESOURCE,
                idempotency_key=f"file:{shared.id}:original:0",
                producer_receipt=f"file:{shared.id}:original:0",
            ),
            content=captured,
            storage_kind=storage_kind,
        )
        session.add(
            FileContentReferences(
                file_id=shared.id,
                content_id=content.id,
                variant=FileContentVariant.ORIGINAL.value,
                ordinal=0,
            )
        )
        await session.commit()
        if storage_kind is StorageKind.OBJECT_STORE:
            await service.store_and_verify(content_id=content.id, content=captured)
    async with session.begin():
        object_key = await session.scalar(
            sa.select(ObjectStoreObjects.object_key).where(
                ObjectStoreObjects.content_id == content.id
            )
        )
    for age, references, state in (
        (timedelta(hours=1), 1, ContentState.AVAILABLE),
        (timedelta(days=2), 0, ContentState.DELETE_PENDING),
    ):
        report = await run_registered_retention(
            session, now=recent_run.created_at + age
        )
        assert report.counts["app_runs.app_runs_deleted"] == 1
        assert report.counts.get("app_runs.files_in_use", 0) == references
        assert report.counts.get("app_runs.files_deleted", 0) == 1 - references
        assert await session.get(AppRuns, old_run.id) is None
        assert (await session.get(AppRuns, recent_run.id) is not None) == bool(
            references
        )
        assert (await session.get(Files, shared.id) is not None) == bool(references)
        assert (
            await session.execute(
                sa.select(ObjectContents.reference_count, ObjectContents.state).where(
                    ObjectContents.id == content.id
                )
            )
        ).one() == (references, state.value)
        if storage_kind is StorageKind.POSTGRES_INLINE:
            assert (
                await session.scalar(
                    sa.select(InlineContentPayloads.payload).where(
                        InlineContentPayloads.content_id == content.id
                    )
                )
                == payload
            )
        else:
            assert object_key is not None
            assert (await real_object_store.store.head(object_key)).size_bytes == len(
                payload
            )
        await session.commit()
        result = await reconciler.run_once()
        if references:
            assert result.inline_deleted == result.content_processed == 0
            assert await service.read_content_bytes(
                [
                    ContentReadGrant(
                        content_id=content.id,
                        tenant_id=admin_user.tenant_id,
                        access_class=ContentAccessClass.PRIVATE_RESOURCE,
                    )
                ]
            ) == {content.id: payload}
        else:
            assert result.inline_deleted + result.content_processed == 1
            async with session.begin():
                assert (
                    await session.scalar(
                        sa.select(ObjectContents.state).where(
                            ObjectContents.id == content.id
                        )
                    )
                    == ContentState.TOMBSTONED.value
                )
                if storage_kind is StorageKind.POSTGRES_INLINE:
                    assert await session.get(InlineContentPayloads, content.id) is None
            if storage_kind is StorageKind.OBJECT_STORE:
                assert object_key is not None
                with pytest.raises(ObjectStoreNotFoundError):
                    await real_object_store.store.head(object_key)


@pytest.mark.asyncio
async def test_used_depth_two_descendant_blocks_root_deletion(
    object_content_database: DatabaseSessionManager,
) -> None:
    tenant_id, user_id = await _owner_ids(object_content_database)
    async with object_content_database.session() as session, session.begin():
        root = await _add_file(
            session,
            tenant_id=tenant_id,
            user_id=user_id,
            name="root.txt",
        )
        child = await _add_file(
            session,
            tenant_id=tenant_id,
            user_id=user_id,
            name="child.txt",
            parent_file_id=root.id,
        )
        grandchild = await _add_file(
            session,
            tenant_id=tenant_id,
            user_id=user_id,
            name="grandchild.txt",
            parent_file_id=child.id,
        )
        relation = await _add_question_file(
            session,
            tenant_id=tenant_id,
            user_id=user_id,
            file_id=grandchild.id,
        )
        root_id = root.id
        relation_key = (relation.question_id, relation.file_id)

    async with object_content_database.session() as session, session.begin():
        service = _service(
            session=session,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        preview = await service.get_deletion_preview(root_id)
        assert preview.can_delete is False
        assert preview.affected_file_count == 3
        assert [(blocker.kind, blocker.count) for blocker in preview.blockers] == [
            (FileUsageKind.CHAT_ATTACHMENT, 1)
        ]

        with pytest.raises(FileInUseError) as exc_info:
            await service.delete_file(root_id)
        assert exc_info.value.preview == preview

        # Mutant: retention checks only root usage and cascades away a used child.
        retained = await FileUsageRepository(session).delete_unused_root(
            root_id, max_rows=100, max_files=100, max_family_rows=100
        )
        assert retained.reason is FileRetentionReason.IN_USE
        assert retained.deleted_members == 0

    async with object_content_database.session() as session, session.begin():
        assert (
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(Files)
                .where(Files.id.in_([root_id, relation_key[1]]))
            )
        ) == 2
        assert await session.get(QuestionsFiles, relation_key) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "members,references,rows,files,cap,reason,spent",
    [
        (1, 0, 2, 1, 10, FileRetentionReason.INSUFFICIENT_BUDGET, 1),
        (1, 0, 3, 1, 3, FileRetentionReason.DELETED, 3),
        (2, 0, 5, 2, 10, FileRetentionReason.INSUFFICIENT_BUDGET, 2),
        (2, 0, 10, 2, 5, FileRetentionReason.FAMILY_EXCEEDS_BUDGET, 2),
        (2, 0, 6, 2, 6, FileRetentionReason.DELETED, 6),
        (1, 1, 4, 1, 10, FileRetentionReason.INSUFFICIENT_BUDGET, 3),
        (1, 1, 10, 1, 4, FileRetentionReason.FAMILY_EXCEEDS_BUDGET, 3),
        (1, 1, 5, 1, 5, FileRetentionReason.DELETED, 5),
        (2, 0, 6, 1, 10, FileRetentionReason.INSUFFICIENT_BUDGET, 2),
        (10, 0, 6, 10, 100, FileRetentionReason.INSUFFICIENT_BUDGET, 3),
    ],
)
async def test_bounded_release_admits_the_whole_family_or_keeps_every_row(
    object_content_database: DatabaseSessionManager,
    members: int,
    references: int,
    rows: int,
    files: int,
    cap: int,
    reason: FileRetentionReason,
    spent: int,
) -> None:
    """Mutants: omit child/reference cost, ignore the cap, or delete before fit."""
    tenant_id, user_id = await _owner_ids(object_content_database)
    async with object_content_database.session() as session, session.begin():
        root = await _add_file(
            session, tenant_id=tenant_id, user_id=user_id, name="bounded.txt"
        )
        file_ids = [root.id]
        for _ in range(members - 1):
            child = await _add_file(
                session,
                tenant_id=tenant_id,
                user_id=user_id,
                name="derived.txt",
                parent_file_id=root.id,
            )
            file_ids.append(child.id)
        for ordinal in range(references):
            await _add_pending_reference(
                session,
                file_id=root.id,
                tenant_id=tenant_id,
                user_id=user_id,
                variant=FileContentVariant.ORIGINAL,
                ordinal=ordinal,
            )
        root_id = root.id

    async with object_content_database.session() as session, session.begin():
        result = await FileUsageRepository(session).delete_unused_root(
            root_id, max_rows=rows, max_files=files, max_family_rows=cap
        )
        assert result.reason is reason
        assert result.rows == spent
        assert result.tenant_id == tenant_id
        deleted = reason is FileRetentionReason.DELETED
        assert result.needs_rollback is not deleted
        assert result.files == result.deleted_members == (members if deleted else 0)
        assert result.deleted_roots == int(deleted)
        assert result.deleted_references == (references if deleted else 0)

    async with object_content_database.session() as session, session.begin():
        remaining = list(
            await session.scalars(sa.select(Files.id).where(Files.id.in_(file_ids)))
        )
        assert set(remaining) == (set() if deleted else set(file_ids))
        retained_references = await session.scalar(
            sa.select(sa.func.count())
            .select_from(FileContentReferences)
            .where(FileContentReferences.file_id == root_id)
        )
        assert retained_references == (0 if deleted else references)


@pytest.mark.asyncio
@pytest.mark.parametrize("held", ["root", "child", "dependency"])
async def test_a_locked_member_keeps_the_whole_family_and_does_not_block_the_next(
    object_content_database: DatabaseSessionManager, held: str
) -> None:
    """Mutants: block on a held row, or treat a skipped member as absent."""
    tenant_id, user_id = await _owner_ids(object_content_database)
    async with object_content_database.session() as session, session.begin():
        root = await _add_file(
            session, tenant_id=tenant_id, user_id=user_id, name="held-root.txt"
        )
        child = await _add_file(
            session,
            tenant_id=tenant_id,
            user_id=user_id,
            name="held-child.txt",
            parent_file_id=root.id,
        )
        later = await _add_file(
            session, tenant_id=tenant_id, user_id=user_id, name="later.txt"
        )
        await _add_pending_reference(
            session,
            file_id=root.id,
            tenant_id=tenant_id,
            user_id=user_id,
            variant=FileContentVariant.ORIGINAL,
        )
        root_id, child_id, later_id = root.id, child.id, later.id

    async with object_content_database.session() as holder, holder.begin():
        lock = (
            sa.select(FileContentReferences).where(
                FileContentReferences.file_id == root_id
            )
            if held == "dependency"
            else sa.select(Files).where(
                Files.id == (root_id if held == "root" else child_id)
            )
        )
        await holder.execute(lock.with_for_update())
        async with object_content_database.session() as session, session.begin():
            await session.execute(sa.text("SET LOCAL lock_timeout = '200ms'"))
            usage = FileUsageRepository(session)
            blocked = await usage.delete_unused_root(
                root_id, max_rows=100, max_files=100, max_family_rows=100
            )
            assert blocked.reason is FileRetentionReason.LOCKED
            assert blocked.needs_rollback
            assert blocked.deleted_members == blocked.deleted_references == 0
            completed = await usage.delete_unused_root(
                later_id, max_rows=100, max_files=100, max_family_rows=100
            )
            assert completed.reason is FileRetentionReason.DELETED

    async with object_content_database.session() as session, session.begin():
        assert set(await session.scalars(sa.select(Files.id))) == {root_id, child_id}
        assert (
            await session.scalar(
                sa.select(sa.func.count()).select_from(FileContentReferences)
            )
            == 1
        )


@pytest.mark.asyncio
async def test_delete_first_prevents_a_late_attachment_without_losing_a_use(
    object_content_database: DatabaseSessionManager,
) -> None:
    tenant_id, user_id = await _owner_ids(object_content_database)
    async with object_content_database.session() as session, session.begin():
        root = await _add_file(
            session,
            tenant_id=tenant_id,
            user_id=user_id,
            name="root.txt",
        )
        child = await _add_file(
            session,
            tenant_id=tenant_id,
            user_id=user_id,
            name="child.txt",
            parent_file_id=root.id,
        )
        grandchild = await _add_file(
            session,
            tenant_id=tenant_id,
            user_id=user_id,
            name="grandchild.txt",
            parent_file_id=child.id,
        )
        chat_session = Sessions(user_id=user_id, name="Concurrent attachment")
        session.add(chat_session)
        await session.flush()
        question = Questions(
            question="Attach concurrently",
            answer="",
            num_tokens_question=0,
            num_tokens_answer=0,
            tenant_id=tenant_id,
            session_id=chat_session.id,
        )
        session.add(question)
        await session.flush()
        root_id = root.id
        grandchild_id = grandchild.id
        question_id = question.id

    family_locked = asyncio.Event()
    allow_delete = asyncio.Event()
    attach_started = asyncio.Event()

    async def delete_family() -> None:
        async with object_content_database.session() as session, session.begin():
            usage = FileUsageRepository(session)
            family_ids = await usage.lock_family(
                root_file_id=root_id,
                tenant_id=tenant_id,
            )
            family_locked.set()
            await allow_delete.wait()
            assert await usage.count_product_usage(family_ids) == []
            await session.execute(sa.delete(Files).where(Files.id == root_id))

    async def attach_file() -> None:
        await family_locked.wait()
        async with object_content_database.session() as session, session.begin():
            session.add(
                QuestionsFiles(
                    question_id=question_id,
                    file_id=grandchild_id,
                    type="user",
                )
            )
            attach_started.set()
            await session.flush()

    delete_task = asyncio.create_task(delete_family())
    attach_task = asyncio.create_task(attach_file())
    await attach_started.wait()
    await asyncio.sleep(0.1)
    assert attach_task.done() is False
    allow_delete.set()

    await delete_task
    with pytest.raises(IntegrityError):
        await attach_task

    async with object_content_database.session() as session, session.begin():
        assert await session.get(Files, root_id) is None
        assert await session.get(QuestionsFiles, (question_id, grandchild_id)) is None
