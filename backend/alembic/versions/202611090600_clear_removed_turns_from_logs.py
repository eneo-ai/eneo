"""clear removed turns from the logs of their conversation

A question's log holds the whole request body, so the log of every later turn
in the conversation holds the question too. Removing questions now also
clears the request body of the later logs in each affected conversation, once
per log, and raises the conversation's history revision. An answer generated
from history read at an older revision is stored with a cleared log.

A removal finds the logs it clears through `logging.session_id`, the
conversation of a log that holds content: linking such a log to its question
sets it, whichever writer links it, clearing the log unsets it, and the
upgrade sets it for the logs stored before, in batches. A partial index holds
only these logs, so a removal never reads an empty log. The index is built
concurrently; a failed build leaves it invalid, and a rerun drops that
leftover before building it again.

Logs that no question refers to are removed: nothing can read or remove them
later. Answers stopped writing such logs, so this runs once.

Each catalog step commits on its own and takes its lock with NOWAIT, retrying
for a bounded time, so chat traffic never queues behind it. The new columns
are nullable or have a constant default, so adding them changes the catalog
only. Every step can be re-run.

Revision ID: 202611090600
Revises: 202611081500
Create Date: 2026-11-09 06:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence
from time import monotonic, sleep

import sqlalchemy as sa
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

_LOG_CONVERSATION = "ALTER TABLE logging ADD COLUMN IF NOT EXISTS session_id UUID"

# What a removal clears. The app stores a log without a request body as a
# JSON null, and older rows may hold SQL NULL: both hold nothing.
_HOLDS_CONTENT = (
    "(logging.json_body <> 'null'::jsonb OR logging.context IS NOT NULL"
    " OR logging.model_kwargs <> '{}'::jsonb)"
)

_LOCATE_QUESTION_LOG_FUNCTION = f"""
CREATE OR REPLACE FUNCTION locate_question_log() RETURNS trigger
LANGUAGE plpgsql AS $$
        BEGIN
            UPDATE logging
            SET session_id = NEW.session_id
            WHERE logging.id = NEW.logging_details_id
              AND logging.session_id IS DISTINCT FROM NEW.session_id
              AND {_HOLDS_CONTENT};
            RETURN NULL;
        END;
        $$
"""

_LOCATE_QUESTION_LOG_TRIGGER = (
    "DROP TRIGGER IF EXISTS locate_question_log ON questions",
    """
    CREATE TRIGGER locate_question_log
    AFTER INSERT OR UPDATE OF logging_details_id ON questions
    FOR EACH ROW
    WHEN (NEW.logging_details_id IS NOT NULL AND NEW.session_id IS NOT NULL)
    EXECUTE FUNCTION locate_question_log()
    """,
)

# Each batch is one short transaction; the last id read continues the scan.
_LOCATE_BATCH_ROWS = 5000
_LOCATE_STORED_LOGS = f"""
WITH batch AS (
    SELECT id FROM logging
    WHERE id > CAST(:after AS uuid)
    ORDER BY id
    LIMIT {_LOCATE_BATCH_ROWS}
), located AS (
    UPDATE logging
    SET session_id = questions.session_id
    FROM questions
    WHERE logging.id IN (SELECT id FROM batch)
      AND questions.logging_details_id = logging.id
      AND questions.session_id IS NOT NULL
      AND logging.session_id IS NULL
      AND {_HOLDS_CONTENT}
)
SELECT id::text FROM batch ORDER BY id DESC LIMIT 1
"""

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

            -- Only a log that holds content is found through its
            -- conversation. A turn asked at the same instant counts as later:
            -- the order between them is unknown.
            UPDATE logging
            SET json_body = NULL, context = NULL, model_kwargs = '{}'::jsonb,
                session_id = NULL
            FROM questions, (
                SELECT session_id, min(created_at) AS removed_from
                FROM removed_questions
                WHERE session_id IS NOT NULL
                GROUP BY session_id
            ) AS removed
            WHERE logging.session_id = removed.session_id
              AND questions.logging_details_id = logging.id
              AND questions.created_at >= removed.removed_from;

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

_LOGS_INDEX = "ix_logging_session_id"

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


def _locate_stored_logs() -> None:
    bind = op.get_bind()
    after = "00000000-0000-0000-0000-000000000000"
    while (
        last := bind.execute(sa.text(_LOCATE_STORED_LOGS), {"after": after}).scalar()
    ) is not None:
        after = last


def _build_logs_index() -> None:
    """Build the index concurrently; drop an invalid leftover of a failed
    build first, which `IF NOT EXISTS` would keep."""
    valid = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT indisvalid FROM pg_index WHERE indexrelid = to_regclass(:name)"
            ),
            {"name": _LOGS_INDEX},
        )
        .scalar()
    )
    if valid is False:
        op.execute(f"DROP INDEX CONCURRENTLY {_LOGS_INDEX}")
    op.execute(
        f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_LOGS_INDEX} "
        "ON logging (session_id) WHERE session_id IS NOT NULL"
    )


def upgrade() -> None:
    with op.get_context().autocommit_block():
        _with_immediate_locks(
            ("sessions IN ACCESS EXCLUSIVE MODE",), (_HISTORY_REVISION,)
        )
        _with_immediate_locks(
            ("logging IN ACCESS EXCLUSIVE MODE",), (_LOG_CONVERSATION,)
        )
        # Found from the first link on, before the stored logs are searched,
        # and all of them before a removal looks for them.
        op.execute(_LOCATE_QUESTION_LOG_FUNCTION)
        _with_immediate_locks(
            ("questions IN ACCESS EXCLUSIVE MODE",), _LOCATE_QUESTION_LOG_TRIGGER
        )
        _locate_stored_logs()
        _build_logs_index()
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
            ("questions IN ACCESS EXCLUSIVE MODE",),
            (
                *_QUESTION_LOG_CLEANUP_TRIGGER,
                "DROP TRIGGER IF EXISTS locate_question_log ON questions",
            ),
        )
        op.execute("DROP FUNCTION IF EXISTS remove_question_logs()")
        op.execute("DROP FUNCTION IF EXISTS locate_question_log()")
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_LOGS_INDEX}")
        _with_immediate_locks(
            ("logging IN ACCESS EXCLUSIVE MODE",),
            ("ALTER TABLE logging DROP COLUMN IF EXISTS session_id",),
        )
        _with_immediate_locks(
            ("sessions IN ACCESS EXCLUSIVE MODE",),
            ("ALTER TABLE sessions DROP COLUMN IF EXISTS history_revision",),
        )
