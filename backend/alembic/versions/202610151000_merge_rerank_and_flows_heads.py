"""Merge the develop head and the Flow copy-input head.

Flow migrations are applied after every develop migration up to
202610191600 (integration knowledge sync failures).

Revision ID: 202610151000
Revises: 202610191600, 202610142100
Create Date: 2026-10-15 10:00:00.000000
"""

revision: str = "202610151000"
down_revision: tuple[str, str] = ("202610191600", "202610142100")
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
