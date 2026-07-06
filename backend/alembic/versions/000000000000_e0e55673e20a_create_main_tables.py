"""create_main_tables
Revision ID: e0e55673e20a
Revises:
Create Date: 2023-04-01 13:41:15.284927
"""

import sqlalchemy as sa

from alembic import op
from eneo.database.alembic_utils import timestamps

# revision identifiers, used by Alembic
revision = "e0e55673e20a"
down_revision = None
branch_labels = None
depends_on = None


def create_updated_at_trigger() -> None:
    # Trigger that will run every time a row in a table is updated
    # and change the updated_at column to reflect when it was updated
    op.execute(
        """
        CREATE OR REPLACE FUNCTION update_updated_at_column()
            RETURNS TRIGGER AS
        $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ language 'plpgsql';
        """
    )


def create_users_table() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("username", sa.Text, unique=True, nullable=False, index=True),
        sa.Column("email", sa.Text, unique=True, nullable=False, index=True),
        sa.Column("email_verified", sa.Boolean, nullable=False, server_default="False"),
        sa.Column("salt", sa.Text, nullable=False),
        sa.Column("password", sa.Text, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="True"),
        sa.Column("is_superuser", sa.Boolean(), nullable=False, server_default="False"),
        *timestamps(),
    )
    op.execute(
        """
        CREATE TRIGGER update_user_modtime
            BEFORE UPDATE
            ON users
            FOR EACH ROW
        EXECUTE PROCEDURE update_updated_at_column();
        """
    )


def create_profiles_table() -> None:
    op.create_table(
        "profiles",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("full_name", sa.Text, nullable=True),
        sa.Column("image", sa.Text, nullable=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE")),
        *timestamps(),
    )
    op.execute(
        """
        CREATE TRIGGER update_profiles_modtime
            BEFORE UPDATE
            ON profiles
            FOR EACH ROW
        EXECUTE PROCEDURE update_updated_at_column();
        """
    )


def create_questions_table() -> None:
    op.create_table(
        "questions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("session", sa.Text, nullable=True),
        sa.Column("owner", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE")),
        *timestamps(),
    )
    op.execute(
        """
        CREATE TRIGGER update_question_modtime
            BEFORE UPDATE
            ON questions
            FOR EACH ROW
        EXECUTE PROCEDURE update_updated_at_column();
        """
    )


def create_sessions_table():
    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("name", sa.Text, nullable=False),
        *timestamps(),
    )

    op.execute(
        """
        CREATE TRIGGER update_session_modtime
            BEFORE UPDATE
            ON sessions
            FOR EACH ROW
        EXECUTE PROCEDURE update_updated_at_column();
        """
    )


def create_info_blobs_table():
    op.create_table(
        "info_blobs",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("path", sa.Text, nullable=False, unique=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("title", sa.Text, nullable=True),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("url", sa.Text, nullable=True),
        sa.Column("author", sa.Text, nullable=False),
        *timestamps(),
    )

    op.execute(
        """
        CREATE TRIGGER update_info_blob_modtime
            BEFORE UPDATE
            ON info_blobs
            FOR EACH ROW
        EXECUTE PROCEDURE update_updated_at_column();
        """
    )


def upgrade() -> None:
    create_updated_at_trigger()
    create_users_table()
    create_profiles_table()
    create_questions_table()
    create_sessions_table()
    create_info_blobs_table()


def downgrade() -> None:
    op.drop_table("info_blobs")
    op.drop_table("questions")
    op.drop_table("profiles")
    op.drop_table("sessions")
    op.drop_table("users")
    op.execute("DROP FUNCTION update_updated_at_column")
