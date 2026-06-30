"""create groups
Revision ID: a244a4aa2d8c
Revises: 6ac6f2cbf0b6
Create Date: 2023-05-06 16:39:41.658568
"""

import sqlalchemy as sa

from alembic import op

# from baseline import timestamps
from eneo.database.alembic_utils import timestamps

# revision identifiers, used by Alembic
revision = "a244a4aa2d8c"
down_revision = "6ac6f2cbf0b6"
branch_labels = None
depends_on = None

GROUPS_TABLE_NAME = "groups"


def create_groups_table():
    op.create_table(
        GROUPS_TABLE_NAME,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("name", sa.Text, nullable=False),
        *timestamps(),
    )
    op.execute(
        """
        CREATE TRIGGER update_reference_modtime
            BEFORE UPDATE
            ON
                %s
            FOR EACH ROW
        EXECUTE PROCEDURE update_updated_at_column();
        """
        % (GROUPS_TABLE_NAME)
    )


def upgrade() -> None:
    # Create tables
    create_groups_table()

    # Add column to infoblob
    op.add_column(
        "info_blobs",
        sa.Column(
            "group_id",
            sa.Integer,
            sa.ForeignKey("groups.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    # Drop tables
    op.drop_column("info_blobs", "group_id")
    op.drop_table(GROUPS_TABLE_NAME)
