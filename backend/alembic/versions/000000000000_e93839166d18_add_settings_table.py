"""add settings table
Revision ID: e93839166d18
Revises: a9713bb4941e
Create Date: 2023-06-04 20:22:35.653752
"""

import sqlalchemy as sa

from alembic import op
from eneo.database.alembic_utils import timestamps

# revision identifiers, used by Alembic
revision = "e93839166d18"
down_revision = "a9713bb4941e"
branch_labels = None
depends_on = None

SETTINGS_TABLE_NAME = "settings"


def create_settings_table():
    op.create_table(
        SETTINGS_TABLE_NAME,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("chat_model", sa.Text, nullable=True),
        *timestamps()
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
        % SETTINGS_TABLE_NAME
    )


def upgrade() -> None:
    create_settings_table()


def downgrade() -> None:
    op.drop_table(SETTINGS_TABLE_NAME)
