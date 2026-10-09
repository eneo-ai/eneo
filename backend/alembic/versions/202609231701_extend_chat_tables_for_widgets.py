"""extend the chat tables for widgets without blocking chat writes

Everything the widget feature changes on `sessions` and `questions`, which are
among the largest tables in a deployment:

- A widget session's principal is a widget plus a pseudonymous visitor, so
  `sessions` gets `widget_id` and `visitor_id`, and the user-xor-API-key check
  becomes a check that exactly one principal is set.
- Deleting a question deletes its private model log once no other question
  references it. Widget retention purges rely on this, but it applies to every
  question deletion.

Each statement commits on its own. The columns are nullable without defaults
and the constraints are added NOT VALID, so the ACCESS EXCLUSIVE locks (on
`sessions`, and on `questions` to replace the trigger) cover catalog updates
only. Validation then runs under SHARE UPDATE EXCLUSIVE and the
indexes are built CONCURRENTLY, so chat writes continue during both scans.
The two catalog steps that need a strong lock never wait in PostgreSQL's
lock queue, where they would stall all chat traffic behind the longest open
transaction: they take their locks with NOWAIT and retry for a bounded time.
Every step can be re-run: an interrupted or timed-out upgrade is completed by
running it again.

Revision ID: 202609231701
Revises: 202609231700
Create Date: 2026-09-23 17:01:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence
from time import monotonic, sleep

from sqlalchemy.exc import DBAPIError

from alembic import op

revision: str = "202609231701"
down_revision: str | None = "202609231700"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LOCK_NOT_AVAILABLE_SQLSTATE = "55P03"
_LOCK_RETRY_SECONDS = 30.0
_LOCK_RETRY_INTERVAL_SECONDS = 0.05

_SESSION_CONSTRAINTS = (
    "sessions_widget_id_fkey",
    "ck_sessions_single_principal",
    "ck_sessions_visitor_requires_widget",
)

# Shared logs remain until their last question disappears. Logs that already
# have no question are left alone: their provenance is unknown.
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
    "DROP TRIGGER IF EXISTS delete_question_owned_log ON questions",
    """
    CREATE TRIGGER delete_question_owned_log
    AFTER DELETE ON questions FOR EACH ROW
    WHEN (OLD.logging_details_id IS NOT NULL)
    EXECUTE FUNCTION delete_question_owned_log()
    """,
)

_SESSION_PRINCIPALS = """
ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS widget_id UUID,
    ADD COLUMN IF NOT EXISTS visitor_id UUID,
    DROP CONSTRAINT IF EXISTS ck_sessions_user_xor_api_key,
    DROP CONSTRAINT IF EXISTS sessions_widget_id_fkey,
    DROP CONSTRAINT IF EXISTS ck_sessions_single_principal,
    DROP CONSTRAINT IF EXISTS ck_sessions_visitor_requires_widget,
    ADD CONSTRAINT sessions_widget_id_fkey
        FOREIGN KEY (widget_id) REFERENCES widgets (id)
        ON DELETE CASCADE NOT VALID,
    ADD CONSTRAINT ck_sessions_single_principal CHECK (
        (user_id IS NOT NULL)::int + (api_key_id IS NOT NULL)::int
        + (widget_id IS NOT NULL)::int = 1
    ) NOT VALID,
    ADD CONSTRAINT ck_sessions_visitor_requires_widget CHECK (
        (visitor_id IS NULL) = (widget_id IS NULL)
    ) NOT VALID
"""


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


def _install_question_log_cleanup() -> None:
    op.execute(_QUESTION_LOG_CLEANUP_FUNCTION)
    # Dropping an existing trigger on a re-run needs ACCESS EXCLUSIVE.
    _with_immediate_locks(
        ("questions IN ACCESS EXCLUSIVE MODE",), _QUESTION_LOG_CLEANUP_TRIGGER
    )


def _create_index_concurrently(name: str, table: str, columns: str) -> None:
    # A failed CREATE INDEX CONCURRENTLY leaves an INVALID index behind;
    # dropping it first lets a re-run rebuild it.
    op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
    op.execute(f"CREATE INDEX CONCURRENTLY {name} ON {table} {columns}")


def upgrade() -> None:
    with op.get_context().autocommit_block():
        # ck_sessions_user_xor_api_key is missing on some older databases.
        _with_immediate_locks(
            (
                "sessions IN ACCESS EXCLUSIVE MODE",
                "widgets IN SHARE ROW EXCLUSIVE MODE",
            ),
            (_SESSION_PRINCIPALS,),
        )
        for constraint in _SESSION_CONSTRAINTS:
            op.execute(f"ALTER TABLE sessions VALIDATE CONSTRAINT {constraint}")
        _create_index_concurrently(
            "ix_sessions_widget_visitor_created",
            "sessions",
            "(widget_id, visitor_id, created_at DESC)",
        )
        # The cleanup trigger looks up other owners of a log on every delete.
        _create_index_concurrently(
            "ix_questions_logging_details_id", "questions", "(logging_details_id)"
        )
        _install_question_log_cleanup()


def downgrade() -> None:
    # Widget sessions cannot satisfy the restored two-principal check. Deleting
    # them while the trigger exists also deletes their questions' logs.
    op.execute("DELETE FROM sessions WHERE widget_id IS NOT NULL")
    op.execute("DROP TRIGGER IF EXISTS delete_question_owned_log ON questions")
    op.execute("DROP FUNCTION IF EXISTS delete_question_owned_log()")
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_questions_logging_details_id")
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS ix_sessions_widget_visitor_created"
        )
    op.execute(
        """
        ALTER TABLE sessions
            DROP CONSTRAINT ck_sessions_visitor_requires_widget,
            DROP CONSTRAINT ck_sessions_single_principal,
            DROP CONSTRAINT sessions_widget_id_fkey,
            DROP COLUMN visitor_id,
            DROP COLUMN widget_id,
            ADD CONSTRAINT ck_sessions_user_xor_api_key
                CHECK ((user_id IS NOT NULL) <> (api_key_id IS NOT NULL))
        """
    )
