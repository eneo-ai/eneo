"""Widget conversations follow their widget's retention, never an assistant,
space or tenant rule: conversation history and the empty-session sweep leave
them in discovery, in the fresh check inside the delete and in the overdue
report."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.data_retention.application.conversation_retention import (
    ConversationRootKind,
)
from eneo.data_retention.application.empty_session_retention_task import (
    EMPTY_SESSIONS_TASK,
)
from eneo.data_retention.domain.retention import RetentionKeyset
from eneo.data_retention.infrastructure.conversation_retention_repo import (
    ConversationRetentionRepository,
)
from eneo.data_retention.infrastructure.empty_session_repo import (
    EmptySessionRepository,
)
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.questions_table import Questions
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.widgets_table import Widgets
from eneo.main.config import get_settings
from eneo.widgets.domain.widget import generate_public_id
from tests.integration.data_retention.retention_support import run_registered_retention

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]

DAYS_OLD = 60


@dataclass(frozen=True)
class Conversations:
    widget_session: UUID
    widget_question: UUID
    user_session: UUID
    user_question: UUID


def _ago(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


async def _owner(
    session: AsyncSession, completion_model_factory, *, tenant_id: UUID, user_id: UUID
) -> tuple[Assistants, Widgets]:
    space = Spaces(
        name=f"Widget retention space {uuid4()}",
        tenant_id=tenant_id,
        user_id=user_id,
        tenant_space_id=None,
    )
    session.add(space)
    await session.flush()
    model = await completion_model_factory(session, "gpt-4")
    # The assistant's rule expired every conversation below long ago.
    assistant = Assistants(
        name="Widget retention assistant",
        user_id=user_id,
        space_id=space.id,
        completion_model_id=model.id,
        completion_model_kwargs={},
        logging_enabled=True,
        is_default=False,
        published=True,
        data_retention_days=1,
    )
    session.add(assistant)
    await session.flush()
    widget = Widgets(
        public_id=generate_public_id(),
        tenant_id=tenant_id,
        space_id=space.id,
        target_type="assistant",
        target_id=assistant.id,
        name="Widget",
        privacy={"retention_days": 365},
    )
    session.add(widget)
    await session.flush()
    return assistant, widget


async def _session(
    session: AsyncSession,
    *,
    created_at: datetime,
    user_id: UUID | None = None,
    widget_id: UUID | None = None,
) -> UUID:
    row = Sessions(
        user_id=user_id,
        widget_id=widget_id,
        visitor_id=uuid4() if widget_id is not None else None,
        name="Session",
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(row)
    await session.flush()
    return row.id


async def _question(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    assistant_id: UUID,
    session_id: UUID,
    created_at: datetime,
) -> UUID:
    row = Questions(
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
    session.add(row)
    await session.flush()
    return row.id


@pytest.fixture
async def conversations(
    retention_session: AsyncSession, test_tenant, admin_user, completion_model_factory
) -> Conversations:
    assistant, widget = await _owner(
        retention_session,
        completion_model_factory,
        tenant_id=test_tenant.id,
        user_id=admin_user.id,
    )
    old = _ago(DAYS_OLD)
    widget_session = await _session(
        retention_session, created_at=old, widget_id=widget.id
    )
    user_session = await _session(
        retention_session, created_at=old, user_id=admin_user.id
    )
    questions = [
        await _question(
            retention_session,
            tenant_id=test_tenant.id,
            assistant_id=assistant.id,
            session_id=session_id,
            created_at=old,
        )
        for session_id in (widget_session, user_session)
    ]
    await retention_session.commit()
    await retention_session.begin()
    return Conversations(widget_session, questions[0], user_session, questions[1])


def _questions(session: AsyncSession) -> ConversationRetentionRepository:
    return ConversationRetentionRepository(
        session, kind=ConversationRootKind.QUESTION, now=datetime.now(timezone.utc)
    )


async def test_history_leaves_a_widget_conversation_its_assistant_rule_expired(
    retention_session: AsyncSession, conversations: Conversations
):
    """Mutant: discovery selects widget questions, so the assistant's rule
    deletes the conversation and the release takes its session."""
    report = await run_registered_retention(retention_session)

    assert report.counts["questions.questions_deleted"] == 1
    assert await retention_session.get(Questions, conversations.user_question) is None
    assert await retention_session.get(Questions, conversations.widget_question)
    assert await retention_session.get(Sessions, conversations.widget_session)


async def test_the_fresh_check_inside_the_delete_refuses_a_widget_question(
    retention_session: AsyncSession, conversations: Conversations
):
    """Mutant: only discovery excludes widgets, so a widget question that reaches
    the delete (discovered before its session was a widget's) is deleted."""
    repository = _questions(retention_session)

    assert await repository.delete_if_still_due(conversations.widget_question) is None
    assert await repository.delete_if_still_due(conversations.user_question)
    assert await retention_session.get(Questions, conversations.widget_question)


async def test_the_overdue_report_does_not_count_widget_questions(
    retention_session: AsyncSession, conversations: Conversations
):
    """Mutant: the overdue walk counts widget questions, so health reports work
    no task will ever do."""
    overdue = await _questions(retention_session).overdue(
        window=timedelta(0), limit=10, owner_page=1000, max_pages=10
    )

    assert (overdue.count, overdue.complete) == (1, True)


@dataclass(frozen=True)
class WidgetBacklog:
    owner: UUID
    # Due by the assistant's rule, oldest first, ahead of the user's question.
    widget_questions: tuple[UUID, ...]
    user_question: UUID


@pytest.fixture
async def widget_backlog(
    retention_session: AsyncSession, test_tenant, admin_user, completion_model_factory
) -> WidgetBacklog:
    assistant, widget = await _owner(
        retention_session,
        completion_model_factory,
        tenant_id=test_tenant.id,
        user_id=admin_user.id,
    )
    widget_session = await _session(
        retention_session, created_at=_ago(DAYS_OLD), widget_id=widget.id
    )
    user_session = await _session(
        retention_session, created_at=_ago(DAYS_OLD), user_id=admin_user.id
    )
    widget_questions = tuple(
        [
            await _question(
                retention_session,
                tenant_id=test_tenant.id,
                assistant_id=assistant.id,
                session_id=widget_session,
                created_at=_ago(DAYS_OLD - offset),
            )
            for offset in range(3)
        ]
    )
    user_question = await _question(
        retention_session,
        tenant_id=test_tenant.id,
        assistant_id=assistant.id,
        session_id=user_session,
        created_at=_ago(DAYS_OLD - 3),
    )
    await retention_session.commit()
    await retention_session.begin()
    return WidgetBacklog(assistant.id, widget_questions, user_question)


def _at_owner(owner: UUID) -> RetentionKeyset:
    """A cursor before the owner's first root, so the page starts at it."""
    return RetentionKeyset(
        at=datetime.min.replace(tzinfo=timezone.utc), id=UUID(int=0), group=owner
    )


async def test_discovery_reads_its_window_and_passes_widget_questions(
    retention_session: AsyncSession, widget_backlog: WidgetBacklog
):
    """Mutant: discovery filters widget questions inside the owner's window, so
    one statement reads every widget question the assistant's rule has passed,
    uncharged, before the first question it returns."""
    page = await _questions(retention_session).lock_due_page(
        _at_owner(widget_backlog.owner), 2
    )

    first_two = widget_backlog.widget_questions[:2]
    assert tuple(root.id for root in page.roots) == first_two
    assert tuple(page.passed_ids) == first_two
    assert tuple(page.locked_ids) == ()


async def test_history_reaches_a_question_behind_widget_questions(
    retention_session: AsyncSession, widget_backlog: WidgetBacklog
):
    """Mutants: a window of widget questions ends the owner or stalls the step,
    so the user's question behind them stays; or a passed widget question is
    reported as a locked root."""
    # One root per discovery page.
    settings = get_settings().model_copy(update={"retention_chunk_rows": 4})

    report = await run_registered_retention(retention_session, settings=settings)

    assert report.counts["questions.questions_deleted"] == 1
    assert report.blocked == {}
    assert await retention_session.get(Questions, widget_backlog.user_question) is None
    for question in widget_backlog.widget_questions:
        assert await retention_session.get(Questions, question)


async def test_the_overdue_walk_counts_a_question_behind_widget_questions(
    retention_session: AsyncSession, widget_backlog: WidgetBacklog
):
    """Mutant: a walk window full of widget questions moves past the owner, so
    the overdue question behind them is never counted."""
    overdue = await _questions(retention_session).overdue(
        window=timedelta(0), limit=1, owner_page=1000, max_pages=10
    )

    assert (overdue.count, overdue.complete) == (1, True)


async def test_an_overdue_walk_its_pages_do_not_finish_is_incomplete(
    retention_session: AsyncSession, widget_backlog: WidgetBacklog
):
    """Mutant: the walk filters widget questions inside one unbounded read and
    reports complete, however many widget questions it had to read."""
    overdue = await _questions(retention_session).overdue(
        window=timedelta(0), limit=1, owner_page=1000, max_pages=1
    )

    assert (overdue.count, overdue.complete) == (0, False)


async def test_the_empty_session_sweep_leaves_widget_sessions(
    retention_session: AsyncSession, test_tenant, admin_user, completion_model_factory
):
    """Mutants: the sweep discovers widget sessions, or its lock or delete takes
    one, before the widget's own retention allows it."""
    _assistant, widget = await _owner(
        retention_session,
        completion_model_factory,
        tenant_id=test_tenant.id,
        user_id=admin_user.id,
    )
    old = _ago(3)
    widget_session = await _session(
        retention_session, created_at=old, widget_id=widget.id
    )
    user_session = await _session(
        retention_session, created_at=old, user_id=admin_user.id
    )
    sessions = EmptySessionRepository(
        retention_session, now=datetime.now(timezone.utc), grace=timedelta(days=1)
    )

    assert [row.id for row in await sessions.window(None, 1000)].count(
        widget_session
    ) == 0
    assert set(await sessions.lock_empty([widget_session, user_session])) == {
        user_session
    }
    assert await sessions.delete_due([widget_session]) == ()

    report = await run_registered_retention(
        retention_session, task_name=EMPTY_SESSIONS_TASK
    )

    assert report.counts["sessions.sessions_deleted"] >= 1
    assert await retention_session.get(Sessions, user_session) is None
    assert await retention_session.get(Sessions, widget_session)
