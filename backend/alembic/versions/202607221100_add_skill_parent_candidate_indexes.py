"""add candidate indexes required by skill bindings

Revision ID: 202607221100
Revises: 202607221000
Create Date: 2026-07-22 11:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "202607221100"
down_revision: str | None = "202607221000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "uq_assistants_space_id_id",
            table_name="assistants",
            if_exists=True,
            postgresql_concurrently=True,
        )
        op.create_index(
            "uq_assistants_space_id_id",
            "assistants",
            ["space_id", "id"],
            unique=True,
            postgresql_concurrently=True,
        )
        op.drop_index(
            "uq_apps_space_id_id",
            table_name="apps",
            if_exists=True,
            postgresql_concurrently=True,
        )
        op.create_index(
            "uq_apps_space_id_id",
            "apps",
            ["space_id", "id"],
            unique=True,
            postgresql_concurrently=True,
        )
        op.drop_index(
            "uq_spaces_tenant_id_id",
            table_name="spaces",
            if_exists=True,
            postgresql_concurrently=True,
        )
        op.create_index(
            "uq_spaces_tenant_id_id",
            "spaces",
            ["tenant_id", "id"],
            unique=True,
            postgresql_concurrently=True,
        )
        op.drop_index(
            "uq_governance_policies_tenant_id_id",
            table_name="governance_policies",
            if_exists=True,
            postgresql_concurrently=True,
        )
        op.create_index(
            "uq_governance_policies_tenant_id_id",
            "governance_policies",
            ["tenant_id", "id"],
            unique=True,
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "uq_governance_policies_tenant_id_id",
            table_name="governance_policies",
            if_exists=True,
            postgresql_concurrently=True,
        )
        op.drop_index(
            "uq_spaces_tenant_id_id",
            table_name="spaces",
            if_exists=True,
            postgresql_concurrently=True,
        )
        op.drop_index(
            "uq_apps_space_id_id",
            table_name="apps",
            if_exists=True,
            postgresql_concurrently=True,
        )
        op.drop_index(
            "uq_assistants_space_id_id",
            table_name="assistants",
            if_exists=True,
            postgresql_concurrently=True,
        )
