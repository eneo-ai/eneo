from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from eneo.database.database import DatabaseSessionManager
from eneo.database.tables.files_table import Files
from eneo.database.tables.flow_tables import (
    Flows,
    FlowTemplateAssets,
    FlowVersionFileReferences,
)
from eneo.database.tables.questions_table import Questions, QuestionsFiles
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.users_table import Users
from eneo.files.file_models import (
    FileFlowVersionHolder,
    FileInUseError,
    FileType,
    FileUsageKind,
)
from eneo.files.file_repo import FileRepository
from eneo.files.file_service import FileService
from eneo.files.file_usage import FileUsageRepository
from eneo.flows.infrastructure.flow_file_family_repo import (
    UPLOAD_ANCHOR_EDGES,
    FlowFileFamilyRepository,
)
from eneo.flows.infrastructure.flow_version_repo import FlowVersionRepository
from eneo.sessions.sessions_repo import SessionRepository
from eneo.users.user import UserInDB


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
        owner_type="user",
        owner_user_id=user_id,
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


async def _add_version_naming(
    session, *, tenant_id: UUID, user_id: UUID, file_id: UUID
) -> tuple[UUID, int]:
    """A published flow version whose assistant attachment is ``file_id``."""
    space = await session.scalar(sa.select(Spaces).where(Spaces.user_id == user_id))
    if space is None:
        space = Spaces(name="Version file space", tenant_id=tenant_id, user_id=user_id)
        session.add(space)
        await session.flush()
    flow = Flows(
        name=f"Version file flow {uuid4().hex}", tenant_id=tenant_id, space_id=space.id
    )
    session.add(flow)
    await session.flush()
    await FlowVersionRepository(session).create(
        flow_id=flow.id,
        version=1,
        tenant_id=tenant_id,
        definition_json={
            "schema_version": 1,
            "steps": [
                {"assistant_snapshot": {"attachments": [{"file_id": str(file_id)}]}}
            ],
        },
    )
    return flow.id, 1


@pytest.mark.asyncio
async def test_file_named_by_a_flow_version_is_in_use_not_a_foreign_key_error(
    object_content_database: DatabaseSessionManager,
) -> None:
    tenant_id, user_id = await _owner_ids(object_content_database)
    async with object_content_database.session() as session, session.begin():
        file = await _add_file(
            session, tenant_id=tenant_id, user_id=user_id, name="frozen.txt"
        )
        free = await _add_file(
            session, tenant_id=tenant_id, user_id=user_id, name="free.txt"
        )
        holder_flow_id, _ = await _add_version_naming(
            session, tenant_id=tenant_id, user_id=user_id, file_id=file.id
        )
        file_id, free_id = file.id, free.id

    async with object_content_database.session() as session, session.begin():
        service = _service(session=session, tenant_id=tenant_id, user_id=user_id)
        preview = await service.get_deletion_preview(file_id)
        assert preview.can_delete is False
        assert [(b.kind, b.count) for b in preview.blockers] == [
            (FileUsageKind.FLOW_VERSION, 1)
        ]
        assert preview.flow_versions == [
            FileFlowVersionHolder(flow_id=holder_flow_id, version=1)
        ]
        with pytest.raises(FileInUseError) as exc_info:
            await service.delete_file(file_id)
        assert exc_info.value.preview == preview
        assert "run-history purge do not release it" in str(exc_info.value)
        assert exc_info.value.details["flow_versions"] == [
            {"flow_id": str(holder_flow_id), "version": 1}
        ]
        # A file no version names stays deletable.
        assert (await service.get_deletion_preview(free_id)).can_delete is True

    async with object_content_database.session() as session, session.begin():
        assert await session.get(Files, file_id) is not None


