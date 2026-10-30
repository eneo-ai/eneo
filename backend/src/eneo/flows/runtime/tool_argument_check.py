"""Bounded JSON Schema checks in a killable child: a tool's arguments at
publish and in runs, and a step's input or output value against its contract.

A schema can hold the GIL while matching an expression or expand references
without a bound. A thread cannot stop that work. Tool arguments and contract
values each have their own checker and time limit; a checker's children serve
one event loop's checks, at most its slot count at once, each over its own
local Pipe. A contract check never delays a tool's argument check. A fresh
interpreter starts only the checker entry module, never the server's or
worker's main script.

A check's limit counts from the moment it is asked, so time queued behind
earlier checks on the same checker is part of it, and a check that waited gets
only what is left. Starting a new child is not part of it: that has its own
budget, and missing it is a host fault. One owned thread handles every framed
pipe read and write, including partial messages. Cancellation or timeout
during a check's own exchange kills the child before waiting for that thread
and closing its connection; the next check starts a new child. A check that
times out or is cancelled while queued leaves every child to the check it
serves. A check whose JSON text is larger than 4 MiB ends its child after
answering; the next check on that slot starts a new one.

A contract checker's child also has a memory budget (on Linux): past it an
allocation fails inside the check, which then answers as one that raised, and
a check that raised ends its child after answering.

An idle child ends on parent pipe EOF; active work carries an alarm that ends
the child within the check limit plus one second if its parent disappears.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import functools
import gc
import json
import logging
import resource
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

# Includes the wait for earlier checks, the pipe writes, evaluation and answer,
# but not child startup. Ordinary arguments take milliseconds; this leaves host
# headroom.
TOOL_ARGUMENT_CHECK_TIMEOUT_SECONDS = 2.0
# A step's checked value can be as large as the inline byte ceiling (8 MiB by
# default). On a development host (load about 6) the slowest valid 8 MiB value
# measured, a list of one-integer lists checked for type and minimum, took 21 s;
# flat integer lists took 14 s and a large object 5 s. Close to three times that
# leaves room for a loaded host. The check's time grows with the value's size
# and the contract's work per item.
CONTRACT_CHECK_TIMEOUT_SECONDS = 60.0
# Importing jsonschema takes about 0.15 s on an idle host. Startup failure is a
# host fault, so it has a separate, generous budget.
_START_TIMEOUT_SECONDS = 10.0
# A child settles at 30-46 MiB after checks up to this size (right after a
# 4 MiB violation it can hold about 220 MiB; see _CONTRACT_CHECKER) and, after
# larger ones, up to about 82 MiB (glibc, CPython 3.11); ending it afterwards
# returns that memory for one later child start (0.1-0.5 s, outside the check's
# limit).
_RECYCLE_ABOVE_BYTES = 4 * 1024 * 1024
# What a child raises when an allocation meets its memory budget: MemoryError,
# or SystemError where C code drops the error (both measured in a Linux child).
_BUDGET_FAILURES = frozenset({"MemoryError", "SystemError"})


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


# What the checker writes as JSON text for the child: a mapping, a sequence or
# a JSON scalar (a str is already a sequence).
CheckedValue = Mapping[str, object] | Sequence[object] | int | float | bool | None
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
    # The imports' objects stay out of the collection after each check, which
    # then costs microseconds unless the check left garbage.
    gc.freeze()
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
        # A violation's error holds reference cycles with the decoded value, and
        # an idle child allocates too little to collect them: up to 0.5 GiB
        # measured, which would count against the next check's memory budget.
        gc.collect()


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


def contract_check_limit_seconds() -> float:
    return CONTRACT_CHECK_TIMEOUT_SECONDS


def contract_check_slots() -> int:
    """The contract checker's children per event loop: FLOW_CONTRACT_CHECK_SLOTS,
    at most the execution worker's run slots, since a run checks one value at a
    time."""
    # Deferred: the child process imports this module and must not load settings.
    from eneo.main.config import get_settings

    settings = get_settings()
    return min(settings.flow_contract_check_slots, settings.task_execution_max_jobs)


def contract_check_child_memory_bytes() -> int:
    """The memory budget of each contract checker child:
    FLOW_CONTRACT_CHECK_CHILD_MEMORY_BYTES."""
    from eneo.main.config import get_settings

    return get_settings().flow_contract_check_child_memory_bytes


def _limit_memory(child: _Child, limit_bytes: int) -> bool:
    """Cap the child's data memory before it is sent a check: its heap and
    private mappings, which hold the decoded value and every validation error,
    but not its stack, so a deep check meets the cap as an allocation that
    fails inside the check rather than as a crash. False when it was not
    applied."""
    if sys.platform != "linux":
        _memory_budget_not_applied(f"{sys.platform} has no prlimit")
        return False
    try:
        resource.prlimit(
            child.process.pid, resource.RLIMIT_DATA, (limit_bytes, limit_bytes)
        )
    except OSError as exc:
        _memory_budget_not_applied(str(exc))
        return False
    return True


@functools.cache
def _memory_budget_not_applied(reason: str) -> None:
    logger.warning("Schema checks run without their memory budget: %s.", reason)


class _Slot:
    """One child and the one thread that owns its pipe's reads and writes."""

    def __init__(
        self,
        limit_seconds: Callable[[], float],
        memory_bytes: Callable[[], int | None],
    ) -> None:
        self._limit_seconds = limit_seconds
        self._memory_bytes = memory_bytes
        self.child: _Child | None = None
        # The budget applied to the current or last child, None for none.
        self.memory_budget: int | None = None
        self._pipe_thread = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="flow-tool-argument-pipe"
        )
        self._pipe_call: concurrent.futures.Future[object] | None = None

    async def ask(
        self, request: _Request, deadline: float
    ) -> _CheckAnswer | _CheckRaised:
        child = self.child
        if child is None:
            loop = asyncio.get_running_loop()
            starting = loop.time()
            try:
                child = await self._started_child()
            except (EOFError, OSError) as exc:
                raise ToolArgumentCheckFailed("its process ended") from exc
            deadline += loop.time() - starting
        async with asyncio.timeout_at(deadline):
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
        child = self.child = _start_child(self._limit_seconds() + 1)
        memory_bytes = self._memory_bytes()
        self.memory_budget = (
            memory_bytes
            if memory_bytes is not None and _limit_memory(child, memory_bytes)
            else None
        )
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

    def end_child(self) -> int | None:
        """Kill before waiting for the pipe call or closing its connection."""
        child, self.child = self.child, None
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


