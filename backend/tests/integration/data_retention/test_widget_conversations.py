"""Widget conversations follow their widget's retention, never an assistant,
space or tenant rule: conversation history and the empty-session sweep leave
them in discovery, in the fresh check inside the delete and in the overdue
report."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.audit.domain.action_types import ActionType
from eneo.data_retention.application.conversation_history_retention_task import (
    CONVERSATION_HISTORY_TASK,
)
from eneo.data_retention.application.conversation_retention import (
    ConversationRootKind,
)
from eneo.data_retention.application.empty_session_retention_task import (
    EMPTY_SESSIONS_TASK,
)
from eneo.data_retention.domain.retention import (
    RetentionErrorCode,
    RetentionJobOutcome,
    RetentionKeyset,
)
from eneo.data_retention.infrastructure.conversation_retention_repo import (
    ConversationRetentionRepository,
)
from eneo.data_retention.infrastructure.empty_session_repo import (
    EmptySessionRepository,
)
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.audit_log_table import AuditLog
from eneo.database.tables.questions_table import Questions
from eneo.database.tables.retention_tables import RetentionJobRuns
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.widgets_table import Widgets
from eneo.main.config import get_settings
from eneo.widgets.domain.widget import generate_public_id
from tests.integration.data_retention.retention_support import (
    run_nightly_retention,
    run_registered_retention,
)

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
    session_id: UUID | None,
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


async def test_the_nightly_cron_keeps_history_while_off_and_then_passes_widgets(
    monkeypatch: pytest.MonkeyPatch,
    retention_session: AsyncSession,
    conversations: Conversations,
):
    """Mutants: the worker runs conversation history while its setting turns it
    off, or skips it without an execution row and audit event; once on again it
    takes the widget conversation with the user's."""
    history_off = get_settings().model_copy(
        update={"retention_conversations_history_enabled": False}
    )

    await run_nightly_retention(monkeypatch, history_off)

    retention_session.expunge_all()
    runs = await retention_session.execute(
        sa.select(RetentionJobRuns.outcome, RetentionJobRuns.error_code).where(
            RetentionJobRuns.task == CONVERSATION_HISTORY_TASK
        )
    )
    assert runs.tuples().all() == [
        (
            RetentionJobOutcome.SKIPPED.value,
            RetentionErrorCode.DISABLED_BY_DEPLOYMENT_SETTING.value,
        )
    ]
    skips = await retention_session.scalars(
        sa.select(AuditLog.log_metadata["task"].astext).where(
            AuditLog.action == ActionType.DATA_RETENTION_SKIPPED.value
        )
    )
    assert skips.all() == [CONVERSATION_HISTORY_TASK]
    assert await retention_session.get(Questions, conversations.user_question)
    assert await retention_session.get(Questions, conversations.widget_question)

    await run_nightly_retention(monkeypatch, get_settings())

    retention_session.expunge_all()
    assert await retention_session.get(Questions, conversations.user_question) is None
    assert await retention_session.get(Sessions, conversations.user_session) is None
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


async def test_a_question_without_a_session_stays_eligible(
    retention_session: AsyncSession, test_tenant, admin_user, completion_model_factory
):
    """Mutant: the widget predicate reads a question without a session as a
    widget's (a NOT EXISTS over sessions outside widgets), so discovery passes
    it, the fresh check inside the delete refuses it and the overdue walk
    leaves it out, while a widget question beside it is still passed."""
    assistant, widget = await _owner(
        retention_session,
        completion_model_factory,
        tenant_id=test_tenant.id,
        user_id=admin_user.id,
    )
    widget_session = await _session(
        retention_session, created_at=_ago(DAYS_OLD), widget_id=widget.id
    )
    widget_question, sessionless = [
        await _question(
            retention_session,
            tenant_id=test_tenant.id,
            assistant_id=assistant.id,
            session_id=session_id,
            created_at=_ago(DAYS_OLD - offset),
        )
        for offset, session_id in enumerate((widget_session, None))
    ]
    await retention_session.commit()
    await retention_session.begin()
    repository = _questions(retention_session)

    # The window (discovery and the overdue walk) marks only the widget question.
    page = await repository.lock_due_page(_at_owner(assistant.id), 10)
    assert [root.id for root in page.roots] == [widget_question, sessionless]
    assert (list(page.passed_ids), list(page.locked_ids)) == (
        [widget_question],
        [sessionless],
    )
    overdue = await repository.overdue(
        window=timedelta(0), limit=10, owner_page=1000, max_pages=10
    )
    assert (overdue.count, overdue.complete) == (1, True)
    # The due query inside the delete refuses only the widget question.
    assert await repository.delete_if_still_due(widget_question) is None
    assert await repository.delete_if_still_due(sessionless)


