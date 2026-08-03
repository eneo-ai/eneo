# Copyright (c) 2026 Sundsvalls Kommun
#
# Licensed under the MIT License.

"""Enable selective Skill activation by default for existing tenants.

Downgrade deliberately resets the tenant-wide setting to the old default.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "202608031000"
down_revision: str | None = "202607301200"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE skill_runtime_policies "
            "SET selective_activation_enabled = true "
            "WHERE selective_activation_enabled = false"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE skill_runtime_policies "
            "SET selective_activation_enabled = false "
            "WHERE selective_activation_enabled = true"
        )
    )
