"""Index exhausted dispatches, approved reviews, and missing-checkpoint discovery.

Revision ID: 202609211000
Revises: 202609201300
"""

import sqlalchemy as sa

from alembic import op

revision = "202609211000"
down_revision = "202609201300"
branch_labels = None
depends_on = None

_INDEXES = (
    (
        "ix_flow_runs_exhausted_dispatch_wait",
        "flow_runs",
        ["dispatch_pending_since", "id"],
        ["tenant_id", "revision"],
        "status = 'queued' AND dispatch_exhausted_at IS NOT NULL",
    ),
    (
        "ix_flow_runs_awaiting_review_created",
        "flow_runs",
        ["created_at", "id"],
        ["tenant_id", "revision"],
        "status = 'awaiting_review'",
    ),
    (
        "ix_flow_review_approved_wait",
        "flow_run_review_checkpoints",
        ["approved_at", "flow_run_id"],
        ["tenant_id", "id"],
        "state = 'approved'",
    ),
)


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '5s'")
        try:
            for name, table, columns, include, predicate in _INDEXES:
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
                    op.drop_index(name, table_name=table, postgresql_concurrently=True)
                op.create_index(
                    name,
                    table,
                    columns,
                    postgresql_include=include,
                    postgresql_where=sa.text(predicate),
                    postgresql_concurrently=True,
                    if_not_exists=True,
                )
        finally:
            op.execute("RESET lock_timeout")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '5s'")
        try:
            for name, table, *_ in reversed(_INDEXES):
                op.drop_index(
                    name,
                    table_name=table,
                    postgresql_concurrently=True,
                    if_exists=True,
                )
        finally:
            op.execute("RESET lock_timeout")
