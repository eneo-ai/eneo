"""Let widgets follow a published template that locks what it governs.

Revision ID: 202609211000
Revises: 202609181500
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "202609211000"
down_revision = "202609181500"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "widget_templates",
        sa.Column(
            "locked_groups",
            JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column("widget_templates", sa.Column("published", JSONB(), nullable=True))
    op.add_column(
        "widget_templates",
        sa.Column("published_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "widget_templates",
        sa.Column("published_by_user_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_widget_templates_published_by_user_id",
        "widget_templates",
        "users",
        ["published_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # Templates that exist already were in use as they stood: treat them as
    # published without locks, so creating widgets from them keeps working
    # and nothing is pushed onto any widget until an admin decides to.
    op.execute(
        """
        UPDATE widget_templates
        SET published = jsonb_build_object(
                'texts', texts,
                'theme', theme,
                'language', language,
                'locked_groups', '[]'::jsonb
            ),
            published_at = now()
        """
    )

    op.add_column(
        "widgets",
        sa.Column("template_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_widgets_template_id",
        "widgets",
        "widget_templates",
        ["template_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_widgets_template_id", "widgets", ["template_id"])


def downgrade() -> None:
    op.drop_index("ix_widgets_template_id", table_name="widgets")
    op.drop_constraint("fk_widgets_template_id", "widgets", type_="foreignkey")
    op.drop_column("widgets", "template_id")
    op.drop_constraint(
        "fk_widget_templates_published_by_user_id",
        "widget_templates",
        type_="foreignkey",
    )
    op.drop_column("widget_templates", "published_by_user_id")
    op.drop_column("widget_templates", "published_at")
    op.drop_column("widget_templates", "published")
    op.drop_column("widget_templates", "locked_groups")
