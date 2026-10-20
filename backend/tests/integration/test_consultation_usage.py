"""PostgreSQL contracts for persisted consultation history and model usage."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.tables.questions_table import Questions
from eneo.database.tables.sessions_table import Sessions
from eneo.questions.question import ConsultationInfo, QuestionAdd
from eneo.questions.questions_repo import QuestionRepository
from eneo.token_usage.infrastructure.question_usage import question_usage_rows


@pytest.mark.asyncio
async def test_consultation_usage_keeps_each_model_and_does_not_repeat_parent_tokens(
    async_session: AsyncSession, admin_user, test_tenant, completion_model_factory
):
    parent_model = await completion_model_factory(async_session, "gpt-4")
    child_model = await completion_model_factory(async_session, "gpt-4o-mini")
    session = Sessions(user_id=admin_user.id, name="Orchestrated group")
    async_session.add(session)
    await async_session.flush()
    child = ConsultationInfo(
        id=uuid4(),
        ordinal=1,
        assistant_id=uuid4(),
        assistant_name="IT",
        question="Check requirements",
        answer="SSO is required",
        status="complete",
        completion_model_id=child_model.id,
        input_tokens=30,
        output_tokens=7,
    )
    unexecuted = ConsultationInfo(
        id=uuid4(),
        ordinal=2,
        assistant_id=uuid4(),
        assistant_name="HR",
        question="Check",
        answer="",
        status="denied",
    )
    now = datetime.now(timezone.utc)
    repo = QuestionRepository(async_session)
    question = await repo.add(
        QuestionAdd(
            question="Parent",
            answer="Synthesis",
            tenant_id=test_tenant.id,
            session_id=session.id,
            completion_model_id=parent_model.id,
            num_tokens_question=20,
            num_tokens_answer=5,
            consultations=[child, unexecuted],
        )
    )
    legacy = await repo.add(
        QuestionAdd(
            question="Earlier turn",
            answer="Answer",
            tenant_id=test_tenant.id,
            session_id=session.id,
            completion_model_id=parent_model.id,
            num_tokens_question=10,
            num_tokens_answer=3,
        )
    )
    # Ordinary asks store SQL NULL, never a JSON scalar that the usage query
    # could mistake for a consultation array.
    assert await async_session.scalar(
        sa.select(Questions.consultations.is_(None)).where(Questions.id == legacy.id)
    )
    scope = question_usage_rows(
        test_tenant.id, now - timedelta(minutes=1), now + timedelta(minutes=1)
    )
    rows = (
        (
            await async_session.execute(
                sa.select(scope).where(scope.c.session_id == session.id)
            )
        )
        .mappings()
        .all()
    )
    assert len(rows) == 3
    assert sorted(
        (row["num_tokens_question"], row["num_tokens_answer"]) for row in rows
    ) == [(10, 3), (20, 5), (30, 7)]
    assert (
        next(row for row in rows if row["id"] == child.id)["completion_model_id"]
        == child_model.id
    )
    other_tenant = question_usage_rows(
        uuid4(), now - timedelta(minutes=1), now + timedelta(minutes=1)
    )
    assert (await async_session.execute(sa.select(other_tenant))).all() == []
    saved = await async_session.scalar(
        sa.select(Questions.consultations).where(Questions.id == question.id)
    )
    assert ConsultationInfo.model_validate(saved[0]) == child
