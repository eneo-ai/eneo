"""The one rule for sessions that must stay out of normal listings.

Some conversations live in the regular ``sessions`` / ``questions`` tables so
streaming, history replay, model selection and tool calling all work, but
must never appear in session, conversation, insights, analytics or export
reads:

* helper runs (``help_assistant_runs``), e.g. the Prompt Guide;
* insight conversations (``insight_conversations``), an operator's analysis
  chat about an assistant's or group chat's conversations.

Every repository query that returns session or question rows, or aggregates
derived from them, applies :func:`hidden_session_clause`. Adding a new kind
of hidden session means adding one ``NOT EXISTS`` here and nowhere else.
Documented exceptions (an owner loading its own hidden session for a
follow-up turn) live next to the repositories that own them.

Hidden assistants (``Assistants.hidden``, e.g. a flow authoring chat's) are a
different rule: they decide which assistants are shown and offered as chat
partners, while their conversations stay in the session and question figures.
See ``backend/docs/hidden-sessions.md``.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from eneo.database.tables.help_assistant_runs_table import HelpAssistantRuns
from eneo.database.tables.insight_conversations_table import InsightConversations


def hidden_session_clause(session_id_col: Any) -> sa.ColumnElement[bool]:
    """``True`` for rows whose session is *not* hidden.

    Parametrised on the session-id column so both Sessions-scoped
    (``Sessions.id``) and Questions-scoped (``Questions.session_id``) queries
    can apply the same rule without joining ``Sessions``.
    """
    return sa.and_(
        ~sa.exists(
            sa.select(HelpAssistantRuns.id).where(
                HelpAssistantRuns.session_id == session_id_col
            )
        ),
        ~sa.exists(
            sa.select(InsightConversations.id).where(
                InsightConversations.session_id == session_id_col
            )
        ),
    )


def exclude_hidden_sessions(
    query: sa.Select[Any], session_id_col: Any
) -> sa.Select[Any]:
    """Restrict ``query`` to rows whose session is not hidden."""
    return query.where(hidden_session_clause(session_id_col))
