"""The child process of the tool argument check: killed at its time limit and
replaced, also when it sends half a message or stops reading, without holding
the event loop; a child that dies is a typed host fault at once, and a checker
serves the event loop it is called from, on up to its slot count of children,
each within its memory budget."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Awaitable
from multiprocessing import Pipe
from multiprocessing.connection import Connection
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from eneo.flows.domain.schema_engine import ContractViolation
from eneo.flows.runtime import tool_argument_check
from eneo.flows.runtime.tool_argument_check import (
    ArgumentCheckUnfinished,
    ToolArgumentChecker,
    ToolArgumentCheckFailed,
    ToolArgumentCheckResult,
)
from eneo.main import config

# Python's re backtracks on this for seconds; each character more doubles it.
_SLOW_SCHEMA: dict[str, object] = {"properties": {"code": {"pattern": "^(a+)+$"}}}
_SLOW_ARGUMENTS: dict[str, object] = {"code": "a" * 27 + "!"}
_REQUIRED: dict[str, object] = {"required": ["days"]}
_MISSING_DAYS = ContractViolation(
    path=(), rule="required", detail="'days' is a required property"
)
_MiB = 1024 * 1024


def _deep_rows(rows: int) -> list[object]:
    """Rows of single-element lists nested 16 deep: decoding takes about 40
    times the JSON's size (60,000 rows, 2 MiB of JSON, about 85 MiB)."""
    deep: object = 0
    for _ in range(16):
        deep = [deep]
    return [deep] * rows


@pytest.fixture(autouse=True)
def children(monkeypatch):
    """Observe actual Popen handles and clean only processes this test started."""
    started: list[tool_argument_check._Child] = []
    start = tool_argument_check._start_child

    def tracked_start(alarm_seconds: float):
        child = start(alarm_seconds)
        started.append(child)
        return child

    monkeypatch.setattr(tool_argument_check, "_start_child", tracked_start)
    yield started
    for child in started:
        if child.process.poll() is None:
            child.process.kill()
        child.process.wait()
        child.connection.close()


def _fixture_child(script: str) -> tool_argument_check._Child:
    ours, theirs = Pipe()
    try:
        process = subprocess.Popen(
            [sys.executable, "-c", script, str(theirs.fileno())],
            pass_fds=(theirs.fileno(),),
            env={
                **os.environ,
                "PYTHONPATH": str(
                    Path(tool_argument_check.__file__).resolve().parents[3]
                ),
            },
        )
    finally:
        theirs.close()
    return tool_argument_check._Child(process, ours)


async def _timed_with_heartbeat(
    check: Awaitable[ToolArgumentCheckResult],
) -> tuple[ToolArgumentCheckResult, float, float]:
    """The check's result, how long it took, and the longest gap between two
    beats of a task that beats every 10 ms on the same event loop."""
    beats: list[float] = []

    async def heartbeat() -> None:
        while True:
            beats.append(time.monotonic())
            await asyncio.sleep(0.01)

    beating = asyncio.create_task(heartbeat())
    started = time.monotonic()
    try:
        result = await check
    finally:
        ended = time.monotonic()
        beating.cancel()
    marks = [started, *beats, ended]
    return result, ended - started, max(b - a for a, b in zip(marks, marks[1:]))


_PAYLOAD_DELAY_SECONDS = 3.0


_ANSWER_IN_PARTS = """
import os, pickle, struct, sys, time
from multiprocessing.connection import Connection
from eneo.flows.runtime.tool_argument_check import _Ready
connection = Connection(int(sys.argv[1]))
connection.send(_Ready())
connection.recv()
answer = pickle.dumps(None)
os.write(connection.fileno(), struct.pack("!i", len(answer)))
time.sleep(3.0)
os.write(connection.fileno(), answer)
time.sleep(60)
"""
_READY_LATE = """
import sys, time
from multiprocessing.connection import Connection
from eneo.flows.runtime.tool_argument_check import serve_tool_argument_checks
connection = Connection(int(sys.argv[1]))
time.sleep(0.6)
serve_tool_argument_checks(connection, 5.0)
"""


