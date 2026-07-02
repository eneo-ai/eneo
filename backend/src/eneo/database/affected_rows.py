from typing import Protocol, cast


class _HasRowCount(Protocol):
    rowcount: int


def affected_row_count(result: object) -> int:
    """Return SQLAlchemy DML rowcount without depending on Result's public typing."""
    return cast(_HasRowCount, result).rowcount or 0
