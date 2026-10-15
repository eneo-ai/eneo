"""Bounded JSON Schema checks in a killable child: a tool's arguments at
publish and in runs, and a copy_input step's value against its contracts.

A schema can hold the GIL while matching an expression or expand references
without a bound. A thread cannot stop that work. Tool arguments and copy
values each have their own checker and time limit; a checker's child serves
one event loop's checks, serialized over a local Pipe, so a check can wait for
every check queued before it on the same checker, each up to that checker's
limit. A copy check never delays a tool's argument check. A fresh interpreter
starts only the checker entry module, never the server's or worker's main
script.

One owned thread handles every framed pipe read and write, including partial
messages. The deadline starts before the request is written, after the child's
ready message. Cancellation or timeout kills the child before waiting for that
thread and closing its connection. The next check starts a new child.

An idle child ends on parent pipe EOF; active work carries an alarm that ends
the child within the check limit plus one second if its parent disappears.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import signal
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum, auto
from multiprocessing import Pipe
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Literal, overload

from eneo.flows.domain.schema_engine import (
    ContractFinding,
    ContractNotEvaluable,
    ContractViolation,
    evaluate_contract,
    evaluate_property,
    property_schema,
)

logger = logging.getLogger(__name__)

# Includes the pipe writes, evaluation and answer, but not earlier checks or
# child startup. Ordinary arguments take milliseconds; this leaves host headroom.
TOOL_ARGUMENT_CHECK_TIMEOUT_SECONDS = 2.0
# A copy value can be as large as the inline byte ceiling (8 MiB by default).
# On a development host (load about 6) the slowest valid 8 MiB value measured,
# a list of one-integer lists checked for type and minimum, took 21 s; flat
# integer lists took 14 s and a large object 5 s. Close to three times that
# leaves room for a loaded host. The check's time grows with the value's size
# and the contract's work per item.
COPY_CONTRACT_CHECK_TIMEOUT_SECONDS = 60.0
# Importing jsonschema takes about 0.15 s on an idle host. Startup failure is a
# host fault, so it has a separate, generous budget.
_START_TIMEOUT_SECONDS = 10.0


class ToolArgumentCheckFailed(Exception):
    """The child failed to start, ended or answered out of protocol: a host fault."""


class ToolArgumentsNotJson(Exception):
    """The checked value contains a non-JSON number or exceeds the JSON
    encoder's nesting."""


@dataclass(frozen=True, slots=True)
class ArgumentCheckUnfinished:
    """A check exceeded its deadline or raised inside the child."""

    timed_out: bool


@dataclass(frozen=True, slots=True)
class FixedPropertyViolation:
    """A fixed property's violation with its known argument name.

    A false subschema's error path can be empty, so the name comes from the
    requested property rather than from the validator's error path.
    """

    argument: str
    violation: ContractViolation


ToolArgumentCheckResult = ContractFinding | ArgumentCheckUnfinished
FixedPropertyCheckResult = (
    FixedPropertyViolation | ContractNotEvaluable | ArgumentCheckUnfinished | None
)
_CheckAnswer = ContractFinding | FixedPropertyViolation


class _Operation(Enum):
    WHOLE_VALUE = auto()
    FIXED_PROPERTIES = auto()


@dataclass(frozen=True, slots=True)
class _Request:
    operation: _Operation
    value_text: bytes
    schema_text: bytes


@dataclass(frozen=True, slots=True)
class _Ready:
    """Imports completed; the check's deadline can start after this message."""


@dataclass(frozen=True, slots=True)
class _CheckRaised:
    exception: str


def _fixed_properties(
    fixed: Mapping[str, object], schema: Mapping[str, object]
) -> FixedPropertyViolation | ContractNotEvaluable | None:
    unfinished = False
    for name, value in fixed.items():
        subschema = property_schema(schema, name)
        if subschema is None:
            continue
        finding = evaluate_property(
            value, schema=schema, name=name, subschema=subschema
        )
        if isinstance(finding, ContractViolation):
            return FixedPropertyViolation(argument=name, violation=finding)
        unfinished |= isinstance(finding, ContractNotEvaluable)
    return ContractNotEvaluable() if unfinished else None