@pytest.mark.asyncio
async def test_derived_file_named_by_a_flow_version_blocks_its_root(
    object_content_database: DatabaseSessionManager,
) -> None:
    tenant_id, user_id = await _owner_ids(object_content_database)
    async with object_content_database.session() as session, session.begin():
        root = await _add_file(
            session, tenant_id=tenant_id, user_id=user_id, name="root.txt"
        )
        child = await _add_file(
            session,
            tenant_id=tenant_id,
            user_id=user_id,
            name="child.txt",
            parent_file_id=root.id,
        )
        await _add_version_naming(
            session, tenant_id=tenant_id, user_id=user_id, file_id=child.id
        )
        root_id = root.id

    async with object_content_database.session() as session, session.begin():
        service = _service(session=session, tenant_id=tenant_id, user_id=user_id)
        with pytest.raises(FileInUseError) as exc_info:
            await service.delete_file(root_id)
        assert [b.kind for b in exc_info.value.preview.blockers] == [
            FileUsageKind.FLOW_VERSION
        ]


@pytest.mark.asyncio
async def test_flow_version_holders_are_bounded_and_the_blocker_counts_all(
    object_content_database: DatabaseSessionManager,
) -> None:
    tenant_id, user_id = await _owner_ids(object_content_database)
    async with object_content_database.session() as session, session.begin():
        file = await _add_file(
            session, tenant_id=tenant_id, user_id=user_id, name="many.txt"
        )
        flow_id, _ = await _add_version_naming(
            session, tenant_id=tenant_id, user_id=user_id, file_id=file.id
        )
        repo = FlowVersionRepository(session)
        for version in range(2, 13):
            await repo.create(
                flow_id=flow_id,
                version=version,
                tenant_id=tenant_id,
                definition_json={
                    "schema_version": 1,
                    "steps": [
                        {
                            "assistant_snapshot": {
                                "attachments": [{"file_id": str(file.id)}]
                            }
                        }
                    ],
                },
            )
        file_id = file.id

    async with object_content_database.session() as session, session.begin():
        preview = await _service(
            session=session, tenant_id=tenant_id, user_id=user_id
        ).get_deletion_preview(file_id)
        assert [(b.kind, b.count) for b in preview.blockers] == [
            (FileUsageKind.FLOW_VERSION, 12)
        ]
        assert [h.version for h in preview.flow_versions] == list(range(1, 11))
        assert {h.flow_id for h in preview.flow_versions} == {flow_id}


@pytest.mark.asyncio
async def test_file_used_as_a_flow_template_is_in_use_not_a_foreign_key_error(
    object_content_database: DatabaseSessionManager,
) -> None:
    tenant_id, user_id = await _owner_ids(object_content_database)
    async with object_content_database.session() as session, session.begin():
        file = await _add_file(
            session, tenant_id=tenant_id, user_id=user_id, name="template.docx"
        )
        space = Spaces(name="Template space", tenant_id=tenant_id, user_id=user_id)
        session.add(space)
        await session.flush()
        flow = Flows(name="Template flow", tenant_id=tenant_id, space_id=space.id)
        session.add(flow)
        await session.flush()
        session.add(
            FlowTemplateAssets(
                flow_id=flow.id,
                space_id=space.id,
                tenant_id=tenant_id,
                file_id=file.id,
                name="template.docx",
                checksum="sum",
                placeholders=[],
                status="ready",
                deleted_at=sa.func.now(),
            )
        )
        file_id = file.id

    async with object_content_database.session() as session, session.begin():
        service = _service(session=session, tenant_id=tenant_id, user_id=user_id)
        with pytest.raises(FileInUseError) as exc_info:
            await service.delete_file(file_id)
        assert [(b.kind, b.count) for b in exc_info.value.preview.blockers] == [
            (FileUsageKind.FLOW_TEMPLATE_ASSET, 1)
        ]


