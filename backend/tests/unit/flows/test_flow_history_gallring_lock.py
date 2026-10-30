"""The Flow-history gallring lock's SQL and its refusal on a busy lock (two-session waits: integration)."""

from __future__ import annotations

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DBAPIError

from eneo.data_retention.infrastructure import gallring_lock
from eneo.data_retention.infrastructure.gallring_lock import GallringSubject

SUBJECT = GallringSubject.FLOW_HISTORY


def _sql(statement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


def test_deletions_lock_shared_and_decisions_lock_exclusive_on_one_key() -> None:
    key = SUBJECT.key
    assert _sql(gallring_lock.shared_lock_statement(SUBJECT)).startswith(
        f"SELECT pg_advisory_xact_lock_shared({key})"
    )
    assert _sql(gallring_lock.exclusive_lock_statement(SUBJECT)).startswith(
        f"SELECT pg_advisory_xact_lock({key})"
    )
    assert len({subject.key for subject in GallringSubject}) == len(GallringSubject)


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


async def test_a_lock_timeout_is_refused_as_a_typed_conflict() -> None:
    session = _Session(DBAPIError("SELECT", {}, _Orig("55P03")))
    with pytest.raises(gallring_lock.GallringLockBusy) as refused:
        await gallring_lock.acquire_exclusive(session, SUBJECT)  # type: ignore[arg-type]
    assert refused.value.code == "flow_retention_lock_busy"
    assert "set_config('lock_timeout', '5s', true)" in session.statements[1]


async def test_other_database_errors_are_not_reported_as_busy() -> None:
    failure = DBAPIError("SELECT", {}, _Orig("40P01"))
    with pytest.raises(DBAPIError):
        await gallring_lock.acquire_shared(_Session(failure), SUBJECT)  # type: ignore[arg-type]