class ToolArgumentChecker:
    """Checks up to ``slots()`` requests at once, each on its own child of the
    current event loop."""

    def __init__(
        self,
        limit_seconds: Callable[[], float] = tool_argument_limit_seconds,
        slots: Callable[[], int] = lambda: 1,
        memory_bytes: Callable[[], int | None] = lambda: None,
    ) -> None:
        """``limit_seconds`` gives the check's time limit, read at each check;
        ``slots`` the number of children, read when an event loop first checks;
        ``memory_bytes`` each child's memory budget (None for none), read when
        the child starts."""
        self._limit_seconds = limit_seconds
        self._slot_count = slots
        self._memory_bytes = memory_bytes
        self._loop: asyncio.AbstractEventLoop | None = None
        self._slots: list[_Slot] = []
        # A stack: the last released warm child first, slots without one last.
        self._idle: list[_Slot] = []
        self._admission = asyncio.Semaphore(1)

    async def check(
        self,
        value: CheckedValue,
        schema: Mapping[str, object],
    ) -> ToolArgumentCheckResult:
        """Validate the whole value, including its schema's metaschema.

        Raises ToolArgumentsNotJson for a non-JSON value and
        ToolArgumentCheckFailed for host faults. Cancellation and deadlines
        during the check's own exchange kill the child; the next check starts
        a new one.
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
        value: CheckedValue,
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
        value: CheckedValue,
        schema: Mapping[str, object],
        operation: _Operation,
    ) -> ToolArgumentCheckResult | FixedPropertyCheckResult:
        limit = self._limit_seconds()
        deadline = asyncio.get_running_loop().time() + limit
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
        admission, idle = self._of_running_loop()
        try:
            async with asyncio.timeout_at(deadline):
                await admission.acquire()
        except TimeoutError:
            # Every child belongs to the check that holds its slot.
            logger.warning(
                "A schema check waited %s seconds for earlier checks and did not run.",
                limit,
            )
            return ArgumentCheckUnfinished(timed_out=True)
        slot = idle.pop()
        budget: int | None = None
        try:
            answer = await slot.ask(request, deadline)
        except TimeoutError:
            exit_code = slot.end_child()
            logger.warning(
                "A schema check ran past %s seconds; its process "
                "was killed (exit code before: %s).",
                limit,
                exit_code,
            )
            return ArgumentCheckUnfinished(timed_out=True)
        except ToolArgumentCheckFailed as exc:
            exit_code = slot.end_child()
            logger.error(
                "A schema check could not run: %s (exit code before the kill: %s).",
                exc,
                exit_code,
            )
            raise
        except BaseException:
            # A late answer must never be read as the next check's result.
            slot.end_child()
            raise
        else:
            budget = slot.memory_budget
            # A raise can be an allocation past the memory budget, which leaves
            # the child holding what it reached; a large check leaves a larger
            # heap than it found.
            if (
                isinstance(answer, _CheckRaised)
                or len(request.value_text) > _RECYCLE_ABOVE_BYTES
            ):
                slot.end_child()
        finally:
            # A slot whose child ended goes under the warm ones, which answer
            # without a start.
            if slot.child is None:
                idle.insert(0, slot)
            else:
                idle.append(slot)
            admission.release()
        if isinstance(answer, _CheckRaised):
            logger.warning("A schema check raised %s in its process.", answer.exception)
            if budget is not None and answer.exception in _BUDGET_FAILURES:
                logger.warning(
                    "A schema check may have met its process's memory budget of "
                    "%s bytes (FLOW_CONTRACT_CHECK_CHILD_MEMORY_BYTES).",
                    budget,
                )
            return ArgumentCheckUnfinished(timed_out=False)
        return answer

    def _of_running_loop(self) -> tuple[asyncio.Semaphore, list[_Slot]]:
        loop = asyncio.get_running_loop()
        if loop is not self._loop:
            # A child serving another loop may still owe that loop an answer.
            self.end_children()
            self._slots = [
                _Slot(self._limit_seconds, self._memory_bytes)
                for _ in range(max(1, self._slot_count()))
            ]
            self._idle = list(self._slots)
            self._loop, self._admission = loop, asyncio.Semaphore(len(self._slots))
        # Taken together: a check still running on an old loop puts its slot
        # back on that loop's stack, never on the new one.
        return self._admission, self._idle

    def end_children(self) -> None:
        """Kill every child this checker started for its current event loop."""
        for slot in self._slots:
            slot.end_child()


_CHECKER = ToolArgumentChecker()
# ponytail: contract_check_slots() children per event loop, started on demand
# and never reaped. Each can take up to its memory budget while it checks; at
# rest it settles at 30-46 MiB after the mixed checks measured, but right
# after a 4 MiB violation it holds about 220 MiB until later checks return it.
# End a child by its resident memory after a check, or reap idle ones, if that
# matters.
_CONTRACT_CHECKER = ToolArgumentChecker(
    contract_check_limit_seconds,
    contract_check_slots,
    contract_check_child_memory_bytes,
)


async def check_tool_arguments(
    arguments: Mapping[str, object], schema: Mapping[str, object]
) -> ToolArgumentCheckResult:
    """Check a run's full arguments with this event loop's killable checker."""
    return await _CHECKER.check(arguments, schema)


async def check_contract_value(
    value: CheckedValue, schema: Mapping[str, object]
) -> ToolArgumentCheckResult:
    """Check a step's input or output value, a scalar included, in the
    contract checker, with the contract limit."""
    return await _CONTRACT_CHECKER.check(value, schema)


async def check_fixed_tool_properties(
    fixed: Mapping[str, object], schema: Mapping[str, object]
) -> FixedPropertyCheckResult:
    """Check publish's fixed properties with the same killable checker."""
    return await _CHECKER.check_fixed_properties(fixed, schema)
