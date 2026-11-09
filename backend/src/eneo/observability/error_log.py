"""What a log line may say about an exception: its kinds, a status code and
where it was raised, never its message.

An exception's message can quote what it failed on: a provider's answer can
echo the input, a parser the file. A logged traceback prints that message
for the exception and every cause, so a log that removed content must not
outlive carries these facts instead.
"""

from __future__ import annotations

import traceback


def error_facts(error: BaseException) -> dict[str, object]:
    """Fields for a log record's `extra`.

    `error_type` names the exception and its causes, outermost first.
    `error_status` is the first HTTP status code in that chain, if any.
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
                if isinstance(status := getattr(exception, "status_code", None), int)
            ),
            None,
        ),
        "error_stack": stack,
        "error_at": stack[-1] if stack else None,
    }


def _chain(error: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    current: BaseException | None = error
    while current is not None and all(current is not seen for seen in chain):
        chain.append(current)
        current = current.__cause__ or (
            None if current.__suppress_context__ else current.__context__
        )
    return chain
