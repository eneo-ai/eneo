"""Keep the audio length measured at a runtime upload.

Revision ID: 202609271200
Revises: 202609241200
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202609271200"
down_revision: str | None = "202609241200"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column(
        "flow_runtime_uploaded_files",
        sa.Column(
            "audio_seconds",
            sa.Float(),
            nullable=True,
            comment=(
                "Decoded audio length, measured at upload under "
                "the tenant's longest recording; null for other files and older uploads."
            ),
        ),
    )
    op.create_check_constraint(
        "ck_flow_runtime_uploaded_files_audio_seconds",
        "flow_runtime_uploaded_files",
        "audio_seconds IS NULL OR audio_seconds >= 0",
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_constraint(
        "ck_flow_runtime_uploaded_files_audio_seconds",
        "flow_runtime_uploaded_files",
        type_="check",
    )
    op.drop_column("flow_runtime_uploaded_files", "audio_seconds")
