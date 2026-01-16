"""
Revision ID: 20260116_update_audit_actor_fk
Revises: d8103542e81d
Create Date: 2026-01-16
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic
revision = "20260116_update_audit_actor_fk"
down_revision = "d8103542e81d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("audit_logs_actor_id_fkey", "audit_logs", type_="foreignkey")
    op.alter_column(
        "audit_logs",
        "actor_id",
        existing_type=UUID(as_uuid=True),
        nullable=True,
    )
    op.create_foreign_key(
        "audit_logs_actor_id_fkey",
        "audit_logs",
        "users",
        ["actor_id"],
        ["id"],
        ondelete="SET NULL",
    )
    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_audit_target_user_id
            ON audit_logs (tenant_id, (metadata->'target'->>'id'))
            WHERE deleted_at IS NULL;
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    null_actor_count = int(
        bind.execute(
            sa.text("SELECT COUNT(*) FROM audit_logs WHERE actor_id IS NULL")
        ).scalar()
        or 0
    )
    if null_actor_count:
        raise RuntimeError(
            "Cannot downgrade: audit_logs contains rows with NULL actor_id. "
            "Delete or reassign those rows before downgrading."
        )

    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_audit_target_user_id;")

    op.drop_constraint("audit_logs_actor_id_fkey", "audit_logs", type_="foreignkey")
    op.alter_column(
        "audit_logs",
        "actor_id",
        existing_type=UUID(as_uuid=True),
        nullable=False,
    )
    op.create_foreign_key(
        "audit_logs_actor_id_fkey",
        "audit_logs",
        "users",
        ["actor_id"],
        ["id"],
        ondelete="CASCADE",
    )
