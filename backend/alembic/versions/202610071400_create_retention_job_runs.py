"""Create generic retention bookkeeping and complete adopter keysets.

Revision ID: 202610071400
Revises: 202610161000
Build indexes on existing tables concurrently (the retention keysets, and the
question index info_blob_references lacks) before removing their shorter
prefixes, then create the new bookkeeping table transactionally. An interrupted
online build retries invalid indexes; offline SQL assumes no invalid leftovers.
No product data or foreign keys change. Downgrade restores the prefix indexes
and removes execution history and cursors, so later executions start new passes.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202610071400"
down_revision: str = "202610161000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_INDEXES = (
    (
        "ix_files_root_created_id",
        "files",
        ("created_at", "id"),
        "parent_file_id IS NULL",
    ),
    ("ix_files_parent_file_id_id", "files", ("parent_file_id", "id"), None),
    (
        "ix_questions_retention_owner_created_id",
        "questions",
        ("assistant_id", "created_at", "id"),
        None,
    ),
    (
        "ix_app_runs_retention_owner_created_id",
        "app_runs",
        ("app_id", "created_at", "id"),
        None,
    ),
    ("ix_sessions_created_id", "sessions", ("created_at", "id"), None),
    # Bounds the proof and the cascade of a question's citations.
    (
        "ix_info_blob_references_question_id",
        "info_blob_references",
        ("question_id",),
        None,
    ),
)
_OLD_INDEXES = (
    ("ix_files_parent_file_id", "files", ("parent_file_id",), None),
    (
        "ix_questions_assistant_created",
        "questions",
        ("assistant_id", "created_at"),
        None,
    ),
    (
        "idx_questions_assistant_created",
        "questions",
        ("assistant_id", "created_at"),
        None,
    ),
    ("ix_app_runs_app_created", "app_runs", ("app_id", "created_at"), None),
    ("created_at_idx", "sessions", ("created_at",), None),
    ("idx_sessions_created_at", "sessions", ("created_at",), None),
)


def _replace_indexes(
    create: tuple[tuple[str, str, tuple[str, ...], str | None], ...],
    drop: tuple[tuple[str, str, tuple[str, ...], str | None], ...],
) -> None:
    # No lock_timeout here: a concurrent build waits for every older transaction
    # that touched the table, and a timeout would cancel it on a busy database
    # and leave an invalid index. Its own locks do not block application writers.
    with op.get_context().autocommit_block():
        for name, table, columns, predicate in create:
            if not op.get_context().as_sql:
                valid = (
                    op.get_bind()
                    .execute(
                        sa.text(
                            "SELECT indisvalid FROM pg_index WHERE indexrelid = to_regclass(:name)"
                        ),
                        {"name": name},
                    )
                    .scalar()
                )
                if valid is False:
                    op.drop_index(
                        name,
                        table_name=table,
                        postgresql_concurrently=True,
                        if_exists=True,
                    )
            op.create_index(
                name,
                table,
                list(columns),
                postgresql_where=sa.text(predicate) if predicate is not None else None,
                postgresql_concurrently=True,
                if_not_exists=True,
            )
        for name, table, _columns, _predicate in drop:
            op.drop_index(
                name, table_name=table, postgresql_concurrently=True, if_exists=True
            )


def upgrade() -> None:
    # Concurrent builds commit independently; keep the new table in the final
    # versioned transaction so an interrupted build can retry this revision.
    _replace_indexes(_NEW_INDEXES, _OLD_INDEXES)
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        "retention_job_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("task", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "batch_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "counts",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "blocked",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "cursors",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("overdue_observed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("overdue_count", sa.Integer(), nullable=True),
        sa.Column("overdue_complete", sa.Boolean(), nullable=True),
        sa.Column("overdue_oldest_due_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "outcome IN ('failed', 'partial', 'running', 'skipped', 'succeeded', 'superseded')",
            name="ck_retention_job_runs_outcome",
        ),
        sa.CheckConstraint(
            "(outcome = 'running') = (finished_at IS NULL)",
            name="ck_retention_job_runs_finished",
        ),
        sa.CheckConstraint(
            "error_code IS NULL OR error_code IN ('chunk_deadlock', 'chunk_failed', "
            "'chunk_timeout', 'claim_timeout', 'contract_violation', "
            "'disabled_by_deployment_setting', 'finish_timeout')",
            name="ck_retention_job_runs_error_code",
        ),
        sa.CheckConstraint(
            "task ~ '^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)*$'",
            name="ck_retention_job_runs_task",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(cursors) = 'object'", name="ck_retention_job_runs_cursors"
        ),
        sa.CheckConstraint(
            "(overdue_observed_at IS NULL) = (overdue_count IS NULL) "
            "AND (overdue_observed_at IS NULL) = (overdue_complete IS NULL) "
            "AND (overdue_count IS NULL OR overdue_count >= 0) "
            "AND COALESCE(overdue_count > 0, false) = (overdue_oldest_due_at IS NOT NULL)",
            name="ck_retention_job_runs_overdue",
        ),
    )
    op.create_index(
        "uq_retention_job_runs_running_task",
        "retention_job_runs",
        ["task"],
        unique=True,
        postgresql_where=sa.text("outcome = 'running'"),
    )
    op.create_index(
        "ix_retention_job_runs_task_started_at",
        "retention_job_runs",
        ["task", sa.text("started_at DESC"), sa.text("id DESC")],
    )
    op.create_index(
        "ix_retention_job_runs_task_finished_at",
        "retention_job_runs",
        ["task", sa.text("finished_at DESC")],
    )
    op.create_index(
        "ix_retention_job_runs_task_overdue_observed_at",
        "retention_job_runs",
        ["task", sa.text("overdue_observed_at DESC")],
        postgresql_where=sa.text("overdue_observed_at IS NOT NULL"),
    )
    op.create_index(
        "ix_retention_job_runs_finished_at", "retention_job_runs", ["finished_at"]
    )


def downgrade() -> None:
    _replace_indexes(_OLD_INDEXES, _NEW_INDEXES)
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_table("retention_job_runs")