def serve_tool_argument_checks(connection: Connection, alarm_seconds: float) -> None:
    """Serve framed requests until parent EOF, with an alarm on active work."""
    signal.signal(signal.SIGALRM, signal.SIG_DFL)
    connection.send(_Ready())
    while True:
        try:
            request = connection.recv()
        except EOFError:
            return
        signal.setitimer(signal.ITIMER_REAL, alarm_seconds)
        try:
            if not isinstance(request, _Request):
                raise TypeError("Unexpected tool check request")
            schema: dict[str, object] = json.loads(request.schema_text)
            answer: _CheckAnswer | _CheckRaised
            if request.operation is _Operation.WHOLE_VALUE:
                answer = evaluate_contract(json.loads(request.value_text), schema)
            else:
                answer = _fixed_properties(json.loads(request.value_text), schema)
        except Exception as exc:  # the child's boundary: the parent logs the type
            answer = _CheckRaised(type(exc).__name__)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
        connection.send(answer)


@dataclass(frozen=True, slots=True)
class _Child:
    process: subprocess.Popen[bytes]
    connection: Connection


def _start_child(alarm_seconds: float) -> _Child:
    ours, theirs = Pipe()
    try:
        process = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve().with_name("tool_argument_check_child.py")),
                str(theirs.fileno()),
                str(alarm_seconds),
            ],
            pass_fds=(theirs.fileno(),),
        )
    except OSError:
        ours.close()
        raise
    finally:
        # Only the child holds its end now, so its exit reads as EOF here.
        theirs.close()
    return _Child(process, ours)


def _exchange(connection: Connection, request: _Request) -> object:
    """The whole exchange belongs to the pipe thread, including both writes."""
    connection.send(request)
    answer: object = connection.recv()
    return answer


def _json_text(value: object) -> bytes:
    return json.dumps(value, allow_nan=False).encode()


def tool_argument_limit_seconds() -> float:
    return TOOL_ARGUMENT_CHECK_TIMEOUT_SECONDS


def copy_contract_limit_seconds() -> float:
    return COPY_CONTRACT_CHECK_TIMEOUT_SECONDS