async def test_the_empty_session_sweep_leaves_widget_sessions(
    retention_session: AsyncSession, test_tenant, admin_user, completion_model_factory
):
    """Mutants: the sweep's window does not mark a widget session, or its lock
    or delete takes one, before the widget's own retention allows it."""
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

    assert {root.id: passed for root, passed in await sessions.window(None, 1000)} == {
        widget_session: True,
        user_session: False,
    }
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


async def test_the_empty_session_sweep_reads_its_page_and_passes_widget_sessions(
    retention_session: AsyncSession, test_tenant, admin_user, completion_model_factory
):
    """Mutants: the sweep filters widget sessions inside its window, so one
    statement reads every retained widget session, uncharged, before the first
    ordinary one, and a timeout repeats that read every night; or a passed
    widget session is locked, deleted or reported as blocked."""
    _assistant, widget = await _owner(
        retention_session,
        completion_model_factory,
        tenant_id=test_tenant.id,
        user_id=admin_user.id,
    )
    # Three retained widget sessions, oldest first, ahead of two empty ones.
    widget_sessions = [
        await _session(
            retention_session,
            created_at=_ago(10) + timedelta(seconds=offset),
            widget_id=widget.id,
        )
        for offset in range(3)
    ]
    ordinary = [
        await _session(
            retention_session,
            created_at=_ago(5) + timedelta(seconds=offset),
            user_id=admin_user.id,
        )
        for offset in range(2)
    ]
    await retention_session.commit()
    await retention_session.begin()

    # A page is the next sessions as they are, the widget ones marked.
    page = await EmptySessionRepository(
        retention_session, now=datetime.now(timezone.utc), grace=timedelta(days=1)
    ).window(None, 2)
    assert [(root.id, passed) for root, passed in page] == [
        (widget_sessions[0], True),
        (widget_sessions[1], True),
    ]

    # One session per call; the budget ends the first night after the widget
    # sessions, each charged one discovery row.
    settings = get_settings().model_copy(
        update={"retention_chunk_rows": 4, "retention_max_rows_per_run": 6}
    )
    first = await run_registered_retention(
        retention_session, task_name=EMPTY_SESSIONS_TASK, settings=settings
    )

    assert first.counts == {
        "sessions.sessions_examined": 3,
        "sessions.deferred": 1,
    }
    assert first.blocked == {}
    row = await retention_session.get(RetentionJobRuns, first.job_run_id)
    assert row is not None and row.cursors["sessions"]["id"] == str(widget_sessions[-1])

    second = await run_registered_retention(
        retention_session,
        task_name=EMPTY_SESSIONS_TASK,
        settings=get_settings().model_copy(update={"retention_chunk_rows": 4}),
    )

    assert second.counts == {
        "sessions.sessions_examined": 2,
        "sessions.sessions_deleted": 2,
    }
    assert second.blocked == {}
    for session_id in ordinary:
        assert await retention_session.get(Sessions, session_id) is None
    for session_id in widget_sessions:
        assert await retention_session.get(Sessions, session_id)
