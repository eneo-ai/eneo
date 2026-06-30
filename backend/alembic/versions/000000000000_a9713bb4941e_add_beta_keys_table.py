"""Add beta-keys table
Revision ID: a9713bb4941e
Revises: 815ff63679e2
Create Date: 2023-05-24 19:56:19.433859
"""

import sqlalchemy as sa

from alembic import op
from eneo.database.alembic_utils import timestamps

# revision identifiers, used by Alembic
revision = "a9713bb4941e"
down_revision = "815ff63679e2"
branch_labels = None
depends_on = None

BETA_KEYS_TABLE_NAME = "beta_keys"


def create_beta_keys_table():
    op.create_table(
        BETA_KEYS_TABLE_NAME,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("key", sa.Text, nullable=False),
        sa.Column("used", sa.Boolean, nullable=False),
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
        % (BETA_KEYS_TABLE_NAME)
    )


def upgrade() -> None:
    create_beta_keys_table()


def downgrade() -> None:
    op.drop_table(BETA_KEYS_TABLE_NAME)
