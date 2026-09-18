"""rename widget texts after where they sit rather than their legal purpose

Revision ID: 202609171500
Revises: 202609171400
Create Date: 2026-09-17 15:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202609171500"
down_revision: str | None = "202609171400"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RENAMES = {
    "ai_disclosure": "subtitle",
    "personal_data_notice": "footer_text",
    "privacy_url": "footer_link_url",
}


def _rename(table: str, renames: dict[str, str]) -> None:
    # `texts` is JSONB and the model forbids unknown keys, so every stored
    # document must carry the new names.
    for old, new in renames.items():
        op.execute(
            sa.text(
                f"UPDATE {table} SET texts = (texts - :old) || "
                f"jsonb_build_object(:new, texts -> :old) WHERE texts ? :old"
            ).bindparams(old=old, new=new)
        )


def upgrade() -> None:
    for table in ("widgets", "widget_templates"):
        _rename(table, _RENAMES)


def downgrade() -> None:
    for table in ("widgets", "widget_templates"):
        _rename(table, {new: old for old, new in _RENAMES.items()})
        op.execute(sa.text(f"UPDATE {table} SET texts = texts - 'footer_link_label'"))
