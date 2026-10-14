"""The child process of the tool argument check: killed at its time limit and
replaced, also when it sends half a message or stops reading, without holding
the event loop; a child that dies is a typed host fault at once, and a checker
serves the event loop it is called from."""

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

import pytest

from eneo.flows.domain.schema_engine import ContractViolation
from eneo.flows.runtime import tool_argument_check
from eneo.flows.runtime.tool_argument_check import (
    ArgumentCheckUnfinished,
    ToolArgumentChecker,
    ToolArgumentCheckFailed,
    ToolArgumentCheckResult,
)

# Python's re backtracks on this for seconds; each character more doubles it.
_SLOW_SCHEMA: dict[str, object] = {"properties": {"code": {"pattern": "^(a+)+$"}}}
_SLOW_ARGUMENTS: dict[str, object] = {"code": "a" * 27 + "!"}
_REQUIRED: dict[str, object] = {"required": ["days"]}
_MISSING_DAYS = ContractViolation(
    path=(), rule="required", detail="'days' is a required property"
)


@pytest.fixture(autouse=True)
def children(monkeypatch):
    """Observe actual Popen handles and clean only processes this test started."""
    started: list[tool_argument_check._Child] = []
    start = tool_argument_check._start_child

    def tracked_start():
        child = start()
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

    def start_one_late() -> tool_argument_check._Child:
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

    def start_one_in_parts() -> tool_argument_check._Child:
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
    child = tool_argument_check._start_child()
    assert isinstance(child.connection.recv(), tool_argument_check._Ready)
    if active:
        child.connection.send(
            tool_argument_check._Request(
                tool_argument_check._Operation.FULL_ARGUMENTS,
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
        finally: checker._end_child()
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
