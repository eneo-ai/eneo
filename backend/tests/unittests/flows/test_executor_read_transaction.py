"""The executor ends its session's transaction before outside work only when
that transaction has done nothing but read.

The session is a real one over SQLite, so the statements a step runs reach
the executor the way they do in production; everything else is the audio
step's usual test doubles.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from eneo.files.file_service import FileService
from eneo.flows.infrastructure.flow_provider_call_recorder import (
    FlowProviderCallRecorder,
)
from tests.unittests.flows import audio_spool_test_support
from tests.unittests.flows.test_flow_transcription import _audio_file, _state
from tests.unittests.flows.test_transcript_spill import _case, _metadata
from tests.unittests.flows.test_typed_io_executor import _runtime_step

spool_contract = audio_spool_test_support.spool_contract


class _Base(DeclarativeBase):
    pass


class _Run(_Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    payload: Mapped[str]


_RUNS = _Run.__table__


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = sa.create_engine("sqlite://")
    _RUNS.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(_RUNS.insert().values(id=1, payload="{}"))
    session = AsyncSession()
    # The statements run inside the session's greenlet, so a sync engine serves.
    session.sync_session.bind = engine
    try:
        yield session
    finally:
        await session.close()
        engine.dispose()


def _commits(session: AsyncSession) -> list[None]:
    commits: list[None] = []
    event.listen(session.sync_session, "after_commit", lambda _: commits.append(None))
    return commits


def _checked_out(session: AsyncSession) -> list[None]:
    """The connections the session holds, kept current by the pool's events."""
    held: list[None] = []
    engine = session.sync_session.bind
    event.listen(engine, "checkout", lambda *_: held.append(None))
    event.listen(engine, "checkin", lambda *_: held.pop())
    return held


async def _read(session: AsyncSession) -> str | None:
    return await session.scalar(sa.select(_RUNS.c.payload).where(_RUNS.c.id == 1))


async def _write(session: AsyncSession, payload: str) -> None:
    await session.execute(
        sa.update(_RUNS).where(_RUNS.c.id == 1).values(payload=payload)
    )


def _executor_on(session: AsyncSession, user, spool_contract):
    executor, repo, run, files, _ = _case(user, "Transcript.", spool_contract)
    executor.session = session
    return executor, repo, run, files


def _observers(executor, run):
    deps = executor._build_step_execution_runtime_deps(
        step=_runtime_step(input_type="audio"), run=run, attempt_no=1
    )
    observers = (
        deps.build_provider_call_observer(None, (0,), None),
        deps.build_transcription_call_observer(),
    )
    for observer in observers:
        assert isinstance(observer, FlowProviderCallRecorder)
        assert observer.before_request is not None
    return observers


async def test_a_transaction_that_only_read_ends_before_each_provider_call(
    session, spool_contract, user
):
    executor, _, run, _ = _executor_on(session, user, spool_contract)
    commits = _commits(session)
    held = _checked_out(session)

    for observer in _observers(executor, run):
        await _read(session)
        assert held
        await observer.before_request()
        # No connection is held while the provider is waited on.
        assert held == []

    assert len(commits) == 2


async def test_rows_loaded_before_an_ended_read_stay_loaded(
    session, spool_contract, user
):
    """A step reads rows it loaded before a provider call after the call. The
    ended transaction only read, so it is committed without expiring them: an
    expired attribute cannot be loaded lazily under asyncio."""
    executor, _, _, _ = _executor_on(session, user, spool_contract)
    row = await session.get(_Run, 1)
    assert row is not None
    await executor._end_read_transaction()

    assert not sa.inspect(row).expired
    assert row.payload == "{}"
    assert session.sync_session.expire_on_commit is True


async def test_a_write_after_an_ended_read_joins_the_step_transaction(
    session, spool_contract, user
):
    """Writers that join an ambient transaction, and begin and commit their
    own only when there is none, still write inside the step's transaction
    after a read-only one was ended: a failure before activation rolls the
    write back."""
    executor, _, _, _ = _executor_on(session, user, spool_contract)
    commits = _commits(session)
    await _read(session)
    await executor._end_read_transaction()

    files = SimpleNamespace(repo=SimpleNamespace(session=session))
    async with FileService._write_transaction(files):  # pyright: ignore[reportArgumentType]
        await _write(session, "written")

    assert len(commits) == 1
    await executor._rollback()
    assert await _read(session) == "{}"