async def test_a_slow_start_does_not_count_against_the_checks_limit(
    monkeypatch,
    children,
) -> None:
    # Kills the mutant that waits for a new child's ready message under the
    # check's limit instead of the start budget: a start slower than the check
    # limit would end every first check as timed out.
    monkeypatch.setattr(tool_argument_check, "TOOL_ARGUMENT_CHECK_TIMEOUT_SECONDS", 0.3)
    real_start = tool_argument_check._start_child

    def start_one_late(alarm_seconds: float) -> tool_argument_check._Child:
        monkeypatch.setattr(tool_argument_check, "_start_child", real_start)
        child = _fixture_child(_READY_LATE)
        children.append(child)
        return child

    monkeypatch.setattr(tool_argument_check, "_start_child", start_one_late)

    assert await ToolArgumentChecker().check({}, _REQUIRED) == _MISSING_DAYS


async def test_a_check_past_the_limit_kills_its_child_and_the_next_gets_a_new_one(
    monkeypatch,
    children,
) -> None:
    # Kills the mutants that drop the child at the limit without killing it
    # (it backtracks on, alive), that keep the killed child (the next check
    # finds its pipe closed), and that close the pipe while the pipe thread is
    # still in its call (without waiting for it, or before the kill).
    monkeypatch.setattr(tool_argument_check, "TOOL_ARGUMENT_CHECK_TIMEOUT_SECONDS", 0.5)
    exchange = tool_argument_check._exchange
    open_when_left: list[bool] = []

    def slow_to_leave(connection: Connection, request) -> object:
        try:
            return exchange(connection, request)
        finally:
            time.sleep(0.2)
            open_when_left.append(not connection.closed)

    monkeypatch.setattr(tool_argument_check, "_exchange", slow_to_leave)
    checker = ToolArgumentChecker()

    assert await checker.check(_SLOW_ARGUMENTS, _SLOW_SCHEMA) == (
        ArgumentCheckUnfinished(timed_out=True)
    )
    assert children[-1].process.poll() == -signal.SIGKILL
    assert open_when_left == [True]
    assert await checker.check({}, _REQUIRED) == _MISSING_DAYS


async def test_an_answer_sent_in_parts_ends_at_the_limit_off_the_event_loop(
    monkeypatch,
    children,
) -> None:
    # Kills the mutant that reads the answer on the event loop: readable is not
    # a whole message, so the loop stops until the rest arrives, and the check
    # returns the late answer instead of ending at its limit.
    limit = 0.3
    monkeypatch.setattr(
        tool_argument_check, "TOOL_ARGUMENT_CHECK_TIMEOUT_SECONDS", limit
    )
    real_start = tool_argument_check._start_child

    def start_one_in_parts(alarm_seconds: float) -> tool_argument_check._Child:
        monkeypatch.setattr(tool_argument_check, "_start_child", real_start)
        child = _fixture_child(_ANSWER_IN_PARTS)
        children.append(child)
        return child

    monkeypatch.setattr(tool_argument_check, "_start_child", start_one_in_parts)
    checker = ToolArgumentChecker()

    result, elapsed, longest_gap = await _timed_with_heartbeat(
        checker.check({}, _REQUIRED)
    )

    assert result == ArgumentCheckUnfinished(timed_out=True)
    assert elapsed < _PAYLOAD_DELAY_SECONDS
    assert longest_gap < limit / 2
    assert await checker.check({}, _REQUIRED) == _MISSING_DAYS


