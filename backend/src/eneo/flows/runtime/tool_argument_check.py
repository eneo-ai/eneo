"""The check of a tool step's arguments against the tool's approved input
schema, in a child process with a hard time limit.

The schema comes from an MCP server. jsonschema matches its expressions
("pattern", the names of "patternProperties", also where
"additionalProperties" and "unevaluatedProperties" read them) with Python's
re, which has no time limit and holds the GIL while it backtracks. In the
worker's process such a check would stop the event loop (heartbeats,
cancellation) for as long as it runs, also on a thread, and a thread cannot
be stopped. A child process can be killed.

One child per worker process, started at the first check with the "spawn"
start method (a fork of a process that runs an event loop and threads can
copy a lock in its held state), and spoken to over a Pipe: the arguments and
the schema go as JSON text, the answer comes back as typed plain data. It
imports this module and domain/schema_engine (jsonschema and referencing,
nothing of the application), and spawn runs the worker's entry script in it
again as __mp_main__, as for the PDF extraction in files/text.py.

Every read and write on the pipe runs on one thread the checker owns, and the
event loop awaits it: a child that stops reading, or that sends a message in
parts, holds that thread and not the loop. A check that ends early kills the
child first, which ends the thread's read or write at once, and closes the
pipe only after that call has returned.

Checks are serialized on the child. A check takes milliseconds, and a worker
runs at most task_execution_max_jobs runs at once (4 by default), so a check
waits for at most that many minus one earlier checks. Each check gets
TOOL_ARGUMENT_CHECK_TIMEOUT_SECONDS from the moment it is handed to the pipe
thread to its answer (its writes, the check in the child, the read), not
counting that wait or the start of a new child.

The child does not outlive its worker by more than the check limit and one
second: a worker that exits kills it (it is a daemon), an idle child ends when
its pipe closes, and a check carries an alarm that ends the child when no one
has stopped it in time.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import multiprocessing
import signal
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess

from eneo.flows.domain.schema_engine import (
    ContractFinding,
    ContractNotEvaluable,
    ContractViolation,
    evaluate_contract,
)

logger = logging.getLogger(__name__)

# How long one check of a tool's arguments may take, from its hand-over to the
# pipe thread to its answer, not counting the wait for earlier checks or the
# start of a new child (_START_TIMEOUT_SECONDS). A real tool's
# arguments are checked in milliseconds; the limit leaves room for a loaded host
# and stays far inside a step's time.
TOOL_ARGUMENT_CHECK_TIMEOUT_SECONDS = 2.0
# How long starting a child may take: a fresh interpreter that imports
# jsonschema, about 0.15 s on an idle host. A start that takes longer is a
# fault of the host, not of the schema, so the limit is generous.
_START_TIMEOUT_SECONDS = 10.0

_SPAWN = multiprocessing.get_context("spawn")


class ToolArgumentCheckFailed(Exception):
    """The check could not run on this worker: its process did not start in
    time, ended, or answered out of protocol. A fault of the host, not of
    the schema or the arguments."""


class ToolArgumentsNotJson(Exception):
    """The arguments cannot be written as JSON text: a NaN or an infinity
    (JSON has no such number), or nesting deeper than the encoder takes."""


@dataclass(frozen=True, slots=True)
class ArgumentCheckUnfinished:
    """The arguments could not be checked against the schema: the check ran
    past its limit (``timed_out``), or raised inside the child."""

    timed_out: bool


ToolArgumentCheckResult = ContractFinding | ArgumentCheckUnfinished


@dataclass(frozen=True, slots=True)
class _Ready:
    """The child's first message: it has imported what it checks with, so
    the import counts against the start's limit and not against a check's."""


@dataclass(frozen=True, slots=True)
class _CheckRaised:
    """A check that raised inside the child, by its exception's type."""

    exception: str


def _serve(connection: Connection, alarm_seconds: float) -> None:
    """The child: answers each check (the arguments, then the schema, as JSON
    text) until the parent closes its end of the pipe."""
    # A check whose worker was killed is never stopped by it: the alarm's
    # default action ends the child instead.
    signal.signal(signal.SIGALRM, signal.SIG_DFL)
    connection.send(_Ready())
    while True:
        try:
            arguments_text = connection.recv_bytes()
            schema_text = connection.recv_bytes()
        except EOFError:
            return
        signal.setitimer(signal.ITIMER_REAL, alarm_seconds)
        try:
            arguments: object = json.loads(arguments_text)
            schema: Mapping[str, object] = json.loads(schema_text)
            answer = evaluate_contract(arguments, schema)
        except Exception as exc:  # the child's boundary: the parent logs it
            answer = _CheckRaised(type(exc).__name__)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
        connection.send(answer)


@dataclass(frozen=True, slots=True)
class _Child:
    process: BaseProcess
    connection: Connection


def _start_child() -> _Child:
    ours, theirs = _SPAWN.Pipe()
    process = _SPAWN.Process(
        target=_serve,
        args=(theirs, TOOL_ARGUMENT_CHECK_TIMEOUT_SECONDS + 1),
        name="flow-tool-argument-check",
        daemon=True,
    )
    process.start()
    # Only the child holds its end now, so its exit reads as EOF here.
    theirs.close()
    return _Child(process, ours)


def _exchange(
    connection: Connection, arguments_text: bytes, schema_text: bytes
) -> object:
    """One check on the pipe thread: both writes and the read of the answer."""
    connection.send_bytes(arguments_text)
    connection.send_bytes(schema_text)
    answer: object = connection.recv()
    return answer


