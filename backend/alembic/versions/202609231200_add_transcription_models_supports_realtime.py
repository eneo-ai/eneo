"""Let an admin mark a transcription model as able to transcribe live audio.

Revision ID: 202609231200
Revises: 202609211400
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202609231200"
down_revision: str | None = "202609211400"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column(
        "transcription_models",
        sa.Column(
            "supports_realtime", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_column("transcription_models", "supports_realtime")
