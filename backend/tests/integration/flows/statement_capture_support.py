"""Capture the read statements a block of code sends, for statement-shape pins."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine


@dataclass(frozen=True, slots=True)
class CapturedStatement:
    sql: str
    parameters: tuple[object, ...]


@contextmanager
def capture_queries(bind: Connection | Engine) -> Iterator[list[CapturedStatement]]:
    """Every SELECT or WITH statement ``bind`` sends inside the block."""
    captured: list[CapturedStatement] = []

    def record(
        _connection: object,
        _cursor: object,
        statement: str,
        parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if statement.lstrip().upper().startswith(("SELECT", "WITH")):
            assert isinstance(parameters, tuple)
            captured.append(CapturedStatement(statement, parameters))

    sa.event.listen(bind, "before_cursor_execute", record)
    try:
        yield captured
    finally:
        sa.event.remove(bind, "before_cursor_execute", record)
