"""Change session
Revision ID: 6ac6f2cbf0b6
Revises: e0e55673e20a
Create Date: 2023-05-05 15:47:59.268078
"""

import sqlalchemy as sa

from alembic import op
from eneo.database.alembic_utils import timestamps

# revision identifiers, used by Alembic
revision = "6ac6f2cbf0b6"
down_revision = "e0e55673e20a"
branch_labels = None
depends_on = None


def create_references_table():
    op.create_table(
        "info_blob_references",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "question_id", sa.Integer, sa.ForeignKey("questions.id", ondelete="CASCADE")
        ),
        sa.Column("reference", sa.Text, nullable=False),
        *timestamps(),
    )
    op.execute(
        """
        CREATE TRIGGER update_reference_modtime
            BEFORE UPDATE
            ON
                info_blob_references
            FOR EACH ROW
        EXECUTE PROCEDURE update_updated_at_column();
        """
    )


def upgrade() -> None:
    # Questions
    # Drop
    op.drop_column("questions", "text")
    op.drop_column("questions", "session")
    op.drop_column("questions", "owner")

    # Add
    op.add_column("questions", sa.Column("question", sa.Text, nullable=False))
    op.add_column("questions", sa.Column("answer", sa.Text, nullable=False))
    op.add_column(
        "questions",
        sa.Column(
            "session_id", sa.Integer, sa.ForeignKey("sessions.id", ondelete="CASCADE")
        ),
    )

    # Sessions
    # Drop
    op.drop_column("sessions", "text")

    # References
    create_references_table()


def downgrade() -> None:
    op.drop_table("info_blob_references")
    op.drop_column("questions", "question")
    op.drop_column("questions", "answer")
    op.drop_column("questions", "session_id")
