"""A pending outbox row always has a next delivery time

The audit outbox and webhook delivery claims read their pending-delivery
partial index, (next_delivery_at, created_at) WHERE delivery_status =
'pending', in key order. That is only the claim's order while no pending row
has a NULL next_delivery_at; the writers already keep it so (the column
defaults to now(), and NULL is written only with 'delivered' or
'dead_lettered'), and this CHECK makes it a database fact.

Each CHECK is installed NOT VALID inside the DDL transaction (a short
exclusive lock, no row scan). A legacy pending row with a NULL time is then
given its created_at, which keeps it at the front of the queue as the old
NULLS FIRST order did, and the CHECK is validated in its own autocommit
statement, so reads and writes go on during the scan. When the validation does
not get its lock in time the revision fails with the CHECK in force for new
rows; running it again installs and validates it again.

The downgrade drops the CHECKs; a repaired row keeps its created_at time.

Revision ID: 202610231100
Revises: 202610231000
Create Date: 2026-10-23 11:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "202610231100"
down_revision: str | None = "202610231000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONDITION = "delivery_status <> 'pending' OR next_delivery_at IS NOT NULL"
_CHECKS = {
    "flow_run_audit_outbox": "ck_flow_run_audit_outbox_pending_next_delivery",
    "flow_run_webhook_deliveries": (
        "ck_flow_run_webhook_deliveries_pending_next_delivery"
    ),
}


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    for table, name in _CHECKS.items():
        op.drop_constraint(name, table, type_="check", if_exists=True)
        op.create_check_constraint(name, table, _CONDITION, postgresql_not_valid=True)
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '5s'")
        try:
            for table, name in _CHECKS.items():
                op.execute(
                    f"UPDATE {table} SET next_delivery_at = created_at "
                    "WHERE delivery_status = 'pending' AND next_delivery_at IS NULL"
                )
                op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {name}")
        finally:
            op.execute("RESET lock_timeout")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    for table, name in _CHECKS.items():
        op.drop_constraint(name, table, type_="check")