async def test_a_child_that_stops_reading_ends_the_check_at_the_limit(
    monkeypatch,
    children,
) -> None:
    # Kills the mutants that write the arguments on the event loop (a stopped
    # child and arguments larger than the pipe's buffer hold the loop) and
    # that start the limit after the writes (the check waits for them).
    limit = 0.3
    checker = ToolArgumentChecker()
    assert await checker.check({}, _REQUIRED) == _MISSING_DAYS
    child = children[-1]
    pid = child.process.pid
    assert child.process.poll() is None
    os.kill(pid, signal.SIGSTOP)
    # Lets a check that waits for its writes finish instead of hanging.
    resume = threading.Timer(3.0, os.kill, (pid, signal.SIGCONT))
    resume.start()
    monkeypatch.setattr(
        tool_argument_check, "TOOL_ARGUMENT_CHECK_TIMEOUT_SECONDS", limit
    )
    try:
        result, elapsed, longest_gap = await _timed_with_heartbeat(
            checker.check({"blob": "x" * (1 << 20)}, _REQUIRED)
        )
    finally:
        resume.cancel()

    assert result == ArgumentCheckUnfinished(timed_out=True)
    assert elapsed < limit + 0.5
    assert longest_gap < limit / 2
    assert children[-1].process.poll() is not None
    assert await checker.check({}, _REQUIRED) == _MISSING_DAYS


async def test_a_child_that_dies_during_a_check_is_a_host_fault_at_once(
    caplog,
    children,
) -> None:
    # Kills the mutants that give the end of the child the schema's outcome,
    # raise it untyped (EOFError) or do not log it.
    checker = ToolArgumentChecker()
    checking = asyncio.create_task(checker.check(_SLOW_ARGUMENTS, _SLOW_SCHEMA))
    while not children:
        await asyncio.sleep(0.01)
    child = children[-1]
    pid = child.process.pid
    await asyncio.sleep(0.5)

    assert pid is not None
    ended = time.monotonic()
    os.kill(pid, signal.SIGKILL)
    with caplog.at_level(logging.WARNING, logger=tool_argument_check.__name__):
        with pytest.raises(ToolArgumentCheckFailed):
            await checking

    assert time.monotonic() - ended < 1.0
    assert [record.name for record in caplog.records] == [tool_argument_check.__name__]


@pytest.mark.parametrize("slots", [1, 2])
async def test_a_check_queued_behind_another_ends_at_its_own_limit(
    children, slots
) -> None:
    # Kills the mutant that starts the limit after the checker's admission:
    # the queued check would wait for the others and then get its full limit.
    # Also kills ending a running check's child when a queued check times out
    # or is cancelled.
    limit = [2.0]
    checker = ToolArgumentChecker(lambda: limit[0], lambda: slots)
    warm = [checker.check({}, _REQUIRED) for _ in range(slots)]
    assert await asyncio.gather(*warm) == [_MISSING_DAYS] * slots
    running = [
        asyncio.create_task(checker.check(_SLOW_ARGUMENTS, _SLOW_SCHEMA))
        for _ in range(slots)
    ]
    await asyncio.sleep(0.1)
    limit[0] = 0.3

    started = time.monotonic()
    queued = await checker.check({}, _REQUIRED)

    assert queued == ArgumentCheckUnfinished(timed_out=True)
    assert time.monotonic() - started < 1.0
    cancelled = asyncio.create_task(checker.check({}, _REQUIRED))
    await asyncio.sleep(0.05)
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    assert not any(task.done() for task in running)
    assert len(children) == slots
    assert all(child.process.poll() is None for child in children)
    for task in running:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_a_cancelled_check_does_not_leave_its_answer_to_the_next(
    children,
) -> None:
    # Kills the mutant that keeps the child of a cancelled check: it is still
    # checking, so the next check waits out the time limit for its answer.
    checker = ToolArgumentChecker()
    checking = asyncio.create_task(checker.check(_SLOW_ARGUMENTS, _SLOW_SCHEMA))
    await asyncio.sleep(0.5)
    child = children[-1]
    checking.cancel()
    with pytest.raises(asyncio.CancelledError):
        await checking

    assert child.process.poll() is not None
    assert await checker.check({}, _REQUIRED) == _MISSING_DAYS
    assert children[-1].process.pid != child.process.pid


