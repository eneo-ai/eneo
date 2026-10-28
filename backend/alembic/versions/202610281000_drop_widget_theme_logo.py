"""drop the widget header logo

The panel header shows the organisation's title and AI disclosure; the persona
says who answers and a "powered by" line belongs in the footer text, so the
header logo (an external image address, plus a file id the first schema
reserved and never populated) is retired. ``WidgetTheme`` forbids unknown keys
and every stored theme is rehydrated through it, so the two keys are stripped
from widgets, template drafts and the release inside
``widget_templates.published`` before the model loses the fields.

Revision ID: 202610281000
Revises: 202610271100
Create Date: 2026-10-28 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202610281000"
down_revision: str | None = "202610271100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LOGO_KEYS = "ARRAY['logo_url', 'logo_file_id']"


def upgrade() -> None:
    for table in ("widgets", "widget_templates"):
        op.execute(
            sa.text(
                f"UPDATE {table} SET theme = theme - 'logo_url' - 'logo_file_id' "
                f"WHERE theme ?| {_LOGO_KEYS}"
            )
        )
    op.execute(
        sa.text(
            "UPDATE widget_templates SET published = jsonb_set("
            "published, '{theme}', (published -> 'theme') - 'logo_url' - 'logo_file_id'"
            ") WHERE jsonb_typeof(published -> 'theme') = 'object' "
            f"AND (published -> 'theme') ?| {_LOGO_KEYS}"
        )
    )


def downgrade() -> None:
    # The previous model treats a missing logo as "none"; the stripped
    # addresses are gone for good.
    pass
