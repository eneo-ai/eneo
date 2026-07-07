"""add module auth client config

Revision ID: 202607021400
Revises: 202606281200
Create Date: 2026-07-02 14:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "202607021400"
down_revision: Union[str, None] = "202606281200"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tenants_modules", sa.Column("redirect_uris", JSONB(), nullable=True))
    op.add_column(
        "tenants_modules",
        sa.Column("service_key_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_tenants_modules_service_key_id_api_keys_v2",
        "tenants_modules",
        "api_keys_v2",
        ["service_key_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_tenants_modules_service_key_id_api_keys_v2",
        "tenants_modules",
        type_="foreignkey",
    )
    op.drop_column("tenants_modules", "service_key_id")
    op.drop_column("tenants_modules", "redirect_uris")
