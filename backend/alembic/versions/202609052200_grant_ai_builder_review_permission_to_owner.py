"""grant flows_ai_builder_review to existing Owner roles

Revision ID: 202609052200
Revises: 202609041000
Create Date: 2026-09-05 22:00:00.000000

Reviewing a published flow's runs with the AI Builder becomes its own role
permission so an organisation can decide who gets the feature. New
organisations receive it from the predefined Owner template; this migration
converges existing Owner roles. Custom roles and AI Configurator remain
unchanged so delegation is always explicit.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202609052200"
down_revision: str = "202609041000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE roles SET permissions = "
            "array_append(permissions, 'flows_ai_builder_review') "
            "WHERE predefined_source = 'Owner' "
            "AND NOT ('flows_ai_builder_review' = ANY(permissions))"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE roles SET permissions = "
            "array_remove(permissions, 'flows_ai_builder_review') "
            "WHERE predefined_source = 'Owner'"
        )
    )
