"""Let widgets follow a template and let templates lock what they govern.

Revision ID: 202609211000
Revises: 202609181000
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "202609211000"
down_revision = "202609181000"
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
    op.drop_column("widget_templates", "locked_groups")
