"""Durable widget budgets, optimistic revisions and question-owned log cleanup.

Revision ID: 202609171600
Revises: 202609171500
"""

import sqlalchemy as sa

from alembic import op

revision = "202609171600"
down_revision = "202609171500"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "widgets",
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "widget_daily_usage",
        sa.Column("reserved_tokens", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "ck_widget_usage_reserved_tokens", "widget_daily_usage", "reserved_tokens >= 0"
    )
    op.create_table(
        "widget_budget_reservations",
        sa.Column(
            "id",
            sa.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "widget_id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("tokens", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(), nullable=False, server_default="reserved"),
        sa.ForeignKeyConstraint(
            ["widget_id", "day"],
            ["widget_daily_usage.widget_id", "widget_daily_usage.day"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("tokens >= 0", name="ck_widget_reservation_tokens"),
        sa.CheckConstraint(
            "state IN ('reserved', 'settled', 'released')",
            name="ck_widget_reservation_state",
        ),
    )
    op.create_index(
        "ix_widget_budget_reservations_day", "widget_budget_reservations", ["day"]
    )
    # Question deletion (including FK cascades from sessions/assistants/spaces)
    # owns deletion of its private log. Shared logs remain until the last owner
    # disappears. Do not sweep old unowned logs: their provenance is unknown.
    op.create_index(
        "ix_questions_logging_details_id", "questions", ["logging_details_id"]
    )
    op.execute("""
        CREATE FUNCTION delete_question_owned_log() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            DELETE FROM logging
            WHERE id = OLD.logging_details_id
              AND NOT EXISTS (
                  SELECT 1 FROM questions WHERE logging_details_id = OLD.logging_details_id
              );
            RETURN NULL;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER delete_question_owned_log
        AFTER DELETE ON questions FOR EACH ROW
        WHEN (OLD.logging_details_id IS NOT NULL)
        EXECUTE FUNCTION delete_question_owned_log()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER delete_question_owned_log ON questions")
    op.execute("DROP FUNCTION delete_question_owned_log()")
    op.drop_index("ix_questions_logging_details_id", table_name="questions")
    op.drop_table("widget_budget_reservations")
    op.drop_constraint(
        "ck_widget_usage_reserved_tokens", "widget_daily_usage", type_="check"
    )
    op.drop_column("widget_daily_usage", "reserved_tokens")
    op.drop_column("widgets", "revision")