@pytest.mark.parametrize(
    "work",
    [
        pytest.param(lambda session: _write(session, "written"), id="update"),
        pytest.param(
            lambda session: session.scalar(
                sa.select(_RUNS.c.payload).where(_RUNS.c.id == 1).with_for_update()
            ),
            id="row lock",
        ),
        pytest.param(lambda session: session.scalar(sa.text("SELECT 1")), id="text"),
    ],
)
async def test_a_transaction_that_wrote_or_locked_stays_open(
    session, spool_contract, user, work
):
    executor, _, run, _ = _executor_on(session, user, spool_contract)
    commits = _commits(session)
    await _read(session)
    await work(session)

    for observer in _observers(executor, run):
        await observer.before_request()

    assert session.in_transaction()
    assert commits == []
    await executor._rollback()
    assert await _read(session) == "{}"


async def test_pending_changes_keep_the_transaction_open(session, spool_contract, user):
    executor, _, _, _ = _executor_on(session, user, spool_contract)
    await _read(session)
    session.add(_Run(id=2, payload="{}"))
    await executor._end_read_transaction()
    assert session.in_transaction()


async def test_a_savepoint_ending_does_not_forget_the_outer_write(
    session, spool_contract, user
):
    executor, _, _, _ = _executor_on(session, user, spool_contract)
    await _write(session, "written")
    savepoint = await session.begin_nested()
    await savepoint.commit()

    await executor._end_read_transaction()

    assert session.in_transaction()
    await executor._rollback()
    assert await _read(session) == "{}"


@pytest.mark.parametrize("end", ["commit", "rollback"])
async def test_the_next_transaction_that_only_reads_is_ended_again(
    session, spool_contract, user, end
):
    executor, _, _, _ = _executor_on(session, user, spool_contract)
    await _write(session, "written")
    await (executor._commit() if end == "commit" else executor._rollback())

    commits = _commits(session)
    await _read(session)
    await executor._end_read_transaction()

    assert len(commits) == 1


async def test_no_transaction_is_begun_to_be_ended(session, spool_contract, user):
    executor, _, _, _ = _executor_on(session, user, spool_contract)
    session.sync_session.autobegin = False

    await executor._end_read_transaction()

    assert not session.in_transaction()


async def test_a_session_open_before_the_executor_used_it_is_not_ended(
    session, spool_contract, user
):
    await _write(session, "written")
    executor, _, _, _ = _executor_on(session, user, spool_contract)

    await executor._end_read_transaction()

    assert session.in_transaction()


async def test_reassigning_the_session_watches_it_once(session, spool_contract, user):
    executor, _, _, _ = _executor_on(session, user, spool_contract)
    watch = executor._transaction_writes
    executor.session = session
    assert executor._transaction_writes is watch

    other = AsyncSession()
    executor.session = other
    for name, listener in (
        ("do_orm_execute", watch._executed),
        ("after_flush", watch._flushed),
        ("after_transaction_end", watch._ended),
    ):
        assert not event.contains(session.sync_session, name, listener)
    await other.close()


async def test_a_session_double_is_never_ended_early(spool_contract, user):
    executor, _, run, _, _ = _case(user, "Transcript.", spool_contract)
    executor.session = AsyncMock()

    for observer in _observers(executor, run):
        await observer.before_request()

    executor.session.commit.assert_not_awaited()


async def test_the_next_audio_source_keeps_the_first_inline_transcript_uncommitted(
    session, spool_contract, user
):
    """A per-source audio step resolves its sources one after the other before
    the attempt is activated. Source one's inline transcript is written on the
    run row and must stay uncommitted, so a failure before activation still
    rolls it back: opening source two's download does not commit it."""
    executor, repo, run, files = _executor_on(session, user, spool_contract)
    second = _audio_file(name="second.wav")
    files[second.id] = second
    executor.file_service.get_audio_download = spool_contract.downloads(
        list(files.values())
    )
    commits = _commits(session)
    persist = repo.update_input_payload.side_effect

    async def update_input_payload(**kwargs):
        # As the repository does: lock the run row, then write its payload.
        await session.scalar(
            sa.select(_RUNS.c.payload).where(_RUNS.c.id == 1).with_for_update()
        )
        payload = await persist(**kwargs)
        await _write(session, json.dumps(payload))
        return payload

    repo.update_input_payload.side_effect = update_input_payload
    # The reads the step runs before its input is resolved.
    await _read(session)

    step = _runtime_step(input_type="audio", output_mode="transcribe_only")
    for file_id in list(files):
        await executor._resolve_step_input(
            run=run,
            step=step,
            context={"flow_input": {}},
            prior_results=[],
            state=_state(),
            requested_file_ids=[file_id],
            attempt_no=1,
            version_metadata=_metadata(executor),
        )

    assert repo.update_input_payload.await_count == 2
    # Only source one's download ended a transaction: the one that had read.
    assert len(commits) == 1
    assert session.in_transaction()
    await executor._rollback()
    assert await _read(session) == "{}"
