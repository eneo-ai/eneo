"""give each browser session a stable id beside its sid

Revision ID: 202611091000
Revises: 202611081500
Create Date: 2026-11-09 10:00:00.000000

The id becomes the primary key; the sid stays, unique and required, as the
secret a token presents. Existing rows get an id from the database, and the
sessions they record stay admitted: a token issued before this revision
carries the sid alone, which is still how such a token is matched.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202611091000"
down_revision: str | None = "202611081500"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "browser_sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
    )
    # Unique first, so the sid is never without a constraint.
    op.create_unique_constraint("browser_sessions_sid_key", "browser_sessions", ["sid"])
    op.drop_constraint("browser_sessions_pkey", "browser_sessions", type_="primary")
    op.create_primary_key("browser_sessions_pkey", "browser_sessions", ["id"])


def downgrade() -> None:
    op.drop_constraint("browser_sessions_pkey", "browser_sessions", type_="primary")
    op.create_primary_key("browser_sessions_pkey", "browser_sessions", ["sid"])
    op.drop_constraint("browser_sessions_sid_key", "browser_sessions", type_="unique")
    op.drop_column("browser_sessions", "id")
