"""allow tenant-safe organisation Skill bindings on resources

Revision ID: 202607221600
Revises: 202607221500
Create Date: 2026-07-20 18:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202607221600"
down_revision: str | None = "202607221500"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BACKFILL_BATCH_SIZE = 1_000
_BINDING_TABLES = ("assistant_skill_bindings", "app_skill_bindings")
_SCOPE_TRIGGER_FUNCTION = "eneo_fill_resource_skill_binding_scope"
_CONTRACT_LOCK_TIMEOUT = "5s"


def _execute_with_contract_lock_timeout(statement: str) -> None:
    op.execute(f"SET lock_timeout = '{_CONTRACT_LOCK_TIMEOUT}'")
    try:
        op.execute(statement)
    finally:
        op.execute("RESET lock_timeout")


def _add_scope_columns_and_legacy_write_trigger(*, table: str) -> None:
    # IF NOT EXISTS keeps the migration restartable because the concurrent index
    # phase below commits independently of Alembic's surrounding transaction.
    _execute_with_contract_lock_timeout(
        f"""
        ALTER TABLE {table}
            ADD COLUMN IF NOT EXISTS tenant_id UUID,
            ADD COLUMN IF NOT EXISTS skill_space_id UUID
        """
    )
    _execute_with_contract_lock_timeout(
        f"""
        DROP TRIGGER IF EXISTS fill_resource_skill_binding_scope ON {table};
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


def _replace_binding_scope_constraints(*, table: str) -> None:
    tenant_not_null = f"ck_{table}_tenant_id_not_null"
    skill_space_not_null = f"ck_{table}_skill_space_id_not_null"

    # One ALTER makes the old-FK/new-NOT-VALID contract swap atomic. Each target
    # constraint is dropped first so a retry after a later committed migration
    # phase remains deterministic.
    _execute_with_contract_lock_timeout(
        f"""
        ALTER TABLE {table}
            DROP CONSTRAINT IF EXISTS fk_{table}_parent_space,
            DROP CONSTRAINT IF EXISTS fk_{table}_skill_space,
            DROP CONSTRAINT IF EXISTS fk_{table}_skill,
            DROP CONSTRAINT IF EXISTS {tenant_not_null},
            DROP CONSTRAINT IF EXISTS {skill_space_not_null},
            ADD CONSTRAINT fk_{table}_parent_space
                FOREIGN KEY (tenant_id, space_id)
                REFERENCES spaces (tenant_id, id)
                ON DELETE NO ACTION NOT VALID,
            ADD CONSTRAINT fk_{table}_skill_space
                FOREIGN KEY (tenant_id, skill_space_id)
                REFERENCES spaces (tenant_id, id)
                ON DELETE NO ACTION NOT VALID,
            ADD CONSTRAINT fk_{table}_skill
                FOREIGN KEY (skill_space_id, skill_id)
                REFERENCES skills (space_id, id)
                ON DELETE NO ACTION NOT VALID,
            ADD CONSTRAINT {tenant_not_null}
                CHECK (tenant_id IS NOT NULL) NOT VALID,
            ADD CONSTRAINT {skill_space_not_null}
                CHECK (skill_space_id IS NOT NULL) NOT VALID
        """
    )


def _validate_binding_scope_constraints(*, table: str) -> None:
    constraints = (
        f"fk_{table}_parent_space",
        f"fk_{table}_skill_space",
        f"fk_{table}_skill",
        f"ck_{table}_tenant_id_not_null",
        f"ck_{table}_skill_space_id_not_null",
    )
    for constraint in constraints:
        op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {constraint}")


def _contract_binding_scope_columns(*, table: str) -> None:
    tenant_not_null = f"ck_{table}_tenant_id_not_null"
    skill_space_not_null = f"ck_{table}_skill_space_id_not_null"

    # The validated checks let PostgreSQL prove NOT NULL without another table
    # scan. Keep the two column changes and helper-check removal in one short,
    # retry-safe contract statement.
    _execute_with_contract_lock_timeout(
        f"""
        ALTER TABLE {table}
            ALTER COLUMN tenant_id SET NOT NULL,
            ALTER COLUMN skill_space_id SET NOT NULL,
            DROP CONSTRAINT IF EXISTS {tenant_not_null},
            DROP CONSTRAINT IF EXISTS {skill_space_not_null}
        """
    )


def upgrade() -> None:
    # Each statement commits independently. Short metadata locks therefore
    # never span sibling tables or populated-table scans, while every phase is
    # restartable if a bounded lock attempt asks the deployment to retry.
    with op.get_context().autocommit_block():
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
        for table in _BINDING_TABLES:
            _backfill_scope_columns(table=table)
            _create_scope_index(table=table)
        for table in _BINDING_TABLES:
            _replace_binding_scope_constraints(table=table)
        for table in _BINDING_TABLES:
            _validate_binding_scope_constraints(table=table)
        for table in _BINDING_TABLES:
            _contract_binding_scope_columns(table=table)

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
