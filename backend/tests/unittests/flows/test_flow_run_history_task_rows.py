from __future__ import annotations

import importlib
import pkgutil
import re
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DBAPIError

import eneo.database.tables as tables
from eneo.data_retention.infrastructure.gallring_lock import (
    GallringLockBusy,
    GallringSubject,
)
from eneo.database.tables.base_class import Base
from eneo.flows.application.flow_run_history_retention_task import (
    is_transient_database_error,
)
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
    ("error", "transient"),
    [
        (_database_error("57014"), True),
        (_database_error("55P03"), True),
        (_database_error("40P01"), True),
        (_busy_lock(), True),
        (_database_error("23505"), False),
        (RuntimeError("defect"), False),
    ],
    ids=["statement", "lock", "deadlock", "busy-gallring-lock", "unique", "defect"],
)
def test_the_runner_retries_exactly_the_transient_database_errors(
    error: Exception, transient: bool
) -> None:
    """The task lets these end the pass as partial instead of blocking a run
    as failed. Mutant: the deadlock or the busy lock counted as a defect."""
    assert is_transient_database_error(error) is transient


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
