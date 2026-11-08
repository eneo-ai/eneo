"""The derived copies task removes what is left of a copy whose source went.

The copy is unreadable from the removal on (see test_derived_copy_reads); this
task then deletes every question of the copy with its Files, the session with
its last question, and finally the copy's edges.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.application.derived_copy_retention_task import (
    COPY_IN_FLIGHT_MARGIN,
    DERIVED_COPIES_TASK,
)
from eneo.data_retention.derivations import register_derivations
from eneo.database.database import sessionmanager
from eneo.database.tables.files_table import Files
from eneo.database.tables.questions_table import Questions
from eneo.database.tables.retention_tables import ContentDerivations
from eneo.database.tables.sessions_table import Sessions
from eneo.main.config import get_settings
from eneo.questions.question import QuestionAdd
from eneo.users.user import UserInDB
from tests.integration.data_retention.copy_support import (
    Copy,
    conversation,
    make_copy,
    remove_by_user,
)
from tests.integration.data_retention.retention_support import (
    run_registered_retention,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def owner_token(db_container, patch_auth_service_jwt, admin_user) -> str:
    async with db_container() as container:
        return container.auth_service().create_access_token_for_user(admin_user)


@pytest.fixture
async def copy(client: AsyncClient, db_container, admin_user, owner_token) -> Copy:
    return await make_copy(client, db_container, admin_user, owner_token)


async def _run(session: AsyncSession, **kwargs):
    return await run_registered_retention(
        session, task_name=DERIVED_COPIES_TASK, **kwargs
    )


async def _edges(session: AsyncSession, copy_session: UUID) -> int:
    return (
        await session.scalar(
            sa.select(sa.func.count()).where(
                ContentDerivations.copy_session_id == copy_session
            )
        )
        or 0
    )


async def _add_turn(
    db_container, owner: UserInDB, copy_session: UUID, **values
) -> UUID:
    async with db_container() as container:
        image = values.pop("image", None)
        files = (
            [
                await container.file_service().save_image_from_bytes(
                    b"\x89PNG" + b"copied image" * 8,
                    name="copied.png",
                    mimetype="image/png",
                )
            ]
            if image
            else None
        )
        added = await container.question_repo().add(
            QuestionAdd(
                question="copied question",
                answer="copied answer",
                num_tokens_question=1,
                num_tokens_answer=1,
                tenant_id=owner.tenant_id,
                session_id=copy_session,
                **values,
            ),
            files=files,
        )
    return added.id


async def test_a_copy_whose_sources_exist_is_kept(
    copy: Copy, retention_session: AsyncSession
):
    """Mutant: discovery treats every copy as invalid, whatever its sources
    (the fresh check would keep it, but each run would lock and retry it)."""
    report = await _run(retention_session)

    assert report.counts.get("copies.questions_deleted", 0) == 0
    assert report.blocked == {}
    assert report.counts["copies.edges_examined"] == 1
    assert await retention_session.get(Sessions, copy.copy_session) is not None
    assert await _edges(retention_session, copy.copy_session) == 1


async def test_an_invalid_copy_goes_with_its_files_session_and_edges(
    client: AsyncClient,
    db_container,
    admin_user,
    owner_token: str,
    copy: Copy,
    retention_session: AsyncSession,
):
    """Mutants: discovery joins an owner and misses a question without one; the
    unit keeps the copy's Files or its emptied session; the edges of a removed
    copy stay; the copy of a source that still exists goes too."""
    ownerless = await _add_turn(db_container, admin_user, copy.copy_session)
    with_file = await _add_turn(
        db_container,
        admin_user,
        copy.copy_session,
        assistant_id=copy.copy_assistant,
        image=True,
    )
    files_before = await retention_session.scalar(sa.select(sa.func.count(Files.id)))
    other_session, _ = await conversation(
        db_container, admin_user, assistant_id=copy.copy_assistant, turns=1
    )
    await register_derivations(
        tenant_id=admin_user.tenant_id,
        copy_session_id=other_session,
        source_question_ids=[copy.copy_questions[0]],
    )
    await remove_by_user(client, owner_token, copy, retention_session)

    report = await _run(retention_session)

    assert report.counts["copies.questions_deleted"] == 4
    assert report.counts["copies.sessions_deleted"] == 1
    assert report.counts["copies.files_deleted"] == 1
    assert report.counts["edges.edges_deleted"] == 1
    for question in (*copy.copy_questions, ownerless, with_file):
        assert await retention_session.get(Questions, question) is None
    assert await retention_session.get(Sessions, copy.copy_session) is None
    assert (
        await retention_session.scalar(sa.select(sa.func.count(Files.id)))
        == (files_before or 0) - 1
    )
    assert await _edges(retention_session, copy.copy_session) == 0
    # A copy of the removed copy's first question is invalid now as well, and
    # goes on the next sweep: it was examined before that question went.
    assert await retention_session.get(Sessions, other_session) is not None
    second = await _run(retention_session)
    assert second.counts["copies.sessions_deleted"] == 1
    assert await retention_session.get(Sessions, other_session) is None


async def test_an_invalid_copy_left_empty_is_released_after_the_margin(
    client: AsyncClient,
    db_container,
    admin_user,
    owner_token: str,
    copy: Copy,
    retention_session: AsyncSession,
):
    """Mutants: an empty invalid copy is released while a producer may still
    be writing it, never released, or its edges outlive it."""
    async with db_container() as container:
        empty = (
            await container.session_service().create_session(
                name="empty copy", assistant_id=copy.copy_assistant
            )
        ).id
    await register_derivations(
        tenant_id=admin_user.tenant_id,
        copy_session_id=empty,
        source_question_ids=[copy.source_question],
    )
    await remove_by_user(client, owner_token, copy, retention_session)
    now = datetime.now(timezone.utc)

    await _run(retention_session, now=now)
    assert await retention_session.get(Sessions, empty) is not None

    later = now + COPY_IN_FLIGHT_MARGIN + timedelta(hours=1)
    released = await _run(retention_session, now=later)
    assert released.counts["edges.sessions_deleted"] == 1
    assert await retention_session.get(Sessions, empty) is None
    assert await _edges(retention_session, empty) == 1

    cleaned = await _run(retention_session, now=later)
    assert cleaned.counts["edges.edges_deleted"] == 1
    assert await _edges(retention_session, empty) == 0


async def test_a_source_removed_behind_the_cursor_is_found_on_the_next_sweep(
    client: AsyncClient,
    db_container,
    admin_user,
    owner_token: str,
    copy: Copy,
    retention_session: AsyncSession,
):
    """Mutants: the cursor does not advance past valid copies, so a pass never
    ends; an ended pass is not started again, so a copy invalidated behind the
    cursor is never removed."""
    second, _ = await conversation(
        db_container, admin_user, assistant_id=copy.copy_assistant, turns=1
    )
    await register_derivations(
        tenant_id=admin_user.tenant_id,
        copy_session_id=second,
        source_question_ids=[copy.source_question],
    )
    first, later = sorted((copy.copy_session, second))
    # One discovery row and one unit per execution: each one examines one edge.
    unit_rows = 4
    tiny = get_settings().model_copy(
        update={
            "retention_conversations_max_unit_rows": unit_rows,
            "retention_conversations_max_rows_per_run": unit_rows + 2,
        }
    )

    started = await _run(retention_session, settings=tiny)
    assert started.counts["copies.edges_examined"] == 1
    await remove_by_user(client, owner_token, copy, retention_session)
    # The pass continues after the first copy, removes the later one and ends.
    await _run(retention_session, settings=tiny)
    await _run(retention_session)
    assert await retention_session.get(Sessions, first) is not None
    assert await retention_session.get(Sessions, later) is None

    swept = await _run(retention_session)

    assert swept.counts["copies.sessions_deleted"] == 1
    assert await retention_session.get(Sessions, first) is None


async def test_registration_and_removal_wait_on_no_lock_of_the_other(
    db_container, admin_user, copy: Copy, retention_session: AsyncSession
):
    """Mutants: a registration waits for the task's question locks; the task
    waits for, or deadlocks with, a registration holding the copy session."""
    _, [another_source] = await conversation(
        db_container, admin_user, assistant_id=copy.source_assistant, turns=1
    )
    # The task holds the copy's questions; a registration locks no question.
    async with sessionmanager.session() as task, task.begin():
        await task.execute(
            sa.select(Questions.id)
            .where(Questions.session_id == copy.copy_session)
            .with_for_update()
        )
        await asyncio.wait_for(
            register_derivations(
                tenant_id=admin_user.tenant_id,
                copy_session_id=copy.copy_session,
                source_question_ids=[another_source],
            ),
            timeout=10,
        )
    assert await _edges(retention_session, copy.copy_session) == 2

    await retention_session.execute(
        sa.delete(Questions).where(Questions.id == copy.source_question)
    )
    await retention_session.commit()
    # A registration holds the copy session; the task skips its release.
    async with sessionmanager.session() as registration, registration.begin():
        await registration.execute(
            sa.select(Sessions.id)
            .where(Sessions.id == copy.copy_session)
            .with_for_update(key_share=True)
        )
        report = await asyncio.wait_for(_run(retention_session), timeout=60)
    assert report.counts["copies.questions_deleted"] == 2
    assert report.counts.get("copies.sessions_deleted", 0) == 0
    assert await retention_session.get(Sessions, copy.copy_session) is not None
