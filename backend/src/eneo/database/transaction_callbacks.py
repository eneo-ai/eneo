import asyncio
from collections.abc import Awaitable, Callable

from sqlalchemy import event
from sqlalchemy.orm import Session

_BACKGROUND_TASKS: set[asyncio.Task[None]] = set()


def after_outer_transaction(
    session: Session,
    *,
    on_commit: Callable[[], Awaitable[None]],
    on_rollback: Callable[[], None] | None = None,
) -> None:
    """Run one callback after the surrounding transaction is durably resolved."""
    if session.in_nested_transaction():
        raise ValueError("Post-commit work cannot be registered in a savepoint")

    outer_committed = False
    active = True

    def after_commit(_session: object) -> None:
        nonlocal outer_committed
        if active and not session.in_nested_transaction():
            outer_committed = True

    def remove_listeners() -> None:
        if event.contains(session, "after_commit", after_commit):
            event.remove(session, "after_commit", after_commit)
        if event.contains(session, "after_transaction_end", after_transaction_end):
            event.remove(session, "after_transaction_end", after_transaction_end)

    def after_transaction_end(_session: object, transaction: object) -> None:
        nonlocal active
        if not active or getattr(transaction, "parent", None) is not None:
            return

        active = False
        loop = asyncio.get_running_loop()
        if outer_committed:

            async def run_on_commit() -> None:
                await on_commit()

            task = loop.create_task(run_on_commit())
            _BACKGROUND_TASKS.add(task)
            task.add_done_callback(_BACKGROUND_TASKS.discard)
        elif on_rollback is not None:
            on_rollback()
        loop.call_soon(remove_listeners)

    event.listen(session, "after_commit", after_commit)
    event.listen(session, "after_transaction_end", after_transaction_end)
