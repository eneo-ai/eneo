"""add tenant_space_id to spaces
Revision ID: 5da161e2e38b
Revises: 1e58cb567f44
Create Date: 2025-08-15 06:32:59.958945
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic
revision = '5da161e2e38b'
down_revision = '1e58cb567f44'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column(
        "spaces",
        sa.Column("tenant_space_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "spaces_tenant_space_fkey",
        "spaces",
        "spaces",
        local_cols=["tenant_space_id"],
        remote_cols=["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_spaces_tenant_space_id", "spaces", ["tenant_space_id"])


def downgrade() -> None:
    op.drop_index("ix_spaces_tenant_space_id", table_name="spaces")
    op.drop_constraint("spaces_tenant_space_fkey", "spaces", type_="foreignkey")
    op.drop_column("spaces", "tenant_space_id")