"""Empty sessions are their own retention task and cannot starve chat history;
conversation history removes the session its last question leaves empty."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.application.empty_session_retention_task import (
    EMPTY_SESSIONS_TASK,
    EmptySessionRetentionTask,
)
from eneo.data_retention.application.retention_runner import RetentionBatch
from eneo.database.database import sessionmanager
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.help_assistant_runs_table import HelpAssistantRuns
from eneo.database.tables.questions_table import Questions
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.spaces_table import Spaces
from eneo.main.config import get_settings
from tests.integration.data_retention.retention_support import run_registered_retention

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def _space(session: AsyncSession, *, tenant_id: UUID, user_id: UUID) -> Spaces:
    space = Spaces(
        name=f"Empty session space {user_id}",
        tenant_id=tenant_id,
        user_id=user_id,
        tenant_space_id=None,
    )
    session.add(space)
    await session.flush()
    return space


async def _assistant(
    session: AsyncSession, completion_model_factory, *, tenant_id: UUID, user_id: UUID
) -> Assistants:
    space = await _space(session, tenant_id=tenant_id, user_id=user_id)
    model = await completion_model_factory(session, "gpt-4")
    assistant = Assistants(
        name="Empty session assistant",
        user_id=user_id,
        space_id=space.id,
        completion_model_id=model.id,
        completion_model_kwargs={},
        logging_enabled=True,
        is_default=False,
        published=False,
        data_retention_days=30,
    )
    session.add(assistant)
    await session.flush()
    return assistant


async def _session(
    session: AsyncSession, *, user_id: UUID, created_at: datetime
) -> Sessions:
    row = Sessions(
        user_id=user_id, name="Session", created_at=created_at, updated_at=created_at
    )
    session.add(row)
    await session.flush()
    return row


async def _question(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    session_id: UUID,
    assistant_id: UUID | None,
    created_at: datetime,
) -> Questions:
    question = Questions(
        question="Question",
        answer="Answer",
        num_tokens_question=1,
        num_tokens_answer=1,
        tenant_id=tenant_id,
        assistant_id=assistant_id,
        session_id=session_id,
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(question)
    await session.flush()
    return question


async def test_an_empty_session_past_its_grace_is_deleted_and_counted(
    retention_session: AsyncSession, test_tenant, admin_user
):
    """Mutants: the sessions step reports exhausted without deleting; the
    no-question guard is dropped, so a session with history is deleted too."""
    old = datetime.now(timezone.utc) - timedelta(days=3)
    empty = await _session(retention_session, user_id=admin_user.id, created_at=old)
    used = await _session(retention_session, user_id=admin_user.id, created_at=old)
    await _question(
        retention_session,
        tenant_id=test_tenant.id,
        session_id=used.id,
        assistant_id=None,
        created_at=old,
    )
    empty_id, used_id = empty.id, used.id

    report = await run_registered_retention(
        retention_session, task_name=EMPTY_SESSIONS_TASK
    )

    assert report.counts == {
        "sessions.sessions_deleted": 1,
        "sessions.sessions_examined": 2,
    }
    assert await retention_session.get(Sessions, empty_id) is None
    assert await retention_session.get(Sessions, used_id) is not None


async def test_a_help_assistant_session_is_charged_its_helper_row(
    retention_session: AsyncSession, test_tenant, admin_user
):
    """Mutant: the UNIQUE helper row the cascade removes is not charged."""
    old = datetime.now(timezone.utc) - timedelta(days=3)
    space = await _space(
        retention_session, tenant_id=test_tenant.id, user_id=admin_user.id
    )
    helped = await _session(retention_session, user_id=admin_user.id, created_at=old)
    retention_session.add(
        HelpAssistantRuns(
            tenant_id=test_tenant.id,
            org_space_id=space.id,
            kind="help",
            target_type="assistant",
            target_id=uuid4(),
            session_id=helped.id,
        )
    )
    await retention_session.flush()
    helped_id = helped.id
    (step,) = EmptySessionRetentionTask(
        retention_session, now=datetime.now(timezone.utc), grace=timedelta(days=1)
    ).steps()

    result = await step.run(
        RetentionBatch(
            job_run_id=uuid4(), batch_seq=1, rows=8, files=0, deadline=math.inf
        )
    )

    # Discovery 1, the lock 1, then the session and its helper row.
    assert result.rows == 1 + 1 + 2
    assert result.exhausted
    assert await retention_session.get(Sessions, helped_id) is None


async def test_empty_sessions_do_not_starve_due_history(
    retention_session: AsyncSession, test_tenant, admin_user, completion_model_factory
):
    """Mutant: the empty-session scan runs inside the conversation task again; on
    its first-place date it spends a small budget before any question is due."""
    real_now = datetime.now(timezone.utc)
    # The date on which a three-step rotation (questions, app runs, sessions)
    # would put the session scan first.
    now = next(
        real_now + timedelta(days=offset)
        for offset in range(3)
        if (real_now + timedelta(days=offset)).date().toordinal() % 3 == 2
    )
    assistant = await _assistant(
        retention_session,
        completion_model_factory,
        tenant_id=test_tenant.id,
        user_id=admin_user.id,
    )
    for _ in range(20):
        kept = await _session(
            retention_session, user_id=admin_user.id, created_at=now - timedelta(days=5)
        )
        await _question(
            retention_session,
            tenant_id=test_tenant.id,
            session_id=kept.id,
            assistant_id=assistant.id,
            created_at=now - timedelta(days=5),
        )
    due_session = await _session(
        retention_session, user_id=admin_user.id, created_at=now - timedelta(days=60)
    )
    due = await _question(
        retention_session,
        tenant_id=test_tenant.id,
        session_id=due_session.id,
        assistant_id=assistant.id,
        created_at=now - timedelta(days=60),
    )
    due_id = due.id
    unit_rows = 4
    settings = get_settings().model_copy(
        update={
            "retention_conversations_max_unit_rows": unit_rows,
            "retention_conversations_max_rows_per_run": unit_rows + 3,
        }
    )

    report = await run_registered_retention(
        retention_session, settings=settings, now=now
    )

    assert report.counts.get("questions.questions_deleted") == 1, report
    assert await retention_session.get(Questions, due_id) is None


async def test_history_deletes_the_session_its_last_question_leaves_empty(
    retention_session: AsyncSession, test_tenant, admin_user, completion_model_factory
):
    """Mutants: the conversation unit leaves the emptied session to the sweep (or
    does not count it); the no-question predicate is dropped, so a session with
    a newer question goes too."""
    now = datetime.now(timezone.utc)
    assistant = await _assistant(
        retention_session,
        completion_model_factory,
        tenant_id=test_tenant.id,
        user_id=admin_user.id,
    )
    emptied = await _session(
        retention_session, user_id=admin_user.id, created_at=now - timedelta(days=60)
    )
    continued = await _session(
        retention_session, user_id=admin_user.id, created_at=now - timedelta(days=60)
    )
    for session_id, age in ((emptied.id, 60), (continued.id, 60), (continued.id, 1)):
        await _question(
            retention_session,
            tenant_id=test_tenant.id,
            session_id=session_id,
            assistant_id=assistant.id,
            created_at=now - timedelta(days=age),
        )
    emptied_id, continued_id = emptied.id, continued.id

    report = await run_registered_retention(retention_session)

    assert report.counts["questions.questions_deleted"] == 2
    assert report.counts["questions.sessions_deleted"] == 1
    assert await retention_session.get(Sessions, emptied_id) is None
    assert await retention_session.get(Sessions, continued_id) is not None


async def test_history_leaves_a_held_session_to_the_sweep(
    retention_session: AsyncSession, test_tenant, admin_user, completion_model_factory
):
    """Mutant: the session lock waits (or fails the unit) instead of skipping, so
    a live chat holding its session blocks the question's deletion."""
    old = datetime.now(timezone.utc) - timedelta(days=60)
    assistant = await _assistant(
        retention_session,
        completion_model_factory,
        tenant_id=test_tenant.id,
        user_id=admin_user.id,
    )
    held = await _session(retention_session, user_id=admin_user.id, created_at=old)
    question = await _question(
        retention_session,
        tenant_id=test_tenant.id,
        session_id=held.id,
        assistant_id=assistant.id,
        created_at=old,
    )
    held_id, question_id = held.id, question.id
    await retention_session.commit()

    async with sessionmanager.session() as chat, chat.begin():
        await chat.execute(
            sa.select(Sessions.id).where(Sessions.id == held_id).with_for_update()
        )
        report = await run_registered_retention(retention_session)

    assert report.counts["questions.questions_deleted"] == 1
    assert "questions.sessions_deleted" not in report.counts
    assert await retention_session.get(Questions, question_id) is None
    assert await retention_session.get(Sessions, held_id) is not None
