"""record the storage administration actor truthfully

Storage administration is a normal permission held by the Owner role, not a
separate platform-administrator authority, and the routers enforce exactly
that. Rows written through this boundary were still classified as
'platform_admin', overstating the privilege of the principal that acted.
This migration renames the persisted classification to 'storage_admin' on
both storage-owned tables and tightens their check constraints to the new
vocabulary. Historical rows are converted: they were written through the
same storage-administration boundary, so the new name describes them more
accurately than the old one did.

Revision ID: 202608101300
Revises: 202608061600
Create Date: 2026-08-10 13:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202608101300"
down_revision: str | None = "202608061600"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = (
    ("object_content_deployment_policy", "ck_object_content_policy_actor"),
    ("object_store_connections", "ck_object_store_connections_actor"),
)


def upgrade() -> None:
    for table, constraint in _TABLES:
        op.drop_constraint(constraint, table, type_="check")
        op.execute(
            f"UPDATE {table} SET updated_by_actor = 'storage_admin' "
            "WHERE updated_by_actor = 'platform_admin'"
        )
        op.create_check_constraint(
            constraint,
            table,
            "updated_by_actor IN ('migration', 'storage_admin')",
        )


def downgrade() -> None:
    for table, constraint in _TABLES:
        op.drop_constraint(constraint, table, type_="check")
        op.execute(
            f"UPDATE {table} SET updated_by_actor = 'platform_admin' "
            "WHERE updated_by_actor = 'storage_admin'"
        )
        op.create_check_constraint(
            constraint,
            table,
            "updated_by_actor IN ('migration', 'platform_admin')",
        )
