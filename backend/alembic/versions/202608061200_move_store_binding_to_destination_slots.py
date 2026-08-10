"""move store-binding facts to per-destination slots

Each object-store destination owns its durable database-to-bucket pairing
facts. The reconciliation-state singleton keeps only inventory/cycle state,
and the administrator-managed connection table gains a second, temporary
slot used by a destination migration (candidate before cutover, retiring
source after it). Slot 1 remains permanently the active destination.

This is the expand half of an expand/contract change: the legacy binding
columns on the reconciliation state stay in place with their constraints so
that the later contract revision owns their removal explicitly. Running
pre-upgrade processes against the upgraded schema is unsupported: this
release upgrades through a coordinated maintenance window in which every
pre-upgrade backend and worker is stopped before Alembic runs and only
current-release processes start afterwards (see
docs/deployment/OBJECT_CONTENT.md). Destination switching in particular
assumes every running writer holds the store-generation fence, which
pre-upgrade code does not. Post-upgrade code reads and writes only the new
table. The contract step — dropping the legacy columns — ships as its own
revision in a later release, once no process reads them.

Revision ID: 202608061200
Revises: 202607061000
Create Date: 2026-08-06 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202608061200"
down_revision: str | None = "202607061000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BINDINGS = "object_store_bindings"
_CONNECTIONS = "object_store_connections"
_STATE = "object_content_reconciliation_state"


def upgrade() -> None:
    op.create_table(
        _BINDINGS,
        sa.Column("slot", sa.SmallInteger(), nullable=False),
        sa.Column("deployment_id", sa.UUID(), nullable=False),
        sa.Column("binding_id", sa.UUID(), nullable=False),
        sa.Column("confirmed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("claim_id", sa.UUID(), nullable=True),
        sa.Column("claim_until", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("create_started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("slot IN (1, 2)", name="ck_object_store_bindings_slot"),
        sa.CheckConstraint(
            "(claim_id IS NULL) = (claim_until IS NULL)",
            name="ck_object_store_bindings_claim_pair",
        ),
        sa.CheckConstraint(
            "claim_id IS NULL OR confirmed_at IS NULL",
            name="ck_object_store_bindings_claim_state",
        ),
        sa.PrimaryKeyConstraint("slot", name="pk_object_store_bindings"),
    )

    # A legacy environment-managed destination can hold a durable binding
    # without any administrator connection row, so the binding row must be
    # created from the reconciliation state unconditionally.
    op.execute(
        sa.text(
            f"""
            INSERT INTO {_BINDINGS}
                (slot, deployment_id, binding_id, confirmed_at,
                 claim_id, claim_until, create_started_at)
            SELECT 1, store_deployment_id, store_binding_id,
                   store_binding_confirmed_at, store_binding_claim_id,
                   store_binding_claim_until, store_binding_create_started_at
            FROM {_STATE}
            WHERE id = 1 AND store_binding_id IS NOT NULL
            """
        )
    )

    # Expand only: the legacy binding columns and their constraints remain so
    # the later contract migration owns their removal explicitly. A later
    # release drops them once no running code reads them.

    op.add_column(
        _CONNECTIONS,
        sa.Column(
            "role",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
    )
    op.drop_constraint(
        "ck_object_store_connections_singleton", _CONNECTIONS, type_="check"
    )
    op.create_check_constraint(
        "ck_object_store_connections_slots", _CONNECTIONS, "id IN (1, 2)"
    )
    op.create_check_constraint(
        "ck_object_store_connections_role",
        _CONNECTIONS,
        "(id = 1 AND role = 'active') OR "
        "(id = 2 AND role IN ('candidate', 'retiring'))",
    )


def downgrade() -> None:
    bind = op.get_bind()
    temporary_state = int(
        bind.execute(
            sa.text(
                f"""
                SELECT (SELECT count(*) FROM {_BINDINGS} WHERE slot = 2)
                     + (SELECT count(*) FROM {_CONNECTIONS} WHERE id = 2)
                """
            )
        ).scalar_one()
    )
    if temporary_state:
        raise RuntimeError(
            "Cannot downgrade while a destination migration holds a candidate "
            "or retiring connection; finish or abandon the migration first, "
            "or restore the paired pre-upgrade database and object-store "
            "backup"
        )

    op.drop_constraint("ck_object_store_connections_role", _CONNECTIONS, type_="check")
    op.drop_constraint("ck_object_store_connections_slots", _CONNECTIONS, type_="check")
    op.create_check_constraint(
        "ck_object_store_connections_singleton", _CONNECTIONS, "id = 1"
    )
    op.drop_column(_CONNECTIONS, "role")

    # The legacy columns were never dropped (expand-only upgrade), so the
    # downgrade only copies the authoritative facts back into them: work
    # recorded by post-upgrade code exists in the table alone.
    op.execute(
        sa.text(
            f"""
            UPDATE {_STATE} AS state
            SET store_deployment_id = binding.deployment_id,
                store_binding_id = binding.binding_id,
                store_binding_confirmed_at = binding.confirmed_at,
                store_binding_claim_id = binding.claim_id,
                store_binding_claim_until = binding.claim_until,
                store_binding_create_started_at = binding.create_started_at
            FROM {_BINDINGS} AS binding
            WHERE state.id = 1 AND binding.slot = 1
            """
        )
    )
    op.drop_table(_BINDINGS)
