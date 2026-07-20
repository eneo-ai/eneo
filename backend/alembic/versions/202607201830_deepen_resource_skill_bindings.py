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

_BACKFILL_BATCH_SIZE = 1_000
_BINDING_TABLES = ("assistant_skill_bindings", "app_skill_bindings")
_SCOPE_TRIGGER_FUNCTION = "eneo_fill_resource_skill_binding_scope"


def _add_scope_columns_and_legacy_write_trigger(*, table: str) -> None:
    # IF NOT EXISTS keeps the migration restartable because the concurrent index
    # phase below commits independently of Alembic's surrounding transaction.
    op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS tenant_id UUID")
    op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS skill_space_id UUID")
    op.execute(f"DROP TRIGGER IF EXISTS fill_resource_skill_binding_scope ON {table}")
    op.execute(
        f"""
        CREATE TRIGGER fill_resource_skill_binding_scope
        BEFORE INSERT OR UPDATE OF space_id, tenant_id, skill_space_id ON {table}
        FOR EACH ROW
        EXECUTE FUNCTION {_SCOPE_TRIGGER_FUNCTION}()
        """
    )


def _backfill_scope_columns(*, table: str) -> None:
    bind = op.get_bind()
    while True:
        result = bind.execute(
            sa.text(
                f"""
                WITH batch AS (
                    SELECT binding.ctid
                    FROM {table} AS binding
                    WHERE binding.tenant_id IS NULL
                       OR binding.skill_space_id IS NULL
                    ORDER BY binding.ctid
                    LIMIT :batch_size
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE {table} AS binding
                SET tenant_id = COALESCE(
                        binding.tenant_id,
                        parent_space.tenant_id
                    ),
                    skill_space_id = COALESCE(
                        binding.skill_space_id,
                        binding.space_id
                    )
                FROM batch, spaces AS parent_space
                WHERE binding.ctid = batch.ctid
                  AND parent_space.id = binding.space_id
                """
            ),
            {"batch_size": _BACKFILL_BATCH_SIZE},
        )
        if result.rowcount == _BACKFILL_BATCH_SIZE:
            continue

        # A short SKIP LOCKED batch may still leave a row owned by a concurrent
        # legacy writer. Wait for one residual row instead of ending early; the
        # autocommit block releases this probe lock before the next batch.
        residual = bind.execute(
            sa.text(
                f"""
                SELECT 1
                FROM {table}
                WHERE tenant_id IS NULL
                   OR skill_space_id IS NULL
                LIMIT 1
                FOR UPDATE
                """
            )
        ).first()
        if residual is None:
            return


def _create_scope_index(*, table: str) -> None:
    index = f"ix_{table}_tenant_skill_space"
    # A failed CREATE INDEX CONCURRENTLY leaves an invalid index behind. Dropping
    # first makes a retry deterministic without blocking writes to the table.
    op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {index}")
    op.execute(
        f"""
        CREATE INDEX CONCURRENTLY {index}
        ON {table} (tenant_id, skill_space_id)
        """
    )


def _enforce_binding_scope(*, table: str) -> None:
    tenant_not_null = f"ck_{table}_tenant_id_not_null"
    skill_space_not_null = f"ck_{table}_skill_space_id_not_null"

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
    op.create_check_constraint(
        tenant_not_null,
        table,
        "tenant_id IS NOT NULL",
        postgresql_not_valid=True,
    )
    op.create_check_constraint(
        skill_space_not_null,
        table,
        "skill_space_id IS NOT NULL",
        postgresql_not_valid=True,
    )

    op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT fk_{table}_parent_space")
    op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT fk_{table}_skill_space")
    op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT fk_{table}_skill")
    op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {tenant_not_null}")
    op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {skill_space_not_null}")

    op.alter_column(table, "tenant_id", nullable=False)
    op.alter_column(table, "skill_space_id", nullable=False)
    op.drop_constraint(tenant_not_null, table, type_="check")
    op.drop_constraint(skill_space_not_null, table, type_="check")


def upgrade() -> None:
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {_SCOPE_TRIGGER_FUNCTION}()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.skill_space_id IS NULL THEN
                NEW.skill_space_id := NEW.space_id;
            END IF;
            IF NEW.tenant_id IS NULL THEN
                SELECT tenant_id
                INTO NEW.tenant_id
                FROM spaces
                WHERE id = NEW.space_id;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    for table in _BINDING_TABLES:
        _add_scope_columns_and_legacy_write_trigger(table=table)

    with op.get_context().autocommit_block():
        for table in _BINDING_TABLES:
            _backfill_scope_columns(table=table)
            _create_scope_index(table=table)

    for table in _BINDING_TABLES:
        _enforce_binding_scope(table=table)

    # Keep the trigger until every supported backend version writes both scope
    # columns. A later contract migration can then remove it safely.


def _restore_local_binding_table(*, table: str) -> None:
    op.execute(f"DROP TRIGGER IF EXISTS fill_resource_skill_binding_scope ON {table}")
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
    for table in reversed(_BINDING_TABLES):
        _restore_local_binding_table(table=table)
    op.execute(f"DROP FUNCTION IF EXISTS {_SCOPE_TRIGGER_FUNCTION}()")