class ToolArgumentChecker:
    """Checks one request at a time on one child of the current event loop."""

    def __init__(
        self, limit_seconds: Callable[[], float] = tool_argument_limit_seconds
    ) -> None:
        """``limit_seconds`` gives the check's time limit, read at each check."""
        self._limit_seconds = limit_seconds
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = asyncio.Lock()
        self._child: _Child | None = None
        self._pipe_thread = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="flow-tool-argument-pipe"
        )
        self._pipe_call: concurrent.futures.Future[object] | None = None

    async def check(
        self,
        value: Mapping[str, object] | Sequence[object],
        schema: Mapping[str, object],
    ) -> ToolArgumentCheckResult:
        """Validate the whole value, including its schema's metaschema.

        Raises ToolArgumentsNotJson for a non-JSON value and
        ToolArgumentCheckFailed for host faults. Cancellation and deadlines
        kill the child; the next check starts a new one.
        """
        return await self._check(value, schema, _Operation.WHOLE_VALUE)

    async def check_fixed_properties(
        self, fixed: Mapping[str, object], schema: Mapping[str, object]
    ) -> FixedPropertyCheckResult:
        """Check properties of an already admitted schema with its root resolver.

        This checks neither absent/bound arguments nor the full object's rules.
        Unfinished checks and host faults have the same boundary as ``check``.
        """
        return await self._check(fixed, schema, _Operation.FIXED_PROPERTIES)

    @overload
    async def _check(
        self,
        value: Mapping[str, object] | Sequence[object],
        schema: Mapping[str, object],
        operation: Literal[_Operation.WHOLE_VALUE],
    ) -> ToolArgumentCheckResult: ...

    @overload
    async def _check(
        self,
        value: Mapping[str, object],
        schema: Mapping[str, object],
        operation: Literal[_Operation.FIXED_PROPERTIES],
    ) -> FixedPropertyCheckResult: ...

    async def _check(
        self,
        value: Mapping[str, object] | Sequence[object],
        schema: Mapping[str, object],
        operation: _Operation,
    ) -> ToolArgumentCheckResult | FixedPropertyCheckResult:
        try:
            value_text = _json_text(value)
        except (RecursionError, ValueError) as exc:
            raise ToolArgumentsNotJson from exc
        try:
            schema_text = _json_text(schema)
        except (RecursionError, ValueError):
            logger.warning("A schema cannot be written as JSON text.")
            return ArgumentCheckUnfinished(timed_out=False)
        request = _Request(operation, value_text, schema_text)
        async with self._lock_of_running_loop():
            try:
                answer = await self._ask(request)
            except TimeoutError:
                exit_code = self._end_child()
                logger.warning(
                    "A schema check ran past %s seconds; its process "
                    "was killed (exit code before: %s).",
                    self._limit_seconds(),
                    exit_code,
                )
                return ArgumentCheckUnfinished(timed_out=True)
            except ToolArgumentCheckFailed as exc:
                exit_code = self._end_child()
                logger.error(
                    "A schema check could not run: %s (exit code before the kill: %s).",
                    exc,
                    exit_code,
                )
                raise
            except BaseException:
                # A late answer must never be read as the next check's result.
                self._end_child()
                raise
        if isinstance(answer, _CheckRaised):
            logger.warning("A schema check raised %s in its process.", answer.exception)
            return ArgumentCheckUnfinished(timed_out=False)
        return answer

    def _lock_of_running_loop(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if loop is not self._loop:
            # A child serving another loop may still owe that loop an answer.
            self._end_child()
            self._loop, self._lock = loop, asyncio.Lock()
        return self._lock

    async def _ask(self, request: _Request) -> _CheckAnswer | _CheckRaised:
        try:
            child = self._child or await self._started_child()
        except (EOFError, OSError) as exc:
            raise ToolArgumentCheckFailed("its process ended") from exc
        async with asyncio.timeout(self._limit_seconds()):
            try:
                answer = await self._on_pipe_thread(
                    lambda: _exchange(child.connection, request)
                )
            except (EOFError, OSError) as exc:
                raise ToolArgumentCheckFailed("its process ended") from exc
        if answer is None or isinstance(answer, ContractNotEvaluable | _CheckRaised):
            return answer
        if request.operation is _Operation.WHOLE_VALUE and isinstance(
            answer, ContractViolation
        ):
            return answer
        if request.operation is _Operation.FIXED_PROPERTIES and isinstance(
            answer, FixedPropertyViolation
        ):
            return answer
        raise ToolArgumentCheckFailed(f"its process answered {type(answer).__name__}")

    async def _started_child(self) -> _Child:
        # The child's own alarm ends it a second after the limit if this
        # process disappears during a check.
        child = self._child = _start_child(self._limit_seconds() + 1)
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
        """Kill before waiting for the pipe call or closing its connection."""
        child, self._child = self._child, None
        pipe_call, self._pipe_call = self._pipe_call, None
        if child is None:
            return None
        exit_code = child.process.poll()
        child.process.kill()
        child.process.wait()
        if pipe_call is not None:
            # Death closes the peer FD, releasing any partial read or write.
            # Close ours only after the thread leaves it, avoiding FD reuse.
            concurrent.futures.wait((pipe_call,))
        child.connection.close()
        return exit_code


_CHECKER = ToolArgumentChecker()
_COPY_CHECKER = ToolArgumentChecker(copy_contract_limit_seconds)


async def check_tool_arguments(
    arguments: Mapping[str, object], schema: Mapping[str, object]
) -> ToolArgumentCheckResult:
    """Check a run's full arguments with this event loop's killable checker."""
    return await _CHECKER.check(arguments, schema)


async def check_contract_value(
    value: Mapping[str, object] | Sequence[object], schema: Mapping[str, object]
) -> ToolArgumentCheckResult:
    """Check a copy_input step's JSON value in its own killable checker, with
    the copy limit."""
    return await _COPY_CHECKER.check(value, schema)


async def check_fixed_tool_properties(
    fixed: Mapping[str, object], schema: Mapping[str, object]
) -> FixedPropertyCheckResult:
    """Check publish's fixed properties with the same killable checker."""
    return await _CHECKER.check_fixed_properties(fixed, schema)
