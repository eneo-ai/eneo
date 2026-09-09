"""Query shape of the insights repository (database behaviour lives in
``tests/integration/analysis/test_insights_repo.py``)."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
import sqlalchemy as sa

from eneo.analysis.insight_scope import InsightScope, InsightWindow
from eneo.analysis.insights_repo import (
    InsightsRepository,
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
def test_normalize_question_text(raw, expected):
    assert normalize_question_text(raw) == expected


def test_normalized_question_expr_applies_the_same_steps():
    sql = str(
        normalized_question_expr(Questions.question).compile(
            compile_kwargs={"literal_binds": True}
        )
    )

    # trim → collapse whitespace → strip trailing ?!. → trim → lower
    assert sql.startswith("lower(btrim(regexp_replace(regexp_replace(btrim(")
    assert "'\\s+', ' ', 'g'" in sql
    assert "'[?!.]+$', ''" in sql


def _scope():
    return InsightScope(kind="assistant", target_id=uuid4(), tenant_id=uuid4())


def _window():
    return InsightWindow(
        start=datetime(2026, 9, 1, tzinfo=timezone.utc),
        end=datetime(2026, 9, 8, tzinfo=timezone.utc),
        timezone="Europe/Stockholm",
    )


def test_scoped_questions_filters_tenant_target_window_and_hidden_sessions():
    scope = _scope()
    query = InsightsRepository(session=None)._scoped_questions(scope, _window())
    sql = str(query.compile())

    assert "questions.tenant_id = :tenant_id_1" in sql
    assert "sessions.assistant_id = :assistant_id_1" in sql
    assert "questions.created_at >=" in sql and "questions.created_at <" in sql
    assert "help_assistant_runs" in sql and "insight_conversations" in sql
    # Never an inner join on users: api-key sessions would vanish.
    assert "JOIN users" not in sql


def test_scoped_questions_targets_group_chats_by_their_column():
    scope = InsightScope(kind="group_chat", target_id=uuid4(), tenant_id=uuid4())
    query = InsightsRepository(session=None)._scoped_questions(scope, _window())
    sql = str(query.compile())

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