@pytest.mark.asyncio
async def test_a_delete_that_wins_the_race_makes_publish_skip_the_file(
    object_content_database: DatabaseSessionManager,
) -> None:
    tenant_id, user_id = await _owner_ids(object_content_database)
    definition = {
        "schema_version": 1,
        "steps": [],
    }
    async with object_content_database.session() as session, session.begin():
        file = await _add_file(
            session, tenant_id=tenant_id, user_id=user_id, name="racing.txt"
        )
        flow_id, _ = await _add_version_naming(
            session, tenant_id=tenant_id, user_id=user_id, file_id=uuid4()
        )
        file_id = file.id
    definition["steps"] = [
        {"assistant_snapshot": {"attachments": [{"file_id": str(file_id)}]}}
    ]

    file_locked = asyncio.Event()
    allow_commit = asyncio.Event()

    async def delete_file() -> None:
        async with object_content_database.session() as session, session.begin():
            await session.execute(
                sa.select(Files.id).where(Files.id == file_id).with_for_update()
            )
            file_locked.set()
            await allow_commit.wait()
            await session.execute(sa.delete(Files).where(Files.id == file_id))

    async def record() -> int:
        await file_locked.wait()
        async with object_content_database.session() as session, session.begin():
            return await FlowVersionRepository(session).record_file_references(
                flow_id=flow_id,
                version=1,
                tenant_id=tenant_id,
                definition_json=definition,
            )

    delete_task = asyncio.create_task(delete_file())
    record_task = asyncio.create_task(record())
    await file_locked.wait()
    await asyncio.sleep(0.3)
    assert record_task.done() is False
    allow_commit.set()
    await delete_task

    assert await record_task == 1
    async with object_content_database.session() as session, session.begin():
        assert (
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(FlowVersionFileReferences)
                .where(FlowVersionFileReferences.file_id == file_id)
            )
        ) == 0


def _naming(file_id: UUID) -> dict[str, object]:
    return {
        "schema_version": 1,
        "steps": [{"assistant_snapshot": {"attachments": [{"file_id": str(file_id)}]}}],
    }


@pytest.mark.asyncio
async def test_publishers_retaining_one_file_do_not_block_each_other_and_fence_delete(
    object_content_database: DatabaseSessionManager,
) -> None:
    tenant_id, user_id = await _owner_ids(object_content_database)
    async with object_content_database.session() as session, session.begin():
        file = await _add_file(
            session, tenant_id=tenant_id, user_id=user_id, name="shared.txt"
        )
        flow_a, _ = await _add_version_naming(
            session, tenant_id=tenant_id, user_id=user_id, file_id=uuid4()
        )
        flow_b, _ = await _add_version_naming(
            session, tenant_id=tenant_id, user_id=user_id, file_id=uuid4()
        )
        file_id = file.id

    a_recorded = asyncio.Event()
    release_a = asyncio.Event()

    async def publisher_a() -> None:
        async with object_content_database.session() as session, session.begin():
            await FlowVersionRepository(session).record_file_references(
                flow_id=flow_a,
                version=1,
                tenant_id=tenant_id,
                definition_json=_naming(file_id),
            )
            a_recorded.set()
            await release_a.wait()

    async def publisher_b() -> int:
        await a_recorded.wait()
        async with object_content_database.session() as session, session.begin():
            return await FlowVersionRepository(session).record_file_references(
                flow_id=flow_b,
                version=1,
                tenant_id=tenant_id,
                definition_json=_naming(file_id),
            )

    async def delete_file() -> None:
        await a_recorded.wait()
        async with object_content_database.session() as session, session.begin():
            await _service(
                session=session, tenant_id=tenant_id, user_id=user_id
            ).delete_file(file_id)

    task_a = asyncio.create_task(publisher_a())
    task_b = asyncio.create_task(publisher_b())
    task_delete = asyncio.create_task(delete_file())
    # A second publisher is not blocked by the first one's uncommitted lock.
    try:
        assert await asyncio.wait_for(task_b, timeout=10) == 0
    except BaseException:
        # Never leave the first publisher (and the delete) waiting on failure.
        release_a.set()
        raise
    # The delete started after the first publisher recorded waits for it.
    await asyncio.sleep(0.3)
    assert task_delete.done() is False
    release_a.set()
    await task_a
    with pytest.raises(FileInUseError) as exc_info:
        await task_delete
    assert {h.flow_id for h in exc_info.value.preview.flow_versions} == {
        flow_a,
        flow_b,
    }


