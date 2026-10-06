"""The Flow-history retention lock's SQL and its refusal on a busy lock (two-session waits: integration)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DBAPIError

from eneo.data_retention.infrastructure import retention_lock
from eneo.data_retention.infrastructure.retention_lock import RetentionSubject
from eneo.main.config import get_settings

SUBJECT = RetentionSubject.FLOW_HISTORY


def _sql(statement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


def test_deletions_lock_shared_and_decisions_lock_exclusive_on_one_key() -> None:
    key = SUBJECT.key
    assert _sql(retention_lock.shared_lock_statement(SUBJECT)).startswith(
        f"SELECT pg_advisory_xact_lock_shared({key})"
    )
    assert _sql(retention_lock.exclusive_lock_statement(SUBJECT)).startswith(
        f"SELECT pg_advisory_xact_lock({key})"
    )
    assert len({subject.key for subject in RetentionSubject}) == len(RetentionSubject)


class _Orig(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


class _Session:
    def __init__(self, failure: DBAPIError) -> None:
        self.failure = failure
        self.statements: list[str] = []

    async def scalar(self, statement):
        self.statements.append(_sql(statement))
        return "0"

    async def execute(self, statement):
        sql = _sql(statement)
        self.statements.append(sql)
        if "pg_advisory" in sql:
            raise self.failure
        return SimpleNamespace(scalar_one=lambda: 0)


async def test_a_lock_timeout_is_refused_as_a_typed_conflict() -> None:
    session = _Session(DBAPIError("SELECT", {}, _Orig("55P03")))
    with pytest.raises(retention_lock.RetentionLockBusy) as refused:
        await retention_lock.acquire_exclusive(session, SUBJECT)  # type: ignore[arg-type]
    assert refused.value.code == "flow_retention_lock_busy"
    configured_ms = get_settings().gallring_chunk_lock_timeout_ms
    assert (
        f"set_config('lock_timeout', '{configured_ms}ms', true)"
        in session.statements[1]
    )


async def test_other_database_errors_are_not_reported_as_busy() -> None:
    failure = DBAPIError("SELECT", {}, _Orig("40P01"))
    with pytest.raises(DBAPIError):
        await retention_lock.acquire_shared(_Session(failure), SUBJECT)  # type: ignore[arg-type]
