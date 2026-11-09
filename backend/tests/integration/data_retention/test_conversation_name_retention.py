"""A conversation's name and feedback text are removed on their own time.

A name is the first question, a title made from the turns or one the user set,
and feedback text can quote the turns. Each keeps the time it was last
written; once that time is older than the conversation's period, conversation
history replaces the name with an empty one and removes the feedback text,
whether or not the conversation's questions are still there.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.database import sessionmanager
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.audit_log_table import AuditLog
from eneo.database.tables.group_chats_table import (
    GroupChatsAssistantsMapping,
    GroupChatsTable,
)
from eneo.database.tables.questions_table import Questions
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.widgets_table import Widgets
from eneo.sessions.session import SessionFeedback, SessionUpdate
from eneo.sessions.sessions_repo import SessionRepository
from eneo.widgets.domain.widget import generate_public_id
from tests.integration.data_retention.retention_support import run_registered_retention

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

STEP = "names_and_feedback"


def _ago(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


async def _space(
    session: AsyncSession, *, tenant_id: UUID, days: int | None = None
) -> Spaces:
    # A shared space under the organisation's: a user has one personal space.
    organisation_space = await session.scalar(
        sa.select(Spaces.id).where(
            Spaces.tenant_id == tenant_id,
            Spaces.user_id.is_(None),
            Spaces.tenant_space_id.is_(None),
        )
    )
    space = Spaces(
        name=f"Name retention space {uuid4()}",
        tenant_id=tenant_id,
        user_id=None,
        tenant_space_id=organisation_space,
        data_retention_days=days,
    )
    session.add(space)
    await session.flush()
    return space


async def _assistant(
    session: AsyncSession,
    model_id: UUID,
    *,
    space: Spaces,
    user_id: UUID,
    days: int | None,
) -> Assistants:
    assistant = Assistants(
        name=f"Name retention assistant {uuid4()}",
        user_id=user_id,
        space_id=space.id,
        completion_model_id=model_id,
        completion_model_kwargs={},
        logging_enabled=True,
        is_default=False,
        published=True,
        data_retention_days=days,
    )
    session.add(assistant)
    await session.flush()
    return assistant


async def _conversation(
    session: AsyncSession,
    *,
    user_id: UUID | None,
    created_days_ago: int,
    named_days_ago: int,
    feedback_days_ago: int | None = None,
    assistant_id: UUID | None = None,
    group_chat_id: UUID | None = None,
    widget_id: UUID | None = None,
) -> tuple[UUID, str, str]:
    name = f"Name {uuid4()}"
    feedback = f"Feedback {uuid4()}"
    created_at = _ago(created_days_ago)
    row = Sessions(
        user_id=user_id,
        widget_id=widget_id,
        visitor_id=uuid4() if widget_id is not None else None,
        assistant_id=assistant_id,
        group_chat_id=group_chat_id,
        name=name,
        name_set_at=_ago(named_days_ago),
        feedback_value=1,
        feedback_text=feedback,
        feedback_set_at=_ago(
            created_days_ago if feedback_days_ago is None else feedback_days_ago
        ),
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(row)
    await session.flush()
    return row.id, name, feedback


async def _texts(
    session: AsyncSession, identifier: UUID
) -> tuple[str, int | None, str | None]:
    row = (
        await session.execute(
            sa.select(
                Sessions.name, Sessions.feedback_value, Sessions.feedback_text
            ).where(Sessions.id == identifier)
        )
    ).one()
    return row.name, row.feedback_value, row.feedback_text


async def _audit_text(session: AsyncSession) -> str:
    rows = (await session.scalars(sa.select(AuditLog))).all()
    return "\n".join(f"{row.description} {row.log_metadata}" for row in rows)


async def test_a_name_and_feedback_text_go_when_their_own_time_has_passed(
    retention_session: AsyncSession, test_tenant, admin_user, completion_model_factory
):
    """Mutants: the step compares the conversation's creation instead of the
    name's own time, so a name set later goes early; a name or feedback text is
    kept past its time; the feedback vote goes with the text; the audit event
    carries the removed name."""
    model_id = (await completion_model_factory(retention_session, "gpt-4")).id
    space = await _space(retention_session, tenant_id=test_tenant.id)
    assistant = await _assistant(
        retention_session,
        model_id,
        space=space,
        user_id=admin_user.id,
        days=30,
    )
    # A model's title written when the conversation began, past its time.
    titled, title, old_feedback = await _conversation(
        retention_session,
        user_id=admin_user.id,
        assistant_id=assistant.id,
        created_days_ago=60,
        named_days_ago=59,
    )
    # A name the user set later, still inside its time; feedback past its time.
    renamed, own_name, renamed_feedback = await _conversation(
        retention_session,
        user_id=admin_user.id,
        assistant_id=assistant.id,
        created_days_ago=60,
        named_days_ago=29,
        feedback_days_ago=31,
    )
    # A title and feedback just inside their time.
    recent, recent_title, recent_feedback = await _conversation(
        retention_session,
        user_id=admin_user.id,
        assistant_id=assistant.id,
        created_days_ago=29,
        named_days_ago=29,
    )

    report = await run_registered_retention(retention_session)

    assert await _texts(retention_session, titled) == ("", 1, None)
    assert await _texts(retention_session, renamed) == (own_name, 1, None)
    assert await _texts(retention_session, recent) == (
        recent_title,
        1,
        recent_feedback,
    )
    assert report.counts[f"{STEP}.names_cleared"] == 1
    assert report.counts[f"{STEP}.feedback_texts_cleared"] == 2
    audited = await _audit_text(retention_session)
    for removed in (title, old_feedback, renamed_feedback):
        assert removed not in audited


async def test_a_conversation_with_both_texts_due_is_written_once(
    retention_session: AsyncSession, test_tenant, admin_user, completion_model_factory
):
    """The step charges one write for each conversation it writes, so a
    conversation whose name and feedback text are both due is written once.
    Mutant: one statement per text writes the row twice for one charge."""
    model_id = (await completion_model_factory(retention_session, "gpt-4")).id
    space = await _space(retention_session, tenant_id=test_tenant.id)
    assistant = await _assistant(
        retention_session,
        model_id,
        space=space,
        user_id=admin_user.id,
        days=30,
    )
    both, _, _ = await _conversation(
        retention_session,
        user_id=admin_user.id,
        assistant_id=assistant.id,
        created_days_ago=60,
        named_days_ago=60,
    )
    await retention_session.commit()
    await retention_session.begin()
    session_writes: list[int] = []

    def count_session_writes(
        conn, cursor, statement: str, parameters, context, executemany
    ) -> None:
        if "UPDATE sessions SET" in statement:
            session_writes.append(cursor.rowcount)

    engine = retention_session.bind.sync_engine
    sa.event.listen(engine, "after_cursor_execute", count_session_writes)
    try:
        report = await run_registered_retention(retention_session)
    finally:
        sa.event.remove(engine, "after_cursor_execute", count_session_writes)

    assert await _texts(retention_session, both) == ("", 1, None)
    assert report.counts[f"{STEP}.names_cleared"] == 1
    assert report.counts[f"{STEP}.feedback_texts_cleared"] == 1
    assert session_writes == [1]


async def test_a_name_outside_any_period_or_in_a_widget_stays(
    retention_session: AsyncSession, test_tenant, admin_user, completion_model_factory
):
    """Mutants: a conversation without a chosen period loses its name; a widget
    conversation, which widget retention owns, loses its name here."""
    model_id = (await completion_model_factory(retention_session, "gpt-4")).id
    unchosen_space = await _space(retention_session, tenant_id=test_tenant.id)
    unchosen = await _assistant(
        retention_session,
        model_id,
        space=unchosen_space,
        user_id=admin_user.id,
        days=None,
    )
    kept, kept_name, kept_feedback = await _conversation(
        retention_session,
        user_id=admin_user.id,
        assistant_id=unchosen.id,
        created_days_ago=400,
        named_days_ago=400,
    )
    widget_space = await _space(retention_session, tenant_id=test_tenant.id)
    widget_assistant = await _assistant(
        retention_session,
        model_id,
        space=widget_space,
        user_id=admin_user.id,
        days=1,
    )
    widget = Widgets(
        public_id=generate_public_id(),
        tenant_id=test_tenant.id,
        space_id=widget_space.id,
        target_type="assistant",
        target_id=widget_assistant.id,
        name="Widget",
        privacy={"retention_days": 365},
    )
    retention_session.add(widget)
    await retention_session.flush()
    in_widget, widget_name, widget_feedback = await _conversation(
        retention_session,
        user_id=None,
        widget_id=widget.id,
        assistant_id=widget_assistant.id,
        created_days_ago=30,
        named_days_ago=30,
    )

    await run_registered_retention(retention_session)

    assert await _texts(retention_session, kept) == (kept_name, 1, kept_feedback)
    assert await _texts(retention_session, in_widget) == (
        widget_name,
        1,
        widget_feedback,
    )


async def test_a_group_chat_name_follows_its_shortest_assistant_period(
    retention_session: AsyncSession, test_tenant, admin_user, completion_model_factory
):
    """Mutant: a group chat's name follows its space, or its longest assistant
    period, and outlives questions an assistant with a shorter period lost."""
    model_id = (await completion_model_factory(retention_session, "gpt-4")).id
    space = await _space(retention_session, tenant_id=test_tenant.id, days=20)
    # One assistant keeps 90 days; the other has none of its own, so the
    # space's 20 days apply to its questions.
    long_kept = await _assistant(
        retention_session,
        model_id,
        space=space,
        user_id=admin_user.id,
        days=90,
    )
    space_kept = await _assistant(
        retention_session,
        model_id,
        space=space,
        user_id=admin_user.id,
        days=None,
    )
    group_chat = GroupChatsTable(
        name="Name retention group chat", space_id=space.id, user_id=admin_user.id
    )
    retention_session.add(group_chat)
    await retention_session.flush()
    for assistant in (long_kept, space_kept):
        retention_session.add(
            GroupChatsAssistantsMapping(
                group_chat_id=group_chat.id, assistant_id=assistant.id
            )
        )
    gone, _, _ = await _conversation(
        retention_session,
        user_id=admin_user.id,
        group_chat_id=group_chat.id,
        created_days_ago=21,
        named_days_ago=21,
    )
    kept, kept_name, kept_feedback = await _conversation(
        retention_session,
        user_id=admin_user.id,
        group_chat_id=group_chat.id,
        created_days_ago=19,
        named_days_ago=19,
    )

    await run_registered_retention(retention_session)

    assert await _texts(retention_session, gone) == ("", 1, None)
    assert await _texts(retention_session, kept) == (kept_name, 1, kept_feedback)


async def test_writing_a_name_or_feedback_text_starts_its_time_again(
    retention_session: AsyncSession, test_tenant, admin_user, completion_model_factory
):
    """Mutants: renaming (the model's title or the user's own name) keeps the
    old time; feedback with a new text keeps the old time; a vote that leaves
    the stored text in place restarts that text's time."""
    model_id = (await completion_model_factory(retention_session, "gpt-4")).id
    space = await _space(retention_session, tenant_id=test_tenant.id)
    assistant = await _assistant(
        retention_session,
        model_id,
        space=space,
        user_id=admin_user.id,
        days=30,
    )
    renamed, _, _ = await _conversation(
        retention_session,
        user_id=admin_user.id,
        assistant_id=assistant.id,
        created_days_ago=60,
        named_days_ago=60,
    )
    voted, voted_name, _ = await _conversation(
        retention_session,
        user_id=admin_user.id,
        assistant_id=assistant.id,
        created_days_ago=10,
        named_days_ago=10,
        feedback_days_ago=40,
    )
    repository = SessionRepository(retention_session)
    await repository.update(SessionUpdate(id=renamed, name="New name"))
    await repository.add_feedback(
        SessionFeedback(value=-1, text="New feedback"), renamed
    )
    await repository.add_feedback(
        SessionFeedback(value=-1), voted, keep_existing_text=True
    )

    await run_registered_retention(retention_session)

    assert await _texts(retention_session, renamed) == (
        "New name",
        -1,
        "New feedback",
    )
    assert await _texts(retention_session, voted) == (voted_name, -1, None)