def test_a_checker_serves_a_second_event_loop() -> None:
    # Kills the mutant that keeps one asyncio.Lock for every event loop: the
    # lock is bound to the first loop that waited on it, and the second
    # loop's waiting check raises RuntimeError.
    checker = ToolArgumentChecker()

    async def two_at_once() -> list[object]:
        return list(
            await asyncio.gather(
                checker.check({}, _REQUIRED), checker.check({}, _REQUIRED)
            )
        )

    for _ in range(2):
        loop = asyncio.new_event_loop()
        try:
            assert loop.run_until_complete(two_at_once()) == [_MISSING_DAYS] * 2
        finally:
            loop.close()


@pytest.mark.parametrize("active", [False, True], ids=["idle-eof", "active-alarm"])
def test_a_child_does_not_outlive_its_parent_pipe(children, active) -> None:
    # Kills missing EOF exit and missing active-work alarm after parent death.
    child = tool_argument_check._start_child(3.0)
    assert isinstance(child.connection.recv(), tool_argument_check._Ready)
    if active:
        child.connection.send(
            tool_argument_check._Request(
                tool_argument_check._Operation.WHOLE_VALUE,
                tool_argument_check._json_text({"code": "a" * 30 + "!"}),
                tool_argument_check._json_text(_SLOW_SCHEMA),
            )
        )
    child.connection.close()
    assert child.process.wait(timeout=5) == (-signal.SIGALRM if active else 0)


