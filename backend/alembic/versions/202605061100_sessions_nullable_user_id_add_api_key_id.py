"""sessions: nullable user_id + add api_key_id + XOR check

Service API keys resolve to a synthetic UserInDB whose id is never inserted
into ``users``. Writing that synthetic id into ``sessions.user_id`` (NOT NULL
FK to ``users.id``) blew up /ask with a ForeignKeyViolationError, surfacing
as a 500 on every question asked through a pk_ service key.

This migration:
1. Drops NOT NULL on ``sessions.user_id`` so service-key sessions can omit it.
2. Adds ``sessions.api_key_id`` (FK to ``api_keys_v2.id``, ON DELETE SET NULL)
   so service-key sessions still have an owning principal recorded for
   ownership checks and audit.
3. Indexes ``api_key_id`` for the ownership-check query path.
4. Enforces the application invariant — exactly one of ``user_id`` /
   ``api_key_id`` is set per row — as a DB CHECK constraint. The ORM mapping
   in ``sessions_table.py`` mirrors the same constraint so model-driven
   setups stay in sync. Without this guard, a future regression in any
   write path (or a manual tweak) could land a NULL/NULL row that is
   invisible to user-scoped listings and dereferences nothing useful.

Revision ID: 202605061100
Revises: 202604291030
Create Date: 2026-05-06
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic
revision = "202605061100"
down_revision = "202604291030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "sessions",
        "user_id",
        existing_type=sa.dialects.postgresql.UUID(),
        nullable=True,
    )
    op.add_column(
        "sessions",
        sa.Column(
            "api_key_id",
            sa.dialects.postgresql.UUID(),
            sa.ForeignKey("api_keys_v2.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_sessions_api_key_id",
        "sessions",
        ["api_key_id"],
        unique=False,
    )
    op.create_check_constraint(
        "ck_sessions_user_xor_api_key",
        "sessions",
        "(user_id IS NOT NULL) <> (api_key_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_sessions_user_xor_api_key", "sessions", type_="check"
    )
    # Service-key sessions (user_id NULL, api_key_id set) can't be represented
    # in the pre-migration schema where user_id is NOT NULL. Purge them BEFORE
    # dropping api_key_id — otherwise the column is gone and there is no way
    # to tell service-key sessions apart from corrupted user sessions when the
    # SET NOT NULL below fails on the remaining NULLs.
    #
    # DATA LOSS: every service-key session and its questions (CASCADE via
    # Questions.session_id) is deleted by this downgrade. Operators rolling
    # back this migration in production should snapshot the sessions and
    # questions tables first; the rows cannot be reconstructed afterwards.
    result = op.get_bind().execute(
        sa.text("SELECT COUNT(*) FROM sessions WHERE user_id IS NULL")
    )
    purge_count = result.scalar() or 0
    if purge_count:
        # Surface the impact in the alembic log so the operator sees how
        # many service-key sessions are about to be dropped.
        print(  # noqa: T201
            f"[downgrade] purging {purge_count} service-key sessions "
            "(and their questions via CASCADE) — these cannot be recovered."
        )
    op.execute("DELETE FROM sessions WHERE user_id IS NULL")
    op.execute("ALTER TABLE sessions ALTER COLUMN user_id SET NOT NULL")
    op.drop_index("ix_sessions_api_key_id", table_name="sessions")
    op.drop_column("sessions", "api_key_id")
