# MIT License

from typing import Any

import sqlalchemy as sa

from eneo.database.tables.help_assistant_runs_table import HelpAssistantRuns


# IMPORTANT: every query that returns session/question rows or aggregates
# derived from them must apply this filter, or document the explicit exception
# in a comment. Mirrors ``SessionRepository._exclude_helper_run_sessions`` —
# PRD §4 ("one rule, one place"). Parametrised on the session-id column so
# both Sessions-scoped (Sessions.id) and Questions-scoped
# (Questions.session_id) queries can apply the same filter without joining
# Sessions.
def exclude_helper_run_sessions(
    query: sa.Select[Any], session_id_col: Any
) -> sa.Select[Any]:
    """Exclude rows whose session is referenced by a ``help_assistant_runs`` row.

    Helper conversations live in the regular ``sessions`` / ``questions``
    tables so streaming, RAG, model selection, and tool calling all work — but
    they must never appear in normal conversation / insights / analytics /
    export endpoints. See PRD §4.
    """
    return query.where(
        ~sa.exists(
            sa.select(HelpAssistantRuns.id).where(
                HelpAssistantRuns.session_id == session_id_col
            )
        )
    )
