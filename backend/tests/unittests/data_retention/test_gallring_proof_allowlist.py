"""The gallring proof shows that, when, by which rule and how much - never what.

Every column of every gallring table is on this allowlist with its kind: an
opaque id, a timestamp, a number, a code from a closed set (a CHECK constraint
names it), or the job run's count maps, whose keys the runner takes only from
the task's declared names. A new column, or a code column without its CHECK,
fails here and needs an explicit review against the content-free rule.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from eneo.database.tables.gallring_tables import (
    GallringJobRuns,
    GallringReceiptItems,
    GallringReceipts,
)

# A JSONB column is a map keyed by declared step or count names: counts, or
# step cursors of an aware timestamp and an id.
ID, TIME, NUMBER, CODE, NAME_MAP = "id", "time", "number", "code", "name-keyed map"

_ALLOWED = {
    GallringJobRuns: {
        "id": ID,
        "task": CODE,
        "outcome": CODE,
        "started_at": TIME,
        "heartbeat_at": TIME,
        "finished_at": TIME,
        "batch_count": NUMBER,
        "counts": NAME_MAP,
        "blocked": NAME_MAP,
        "cursors": NAME_MAP,
        "error_code": CODE,
    },
    GallringReceipts: {
        "id": ID,
        "task": CODE,
        "entity_kind": CODE,
        "entity_id": ID,
        "category": CODE,
        "trigger": CODE,
        "tenant_id": ID,
        "space_id": ID,
        "flow_id": ID,
        "policy_source": CODE,
        "policy_days": NUMBER,
        "anchor_at": TIME,
        "due_at": TIME,
        "phase": CODE,
        "paused_from_phase": CODE,
        "reason": CODE,
        "manifest_after_file_id": ID,
        "manifest_after_variant": CODE,
        "manifest_after_ordinal": NUMBER,
        "chunk_count": NUMBER,
        "files_deleted": NUMBER,
        "started_at": TIME,
        "updated_at": TIME,
        "manifest_completed_at": TIME,
        "completed_at": TIME,
        "physical_confirmed_at": TIME,
        "pruning_started_at": TIME,
    },
    GallringReceiptItems: {
        "id": NUMBER,
        "receipt_id": ID,
        "file_id": ID,
        "content_id": ID,
        "disposition": CODE,
        "confirmed_at": TIME,
    },
}


def _kind(column: sa.Column[object]) -> str:
    column_type = column.type
    if isinstance(column_type, (sa.Uuid, postgresql.UUID)):
        return ID
    if isinstance(column_type, sa.TIMESTAMP):
        return TIME
    if isinstance(column_type, (sa.Integer, sa.BigInteger)):
        return NUMBER
    if isinstance(column_type, sa.String):
        return CODE
    if isinstance(column_type, postgresql.JSONB):
        return NAME_MAP
    return repr(column_type)


@pytest.mark.parametrize("table", list(_ALLOWED), ids=lambda t: t.__tablename__)
def test_every_gallring_column_is_an_allowed_content_free_kind(table) -> None:
    columns = {column.name: _kind(column) for column in table.__table__.columns}

    assert columns == _ALLOWED[table]
    checks = " ".join(
        str(constraint.sqltext)
        for constraint in table.__table__.constraints
        if isinstance(constraint, sa.CheckConstraint)
    )
    for name, kind in columns.items():
        if kind == CODE:
            # A code column holds a closed set or an identifier pattern.
            assert f"{name} IN (" in checks or f"{name} ~ " in checks, name
