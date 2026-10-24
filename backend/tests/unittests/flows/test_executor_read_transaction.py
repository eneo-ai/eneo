"""The executor ends its session's transaction before outside work only when
that transaction has done nothing but read.

The session is a real one over SQLite, so the statements a step runs reach
the executor the way they do in production; everything else is the audio
step's usual test doubles.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from eneo.files.file_service import FileService
from eneo.files.transcriber import TranscribedAudio
from eneo.flows.domain.flow import FlowRunStatus
from eneo.flows.domain.flow_run_exceptions import FlowExecutionOwnershipLost
from eneo.flows.domain.runtime_invariant_exceptions import FlowRuntimeInvariantError
from eneo.flows.domain.step_output import FileBackedStepText
from eneo.flows.infrastructure.flow_provider_call_recorder import (
    FlowProviderCallRecorder,
)
from eneo.flows.infrastructure.flow_transcript_source_repo import (
    FlowTranscriptSourceRepository,
)
from eneo.flows.runtime import executor as executor_module
from eneo.main.exceptions import TypedIOValidationException
from tests.unittests.flows import audio_spool_test_support
from tests.unittests.flows.test_flow_transcription import _audio_file, _state
from tests.unittests.flows.test_transcript_spill import _case, _metadata
from tests.unittests.flows.test_typed_io_executor import (
    _completed_step_result,
    _runtime_step,
)

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


_SHORT = "Short transcript."
# Over the case's 2048-byte inline limit, so it is spilled to a file.
_LONG = ("Long transcript. " * 200).strip()


def _two_sources(session, user, spool_contract, texts):
    """A per-source audio step's two sources, with the repository writing the
    run row as it does: lock the row, then write its payload. Records each
    write and each commit, in order."""
    executor, repo, run, files = _executor_on(session, user, spool_contract)
    second = _audio_file(name="second.wav")
    files[second.id] = second
    executor.file_service.get_audio_download = spool_contract.downloads(
        list(files.values())
    )
    executor.transcribers.model.transcribe.side_effect = [
        TranscribedAudio(text=text, duration_seconds=15000) for text in texts
    ]
    events: list[str] = []
    event.listen(
        session.sync_session, "after_commit", lambda _: events.append("commit")
    )
    persist = repo.update_input_payload.side_effect

    async def update_input_payload(**kwargs):
        await session.scalar(
            sa.select(_RUNS.c.payload).where(_RUNS.c.id == 1).with_for_update()
        )
        payload = await persist(**kwargs)
        await _write(session, json.dumps(payload))
        events.append("write")
        return payload

    repo.update_input_payload.side_effect = update_input_payload
    return executor, repo, run, list(files), events


async def _resolve_each_source(executor, run, step, file_ids, session):
    # The reads the step runs before its input is resolved.
    await _read(session)
    for file_id in file_ids:
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


async def _committed_transcript(session) -> dict | None:
    payload = await _read(session)
    assert payload is not None
    return json.loads(payload).get("transkribering")


async def test_the_next_audio_source_holds_no_transaction_for_an_inline_transcript(
    session, spool_contract, user
):
    """A per-source audio step resolves its sources one after the other before
    the attempt is activated. Source one's inline transcript is not written on
    the run row then: activation writes it, so no row lock is held while source
    two is downloaded and transcribed, and a failure before activation still
    leaves nothing."""
    executor, repo, run, file_ids, events = _two_sources(
        session, user, spool_contract, ("First transcript.", "Second transcript.")
    )
    step = _runtime_step(input_type="audio", output_mode="transcribe_only")

    await _resolve_each_source(executor, run, step, file_ids, session)

    repo.update_input_payload.assert_not_awaited()
    # Both downloads ended a transaction that had only read.
    assert events == ["commit", "commit"]
    # The step's own readers see the latest source's transcript.
    transcript = run.input_payload_json["transkribering"]
    assert transcript["text"] == "Second transcript."
    assert transcript["reference"]["source_attempt_no"] == 1
    assert await _read(session) == "{}"


@pytest.mark.parametrize(
    ("texts", "durable_before_activation"),
    [
        pytest.param(("First transcript.", _SHORT), None, id="inline-inline"),
        pytest.param(("First transcript.", _LONG), "file", id="inline-spill"),
        pytest.param((_LONG, _SHORT), "file", id="spill-inline"),
    ],
)
@pytest.mark.parametrize("ending", ["activated", "failed", "activation_commit_failed"])
async def test_activation_writes_the_last_inline_transcript_and_nothing_else_does(
    session, spool_contract, user, monkeypatch, texts, durable_before_activation, ending
):
    """Activation writes the attempt's staged inline transcript just before its
    commit. A spilled transcript is committed when it is written; a later one
    replaces it. A step that fails before its activation is committed writes
    no inline transcript, keeps a spilled one, and still publishes its
    transcript source."""
    executor, repo, run, file_ids, events = _two_sources(
        session, user, spool_contract, texts
    )
    insert = AsyncMock()
    monkeypatch.setattr(FlowTranscriptSourceRepository, "insert", insert)
    step = _runtime_step(input_type="audio", output_mode="transcribe_only")
    key = (run.id, step.step_id, 1)

    await _resolve_each_source(executor, run, step, file_ids, session)

    # Each spilled transcript is committed as soon as it is written.
    for index, recorded in enumerate(events):
        if recorded == "write":
            assert events[index + 1] == "commit"
    assert events.count("write") == sum(text == _LONG for text in texts)
    resolved = len(events)
    before_activation = await _committed_transcript(session)
    if durable_before_activation is None:
        assert before_activation is None
    else:
        assert FileBackedStepText.model_validate(before_activation).file_id

    last_inline = texts[-1] != _LONG
    if ending == "activated":
        await executor._activate_resolved_input_edges(run, step, _state(), 1, ())
        assert events[resolved:] == (["write", "commit"] if last_inline else ["commit"])
        committed = await _committed_transcript(session)
        assert committed is not None
        if last_inline:
            assert committed["kind"] == "inline_transcript"
            assert committed["text"] == texts[-1]
            assert run.input_payload_json["transkribering"] == committed
        else:
            assert committed == before_activation
    else:
        if ending == "activation_commit_failed":

            def refuse(_):
                raise RuntimeError("commit refused")

            event.listen(session.sync_session, "before_commit", refuse)
            with pytest.raises(RuntimeError, match="commit refused"):
                await executor._activate_resolved_input_edges(
                    run, step, _state(), 1, ()
                )
            event.remove(session.sync_session, "before_commit", refuse)
        claimed = _completed_step_result(
            run_id=run.id,
            flow_id=run.flow_id,
            tenant_id=run.tenant_id,
            step_order=1,
            text="",
        ).model_copy(
            update={
                "step_id": step.step_id,
                "current_attempt_no": 1,
                "status": "running",
            }
        )
        await executor._handle_generic_step_failure(
            run_id=run.id,
            tenant_id=run.tenant_id,
            step=step,
            attempt_no=1,
            claimed=claimed,
            exc=RuntimeError("source two failed"),
        )
        # The failure is written without the inline transcript.
        assert await _committed_transcript(session) == before_activation
    # The source is published once more by the failure when the activation
    # that published it first was rolled back.
    assert insert.await_count == (2 if ending == "activation_commit_failed" else 1)
    assert insert.await_args.kwargs["reference"].attempt_no == 1
    assert key not in executor._pending_transcript_sources


async def test_a_step_that_transcribed_must_activate_before_it_completes(
    session, spool_contract, user, monkeypatch
):
    """A handler that transcribes and returns without activating its attempt
    would lose the transcript and its source; the step fails instead."""
    executor, _, run, files = _executor_on(session, user, spool_contract)
    step = _runtime_step(input_type="audio", output_mode="transcribe_only")

    class _NeverActivates:
        async def execute(self, *, step, run, state, version_metadata, attempt_no):
            await executor._resolve_step_input(
                run=run,
                step=step,
                context={"flow_input": {}},
                prior_results=[],
                state=state,
                requested_file_ids=list(files),
                attempt_no=attempt_no,
                version_metadata=version_metadata,
            )
            return SimpleNamespace(output=SimpleNamespace())

    monkeypatch.setattr(executor, "_build_step_handler", lambda mode: _NeverActivates())

    with pytest.raises(FlowRuntimeInvariantError, match="without activating"):
        await executor._execute_step(
            step=step,
            run=run,
            state=_state(),
            attempt_no=1,
            version_metadata=_metadata(executor),
        )


async def _staged_inline_transcript(session, user, spool_contract, monkeypatch):
    """An audio step's attempt that transcribed one source inline and has not
    been activated: its transcript and source are staged, nothing is written."""
    executor, repo, run, file_ids, _ = _two_sources(
        session, user, spool_contract, (_SHORT, _SHORT)
    )
    insert = AsyncMock()
    monkeypatch.setattr(FlowTranscriptSourceRepository, "insert", insert)
    step = _runtime_step(input_type="audio", output_mode="transcribe_only")
    await _resolve_each_source(executor, run, step, file_ids[:1], session)
    key = (run.id, step.step_id, 1)
    assert executor._pending_transcript_sources[key].run_transcript is not None
    return executor, repo, run, step, key, insert


async def _assert_nothing_written(executor, repo, session, insert) -> None:
    repo.update_input_payload.assert_not_awaited()
    insert.assert_not_awaited()
    assert await _read(session) == "{}"


@pytest.mark.parametrize("failure", ["typed", "generic"])
async def test_a_failure_that_lost_the_terminalization_race_forgets_its_transcript(
    session, spool_contract, user, monkeypatch, failure
):
    """Terminalization won the race: the failure writes neither the staged
    transcript nor its source, and keeps no record of them."""
    executor, repo, run, step, key, insert = await _staged_inline_transcript(
        session, user, spool_contract, monkeypatch
    )
    repo.save_step_result.return_value = None
    repo.get.return_value = run.model_copy(update={"status": FlowRunStatus.CANCELLED})
    claimed = _completed_step_result(
        run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_order=1,
        text="",
    ).model_copy(
        update={"step_id": step.step_id, "current_attempt_no": 1, "status": "running"}
    )
    if failure == "typed":
        result = await executor._handle_typed_step_failure(
            run_id=run.id,
            tenant_id=run.tenant_id,
            step=step,
            attempt_no=1,
            claimed=claimed,
            typed_exc=TypedIOValidationException("bad input"),
            failed_input_payload=None,
        )
    else:
        result = await executor._handle_generic_step_failure(
            run_id=run.id,
            tenant_id=run.tenant_id,
            step=step,
            attempt_no=1,
            claimed=claimed,
            exc=RuntimeError("source failed"),
        )

    assert result == {"status": "skipped", "reason": "run_cancelled"}
    assert key not in executor._pending_transcript_sources
    await _assert_nothing_written(executor, repo, session, insert)


async def test_a_cancelled_step_forgets_its_transcript(
    session, spool_contract, user, monkeypatch
):
    executor, repo, run, step, key, insert = await _staged_inline_transcript(
        session, user, spool_contract, monkeypatch
    )

    result = await executor._handle_cancelled_step(
        run_id=run.id, tenant_id=run.tenant_id, step=step, attempt_no=1, state=None
    )

    assert result == {"status": "skipped", "reason": "run_cancelled"}
    assert key not in executor._pending_transcript_sources
    await _assert_nothing_written(executor, repo, session, insert)


async def test_an_execution_that_lost_its_ownership_forgets_its_transcript(
    session, spool_contract, user, monkeypatch
):
    executor, repo, run, _, key, insert = await _staged_inline_transcript(
        session, user, spool_contract, monkeypatch
    )

    class _Heartbeats:
        @asynccontextmanager
        async def track(self, owner, *, leased_at=None):
            yield

    async def execute_claimed(**kwargs):
        raise FlowExecutionOwnershipLost()

    monkeypatch.setattr(executor_module, "execution_heartbeats", _Heartbeats)
    monkeypatch.setattr(executor, "execute_claimed", execute_claimed)
    repo.mark_running_if_claimable.return_value = True
    repo.get.return_value = run

    result = await executor.execute(
        run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        run_revision=1,
        dispatch_task_id=None,
        retry_count=0,
    )

    assert result == {"status": "skipped", "reason": "execution_ownership_lost"}
    assert key not in executor._pending_transcript_sources
    await _assert_nothing_written(executor, repo, session, insert)
