"""grant assistant debug permission to trusted predefined roles

Revision ID: 202607261730
Revises: 202607261700
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202607261730"
down_revision: str | None = "202607261700"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        UPDATE roles
        SET permissions = array_append(permissions, 'assistant_debug')
        WHERE predefined_source IN ('Owner', 'AI Configurator')
          AND NOT ('assistant_debug' = ANY(permissions))
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE roles
        SET permissions = array_remove(permissions, 'assistant_debug')
        WHERE predefined_source IN ('Owner', 'AI Configurator')
    """)