def _json_text(value: Mapping[str, object]) -> bytes:
    return json.dumps(value, allow_nan=False).encode()


class ToolArgumentChecker:
    """Checks one call at a time on one child."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = asyncio.Lock()
        self._child: _Child | None = None
        self._pipe_thread = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="flow-tool-argument-pipe"
        )
        self._pipe_call: concurrent.futures.Future[object] | None = None

    async def check(
        self, arguments: Mapping[str, object], schema: Mapping[str, object]
    ) -> ToolArgumentCheckResult:
        """``evaluate_contract(arguments, schema)``, in the child, or
        ArgumentCheckUnfinished: when it runs past
        TOOL_ARGUMENT_CHECK_TIMEOUT_SECONDS the child is killed.

        Raises ToolArgumentsNotJson for arguments that are no JSON text, and
        ToolArgumentCheckFailed when the child does not start within
        _START_TIMEOUT_SECONDS, ends or answers out of protocol. A child that
        failed, or whose check was cancelled, is killed, and the next check
        starts a new one."""
        try:
            arguments_text = _json_text(arguments)
        except (RecursionError, ValueError) as exc:
            raise ToolArgumentsNotJson from exc
        try:
            schema_text = _json_text(schema)
        except (RecursionError, ValueError):
            logger.warning("A tool's input schema cannot be written as JSON text.")
            return ArgumentCheckUnfinished(timed_out=False)
        async with self._lock_of_running_loop():
            try:
                answer = await self._ask(arguments_text, schema_text)
            except TimeoutError:
                exit_code = self._end_child()
                logger.warning(
                    "A tool argument check ran past %s seconds; its process "
                    "was killed (exit code before: %s).",
                    TOOL_ARGUMENT_CHECK_TIMEOUT_SECONDS,
                    exit_code,
                )
                return ArgumentCheckUnfinished(timed_out=True)
            except ToolArgumentCheckFailed as exc:
                exit_code = self._end_child()
                logger.error(
                    "A tool argument check could not run: %s (exit code "
                    "before the kill: %s).",
                    exc,
                    exit_code,
                )
                raise
            except BaseException:
                # The child may still be checking, and its late answer would
                # be read as the next check's.
                self._end_child()
                raise
        if isinstance(answer, _CheckRaised):
            logger.warning(
                "A tool argument check raised %s in its process.", answer.exception
            )
            return ArgumentCheckUnfinished(timed_out=False)
        return answer

    def _lock_of_running_loop(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if loop is not self._loop:
            # A lock belongs to one event loop, and a child that served
            # another loop may still owe that loop an answer.
            self._end_child()
            self._loop, self._lock = loop, asyncio.Lock()
        return self._lock

    async def _ask(
        self, arguments_text: bytes, schema_text: bytes
    ) -> ContractFinding | _CheckRaised:
        """Raises TimeoutError when the check runs past its limit, and
        ToolArgumentCheckFailed for a fault of the child."""
        try:
            child = self._child or await self._started_child()
        except (EOFError, OSError) as exc:
            raise ToolArgumentCheckFailed("its process ended") from exc
        async with asyncio.timeout(TOOL_ARGUMENT_CHECK_TIMEOUT_SECONDS):
            try:
                answer = await self._on_pipe_thread(
                    lambda: _exchange(child.connection, arguments_text, schema_text)
                )
            except (EOFError, OSError) as exc:
                raise ToolArgumentCheckFailed("its process ended") from exc
        if answer is None or isinstance(
            answer, ContractViolation | ContractNotEvaluable | _CheckRaised
        ):
            return answer
        raise ToolArgumentCheckFailed(f"its process answered {type(answer).__name__}")

    async def _started_child(self) -> _Child:
        child = self._child = _start_child()
        try:
            async with asyncio.timeout(_START_TIMEOUT_SECONDS):
                ready = await self._on_pipe_thread(child.connection.recv)
        except TimeoutError as exc:
            raise ToolArgumentCheckFailed(
                f"its process did not start within {_START_TIMEOUT_SECONDS} seconds"
            ) from exc
        if not isinstance(ready, _Ready):
            raise ToolArgumentCheckFailed(f"its process started with {ready!r}")
        return child

    async def _on_pipe_thread(self, call: Callable[[], object]) -> object:
        self._pipe_call = self._pipe_thread.submit(call)
        return await asyncio.wrap_future(self._pipe_call)

    def _end_child(self) -> int | None:
        """Kill the child, if any; its exit code before the kill (None while
        it ran)."""
        child, self._child = self._child, None
        pipe_call, self._pipe_call = self._pipe_call, None
        if child is None:
            return None
        child.process.join(0)
        exit_code = child.process.exitcode
        child.process.kill()
        # A killed child ends at once, also a stopped one, so the join does not
        # hold the event loop.
        child.process.join()
        if pipe_call is not None:
            # The child's end of the pipe closed when it died, so a read or
            # write the thread is in fails at once (EOF, broken pipe), and this
            # waits only until the thread leaves that call. The parent's end is
            # closed after it: never under a running call, and its number is
            # not reused for the next child's pipe while the call holds it.
            concurrent.futures.wait((pipe_call,))
        child.connection.close()
        return exit_code


_CHECKER = ToolArgumentChecker()


async def check_tool_arguments(
    arguments: Mapping[str, object], schema: Mapping[str, object]
) -> ToolArgumentCheckResult:
    """The result of ``arguments`` against ``schema``, from this worker's
    child process (ToolArgumentChecker.check)."""
    return await _CHECKER.check(arguments, schema)
