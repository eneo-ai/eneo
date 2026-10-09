"""Widget conversations have one retention owner: the widget retention job."""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import sqlalchemy as sa

from eneo.data_retention.infrastructure.data_retention_service import (
    DataRetentionService,
)
from eneo.database.database import sessionmanager
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.questions_table import Questions
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users
from eneo.database.tables.widgets_table import Widgets
from eneo.widgets.application.widget_retention import purge_expired_widget_sessions
from eneo.widgets.domain.widget import generate_public_id
from eneo.widgets.infrastructure.widget_repo_impl import WidgetRepoImpl


def _days_ago(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


async def _conversation(
    session,
    *,
    assistant_id: UUID,
    tenant_id: UUID,
    days_old: int,
    widget_id: UUID | None = None,
    user_id: UUID | None = None,
    with_question: bool = True,
) -> UUID:
    session_id = uuid4()
    await session.execute(
        sa.insert(Sessions).values(
            id=session_id,
            widget_id=widget_id,
            visitor_id=uuid4() if widget_id else None,
            user_id=user_id,
            name="Conversation",
            assistant_id=assistant_id,
            created_at=_days_ago(days_old),
        )
    )
    if with_question:
        await session.execute(
            sa.insert(Questions).values(
                session_id=session_id,
                tenant_id=tenant_id,
                assistant_id=assistant_id,
                question="Question",
                answer="Answer",
                num_tokens_question=1,
                num_tokens_answer=1,
                created_at=_days_ago(days_old),
            )
        )
    return session_id


async def _existing(session_ids: list[UUID]) -> set[UUID]:
    async with sessionmanager.session() as session, session.begin():
        rows = await session.scalars(
            sa.select(Sessions.id).where(Sessions.id.in_(session_ids))
        )
        return set(rows)


async def _question_sessions(session_ids: list[UUID]) -> set[UUID]:
    async with sessionmanager.session() as session, session.begin():
        rows = await session.scalars(
            sa.select(Questions.session_id).where(Questions.session_id.in_(session_ids))
        )
        return set(rows)


async def test_only_the_widget_job_deletes_widget_conversations_within_the_policy(
    active_widget,
):
    widget_id = UUID(active_widget["id"])
    assistant_id = UUID(active_widget["target_id"])
    async with sessionmanager.session() as session, session.begin():
        widget = await WidgetRepoImpl(session).get(widget_id)
        assert widget is not None
        tenant_id = widget.tenant_id
        user_id = await session.scalar(
            sa.select(Users.id).where(Users.email == "test@example.com")
        )
        # The assistant's own schedule would delete anything a day old.
        await session.execute(
            sa.update(Assistants)
            .where(Assistants.id == assistant_id)
            .values(data_retention_days=1)
        )
        # Tightened after both widgets were saved with values outside it.
        await session.execute(
            sa.update(Tenants)
            .where(Tenants.id == tenant_id)
            .values(widget_policy={"min_retention_days": 20, "max_retention_days": 60})
        )
        other = widget.model_copy(deep=True)
        other.public_id = generate_public_id()
        other = await WidgetRepoImpl(session).add(other)
        assert other.id is not None
        for owner, retention_days in [(widget_id, 5), (other.id, 365)]:
            await session.execute(
                sa.update(Widgets)
                .where(Widgets.id == owner)
                .values(privacy={"retention_days": retention_days})
            )

        internal = await _conversation(
            session,
            assistant_id=assistant_id,
            tenant_id=tenant_id,
            user_id=user_id,
            days_old=10,
        )
        # Past its own 5 days, inside the policy minimum of 20.
        within_minimum = await _conversation(
            session,
            assistant_id=assistant_id,
            tenant_id=tenant_id,
            widget_id=widget_id,
            days_old=10,
        )
        past_minimum = await _conversation(
            session,
            assistant_id=assistant_id,
            tenant_id=tenant_id,
            widget_id=widget_id,
            days_old=25,
        )
        # Inside its own 365 days, past the policy maximum of 60.
        past_maximum = await _conversation(
            session,
            assistant_id=assistant_id,
            tenant_id=tenant_id,
            widget_id=other.id,
            days_old=70,
        )
        without_questions = await _conversation(
            session,
            assistant_id=assistant_id,
            tenant_id=tenant_id,
            widget_id=widget_id,
            days_old=3,
            with_question=False,
        )
    widget_conversations = [within_minimum, past_minimum, past_maximum]
    everything = [internal, *widget_conversations, without_questions]

    async with sessionmanager.session() as session, session.begin():
        retention = DataRetentionService(session)
        assert (
            await retention.get_affected_questions_count_for_assistant(assistant_id, 1)
            == 1
        )
        assert await retention.delete_old_questions() == 1
        await retention.delete_old_sessions()

    assert await _question_sessions(everything) == set(widget_conversations)
    assert await _existing(everything) == {*widget_conversations, without_questions}

    result = await purge_expired_widget_sessions()
    assert result["errors"] == 0
    assert await _existing(everything) == {within_minimum, without_questions}
    assert await _question_sessions(everything) == {within_minimum}
