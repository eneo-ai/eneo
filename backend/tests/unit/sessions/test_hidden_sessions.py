"""The hidden-session rule covers every hidden kind, once."""

import sqlalchemy as sa

from eneo.database.tables.questions_table import Questions
from eneo.database.tables.sessions_table import Sessions
from eneo.sessions.hidden_sessions import (
    exclude_hidden_sessions,
    hidden_session_clause,
)


def _sql(clause) -> str:
    return str(clause.compile(compile_kwargs={"literal_binds": True}))


def test_clause_excludes_helper_runs_and_insight_conversations():
    sql = _sql(hidden_session_clause(Sessions.id))

    assert sql.count("NOT (EXISTS") == 2
    assert "help_assistant_runs.session_id = sessions.id" in sql
    assert "insight_conversations.session_id = sessions.id" in sql


def test_clause_binds_to_the_given_session_column():
    """Questions-scoped queries apply the rule without joining sessions."""
    sql = _sql(hidden_session_clause(Questions.session_id))

    assert "help_assistant_runs.session_id = questions.session_id" in sql
    assert "insight_conversations.session_id = questions.session_id" in sql
    assert "sessions.id" not in sql


def test_exclude_hidden_sessions_adds_the_clause_to_a_select():
    query = exclude_hidden_sessions(sa.select(Sessions.id), Sessions.id)
    sql = _sql(query)

    assert "WHERE NOT (EXISTS" in sql
    assert "help_assistant_runs" in sql
    assert "insight_conversations" in sql
