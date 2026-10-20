"""flow revisions

Every save of a flow's name, description or definition is kept as a
revision a person can read later and restore. A published version records
the revision it froze.

Revision ID: 202610201200
Revises: 202610201100
Create Date: 2026-10-20 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision: str = "202610201200"
down_revision: str | None = "202610201100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "flow_revisions",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("definition", JSONB(), nullable=False),
        sa.Column("principal_type", sa.String(), nullable=False, server_default="user"),
        sa.Column(
            "principal_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("principal_service_id", UUID(as_uuid=True), nullable=True),
        sa.Column("channel", sa.String(), nullable=False, server_default="api"),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column(
            "flow_id",
            UUID(as_uuid=True),
            sa.ForeignKey("flows.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "flow_id", "revision", name="uq_flow_revisions_flow_revision"
        ),
    )
    op.add_column("flow_versions", sa.Column("revision", sa.Integer(), nullable=True))
    # Flows that exist already start their history at revision 1 as they are.
    op.execute(
        sa.text(
            """
            INSERT INTO flow_revisions
                (flow_id, revision, name, description, definition,
                 principal_type, principal_user_id, channel, created_at, updated_at)
            SELECT id, 1, name, description, definition,
                   'user', user_id, 'api', updated_at, updated_at
            FROM flows
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE flow_versions AS v
            SET revision = 1
            FROM flows AS f
            WHERE v.flow_id = f.id
              AND v.version = f.published_version
              AND v.definition = f.definition
            """
        )
    )


def downgrade() -> None:
    op.drop_column("flow_versions", "revision")
    op.drop_table("flow_revisions")
