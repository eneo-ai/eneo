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
    op.create_index(
        "idx_audit_target_user_id",
        "audit_logs",
        ["tenant_id", sa.text("(metadata->'target'->>'id')")],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.execute("DELETE FROM audit_logs WHERE actor_id IS NULL")
    op.drop_index("idx_audit_target_user_id", table_name="audit_logs")
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
