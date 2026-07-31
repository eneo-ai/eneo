from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from eneo.database.database import DatabaseSessionManager
from eneo.database.tables.files_table import Files
from eneo.database.tables.questions_table import Questions, QuestionsFiles
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.users_table import Users
from eneo.files.file_models import FileInUseError, FileType, FileUsageKind
from eneo.files.file_repo import FileRepository
from eneo.files.file_service import FileService
from eneo.files.file_usage import FileUsageRepository
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