async def test_a_title_made_late_from_the_turns_goes_with_their_oldest_question(
    retention_session: AsyncSession, test_tenant, admin_user, completion_model_factory
):
    """A title can quote any turn it was made from, so it keeps the time of
    the oldest question still there, however late it is made. A name the
    user sets starts its own time."""
    model_id = (await completion_model_factory(retention_session, "gpt-4")).id
    space = await _space(retention_session, tenant_id=test_tenant.id)
    assistant = await _assistant(
        retention_session,
        model_id,
        space=space,
        user_id=admin_user.id,
        days=30,
    )
    titled, _, _ = await _conversation(
        retention_session,
        user_id=admin_user.id,
        assistant_id=assistant.id,
        created_days_ago=31,
        named_days_ago=31,
    )
    renamed, _, _ = await _conversation(
        retention_session,
        user_id=admin_user.id,
        assistant_id=assistant.id,
        created_days_ago=31,
        named_days_ago=31,
    )
    for conversation, days in ((titled, 31), (titled, 5), (renamed, 31), (renamed, 5)):
        retention_session.add(
            Questions(
                question="Question",
                answer="Answer",
                num_tokens_question=1,
                num_tokens_answer=1,
                tenant_id=test_tenant.id,
                assistant_id=assistant.id,
                session_id=conversation,
                created_at=_ago(days),
                updated_at=_ago(days),
            )
        )
    await retention_session.flush()
    repository = SessionRepository(retention_session)
    await repository.update(
        SessionUpdate(id=titled, name="Title made today"), title_from_turns=True
    )
    await repository.update(SessionUpdate(id=renamed, name="Name set today"))

    await run_registered_retention(retention_session)

    assert (await _texts(retention_session, titled))[0] == ""
    assert (await _texts(retention_session, renamed))[0] == "Name set today"


async def test_a_held_conversation_keeps_its_name_and_is_reported(
    retention_session: AsyncSession, test_tenant, admin_user, completion_model_factory
):
    """Mutant: the step waits for, or silently passes, a conversation another
    transaction holds, so the readback cannot see a name still due."""
    model_id = (await completion_model_factory(retention_session, "gpt-4")).id
    space = await _space(retention_session, tenant_id=test_tenant.id)
    assistant = await _assistant(
        retention_session,
        model_id,
        space=space,
        user_id=admin_user.id,
        days=30,
    )
    held, held_name, held_feedback = await _conversation(
        retention_session,
        user_id=admin_user.id,
        assistant_id=assistant.id,
        created_days_ago=60,
        named_days_ago=60,
    )
    await retention_session.commit()
    await retention_session.begin()

    async with sessionmanager.session() as holder, holder.begin():
        await holder.execute(
            sa.select(Sessions.id).where(Sessions.id == held).with_for_update()
        )
        report = await run_registered_retention(retention_session)

    assert await _texts(retention_session, held) == (held_name, 1, held_feedback)
    assert report.blocked[f"{STEP}.root_locked"] == 1
