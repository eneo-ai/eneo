"""Whether a session's open transaction has done more than read."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import ORMExecuteState, Session, SessionTransaction, UOWTransaction


class TransactionWrites:
    """Watches one session's outer transaction for anything beyond a read.

    The transaction has written once it ran a statement that is not a plain
    SELECT, a SELECT that locks rows (FOR UPDATE or FOR SHARE: a lock is taken
    for a write that follows), or a flush, and while the session holds changes
    a commit would flush. Ending such a transaction would make that work
    durable, so only one that has done none of it may be ended early. The mark
    clears when the outer transaction ends; a SAVEPOINT ending inside it
    changes nothing. A transaction already open when the watch begins counts
    as written, since what it did is unknown. A session that is not an
    AsyncSession (a test double) is not watched and never counts as read-only.
    """

    def __init__(self, session: object) -> None:
        self._session = (
            session.sync_session if isinstance(session, AsyncSession) else None
        )
        self._wrote = self._session is not None and self._session.in_transaction()
        if self._session is not None:
            for name, listener in self._listeners():
                event.listen(self._session, name, listener)

    def stop(self) -> None:
        """Stop watching the session."""
        if self._session is not None:
            for name, listener in self._listeners():
                event.remove(self._session, name, listener)
            self._session = None

    def _listeners(self) -> tuple[tuple[str, Callable[..., None]], ...]:
        return (
            ("do_orm_execute", self._executed),
            ("after_flush", self._flushed),
            ("after_transaction_end", self._ended),
        )

    def only_read(self) -> bool:
        """A transaction is open on the session and has done nothing but read."""
        session = self._session
        return (
            session is not None
            and session.in_transaction()
            and not self._wrote
            and not (session.new or session.dirty or session.deleted)
        )

    def _executed(self, state: ORMExecuteState) -> None:
        # SQLAlchemy offers no public accessor for a SELECT's lock clause.
        if not state.is_select or (
            getattr(state.statement, "_for_update_arg", None) is not None
        ):
            self._wrote = True

    def _flushed(self, _session: Session, _flush: UOWTransaction) -> None:
        self._wrote = True

    def _ended(self, _session: Session, transaction: SessionTransaction) -> None:
        if transaction.parent is None:
            self._wrote = False
