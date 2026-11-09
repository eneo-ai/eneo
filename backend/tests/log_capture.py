"""Capture what loggers emit and check that an error's text stays out of it."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager

SENTINEL = "quoted-content-5e0b"
CHAIN = "RuntimeError <- ValueError"


def chained_error() -> RuntimeError:
    """A raised RuntimeError caused by a ValueError, both quoting `SENTINEL`."""
    try:
        try:
            raise ValueError(f"cannot read {SENTINEL}")
        except ValueError as cause:
            raise RuntimeError(f"failed on {SENTINEL}") from cause
    except RuntimeError as error:
        return error


class _Records(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def emitted(*loggers: logging.Logger) -> Iterator[list[logging.LogRecord]]:
    """Every record the root logger and `loggers` emit inside the block;
    pass a logger that does not propagate to the root."""
    handler = _Records()
    targets = {logging.getLogger(), *loggers}
    levels = {log: log.level for log in targets}
    for log in targets:
        log.addHandler(handler)
        log.setLevel(logging.DEBUG)
    try:
        yield handler.records
    finally:
        for log in targets:
            log.removeHandler(handler)
            log.setLevel(levels[log])


def logged_errors(records: list[logging.LogRecord]) -> list[logging.LogRecord]:
    """Fail if any record carries `SENTINEL` or a traceback; return those
    that name the error chain of `chained_error`."""
    for record in records:
        assert not record.exc_info and not record.stack_info, record.getMessage()
        assert SENTINEL not in repr(record.__dict__), record.getMessage()
    return [
        record
        for record in records
        if str(getattr(record, "error_type", "")).startswith(CHAIN)
    ]
