"""Bounded tool schema checks in a killable child, shared by publish and runs.

A schema can hold the GIL while matching an expression or expand references
without a bound. A thread cannot stop that work. One child serves one event
loop's checks, serialized over a local Pipe. A fresh interpreter starts only
the checker entry module, never the server's or worker's main script.

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
from collections.abc import Callable, Mapping
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
# Importing jsonschema takes about 0.15 s on an idle host. Startup failure is a
# host fault, so it has a separate, generous budget.
_START_TIMEOUT_SECONDS = 10.0


class ToolArgumentCheckFailed(Exception):
    """The child failed to start, ended or answered out of protocol: a host fault."""


class ToolArgumentsNotJson(Exception):
    """Arguments contain a non-JSON number or exceed the JSON encoder's nesting."""


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
    FULL_ARGUMENTS = auto()
    FIXED_PROPERTIES = auto()


@dataclass(frozen=True, slots=True)
class _Request:
    operation: _Operation
    arguments_text: bytes
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
            arguments: dict[str, object] = json.loads(request.arguments_text)
            schema: dict[str, object] = json.loads(request.schema_text)
            answer: _CheckAnswer | _CheckRaised
            if request.operation is _Operation.FULL_ARGUMENTS:
                answer = evaluate_contract(arguments, schema)
            else:
                answer = _fixed_properties(arguments, schema)
        except Exception as exc:  # the child's boundary: the parent logs the type
            answer = _CheckRaised(type(exc).__name__)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
        connection.send(answer)


@dataclass(frozen=True, slots=True)
class _Child:
    process: subprocess.Popen[bytes]
    connection: Connection


def _start_child() -> _Child:
    ours, theirs = Pipe()
    try:
        process = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve().with_name("tool_argument_check_child.py")),
                str(theirs.fileno()),
                str(TOOL_ARGUMENT_CHECK_TIMEOUT_SECONDS + 1),
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


def _json_text(value: Mapping[str, object]) -> bytes:
    return json.dumps(value, allow_nan=False).encode()


class ToolArgumentChecker:
    """Checks one request at a time on one child of the current event loop."""

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
        """Validate the full object, including its schema's metaschema.

        Raises ToolArgumentsNotJson for non-JSON arguments and
        ToolArgumentCheckFailed for host faults. Cancellation and deadlines
        kill the child; the next check starts a new one.
        """
        return await self._check(arguments, schema, _Operation.FULL_ARGUMENTS)

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
        arguments: Mapping[str, object],
        schema: Mapping[str, object],
        operation: Literal[_Operation.FULL_ARGUMENTS],
    ) -> ToolArgumentCheckResult: ...

    @overload
    async def _check(
        self,
        arguments: Mapping[str, object],
        schema: Mapping[str, object],
        operation: Literal[_Operation.FIXED_PROPERTIES],
    ) -> FixedPropertyCheckResult: ...

    async def _check(
        self,
        arguments: Mapping[str, object],
        schema: Mapping[str, object],
        operation: _Operation,
    ) -> ToolArgumentCheckResult | FixedPropertyCheckResult:
        try:
            arguments_text = _json_text(arguments)
        except (RecursionError, ValueError) as exc:
            raise ToolArgumentsNotJson from exc
        try:
            schema_text = _json_text(schema)
        except (RecursionError, ValueError):
            logger.warning("A tool's input schema cannot be written as JSON text.")
            return ArgumentCheckUnfinished(timed_out=False)
        request = _Request(operation, arguments_text, schema_text)
        async with self._lock_of_running_loop():
            try:
                answer = await self._ask(request)
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
                # A late answer must never be read as the next check's result.
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
            # A child serving another loop may still owe that loop an answer.
            self._end_child()
            self._loop, self._lock = loop, asyncio.Lock()
        return self._lock

    async def _ask(self, request: _Request) -> _CheckAnswer | _CheckRaised:
        try:
            child = self._child or await self._started_child()
        except (EOFError, OSError) as exc:
            raise ToolArgumentCheckFailed("its process ended") from exc
        async with asyncio.timeout(TOOL_ARGUMENT_CHECK_TIMEOUT_SECONDS):
            try:
                answer = await self._on_pipe_thread(
                    lambda: _exchange(child.connection, request)
                )
            except (EOFError, OSError) as exc:
                raise ToolArgumentCheckFailed("its process ended") from exc
        if answer is None or isinstance(answer, ContractNotEvaluable | _CheckRaised):
            return answer
        if request.operation is _Operation.FULL_ARGUMENTS and isinstance(
            answer, ContractViolation
        ):
            return answer
        if request.operation is _Operation.FIXED_PROPERTIES and isinstance(
            answer, FixedPropertyViolation
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


async def check_tool_arguments(
    arguments: Mapping[str, object], schema: Mapping[str, object]
) -> ToolArgumentCheckResult:
    """Check a run's full arguments with this event loop's killable checker."""
    return await _CHECKER.check(arguments, schema)


async def check_fixed_tool_properties(
    fixed: Mapping[str, object], schema: Mapping[str, object]
) -> FixedPropertyCheckResult:
    """Check publish's fixed properties with the same killable checker."""
    return await _CHECKER.check_fixed_properties(fixed, schema)