def test_dev_entrypoint_starts_checker_without_reimporting_main(tmp_path) -> None:
    # Kills spawn's replay of a dev server entrypoint and source-checkout drift.
    entry = tmp_path / "start"
    marker = tmp_path / "main-imports"
    wrong_source = tmp_path / "eneo"
    wrong_source.mkdir()
    (wrong_source / "__init__.py").write_text(
        "raise RuntimeError('wrong checker checkout')\n"
    )
    entry.write_text(
        rf"""
from pathlib import Path
marker = Path({str(marker)!r})
with marker.open('a') as log: log.write(__name__ + '\n')
if __name__ != '__main__': raise RuntimeError('server main was replayed')
if __name__ == '__main__':
    import asyncio, sys
    sys.path.insert(0, {str(Path(tool_argument_check.__file__).resolve().parents[3])!r})
    from eneo.flows.runtime.tool_argument_check import ToolArgumentChecker
    async def check():
        checker = ToolArgumentChecker()
        try:
            assert await checker.check({{'limit': 5}}, {{'properties': {{'limit': {{'type': 'integer'}}}}}}) is None
            print('checker source:', sys.modules['eneo.flows.runtime.tool_argument_check'].__file__)
        finally: checker.end_children()
    asyncio.run(check())
"""
    )
    result = subprocess.run(
        [sys.executable, str(entry)],
        env={**os.environ, "PYTHONPATH": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr
    assert marker.read_text() == "__main__\n"
    assert tool_argument_check.__file__ in result.stdout


async def test_a_slow_check_leaves_the_second_slot_to_another(children) -> None:
    # Kills the checker that runs one check at a time: the second check would
    # wait for the slow one to reach its limit.
    checker = ToolArgumentChecker(lambda: 5.0, lambda: 2)
    warm = [checker.check({}, _REQUIRED), checker.check({}, _REQUIRED)]
    assert await asyncio.gather(*warm) == [_MISSING_DAYS] * 2
    slow = asyncio.create_task(checker.check(_SLOW_ARGUMENTS, _SLOW_SCHEMA))
    await asyncio.sleep(0.1)

    started = time.monotonic()
    assert await checker.check({}, _REQUIRED) == _MISSING_DAYS

    assert time.monotonic() - started < 1.0
    assert not slow.done()
    assert len(children) == 2
    assert all(child.process.poll() is None for child in children)
    slow.cancel()
    with pytest.raises(asyncio.CancelledError):
        await slow


async def test_a_timeout_kills_only_its_own_slots_child(children) -> None:
    # Kills the mutant that ends every child when one check runs past its
    # limit.
    checker = ToolArgumentChecker(lambda: 0.5, lambda: 2)
    warm = [checker.check({}, _REQUIRED), checker.check({}, _REQUIRED)]
    assert await asyncio.gather(*warm) == [_MISSING_DAYS] * 2

    assert await checker.check(_SLOW_ARGUMENTS, _SLOW_SCHEMA) == (
        ArgumentCheckUnfinished(timed_out=True)
    )

    assert len(children) == 2
    assert sorted(child.process.poll() is None for child in children) == [False, True]


async def test_sequential_checks_share_one_child_and_concurrent_ones_start_at_most_n(
    children,
) -> None:
    # Kills the slots taken in turn (each sequential check would start or
    # wake another child) and a slot count that does not bound the children.
    checker = ToolArgumentChecker(lambda: 5.0, lambda: 2)
    for _ in range(3):
        assert await checker.check({}, _REQUIRED) == _MISSING_DAYS
    assert len(children) == 1

    four = [checker.check({}, _REQUIRED) for _ in range(4)]
    assert await asyncio.gather(*four) == [_MISSING_DAYS] * 4

    assert len(children) == 2
    assert all(child.process.poll() is None for child in children)


def test_a_second_event_loop_ends_every_child(children) -> None:
    # Kills the mutant that ends only one slot's child when another event
    # loop starts checking: the other child would serve no loop and stay.
    checker = ToolArgumentChecker(lambda: 5.0, lambda: 2)

    async def two_at_once() -> list[object]:
        return list(
            await asyncio.gather(
                checker.check({}, _REQUIRED), checker.check({}, _REQUIRED)
            )
        )

    first = asyncio.new_event_loop()
    try:
        assert first.run_until_complete(two_at_once()) == [_MISSING_DAYS] * 2
    finally:
        first.close()
    assert len(children) == 2
    second = asyncio.new_event_loop()
    try:
        assert second.run_until_complete(checker.check({}, _REQUIRED)) == (
            _MISSING_DAYS
        )
    finally:
        second.close()

    assert all(child.process.poll() is not None for child in children[:2])
    assert len(children) == 3
    checker.end_children()


@pytest.mark.parametrize(
    ("value", "answer"),
    [({"pad": "x" * 100}, _MISSING_DAYS), ({"days": 1, "pad": "x" * 100}, None)],
    ids=["violation", "fits"],
)
async def test_a_check_above_the_recycle_size_ends_its_child_after_answering(
    monkeypatch, children, value, answer
) -> None:
    # Kills the mutants that keep a child after a large check, that end it
    # before it answered, and that end it after a check of exactly the size.
    monkeypatch.setattr(tool_argument_check, "_RECYCLE_ABOVE_BYTES", 64)
    checker = ToolArgumentChecker()

    assert await checker.check(value, _REQUIRED) == answer

    assert len(children) == 1
    assert children[0].process.poll() is not None
    at_the_size = {"pad": "x" * 53}
    assert len(tool_argument_check._json_text(at_the_size)) == 64
    assert await checker.check(at_the_size, _REQUIRED) == _MISSING_DAYS
    assert await checker.check({"days": 1}, _REQUIRED) is None
    assert len(children) == 2
    assert children[1].process.poll() is None


_RAISES = """
import sys
from multiprocessing.connection import Connection
from eneo.flows.runtime.tool_argument_check import _CheckRaised, _Ready
connection = Connection(int(sys.argv[1]))
connection.send(_Ready())
while True:
    connection.recv()
    connection.send(_CheckRaised("{exception}"))
"""


def _start_one_that_raises(monkeypatch, children, exception: str = "SystemError"):
    real_start = tool_argument_check._start_child

    def start(alarm_seconds: float) -> tool_argument_check._Child:
        monkeypatch.setattr(tool_argument_check, "_start_child", real_start)
        child = _fixture_child(_RAISES.replace("{exception}", exception))
        children.append(child)
        return child

    monkeypatch.setattr(tool_argument_check, "_start_child", start)


async def test_a_check_that_raised_in_its_child_ends_that_child(
    monkeypatch, children
) -> None:
    # Kills the mutant that keeps a child after it raised: a raise can be an
    # allocation its memory budget refused (CPython then raises MemoryError or
    # SystemError), which leaves the child holding what it reached.
    _start_one_that_raises(monkeypatch, children)
    checker = ToolArgumentChecker()

    assert await checker.check({}, _REQUIRED) == ArgumentCheckUnfinished(
        timed_out=False
    )

    assert children[0].process.poll() is not None
    assert await checker.check({}, _REQUIRED) == _MISSING_DAYS
    assert len(children) == 2


@pytest.mark.parametrize(
    ("exception", "budget", "applied", "names_the_budget"),
    [
        ("SystemError", 256 * _MiB, True, True),
        ("MemoryError", 256 * _MiB, True, True),
        ("TypeError", 256 * _MiB, True, False),
        ("MemoryError", 256 * _MiB, False, False),
        ("MemoryError", None, False, False),
    ],
)
async def test_a_raise_that_can_be_the_memory_budget_names_its_setting(
    caplog, monkeypatch, children, exception, budget, applied, names_the_budget
) -> None:
    # Kills a budget refusal that the log does not tell apart from any other
    # raise, and a budget named where none was applied or the raise cannot be
    # an allocation that failed.
    monkeypatch.setattr(tool_argument_check, "_limit_memory", lambda *_: applied)
    _start_one_that_raises(monkeypatch, children, exception)
    checker = ToolArgumentChecker(memory_bytes=lambda: budget)

    with caplog.at_level(logging.WARNING, logger=tool_argument_check.__name__):
        assert await checker.check({}, _REQUIRED) == ArgumentCheckUnfinished(
            timed_out=False
        )

    messages = [record.getMessage() for record in caplog.records]
    assert messages[0] == f"A schema check raised {exception} in its process."
    if names_the_budget:
        assert messages[1:] == [
            "A schema check may have met its process's memory budget of "
            "268435456 bytes (FLOW_CONTRACT_CHECK_CHILD_MEMORY_BYTES)."
        ]
    else:
        assert messages[1:] == []


@pytest.mark.parametrize(
    ("budget", "accepted"), [(128 * _MiB - 1, False), (128 * _MiB, True)]
)
def test_the_child_memory_budget_holds_the_largest_request(budget, accepted) -> None:
    # Kills a budget below what the largest request at the default inline
    # ceiling needs to arrive (80 MiB measured): every such check would end
    # its child as a host fault.
    values = {
        **config.get_settings().model_dump(),
        "flow_contract_check_child_memory_bytes": budget,
    }
    if accepted:
        config.Settings.model_validate(values)
    else:
        with pytest.raises(
            ValidationError, match="flow_contract_check_child_memory_bytes"
        ):
            config.Settings.model_validate(values)


async def test_a_slot_whose_child_died_leaves_the_other_slot_serving(
    children,
) -> None:
    # Kills the mutant that ends every child on one child's host fault, and a
    # slot that stays unusable after its child died.
    checker = ToolArgumentChecker(lambda: 5.0, lambda: 2)
    dying = asyncio.create_task(checker.check(_SLOW_ARGUMENTS, _SLOW_SCHEMA))
    while not children:
        await asyncio.sleep(0.01)
    assert await checker.check({}, _REQUIRED) == _MISSING_DAYS
    assert len(children) == 2
    pid = children[0].process.pid
    assert pid is not None
    os.kill(pid, signal.SIGKILL)
    with pytest.raises(ToolArgumentCheckFailed):
        await dying

    two = [checker.check({}, _REQUIRED), checker.check({}, _REQUIRED)]
    assert await asyncio.gather(*two) == [_MISSING_DAYS] * 2

    assert len(children) == 3
    assert children[1].process.poll() is None


async def test_queued_checks_are_admitted_in_arrival_order(children) -> None:
    # Kills an admission that is not first come, first served, including one
    # that lets a check arriving as a slot is handed on take it from the check
    # it was handed to.
    checker = ToolArgumentChecker(lambda: 5.0)
    assert await checker.check({}, _REQUIRED) == _MISSING_DAYS
    running = asyncio.create_task(checker.check(_SLOW_ARGUMENTS, _SLOW_SCHEMA))
    await asyncio.sleep(0.1)
    admitted: list[int] = []

    async def queued(number: int) -> None:
        assert await checker.check({}, _REQUIRED) == _MISSING_DAYS
        admitted.append(number)

    waiting: list[asyncio.Task[None]] = []
    for number in range(4):
        waiting.append(asyncio.create_task(queued(number)))
        await asyncio.sleep(0.01)
    running.cancel()
    # The running check ends and hands its slot to check 0, which has not run
    # yet when this one asks.
    await asyncio.sleep(0)
    await queued(4)
    await asyncio.gather(*waiting)
    with pytest.raises(asyncio.CancelledError):
        await running

    assert admitted == [0, 1, 2, 3, 4]


async def test_a_check_cancelled_as_its_slot_is_handed_to_it_passes_it_on(
    children,
) -> None:
    # Kills an admission that loses the slot of a check cancelled after it
    # was woken (the next check would wait out its limit) or that gives the
    # slot out twice (two checks would take one child).
    checker = ToolArgumentChecker(lambda: 5.0)
    assert await checker.check({}, _REQUIRED) == _MISSING_DAYS
    running = asyncio.create_task(checker.check(_SLOW_ARGUMENTS, _SLOW_SCHEMA))
    await asyncio.sleep(0.1)
    woken = asyncio.create_task(checker.check({}, _REQUIRED))
    behind = asyncio.create_task(checker.check({}, _REQUIRED))
    await asyncio.sleep(0.05)
    running.cancel()
    # The running check ends and hands its slot to `woken`, which has not run.
    await asyncio.sleep(0)
    woken.cancel()

    with pytest.raises(asyncio.CancelledError):
        await woken
    started = time.monotonic()
    assert await behind == _MISSING_DAYS
    assert time.monotonic() - started < 1.0
    two = [checker.check({}, _REQUIRED), checker.check({}, _REQUIRED)]
    assert await asyncio.gather(*two) == [_MISSING_DAYS] * 2
    with pytest.raises(asyncio.CancelledError):
        await running


def test_importing_the_checker_does_not_import_settings() -> None:
    # Kills a settings read when the module loads: the child imports this
    # module and must not load the server's settings.
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, eneo.flows.runtime.tool_argument_check; "
            "assert 'eneo.main.config' not in sys.modules",
        ],
        env={
            **os.environ,
            "PYTHONPATH": str(Path(tool_argument_check.__file__).resolve().parents[3]),
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(("configured", "run_slots", "slots"), [(8, 3, 3), (2, 4, 2)])
def test_contract_check_slots_are_bounded_by_the_run_slots(
    monkeypatch, configured, run_slots, slots
) -> None:
    # Kills slots that follow only the setting: a run checks one value at a
    # time, so a slot past the run slots is never used.
    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: SimpleNamespace(
            flow_contract_check_slots=configured, task_execution_max_jobs=run_slots
        ),
    )
    assert tool_argument_check.contract_check_slots() == slots


def _data_limit(pid: int) -> int | None:
    """A process's soft RLIMIT_DATA in bytes, None when unlimited."""
    for line in Path(f"/proc/{pid}/limits").read_text().splitlines():
        if line.startswith("Max data size"):
            soft = line.split()[3]
            return None if soft == "unlimited" else int(soft)
    raise AssertionError("no data limit line")


@pytest.mark.skipif(sys.platform != "linux", reason="the budget is a Linux rlimit")
async def test_only_contract_check_children_take_the_memory_budget(
    monkeypatch, children
) -> None:
    # Kills a budget that is not applied, not read from the setting, or also
    # given to the tool argument checker.
    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: SimpleNamespace(
            flow_contract_check_slots=2,
            task_execution_max_jobs=4,
            flow_contract_check_child_memory_bytes=300 * _MiB,
        ),
    )
    # Earlier tests on this event loop can leave the module checkers warm
    # children started before the setting was patched.
    tool_argument_check._CONTRACT_CHECKER.end_children()
    tool_argument_check._CHECKER.end_children()
    try:
        assert await tool_argument_check.check_contract_value({}, _REQUIRED) == (
            _MISSING_DAYS
        )
        assert await tool_argument_check.check_tool_arguments({}, _REQUIRED) == (
            _MISSING_DAYS
        )
        assert [_data_limit(child.process.pid) for child in children] == [
            300 * _MiB,
            None,
        ]
    finally:
        tool_argument_check._CONTRACT_CHECKER.end_children()
        tool_argument_check._CHECKER.end_children()


