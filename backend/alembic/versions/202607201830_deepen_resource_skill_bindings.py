"""allow tenant-safe organisation Skill bindings on resources

Revision ID: 202607201830
Revises: 202607151400
Create Date: 2026-07-20 18:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202607201830"
down_revision: str | None = "202607151400"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _deepen_binding_table(*, table: str) -> None:
    op.add_column(table, sa.Column("tenant_id", sa.UUID(), nullable=True))
    op.add_column(table, sa.Column("skill_space_id", sa.UUID(), nullable=True))
    op.execute(
        sa.text(
            f"""
            UPDATE {table} AS binding
            SET tenant_id = parent_space.tenant_id,
                skill_space_id = binding.space_id
            FROM spaces AS parent_space
            WHERE parent_space.id = binding.space_id
            """
        )
    )
    op.alter_column(table, "tenant_id", nullable=False)
    op.alter_column(table, "skill_space_id", nullable=False)

    op.drop_constraint(f"fk_{table}_skill", table, type_="foreignkey")
    op.create_foreign_key(
        f"fk_{table}_parent_space",
        table,
        "spaces",
        ["tenant_id", "space_id"],
        ["tenant_id", "id"],
        ondelete="NO ACTION",
        postgresql_not_valid=True,
    )
    op.create_foreign_key(
        f"fk_{table}_skill_space",
        table,
        "spaces",
        ["tenant_id", "skill_space_id"],
        ["tenant_id", "id"],
        ondelete="NO ACTION",
        postgresql_not_valid=True,
    )
    op.create_foreign_key(
        f"fk_{table}_skill",
        table,
        "skills",
        ["skill_space_id", "skill_id"],
        ["space_id", "id"],
        ondelete="NO ACTION",
        postgresql_not_valid=True,
    )
    op.create_index(
        f"ix_{table}_tenant_skill_space",
        table,
        ["tenant_id", "skill_space_id"],
    )

    op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT fk_{table}_parent_space")
    op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT fk_{table}_skill_space")
    op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT fk_{table}_skill")


def upgrade() -> None:
    _deepen_binding_table(table="assistant_skill_bindings")
    _deepen_binding_table(table="app_skill_bindings")


def _restore_local_binding_table(*, table: str) -> None:
    op.drop_index(f"ix_{table}_tenant_skill_space", table_name=table)
    op.drop_constraint(f"fk_{table}_skill", table, type_="foreignkey")
    op.drop_constraint(f"fk_{table}_skill_space", table, type_="foreignkey")
    op.drop_constraint(f"fk_{table}_parent_space", table, type_="foreignkey")
    op.create_foreign_key(
        f"fk_{table}_skill",
        table,
        "skills",
        ["space_id", "skill_id"],
        ["space_id", "id"],
        ondelete="NO ACTION",
    )
    op.drop_column(table, "skill_space_id")
    op.drop_column(table, "tenant_id")


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM assistant_skill_bindings
                    WHERE skill_space_id <> space_id
                ) OR EXISTS (
                    SELECT 1
                    FROM app_skill_bindings
                    WHERE skill_space_id <> space_id
                ) THEN
                    RAISE EXCEPTION
                        'Cannot downgrade Skill bindings while cross-Space bindings exist'
                        USING ERRCODE = 'check_violation';
                END IF;
            END
            $$;
            """
        )
    )
    _restore_local_binding_table(table="app_skill_bindings")
    _restore_local_binding_table(table="assistant_skill_bindings")
