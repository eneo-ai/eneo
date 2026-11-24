from __future__ import annotations

import importlib
import pkgutil
import re
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import (
    CompileError,
    DBAPIError,
    InterfaceError,
    OperationalError,
    PendingRollbackError,
)

import eneo.database.tables as tables
from eneo.data_retention.application.retention_runner import (
    RetentionContractError,
    RetentionOwnershipLost,
)
from eneo.data_retention.infrastructure.gallring_lock import (
    GallringLockBusy,
    GallringSubject,
)
from eneo.database.tables.base_class import Base
from eneo.flows.application.flow_run_history_retention_task import is_run_failure
from eneo.flows.infrastructure.flow_run_history_purge_repo import (
    flow_run_owned_row_count,
)


class _Database(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


def _database_error(sqlstate: str) -> DBAPIError:
    return DBAPIError("SELECT", {}, _Database(sqlstate))


def _busy_lock() -> GallringLockBusy:
    busy = GallringLockBusy(GallringSubject.FLOW_HISTORY)
    busy.__cause__ = _database_error("55P03")
    return busy


@pytest.mark.parametrize(
    ("error", "run_failure"),
    [
        (_database_error("57014"), False),
        (_database_error("55P03"), False),
        (_database_error("40P01"), False),
        (_busy_lock(), False),
        (
            DBAPIError("SELECT", {}, _Database("23505"), connection_invalidated=True),
            False,
        ),
        (OperationalError("SELECT", {}, _Database("23505")), False),
        (InterfaceError("SELECT", {}, _Database("23505")), False),
        (_database_error("08006"), False),
        (_database_error("28000"), False),
        (_database_error("42501"), False),
        (_database_error("53100"), False),
        (_database_error("57P01"), False),
        (_database_error("58030"), False),
        (_database_error("XX000"), False),
        (RetentionContractError("engine"), False),
        (RetentionOwnershipLost("superseded"), False),
        (CompileError("unconsumed column"), False),
        (PendingRollbackError("rolled back"), False),
        (MemoryError(), False),
        (_database_error("22001"), True),
        (_database_error("23505"), True),
        (RuntimeError("defect"), True),
    ],
    ids=[
        "statement",
        "lock",
        "deadlock",
        "busy-gallring-lock",
        "invalidated-connection",
        "operational",
        "interface",
        "connection",
        "sign-in",
        "privilege",
        "resources",
        "operator",
        "system",
        "internal",
        "contract",
        "ownership",
        "compile",
        "pending-rollback",
        "memory",
        "data",
        "integrity",
        "defect",
    ],
)
def test_only_the_runs_own_errors_block_it_as_failed(
    error: Exception, run_failure: bool
) -> None:
    """A data or integrity error, or the removal's own defect, blocks one run
    and the pass goes on; anything else ends the chunk, retried or failed by
    the runner. Mutants: a missing privilege, a dropped connection, a statement
    SQLAlchemy cannot compile, a session left unusable or exhausted memory
    blocking every run as failed; a deadlock or a busy lock counted as the
    run's."""
    assert is_run_failure(error) is run_failure


def test_every_table_under_a_run_is_counted_in_its_rows() -> None:
    """A table added under ``flow_runs`` is removed with the run; without its
    rows in the count a run could exceed its budget unseen."""
    for module in pkgutil.iter_modules(tables.__path__):
        importlib.import_module(f"{tables.__name__}.{module.name}")
    under_a_run = {"flow_runs"}
    grown = True
    while grown:
        grown = False
        for table in Base.metadata.tables.values():
            if table.name in under_a_run:
                continue
            if any(fk.column.table.name in under_a_run for fk in table.foreign_keys):
                under_a_run.add(table.name)
                grown = True

    compiled = str(
        flow_run_owned_row_count(uuid4(), ceiling=10).compile(
            dialect=postgresql.dialect()
        )
    )

    assert set(re.findall(r"FROM (\w+)", compiled)) == under_a_run