@pytest.mark.skipif(sys.platform != "linux", reason="the budget is a Linux rlimit")
async def test_a_check_past_its_memory_budget_is_unfinished_and_ends_its_child(
    caplog, children
) -> None:
    # Kills a budget that is not enforced (decoding takes about 210 MiB and
    # the value is valid), that leaves the child holding what it reached, or
    # that leaves the slot without a child.
    checker = ToolArgumentChecker(lambda: 30.0, memory_bytes=lambda: 160 * _MiB)

    with caplog.at_level(logging.WARNING, logger=tool_argument_check.__name__):
        assert await checker.check(
            _deep_rows(150_000),  # 5 MiB of JSON
            {"type": "array", "items": {"type": "array"}},
        ) == ArgumentCheckUnfinished(timed_out=False)

    assert "FLOW_CONTRACT_CHECK_CHILD_MEMORY_BYTES" in caplog.records[-1].getMessage()
    assert children[0].process.poll() is not None
    assert await checker.check({}, _REQUIRED) == _MISSING_DAYS
    assert len(children) == 2


@pytest.mark.skipif(sys.platform == "linux", reason="Linux applies the budget")
async def test_where_no_budget_can_be_set_checks_run_and_say_so_once(
    caplog, children
) -> None:
    # Kills refusing every check on a development host without the rlimit,
    # and a warning for each child.
    tool_argument_check._memory_budget_not_applied.cache_clear()
    checker = ToolArgumentChecker(lambda: 5.0, lambda: 2, lambda: 1)

    with caplog.at_level(logging.WARNING, logger=tool_argument_check.__name__):
        two = [checker.check({}, _REQUIRED), checker.check({}, _REQUIRED)]
        assert await asyncio.gather(*two) == [_MISSING_DAYS] * 2

    assert len(children) == 2
    assert len(caplog.records) == 1
    assert "without their memory budget" in caplog.records[0].getMessage()


