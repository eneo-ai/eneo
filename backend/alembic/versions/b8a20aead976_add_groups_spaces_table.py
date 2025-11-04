"""add groups_spaces table
Revision ID: b8a20aead976
Revises: 8cf9fcbc40fb
Create Date: 2025-08-19 10:42:14.577930
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg


# revision identifiers, used by Alembic
revision = 'b8a20aead976'
down_revision = '8cf9fcbc40fb'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "groups_spaces",
        sa.Column("group_id", pg.UUID(as_uuid=True), sa.ForeignKey("groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("space_id", pg.UUID(as_uuid=True), sa.ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("group_id", "space_id", name="pk_groups_spaces"),
    )

    op.create_index("ix_groups_spaces_space_id", "groups_spaces", ["space_id"])
    op.create_index("ix_groups_spaces_group_id", "groups_spaces", ["group_id"])

    # Backfill så att befintliga grupper även får en rad i groups_spaces
    op.execute("""
        INSERT INTO groups_spaces (group_id, space_id)
        SELECT id, space_id
        FROM groups
        WHERE space_id IS NOT NULL
        ON CONFLICT DO NOTHING;
    """)


def downgrade():
    op.drop_index("ix_groups_spaces_group_id", table_name="groups_spaces")
    op.drop_index("ix_groups_spaces_space_id", table_name="groups_spaces")
    op.drop_table("groups_spaces")