@pytest.mark.asyncio
async def test_chat_deletion_keeps_a_generated_file_a_flow_version_names(
    object_content_database: DatabaseSessionManager,
) -> None:
    tenant_id, user_id = await _owner_ids(object_content_database)
    async with object_content_database.session() as session, session.begin():
        kept = await _add_file(
            session, tenant_id=tenant_id, user_id=user_id, name="kept.png"
        )
        unused = await _add_file(
            session, tenant_id=tenant_id, user_id=user_id, name="unused.png"
        )
        await _add_version_naming(
            session, tenant_id=tenant_id, user_id=user_id, file_id=kept.id
        )
        chat = Sessions(user_id=user_id, name="Generating chat")
        session.add(chat)
        await session.flush()
        question = Questions(
            question="Draw",
            answer="",
            num_tokens_question=0,
            num_tokens_answer=0,
            tenant_id=tenant_id,
            session_id=chat.id,
        )
        session.add(question)
        await session.flush()
        session.add_all(
            [
                QuestionsFiles(question_id=question.id, file_id=f.id, type="assistant")
                for f in (kept, unused)
            ]
        )
        chat_id, kept_id, unused_id = chat.id, kept.id, unused.id

    async with object_content_database.session() as session, session.begin():
        await SessionRepository(session).delete(chat_id)

    async with object_content_database.session() as session, session.begin():
        assert await session.get(Sessions, chat_id) is None
        assert await session.get(Files, kept_id) is not None
        assert await session.get(Files, unused_id) is None


async def _chat_with_generated_file(
    session, *, tenant_id: UUID, user_id: UUID, file_id: UUID
) -> UUID:
    chat = Sessions(user_id=user_id, name=f"Generating chat {uuid4().hex}")
    session.add(chat)
    await session.flush()
    question = Questions(
        question="Draw",
        answer="",
        num_tokens_question=0,
        num_tokens_answer=0,
        tenant_id=tenant_id,
        session_id=chat.id,
    )
    session.add(question)
    await session.flush()
    session.add(
        QuestionsFiles(question_id=question.id, file_id=file_id, type="assistant")
    )
    await session.flush()
    return chat.id


@pytest.mark.asyncio
async def test_chat_deletion_waits_for_a_publisher_and_then_keeps_the_file(
    object_content_database: DatabaseSessionManager,
) -> None:
    tenant_id, user_id = await _owner_ids(object_content_database)
    async with object_content_database.session() as session, session.begin():
        file = await _add_file(
            session, tenant_id=tenant_id, user_id=user_id, name="contested.png"
        )
        flow_id, _ = await _add_version_naming(
            session, tenant_id=tenant_id, user_id=user_id, file_id=uuid4()
        )
        chat_id = await _chat_with_generated_file(
            session, tenant_id=tenant_id, user_id=user_id, file_id=file.id
        )
        file_id = file.id

    recorded = asyncio.Event()
    commit = asyncio.Event()

    async def publisher() -> None:
        async with object_content_database.session() as session, session.begin():
            await FlowVersionRepository(session).record_file_references(
                flow_id=flow_id,
                version=1,
                tenant_id=tenant_id,
                definition_json=_naming(file_id),
            )
            recorded.set()
            await commit.wait()

    async def delete_chat() -> None:
        await recorded.wait()
        async with object_content_database.session() as session, session.begin():
            await SessionRepository(session).delete(chat_id)

    publisher_task = asyncio.create_task(publisher())
    chat_task = asyncio.create_task(delete_chat())
    await recorded.wait()
    await asyncio.sleep(0.3)
    try:
        # The cleanup waits for the publisher's lock instead of racing it.
        assert chat_task.done() is False
    finally:
        commit.set()
    await publisher_task
    await asyncio.wait_for(chat_task, timeout=20)

    async with object_content_database.session() as session, session.begin():
        assert await session.get(Sessions, chat_id) is None
        assert await session.get(Files, file_id) is not None
        assert (
            await session.scalar(
                sa.select(sa.func.count())
                .select_from(FlowVersionFileReferences)
                .where(FlowVersionFileReferences.file_id == file_id)
            )
        ) == 1


