"""Query shape of the insights repository (database behaviour lives in
``tests/integration/analysis/test_insights_repo.py``)."""

from datetime import datetime, timezone
from typing import Any, cast
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from eneo.analysis.insight_scope import InsightScope, InsightWindow
from eneo.analysis.insights_repo import (
    InsightsRepository,
    KnowledgeSetup,
    normalize_question_text,
    normalized_question_expr,
)
from eneo.database.tables.questions_table import Questions


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Hur ansöker jag om bygglov?", "hur ansöker jag om bygglov"),
        ("  hur   ansöker\tjag om\nbygglov ?!. ", "hur ansöker jag om bygglov"),
        ("VAD KOSTAR DET...", "vad kostar det"),
        ("Hej!?", "hej"),
        ("Fråga utan skiljetecken", "fråga utan skiljetecken"),
        ("3.5 eller 4.0?", "3.5 eller 4.0"),
    ],
)
def test_normalize_question_text(raw: str, expected: str):
    assert normalize_question_text(raw) == expected


def test_normalized_question_expr_applies_the_same_steps():
    sql = str(
        normalized_question_expr(Questions.question).compile(
            compile_kwargs={"literal_binds": True}
        )
    )

    # trim, collapse whitespace, strip trailing ?!., trim, lower
    assert sql.startswith("lower(btrim(regexp_replace(regexp_replace(btrim(")
    assert "'\\s+', ' ', 'g'" in sql
    assert "'[?!.]+$', ''" in sql


def _window() -> InsightWindow:
    return InsightWindow(
        start=datetime(2026, 9, 1, tzinfo=timezone.utc),
        end=datetime(2026, 9, 8, tzinfo=timezone.utc),
        timezone="Europe/Stockholm",
    )


def _repo() -> InsightsRepository:
    return InsightsRepository(session=cast(Any, None))


def test_scoped_questions_filters_tenant_target_window_and_hidden_sessions():
    scope = InsightScope(kind="assistant", target_id=uuid4(), tenant_id=uuid4())
    sql = str(_repo()._scoped_questions(scope, _window()).compile())

    assert "questions.tenant_id = :tenant_id_1" in sql
    assert "sessions.assistant_id = :assistant_id_1" in sql
    assert "questions.created_at >=" in sql and "questions.created_at <" in sql
    assert "help_assistant_runs" in sql and "insight_conversations" in sql
    # A copy of removed content is left out in the same statement.
    assert "content_derivations" in sql
    # Never an inner join on users: api-key and widget sessions would vanish.
    assert "JOIN users" not in sql


def test_scoped_questions_carries_the_question_id_for_its_sources():
    scope = InsightScope(kind="assistant", target_id=uuid4(), tenant_id=uuid4())
    query = _repo()._scoped_questions(scope, _window())

    assert "id" in query.selected_columns.keys()


def test_scoped_questions_targets_group_chats_by_their_column():
    scope = InsightScope(kind="group_chat", target_id=uuid4(), tenant_id=uuid4())
    sql = str(_repo()._scoped_questions(scope, _window()).compile())

    assert "sessions.group_chat_id = :group_chat_id_1" in sql
    assert "sessions.assistant_id" not in sql


def test_followup_flag_is_a_correlated_exists_on_the_same_session():
    sql = str(
        sa.select(InsightsRepository._is_followup_expr()).compile(
            compile_kwargs={"literal_binds": True}
        )
    )

    assert "EXISTS" in sql
    assert "session_id = questions.session_id" in sql


def test_scoped_questions_narrow_to_one_source_when_asked():
    scope = InsightScope(kind="assistant", target_id=uuid4(), tenant_id=uuid4())

    narrowed = str(_repo()._scoped_questions(scope, _window(), "widget").compile())
    everything = str(_repo()._scoped_questions(scope, _window()).compile())

    assert "sessions.widget_id IS NOT NULL" in narrowed
    assert "sessions.widget_id IS NOT NULL" not in everything


class _Recorder:
    """Records each statement and answers with neutral rows."""

    def __init__(self) -> None:
        self.statements: list[Any] = []

    async def execute(self, statement: Any) -> Any:
        self.statements.append(statement)
        result = MagicMock()
        result.all.return_value = []
        return result

    async def scalar(self, statement: Any) -> int:
        self.statements.append(statement)
        return 0


async def test_figure_reads_never_join_users_and_keep_the_hidden_and_copy_rules():
    recorder = _Recorder()
    repo = InsightsRepository(session=cast(Any, recorder))
    scope = InsightScope(kind="assistant", target_id=uuid4(), tenant_id=uuid4())

    await repo.summarize(
        scope,
        _window(),
        source=None,
        knowledge=KnowledgeSetup(True, frozenset({uuid4()})),
    )
    await repo.count_activity(scope, _window(), source="user")
    await repo.list_ratings(
        scope,
        _window(),
        source=None,
        value=-1,
        has_comment=True,
        limit=10,
        after=None,
    )
    await repo.list_targets(
        tenant_id=scope.tenant_id,
        window=_window(),
        previous=None,
        query="bygg",
        unused_only=True,
        sort="questions",
        descending=True,
        offset=0,
        limit=10,
    )
    await repo.count_tenant_activity(tenant_id=scope.tenant_id, window=_window())

    assert len(recorder.statements) == 6
    for statement in recorder.statements:
        sql = str(statement.compile(dialect=postgresql.dialect()))
        assert "JOIN users" not in sql
        assert "help_assistant_runs" in sql and "insight_conversations" in sql
        assert "content_derivations" in sql


def test_the_knowledge_server_name_is_the_internal_servers():
    from eneo.analysis.insights_repo import KNOWLEDGE_SERVER
    from eneo.internal_mcp.constants import KNOWLEDGE_SERVER_NAME

    assert KNOWLEDGE_SERVER == KNOWLEDGE_SERVER_NAME


async def test_knowledge_question_and_tool_reads_keep_the_hidden_and_copy_rules():
    recorder = _Recorder()
    repo = InsightsRepository(session=cast(Any, recorder))
    scope = InsightScope(kind="group_chat", target_id=uuid4(), tenant_id=uuid4())
    knowledge = KnowledgeSetup(True, frozenset({uuid4()}))

    await repo.knowledge_citations(scope, _window(), source="widget")
    await repo.question_groups(
        scope,
        _window(),
        source=None,
        knowledge=knowledge,
        n=5,
        include_followups=False,
    )
    await repo.tool_use(scope, _window(), source=None)
    await repo.find_no_knowledge(
        scope, _window(), offset=0, limit=3, absolute=knowledge
    )

    compiled = [
        str(statement.compile(dialect=postgresql.dialect()))
        for statement in recorder.statements
    ]
    reads = [sql for sql in compiled if "FROM questions" in sql]
    # Citations, question groups, tool calls, and the misses' total and page;
    # the attached sources are read from the assistants alone.
    assert len(reads) == 5 and len(compiled) == 6
    for sql in reads:
        assert "JOIN users" not in sql
        assert "help_assistant_runs" in sql and "insight_conversations" in sql
        assert "content_derivations" in sql


def test_the_skill_activation_tool_name_is_the_runtimes():
    from eneo.analysis.insights_repo import SKILL_ACTIVATION_TOOL
    from eneo.completion_models.domain.skill_activation import (
        SKILL_ACTIVATION_TOOL_NAME,
    )

    assert SKILL_ACTIVATION_TOOL == SKILL_ACTIVATION_TOOL_NAME
