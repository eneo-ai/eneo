"""The child process of the tool argument check: killed at its time limit and
replaced, also when it sends half a message or stops reading, without holding
the event loop; a child that dies is a typed host fault at once, and a checker
serves the event loop it is called from."""

from __future__ import annotations

import asyncio
import logging
import multiprocessing
import os
import pickle
import signal
import struct
import threading
import time
from collections.abc import Awaitable
from multiprocessing.connection import Connection

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


def _children() -> set[int | None]:
    return {child.pid for child in multiprocessing.active_children()}


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


def _answer_in_two_parts(connection: Connection) -> None:
    """A child (spawned, so module level) that starts as the real one, then
    sends the header of its answer at once and the rest only after
    _PAYLOAD_DELAY_SECONDS."""
    connection.send(tool_argument_check._Ready())
    connection.recv_bytes()
    connection.recv_bytes()
    answer = pickle.dumps(None)
    os.write(connection.fileno(), struct.pack("!i", len(answer)))
    time.sleep(_PAYLOAD_DELAY_SECONDS)
    os.write(connection.fileno(), answer)
    time.sleep(60)


_READY_DELAY_SECONDS = 0.6


def _ready_late(connection: Connection, alarm_seconds: float) -> None:
    """A child (spawned, so module level) that takes _READY_DELAY_SECONDS to
    start, then serves as the real one."""
    time.sleep(_READY_DELAY_SECONDS)
    tool_argument_check._serve(connection, alarm_seconds)


async def test_a_slow_start_does_not_count_against_the_checks_limit(
    monkeypatch,
) -> None:
    # Kills the mutant that waits for a new child's ready message under the
    # check's limit instead of the start budget: a start slower than the check
    # limit would end every first check as timed out.
    monkeypatch.setattr(tool_argument_check, "TOOL_ARGUMENT_CHECK_TIMEOUT_SECONDS", 0.3)
    real_start = tool_argument_check._start_child

    def start_one_late() -> tool_argument_check._Child:
        monkeypatch.setattr(tool_argument_check, "_start_child", real_start)
        ours, theirs = multiprocessing.get_context("spawn").Pipe()
        process = multiprocessing.get_context("spawn").Process(
            target=_ready_late, args=(theirs, 5.0), daemon=True
        )
        process.start()
        theirs.close()
        return tool_argument_check._Child(process, ours)

    monkeypatch.setattr(tool_argument_check, "_start_child", start_one_late)

    assert await ToolArgumentChecker().check({}, _REQUIRED) == _MISSING_DAYS


async def test_a_check_past_the_limit_kills_its_child_and_the_next_gets_a_new_one(
    monkeypatch,
) -> None:
    # Kills the mutants that drop the child at the limit without killing it
    # (it backtracks on, alive), that keep the killed child (the next check
    # finds its pipe closed), and that close the pipe while the pipe thread is
    # still in its call (without waiting for it, or before the kill).
    monkeypatch.setattr(tool_argument_check, "TOOL_ARGUMENT_CHECK_TIMEOUT_SECONDS", 0.5)
    exchange = tool_argument_check._exchange
    open_when_left: list[bool] = []

    def slow_to_leave(connection: Connection, *texts: bytes) -> object:
        try:
            return exchange(connection, *texts)
        finally:
            time.sleep(0.2)
            open_when_left.append(not connection.closed)

    monkeypatch.setattr(tool_argument_check, "_exchange", slow_to_leave)
    checker = ToolArgumentChecker()
    before = _children()

    assert await checker.check(_SLOW_ARGUMENTS, _SLOW_SCHEMA) == (
        ArgumentCheckUnfinished(timed_out=True)
    )
    assert _children() - before == set()
    assert open_when_left == [True]
    assert await checker.check({}, _REQUIRED) == _MISSING_DAYS


async def test_an_answer_sent_in_parts_ends_at_the_limit_off_the_event_loop(
    monkeypatch,
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
        ours, theirs = multiprocessing.get_context("spawn").Pipe()
        process = multiprocessing.get_context("spawn").Process(
            target=_answer_in_two_parts, args=(theirs,), daemon=True
        )
        process.start()
        theirs.close()
        return tool_argument_check._Child(process, ours)

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
) -> None:
    # Kills the mutants that write the arguments on the event loop (a stopped
    # child and arguments larger than the pipe's buffer hold the loop) and
    # that start the limit after the writes (the check waits for them).
    limit = 0.3
    checker = ToolArgumentChecker()
    before = _children()
    assert await checker.check({}, _REQUIRED) == _MISSING_DAYS
    (pid,) = _children() - before
    assert pid is not None
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
    assert _children() - before == set()
    assert await checker.check({}, _REQUIRED) == _MISSING_DAYS


async def test_a_child_that_dies_during_a_check_is_a_host_fault_at_once(
    caplog,
) -> None:
    # Kills the mutants that give the end of the child the schema's outcome,
    # raise it untyped (EOFError) or do not log it.
    checker = ToolArgumentChecker()
    before = _children()
    checking = asyncio.create_task(checker.check(_SLOW_ARGUMENTS, _SLOW_SCHEMA))
    while not _children() - before:
        await asyncio.sleep(0.01)
    (pid,) = _children() - before
    await asyncio.sleep(0.5)

    assert pid is not None
    ended = time.monotonic()
    os.kill(pid, signal.SIGKILL)
    with caplog.at_level(logging.WARNING, logger=tool_argument_check.__name__):
        with pytest.raises(ToolArgumentCheckFailed):
            await checking

    assert time.monotonic() - ended < 1.0
    assert [record.name for record in caplog.records] == [tool_argument_check.__name__]


async def test_a_cancelled_check_does_not_leave_its_answer_to_the_next() -> None:
    # Kills the mutant that keeps the child of a cancelled check: it is still
    # checking, so the next check waits out the time limit for its answer.
    checker = ToolArgumentChecker()
    checking = asyncio.create_task(checker.check(_SLOW_ARGUMENTS, _SLOW_SCHEMA))
    await asyncio.sleep(0.5)
    checking.cancel()
    with pytest.raises(asyncio.CancelledError):
        await checking

    assert await checker.check({}, _REQUIRED) == _MISSING_DAYS


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
