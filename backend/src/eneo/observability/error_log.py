"""What a log line may say about an exception: its kinds, a status code and
where it was raised, never its message.

An exception's message can quote what it failed on: a provider's answer can
echo the input, a parser the file. A logged traceback prints that message
for the exception and every cause, so a log that removed content must not
outlive carries these facts instead.
"""

from __future__ import annotations

import logging
import traceback
from collections.abc import Mapping

from eneo.observability.error_text import http_response


def log_error(
    log: logging.Logger,
    level: int,
    message: str,
    *args: object,
    error: BaseException,
    extra: Mapping[str, object] | None = None,
) -> None:
    """Log `message % args`, then the error's kinds and where it was raised.

    The record carries `error_facts` and `extra`, never the error's message or
    traceback, and points at the caller.
    """
    facts = error_facts(error)
    log.log(
        level,
        message + ": %s at %s",
        *args,
        facts["error_type"],
        facts["error_at"],
        extra={**(extra or {}), **facts},
        stacklevel=2,
    )


def error_facts(error: BaseException) -> dict[str, object]:
    """Fields for a log record's `extra`.

    `error_type` names the exception and its causes, outermost first.
    `error_status` is the first HTTP status code in that chain, if any: an
    HTTP client's response status or an integer `status_code`.
    `error_stack` lists where each was raised, as `file:line in function`,
    and `error_at` is the innermost of those: where the failure began.
    """
    chain = _chain(error)
    stack = [
        f"{frame.filename}:{frame.lineno} in {frame.name}"
        for exception in chain
        for frame in traceback.extract_tb(exception.__traceback__)
    ]
    return {
        "error_type": " <- ".join(type(exception).__name__ for exception in chain),
        "error_status": next(
            (
                status
                for exception in chain
                if isinstance(status := _status(exception), int)
            ),
            None,
        ),
        "error_stack": stack,
        "error_at": stack[-1] if stack else None,
    }


def _status(exception: BaseException) -> object:
    response = http_response(exception)
    if response is not None:
        return response[0]
    return getattr(exception, "status_code", None)


def _chain(error: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    current: BaseException | None = error
    while current is not None and all(current is not seen for seen in chain):
        chain.append(current)
        current = current.__cause__ or (
            None if current.__suppress_context__ else current.__context__
        )
    return chain
