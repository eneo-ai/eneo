"""clear removed turns from the logs of their conversation

A question's log holds the whole request body, so the log of every later turn
in the conversation holds the question too. Removing questions now also
clears the request body of the later logs in each affected conversation, once
per log, and raises the conversation's history revision. An answer generated
from history read at an older revision is stored with a cleared log.

Logs that no question refers to are removed: nothing can read or remove them
later. Answers stopped writing such logs, so this runs once.

Each catalog step commits on its own and takes its lock with NOWAIT, retrying
for a bounded time, so chat traffic never queues behind it. The new column has
a constant default, so adding it changes the catalog only. Every step can be
re-run.

Revision ID: 202611090600
Revises: 202611081500
Create Date: 2026-11-09 06:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence
from time import monotonic, sleep

from sqlalchemy.exc import DBAPIError

from alembic import op

revision: str = "202611090600"
down_revision: str | None = "202611081500"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LOCK_NOT_AVAILABLE_SQLSTATE = "55P03"
_LOCK_RETRY_SECONDS = 30.0
_LOCK_RETRY_INTERVAL_SECONDS = 0.05

_HISTORY_REVISION = (
    "ALTER TABLE sessions "
    "ADD COLUMN IF NOT EXISTS history_revision INTEGER NOT NULL DEFAULT 0"
)

_REMOVE_QUESTION_LOGS_FUNCTION = """
CREATE OR REPLACE FUNCTION remove_question_logs() RETURNS trigger
LANGUAGE plpgsql AS $$
        BEGIN
            -- An answer being stored in one of these conversations holds the
            -- revision FOR SHARE, so this waits for it, and the clearing
            -- below, a later statement, sees that answer's log.
            UPDATE sessions
            SET history_revision = history_revision + 1
            WHERE id IN (
                SELECT session_id FROM removed_questions
                WHERE session_id IS NOT NULL
            );

            -- A turn asked at the same instant counts as later: the order
            -- between them is unknown.
            UPDATE logging
            SET json_body = NULL, context = NULL, model_kwargs = '{}'::jsonb
            FROM questions, (
                SELECT session_id, min(created_at) AS removed_from
                FROM removed_questions
                WHERE session_id IS NOT NULL
                GROUP BY session_id
            ) AS removed
            WHERE questions.session_id = removed.session_id
              AND questions.created_at >= removed.removed_from
              AND logging.id = questions.logging_details_id
              AND (
                  logging.json_body IS NOT NULL
                  OR logging.context IS NOT NULL
                  OR logging.model_kwargs IS DISTINCT FROM '{}'::jsonb
              );

            DELETE FROM logging
            WHERE id IN (
                SELECT logging_details_id FROM removed_questions
                WHERE logging_details_id IS NOT NULL
            )
              AND NOT EXISTS (
                  SELECT 1 FROM questions
                  WHERE questions.logging_details_id = logging.id
              );
            RETURN NULL;
        END;
        $$
"""

_REMOVE_QUESTION_LOGS_TRIGGER = (
    "DROP TRIGGER IF EXISTS delete_question_owned_log ON questions",
    "DROP TRIGGER IF EXISTS remove_question_logs ON questions",
    """
    CREATE TRIGGER remove_question_logs
    AFTER DELETE ON questions
    REFERENCING OLD TABLE AS removed_questions
    FOR EACH STATEMENT
    EXECUTE FUNCTION remove_question_logs()
    """,
)

_ORPHAN_LOGS = """
DELETE FROM logging
WHERE NOT EXISTS (
    SELECT 1 FROM questions WHERE questions.logging_details_id = logging.id
)
"""

# The row trigger this revision replaces, as revision 202610291001 left it.
_QUESTION_LOG_CLEANUP_FUNCTION = """
CREATE OR REPLACE FUNCTION delete_question_owned_log() RETURNS trigger
LANGUAGE plpgsql AS $$
        BEGIN
            DELETE FROM logging
            WHERE id = OLD.logging_details_id
              AND NOT EXISTS (
                  SELECT 1 FROM questions WHERE logging_details_id = OLD.logging_details_id
              );
            RETURN NULL;
        END;
        $$
"""
_QUESTION_LOG_CLEANUP_TRIGGER = (
    "DROP TRIGGER IF EXISTS remove_question_logs ON questions",
    "DROP TRIGGER IF EXISTS delete_question_owned_log ON questions",
    """
    CREATE TRIGGER delete_question_owned_log
    AFTER DELETE ON questions FOR EACH ROW
    WHEN (OLD.logging_details_id IS NOT NULL)
    EXECUTE FUNCTION delete_question_owned_log()
    """,
)


def _with_immediate_locks(locks: Sequence[str], statements: Sequence[str]) -> None:
    """Run one short catalog step in its own transaction, locking with NOWAIT.

    A lock request that has to wait joins the table's lock queue, and every
    later request on the table queues behind it. Failing at once and retrying
    keeps chat traffic flowing; after the deadline the upgrade fails and can be
    run again.
    """
    bind = op.get_bind()
    deadline = monotonic() + _LOCK_RETRY_SECONDS
    while True:
        bind.exec_driver_sql("BEGIN")
        try:
            for lock in locks:
                bind.exec_driver_sql(f"LOCK TABLE {lock} NOWAIT")
            for statement in statements:
                bind.exec_driver_sql(statement)
            bind.exec_driver_sql("COMMIT")
            return
        except DBAPIError as error:
            bind.exec_driver_sql("ROLLBACK")
            sqlstate = getattr(error.orig, "sqlstate", None) or getattr(
                error.orig, "pgcode", None
            )
            if sqlstate != _LOCK_NOT_AVAILABLE_SQLSTATE or monotonic() >= deadline:
                raise
            sleep(_LOCK_RETRY_INTERVAL_SECONDS)
        except Exception:
            bind.exec_driver_sql("ROLLBACK")
            raise


def upgrade() -> None:
    with op.get_context().autocommit_block():
        _with_immediate_locks(
            ("sessions IN ACCESS EXCLUSIVE MODE",), (_HISTORY_REVISION,)
        )
        op.execute(_REMOVE_QUESTION_LOGS_FUNCTION)
        _with_immediate_locks(
            ("questions IN ACCESS EXCLUSIVE MODE",), _REMOVE_QUESTION_LOGS_TRIGGER
        )
        op.execute("DROP FUNCTION IF EXISTS delete_question_owned_log()")
        op.execute(_ORPHAN_LOGS)


def downgrade() -> None:
    # Removed orphan logs and cleared request bodies stay removed.
    with op.get_context().autocommit_block():
        op.execute(_QUESTION_LOG_CLEANUP_FUNCTION)
        _with_immediate_locks(
            ("questions IN ACCESS EXCLUSIVE MODE",), _QUESTION_LOG_CLEANUP_TRIGGER
        )
        op.execute("DROP FUNCTION IF EXISTS remove_question_logs()")
        _with_immediate_locks(
            ("sessions IN ACCESS EXCLUSIVE MODE",),
            ("ALTER TABLE sessions DROP COLUMN IF EXISTS history_revision",),
        )