@pytest.mark.asyncio
async def test_a_publisher_after_chat_deletion_skips_the_deleted_generated_file(
    object_content_database: DatabaseSessionManager,
) -> None:
    tenant_id, user_id = await _owner_ids(object_content_database)
    async with object_content_database.session() as session, session.begin():
        file = await _add_file(
            session, tenant_id=tenant_id, user_id=user_id, name="doomed.png"
        )
        flow_id, _ = await _add_version_naming(
            session, tenant_id=tenant_id, user_id=user_id, file_id=uuid4()
        )
        chat_id = await _chat_with_generated_file(
            session, tenant_id=tenant_id, user_id=user_id, file_id=file.id
        )
        file_id = file.id

    deleted = asyncio.Event()
    commit = asyncio.Event()

    async def delete_chat() -> None:
        async with object_content_database.session() as session, session.begin():
            await SessionRepository(session).delete(chat_id)
            deleted.set()
            await commit.wait()

    async def publisher() -> int:
        await deleted.wait()
        async with object_content_database.session() as session, session.begin():
            return await FlowVersionRepository(session).record_file_references(
                flow_id=flow_id,
                version=1,
                tenant_id=tenant_id,
                definition_json=_naming(file_id),
            )

    chat_task = asyncio.create_task(delete_chat())
    publisher_task = asyncio.create_task(publisher())
    await deleted.wait()
    await asyncio.sleep(0.3)
    try:
        assert publisher_task.done() is False
    finally:
        commit.set()
    await chat_task
    assert await asyncio.wait_for(publisher_task, timeout=20) == 1
    async with object_content_database.session() as session, session.begin():
        assert await session.get(Files, file_id) is None


@pytest.mark.asyncio
async def test_run_history_deletion_skips_a_file_a_publisher_holds_and_then_keeps_it(
    object_content_database: DatabaseSessionManager,
) -> None:
    tenant_id, user_id = await _owner_ids(object_content_database)
    async with object_content_database.session() as session, session.begin():
        file = await _add_file(
            session, tenant_id=tenant_id, user_id=user_id, name="purge-candidate.txt"
        )
        flow_id, _ = await _add_version_naming(
            session, tenant_id=tenant_id, user_id=user_id, file_id=uuid4()
        )
        file_id = file.id

    recorded = asyncio.Event()
    commit = asyncio.Event()

    async def publisher() -> None:
        async with object_content_database.session() as session, session.begin():
            await FlowVersionRepository(session).record_file_references(
                flow_id=flow_id,
                version=1,
                tenant_id=tenant_id,
                definition_json=_naming(file_id),
            )
            recorded.set()
            await commit.wait()

    async def purge_families() -> tuple[bool, bool]:
        """(skipped while the publisher holds the file, owned once it commits)."""
        await asyncio.wait_for(recorded.wait(), timeout=20)
        async with object_content_database.session() as session, session.begin():
            families = FlowFileFamilyRepository(session)
            skipped = (await families.lock_members(file_id, limit=1)).items is None
        checked.set()
        await asyncio.wait_for(publisher_done.wait(), timeout=20)
        async with object_content_database.session() as session, session.begin():
            families = FlowFileFamilyRepository(session)
            members = (await families.lock_members(file_id, limit=1)).items
            assert members is not None
            owned = (
                await families.outside_owner(
                    file_id, members, root_anchor_edges=UPLOAD_ANCHOR_EDGES
                )
                is not None
            )
        return skipped, owned

    publisher_done = asyncio.Event()
    checked = asyncio.Event()

    async def publish_and_signal() -> None:
        await publisher()
        publisher_done.set()

    publisher_task = asyncio.create_task(publish_and_signal())
    purge_task = asyncio.create_task(purge_families())
    try:
        await asyncio.wait_for(checked.wait(), timeout=20)
    finally:
        commit.set()
        _, purge_result = await asyncio.wait_for(
            asyncio.gather(publisher_task, purge_task), timeout=20
        )
    assert purge_result == (True, True)
    async with object_content_database.session() as session, session.begin():
        assert await session.get(Files, file_id) is not None
