"""add flow-managed assistant ownership

Revision ID: 1d7f1a43c0c2
Revises: 579199d395dd
Create Date: 2026-03-01 15:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "1d7f1a43c0c2"
down_revision = "579199d395dd"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "assistants",
        sa.Column(
            "origin",
            sa.String(length=32),
            nullable=False,
            server_default="user",
        ),
    )
    op.add_column(
        "assistants",
        sa.Column("managing_flow_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    op.create_foreign_key(
        "fk_assistants_managing_flow_id_flows",
        "assistants",
        "flows",
        ["managing_flow_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_check_constraint(
        "ck_assistants_origin",
        "assistants",
        "origin IN ('user','flow_managed')",
    )
    op.create_check_constraint(
        "ck_assistants_origin_flow_owner",
        "assistants",
        "(origin = 'user' AND managing_flow_id IS NULL) OR "
        "(origin = 'flow_managed' AND managing_flow_id IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_assistants_flow_managed_hidden",
        "assistants",
        "origin <> 'flow_managed' OR hidden = true",
    )
    op.create_index(
        "ix_assistants_origin_managing_flow",
        "assistants",
        ["origin", "managing_flow_id"],
        unique=False,
    )

    conn = op.get_bind()
    conflicting_rows = conn.execute(
        sa.text(
            """
            SELECT assistant_id
            FROM flow_steps
            GROUP BY assistant_id
            HAVING COUNT(DISTINCT flow_id) > 1
            """
        )
    ).fetchall()
    if conflicting_rows:
        conflicting_ids = ", ".join(str(row[0]) for row in conflicting_rows[:10])
        raise RuntimeError(
            "Flow assistant ownership backfill conflict: assistants linked to multiple flows. "
            f"Example assistant IDs: {conflicting_ids}"
        )

    conn.execute(
        sa.text(
            """
            UPDATE assistants AS a
            SET origin = 'flow_managed',
                managing_flow_id = flow_refs.flow_id,
                hidden = true
            FROM (
                SELECT DISTINCT ON (assistant_id) assistant_id, flow_id
                FROM flow_steps
                ORDER BY assistant_id, flow_id
            ) AS flow_refs
            WHERE a.id = flow_refs.assistant_id
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_assistants_origin_managing_flow", table_name="assistants")
    op.drop_constraint("ck_assistants_flow_managed_hidden", "assistants", type_="check")
    op.drop_constraint("ck_assistants_origin_flow_owner", "assistants", type_="check")
    op.drop_constraint("ck_assistants_origin", "assistants", type_="check")
    op.drop_constraint(
        "fk_assistants_managing_flow_id_flows",
        "assistants",
        type_="foreignkey",
    )
    op.drop_column("assistants", "managing_flow_id")
    op.drop_column("assistants", "origin")