@pytest.mark.skipif(sys.platform != "linux", reason="the budget is a Linux rlimit")
async def test_a_violation_leaves_no_garbage_against_the_next_checks_budget(
    children,
) -> None:
    # Kills the child that keeps a violation's garbage: the error holds
    # reference cycles with the decoded value (about 85 MiB here), and a next
    # check that allocates few containers, like a list of integers, never
    # starts a collection, so it would meet the budget and not be checked.
    checker = ToolArgumentChecker(lambda: 30.0, memory_bytes=lambda: 160 * _MiB)

    violation = await checker.check(
        _deep_rows(60_000),  # 2 MiB of JSON
        {"type": "array", "items": {"type": "integer"}},
    )
    fits = await checker.check([0] * 5_000_000, {"type": "array"})  # 14 MiB

    assert isinstance(violation, ContractViolation)
    assert fits is None
    assert len(children) == 1


async def test_a_check_after_a_recycled_child_takes_a_warm_one(
    monkeypatch, children
) -> None:
    # Kills the recycled slot that goes back on top of the warm ones: the
    # next check would start a child while a warm one waits.
    monkeypatch.setattr(tool_argument_check, "_RECYCLE_ABOVE_BYTES", 64)
    checker = ToolArgumentChecker(lambda: 5.0, lambda: 2)
    warm = [checker.check({}, _REQUIRED), checker.check({}, _REQUIRED)]
    assert await asyncio.gather(*warm) == [_MISSING_DAYS] * 2

    assert await checker.check({"pad": "x" * 100}, _REQUIRED) == _MISSING_DAYS
    assert await checker.check({}, _REQUIRED) == _MISSING_DAYS

    assert len(children) == 2
    assert sorted(child.process.poll() is None for child in children) == [False, True]
