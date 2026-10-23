"""The read of a step whose input is the answer of one MCP tool.

The order, each refusal with its own typed code: the pinned configuration,
the arguments, what every level says about the tool now and whether it is
still the tool the flow pinned, the level of the tool's server against the
one the run counted, the arguments against the tool's approved input schema
(in a child process with a time limit: tool_argument_check),
the step's time, the server's address, the record of the call's start, the
call, the answer, the record of its result.
The levels are asked before the call; the server's name is resolved in
between, within the time the step has left. The run's preflight asks the
levels and the pin with the same function, so a run that would be refused
at the call is refused before its first step when the refusal already holds
then.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
import time
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, TypeAlias
from uuid import UUID

from pydantic import TypeAdapter, ValidationError

from eneo.audit.domain.outcome import Outcome
from eneo.flows.application.flow_tool_publication import (
    AllowedTool,
    read_allowed_tool,
)
from eneo.flows.domain.flow_step_attempt_input import (
    FlowStepAttemptToolCallResult,
    FlowStepAttemptToolCallStart,
    storable_tool_call_start,
)
from eneo.flows.domain.runtime_invariant_exceptions import FlowRuntimeInvariantError
from eneo.flows.domain.tool_facts import UnattendedToolFactsSource
from eneo.flows.domain.tool_input import (
    TOOL_INPUT_TYPES,
    PublishedToolInputConfig,
    ToolArgumentError,
    read_published_tool_input_config,
    required_tool_arguments,
    tool_input_schema_sha256,
)
from eneo.flows.enums import FlowInputType
from eneo.flows.flow_api_error_code import FlowApiErrorCode, typed_io_failure_code
from eneo.flows.flow_run_error import (
    TOOL_ERROR_TEXT_MAX_LENGTH,
    FlowRunContractViolation,
)
from eneo.flows.flow_run_provenance import (
    FlowResolvedInputEdge,
    FlowResolvedInputHashedSelection,
    FlowResolvedInputJsonPath,
    FlowResolvedInputToolAnswerSource,
    build_resolved_input_edge,
)
from eneo.flows.flow_security_classification import (
    tool_server_classification_level,
)
from eneo.flows.http_transport.effective_url import (
    InvalidHttpUrl,
    parse_effective_http_url,
)
from eneo.flows.output_processing import (
    ContractUnevaluable,
    raise_contract_finding,
    refuse_unknown_dialect,
)
from eneo.flows.runtime.contract_check import not_checked_message
from eneo.flows.runtime.egress.http import VettedClientFactory
from eneo.flows.runtime.egress.policy import (
    Deadline,
    DestinationRefused,
    DestinationUnresolvable,
    FlowDestinationPolicy,
    Resolver,
    vet_destination,
)
from eneo.flows.runtime.http_audit import (
    AuditedToolCall,
    await_read_audit,
    unfinished_call_message,
)
from eneo.flows.runtime.http_orchestration import FlowOutsideInputResolution
from eneo.flows.runtime.step_deadline import current_step_deadline_scope
from eneo.flows.runtime.tool_argument_check import (
    ArgumentCheckUnfinished,
    ToolArgumentsNotJson,
    check_tool_arguments,
)
from eneo.json_types import JsonValue
from eneo.main.exceptions import (
    MCPClientError,
    MCPToolAnswerTooLarge,
    MCPToolCallTimedOut,
    TypedIOValidationException,
)
from eneo.mcp_servers.application.unattended_tool_call import (
    EXCHANGE_STOP_GRACE_SECONDS,
)

if TYPE_CHECKING:
    from eneo.flows.domain.flow import FlowRun
    from eneo.flows.domain.runtime import RuntimeStep
    from eneo.flows.variable_resolver import FlowVariableContext, FlowVariableResolver
    from eneo.mcp_servers.domain.entities.mcp_server import MCPServer, MCPServerTool
    from eneo.mcp_servers.infrastructure.client.mcp_client import (
        MCPHttpClientFactory,
        MCPToolAnswer,
    )

_CALL_PHASE = "the tool call"
_TOOL_INPUT_TYPE_VALUES = frozenset(item.value for item in TOOL_INPUT_TYPES)
_JsonContainer: TypeAlias = dict[str, JsonValue] | list[JsonValue]
_JSON_OBJECT_OR_ARRAY = TypeAdapter[_JsonContainer](_JsonContainer)
# U+0000 is valid in JSON and in a string, and the columns that hold a step's
# input and a run's error cannot store it.
_NUL = "\x00"
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f]+")


class AuditToolCallFn(Protocol):
    def __call__(
        self,
        *,
        run: FlowRun,
        step: RuntimeStep,
        url: str,
        method: str,
        call_type: str,
        outcome: Outcome,
        error_message: str | None,
        duration_ms: float,
        tool: AuditedToolCall,
    ) -> Awaitable[None]: ...


class RecordToolCallFn(Protocol):
    """Stores the start, or the start and the result, of the attempt's tool
    call and commits it. Raises FlowStepAttemptClosed when the attempt is
    already closed; any other failure to store passes on as it is. When it
    raises, it holds no row lock (its transaction is rolled back)."""

    def __call__(
        self,
        *,
        start: FlowStepAttemptToolCallStart,
        result: FlowStepAttemptToolCallResult | None,
    ) -> Awaitable[None]: ...


class ToolCaller(Protocol):
    async def call(
        self,
        server: MCPServer,
        tool_name: str,
        arguments: dict[str, object],
        *,
        max_answer_bytes: int,
        timeout_seconds: int,
        http_client_factory: MCPHttpClientFactory,
    ) -> MCPToolAnswer: ...


@dataclass(frozen=True)
class ToolInputDeps:
    facts_reader: UnattendedToolFactsSource
    caller: ToolCaller
    variable_resolver: FlowVariableResolver
    destination_policy: FlowDestinationPolicy
    name_resolver: Resolver
    # The deployment's ceiling for one call; the step's deadline may leave less.
    call_timeout_seconds: int
    # The deployment's inline budget: the most a step's input may hold, and
    # the most the stored record of a call's arguments may take.
    max_inline_text_bytes: int
    audit_http_outbound: AuditToolCallFn


def pinned_tool_config(step: RuntimeStep) -> PublishedToolInputConfig:
    """The pinned configuration of a tool step, or the typed refusal of a step
    that has none or whose input type a tool cannot fill."""
    if step.input_type not in _TOOL_INPUT_TYPE_VALUES:
        raise _refusal(
            f"Step {step.step_order}: input_type '{step.input_type}' is not "
            "supported with input_source 'tool'.",
            FlowApiErrorCode.TYPED_IO_TOOL_INVALID_CONFIG,
            step_order=step.step_order,
        )
    try:
        return read_published_tool_input_config(step.input_config)
    except ValidationError:
        raise _refusal(
            f"Step {step.step_order}: input_config.tool is not a pinned tool "
            "configuration.",
            FlowApiErrorCode.TYPED_IO_TOOL_INVALID_CONFIG,
            step_order=step.step_order,
        ) from None


async def read_usable_tool(
    *,
    step_order: int,
    config: PublishedToolInputConfig,
    facts_reader: UnattendedToolFactsSource,
    tenant_id: UUID,
    space_id: UUID,
) -> AllowedTool:
    """The server and the tool as they are stored now, when every level allows
    the call for the space and the tool is still what the flow pinned.

    Raises ``typed_io_tool_not_allowed`` with the first refusing level, or
    ``typed_io_tool_changed`` when the tool's name or its approved input
    schema is not the pinned one.
    """
    allowed = await read_allowed_tool(
        step_order=step_order,
        config=config,
        facts_reader=facts_reader,
        tenant_id=tenant_id,
        space_id=space_id,
    )
    tool = allowed.tool
    if (
        tool.name != config.tool_name
        or tool_input_schema_sha256(tool.input_schema) != config.input_schema_sha256
    ):
        raise _refusal(
            f"Step {step_order}: the tool has changed since the flow was "
            "published, so publish the flow again.",
            FlowApiErrorCode.TYPED_IO_TOOL_CHANGED,
            step_order=step_order,
        )
    return allowed


async def resolve_tool_input(
    *,
    step: RuntimeStep,
    run: FlowRun,
    context: FlowVariableContext,
    space_id: UUID,
    counted_server_levels: Mapping[int, int | None],
    deps: ToolInputDeps,
    record_call: RecordToolCallFn,
) -> FlowOutsideInputResolution:
    """Read the tool of ``step`` and return its answer as the step's input.

    ``counted_server_levels`` holds, by step order, the level the run's
    preflight counted the tool's server at; a step it does not hold was
    counted at none, which is the case while classifications are off.

    ``record_call`` stores what is sent before the request goes out, and how
    the call ended (a typed failure or the accepted answer) before this
    returns, so nothing reads the answer before its result is stored.
    """
    config = pinned_tool_config(step)
    resolved, bound_edges = _resolve_arguments(step, config, context, deps)
    usable = await read_usable_tool(
        step_order=step.step_order,
        config=config,
        facts_reader=deps.facts_reader,
        tenant_id=run.tenant_id,
        space_id=space_id,
    )
    arguments, argument_edges = _arguments_sent(
        resolved, bound_edges, input_schema=usable.tool.input_schema
    )
    counted_level = _counted_server_level(step, usable.server, counted_server_levels)
    await _refuse_arguments_outside_the_schema(step, arguments, usable.tool)
    call_start = _storable_call_start(step, config, usable.tool, arguments, deps)
    # Asked before anything goes out: a step whose time is spent makes no
    # outbound call, so there is none to audit.
    vet_seconds = _budget_seconds(step, deps)
    started = time.monotonic()

    async def audit(outcome: Outcome, error_message: str | None) -> None:
        await await_read_audit(
            deps.audit_http_outbound(
                run=run,
                step=step,
                url=usable.server.http_url,
                method="POST",
                call_type="tool_input",
                outcome=outcome,
                error_message=error_message,
                duration_ms=(time.monotonic() - started) * 1000,
                tool=AuditedToolCall(
                    mcp_server_id=config.mcp_server_id, tool_name=config.tool_name
                ),
            )
        )

    # From here the run reaches out for the server: its name is resolved, then
    # it is called. Every ending is one audited outbound call: a typed one with
    # its message, a stopped one or one with an error that has no typed code
    # with a fixed text that says whether the request was sent. Once the
    # success is audited, a later failure (storing the result) is not audited
    # again.
    sent_at: float | None = None
    try:
        await _vet_server_address(step, usable.server, deps, vet_seconds)
        # Committed before the request: a call whose start cannot be stored
        # is not made, and a call the worker does not live through keeps its
        # start without a result.
        await record_call(start=call_start, result=None)
        sent_at = time.monotonic()
        answer = await _call(step, usable.server, config, arguments, deps)
        duration_ms = _milliseconds_since(sent_at)
        text, structured = _answer_as_step_input(
            step, config, answer, max_bytes=deps.max_inline_text_bytes
        )
    except TypedIOValidationException as exc:
        failed = (
            None
            if sent_at is None
            else FlowStepAttemptToolCallResult(
                outcome="failed",
                duration_ms=_milliseconds_since(sent_at),
                error_code=typed_io_failure_code(exc.code),
            )
        )
        await audit(Outcome.FAILURE, str(exc))
        if failed is not None:
            await record_call(start=call_start, result=failed)
        raise
    except (asyncio.CancelledError, Exception) as exc:
        await audit(
            Outcome.FAILURE,
            unfinished_call_message(exc, request_sent=sent_at is not None),
        )
        raise
    # Built before the success is audited, so that hashing the answer cannot
    # fail after it.
    answer_edge = build_resolved_input_edge(
        binding_ref="tool.answer",
        source=FlowResolvedInputToolAnswerSource(
            kind="tool_answer",
            mcp_server_id=config.mcp_server_id,
            tool_id=config.tool_id,
            tool_name=config.tool_name,
            server_classification_level=counted_level,
            selector=FlowResolvedInputJsonPath(kind="json_path", path=()),
        ),
        selected_value=text if structured is None else structured,
    )
    selection = answer_edge.selection
    if not isinstance(selection, FlowResolvedInputHashedSelection):
        raise FlowRuntimeInvariantError("A tool answer edge must hash the answer.")
    await audit(Outcome.SUCCESS, None)
    await record_call(
        start=call_start,
        result=FlowStepAttemptToolCallResult(
            outcome="answered",
            duration_ms=duration_ms,
            answer_byte_size=selection.byte_size,
            answer_sha256=selection.sha256,
        ),
    )
    return FlowOutsideInputResolution(
        text=text,
        structured=structured,
        resolved_input_edges=(*argument_edges, answer_edge),
    )


def _storable_call_start(
    step: RuntimeStep,
    config: PublishedToolInputConfig,
    tool: MCPServerTool,
    arguments: dict[str, object],
    deps: ToolInputDeps,
) -> FlowStepAttemptToolCallStart:
    """The record of what the call sends: the arguments are stored whole, or
    the call is not made."""
    start = storable_tool_call_start(
        mcp_server_id=config.mcp_server_id,
        tool_id=config.tool_id,
        tool_name=config.tool_name,
        published_input_schema_sha256=config.input_schema_sha256,
        current_input_schema_sha256=tool_input_schema_sha256(tool.input_schema),
        arguments=arguments,
        max_bytes=deps.max_inline_text_bytes,
    )
    if start is None:
        raise _refusal(
            f"Step {step.step_order}: the tool's arguments cannot be stored whole "
            f"as the record of the call (more than {deps.max_inline_text_bytes} "
            "bytes, or nested too deep), so the call is not made.",
            FlowApiErrorCode.TYPED_IO_INPUT_TOO_LARGE,
            step_order=step.step_order,
        )
    return start


def _milliseconds_since(started: float) -> int:
    return round((time.monotonic() - started) * 1000)


def _refusal(
    message: str, code: FlowApiErrorCode, **context: object
) -> TypedIOValidationException:
    return TypedIOValidationException(message, code=code, context=context)


def _counted_server_level(
    step: RuntimeStep,
    server: MCPServer,
    counted_server_levels: Mapping[int, int | None],
) -> int | None:
    """The level the preflight counted the step's server at, when the server
    row the decision just allowed still has it; None when none was counted.

    The preflight held the step's model, and what the step sends to the
    server, to the level the server had then. A server that is lower now
    would be sent data above it, and one that is higher would answer above
    what the model was held to, so either difference fails the step before
    anything goes out.
    """
    if step.step_order not in counted_server_levels:
        return None
    counted = counted_server_levels[step.step_order]
    if tool_server_classification_level(server) != counted:
        raise _refusal(
            f"Step {step.step_order}: the security classification of the tool's "
            "server changed after the run started. Start the run again.",
            FlowApiErrorCode.TYPED_IO_TOOL_CLASSIFICATION_CHANGED,
            step_order=step.step_order,
        )
    return counted


def _resolve_arguments(
    step: RuntimeStep,
    config: PublishedToolInputConfig,
    context: FlowVariableContext,
    deps: ToolInputDeps,
) -> tuple[dict[str, object], dict[str, FlowResolvedInputEdge]]:
    """Every argument the step gives: a fixed value as it is stored, a bound
    one replaced by the value its reference names, with its JSON type; and
    the evidence edge of each bound one, by name."""
    try:
        bound = config.bound_arguments()
    except ToolArgumentError as exc:
        raise _refusal(
            f"Step {step.step_order}: tool argument '{exc.argument}' is not a "
            "fixed value or one whole reference.",
            FlowApiErrorCode.TYPED_IO_TOOL_INVALID_CONFIG,
            step_order=step.step_order,
        ) from None
    arguments: dict[str, object] = dict(config.arguments)
    edges: dict[str, FlowResolvedInputEdge] = {}
    for argument in bound:
        value, edge = deps.variable_resolver.resolve_reference_with_evidence(
            argument.expression,
            context,
            binding_ref=f"tool.arguments.{argument.name}",
        )
        arguments[argument.name] = value
        edges[argument.name] = edge
    return arguments, edges


def _arguments_sent(
    resolved: Mapping[str, object],
    bound_edges: Mapping[str, FlowResolvedInputEdge],
    *,
    input_schema: Mapping[str, object] | None,
) -> tuple[dict[str, object], tuple[FlowResolvedInputEdge, ...]]:
    """The arguments object the tool gets, and the edges of the bound ones in
    it. A bound argument whose value is null is left out, with its edge, when
    the schema's top-level ``required`` does not name it: a run-form field
    left empty reads as null, and an optional argument without a value is
    one the tool is not given. A fixed null is the author's and stays."""
    required = set(required_tool_arguments(input_schema or {}))
    absent = {
        name for name in bound_edges if resolved[name] is None and name not in required
    }
    return (
        {name: value for name, value in resolved.items() if name not in absent},
        tuple(edge for name, edge in bound_edges.items() if name not in absent),
    )


def _unevaluable_schema(
    step: RuntimeStep, tool: MCPServerTool
) -> TypedIOValidationException:
    return _refusal(
        f"Step {step.step_order}: the input schema the MCP server gives for "
        f"tool '{tool.name}' cannot be evaluated, so the tool's arguments "
        "cannot be checked. The schema is the server's to correct.",
        FlowApiErrorCode.TYPED_IO_TOOL_INVALID_SCHEMA,
        step_order=step.step_order,
    )


async def _refuse_arguments_outside_the_schema(
    step: RuntimeStep, arguments: dict[str, object], tool: MCPServerTool
) -> None:
    # A tool that declares no input schema accepts any arguments object.
    if tool.input_schema is None:
        return
    label = f"Step {step.step_order}: tool arguments"
    try:
        refuse_unknown_dialect(tool.input_schema, label=label)
        # A fault of the check's process (ToolArgumentCheckFailed) is not the
        # schema's: it passes on and ends the step as flow_step_execution_failed.
        result = await check_tool_arguments(arguments, tool.input_schema)
    except ContractUnevaluable:
        raise _unevaluable_schema(step, tool) from None
    except ToolArgumentsNotJson:
        raise _refusal(
            f"Step {step.step_order}: the tool's arguments cannot be written as "
            "JSON text (a NaN, an infinity, or nesting too deep), so they cannot "
            "be checked.",
            FlowApiErrorCode.TYPED_IO_TOOL_INVALID_ARGUMENTS,
            step_order=step.step_order,
        ) from None
    if isinstance(result, ArgumentCheckUnfinished):
        raise _refusal(
            not_checked_message(
                f"Step {step.step_order}",
                "the tool's arguments",
                "its input schema",
                timed_out=result.timed_out,
            ),
            FlowApiErrorCode.TYPED_IO_CONTRACT_NOT_CHECKED,
            step_order=step.step_order,
        )
    try:
        raise_contract_finding(result, tool.input_schema, label=label, side="input")
    except ContractUnevaluable:
        raise _unevaluable_schema(step, tool) from None
    except TypedIOValidationException as exc:
        # The validator's message keeps the full location, and a key of a
        # bound object comes from run data. Its context holds the location
        # cut before any such key, and the rule: they go on as they are, so
        # the run error's details name them too.
        context = exc.context or {}
        violation = FlowRunContractViolation.from_context(context)
        raise _refusal(
            f"Step {step.step_order}: the tool's arguments do not fit its input "
            "schema"
            + (
                "."
                if violation is None
                else f" at '{violation.json_pointer or '/'}' "
                f"(rule '{violation.schema_rule}')."
            ),
            FlowApiErrorCode.TYPED_IO_TOOL_INVALID_ARGUMENTS,
            **{**context, "step_order": step.step_order},
        ) from None


async def _vet_server_address(
    step: RuntimeStep, server: MCPServer, deps: ToolInputDeps, seconds: int
) -> None:
    # A check of the addresses the server's name has now, so that a server the
    # policy refuses ends with its own code before anything is sent. Every
    # connection of the call is vetted again when it is opened (_call).
    try:
        address = parse_effective_http_url(server.http_url)
    except InvalidHttpUrl:
        raise _destination_blocked(step) from None
    try:
        await vet_destination(
            address.host,
            address.port,
            policy=deps.destination_policy,
            deadline=Deadline(float(seconds)),
            resolver=deps.name_resolver,
        )
    except DestinationRefused:
        raise _destination_blocked(step) from None
    except (DestinationUnresolvable, TimeoutError):
        raise _refusal(
            f"Step {step.step_order}: the name of the tool's MCP server did "
            "not resolve.",
            FlowApiErrorCode.TYPED_IO_TOOL_CONNECTION_ERROR,
            step_order=step.step_order,
        ) from None


def _destination_blocked(step: RuntimeStep) -> TypedIOValidationException:
    return _refusal(
        f"Step {step.step_order}: the address of the tool's MCP server is not "
        "allowed for flows.",
        FlowApiErrorCode.TYPED_IO_TOOL_DESTINATION_BLOCKED,
        step_order=step.step_order,
    )


def _budget_seconds(step: RuntimeStep, deps: ToolInputDeps) -> int:
    """Whole seconds that what starts now, resolving the server's name or the
    call, may take: the deployment's ceiling for one call, or less when the
    step's deadline leaves less.

    The caller reports a spent budget at the latest
    ``EXCHANGE_STOP_GRACE_SECONDS`` after it. That much of the step's time is
    kept back, so the report arrives before the step's own deadline cuts the
    attempt.
    """
    scope = current_step_deadline_scope()
    if scope is None:
        return deps.call_timeout_seconds
    left = math.floor(scope.deadline.remaining() - EXCHANGE_STOP_GRACE_SECONDS)
    if left < 1:
        raise scope.deadline.timeout_error(
            step_order=step.step_order,
            phase=_CALL_PHASE,
            provider_request_in_flight=False,
        )
    return min(deps.call_timeout_seconds, left)


async def _call(
    step: RuntimeStep,
    server: MCPServer,
    config: PublishedToolInputConfig,
    arguments: dict[str, object],
    deps: ToolInputDeps,
) -> MCPToolAnswer:
    # The client's own error text can quote the server; the typed message
    # that is stored, logged and audited does not carry it.
    name = config.tool_name
    timeout_seconds = _budget_seconds(step, deps)
    try:
        return await deps.caller.call(
            server,
            name,
            arguments,
            max_answer_bytes=deps.max_inline_text_bytes,
            timeout_seconds=timeout_seconds,
            # The name may answer differently when the client connects than
            # it did to the check before: each connection connects to an
            # address the policy allows at that moment, or is not opened.
            http_client_factory=VettedClientFactory(
                policy=deps.destination_policy, resolver=deps.name_resolver
            ),
        )
    except MCPToolCallTimedOut:
        raise _refusal(
            f"Step {step.step_order}: tool '{name}' did not answer within "
            f"{timeout_seconds}s.",
            FlowApiErrorCode.TYPED_IO_TOOL_TIMEOUT,
            step_order=step.step_order,
        ) from None
    except MCPToolAnswerTooLarge:
        raise _refusal(
            f"Step {step.step_order}: the answer of tool '{name}' exceeded "
            f"{deps.max_inline_text_bytes} bytes.",
            FlowApiErrorCode.TYPED_IO_TOOL_ANSWER_TOO_LARGE,
            step_order=step.step_order,
        ) from None
    except MCPClientError:
        raise _refusal(
            f"Step {step.step_order}: the call to tool '{name}' failed.",
            FlowApiErrorCode.TYPED_IO_TOOL_CONNECTION_ERROR,
            step_order=step.step_order,
        ) from None


def _answer_as_step_input(
    step: RuntimeStep,
    config: PublishedToolInputConfig,
    answer: MCPToolAnswer,
    *,
    max_bytes: int,
) -> tuple[str, _JsonContainer | None]:
    """The step's input text and, for a JSON step, its structured value.

    A JSON step reads the structured content, or else the one text block when
    it is a JSON object or array: several text blocks are not one document. A
    text step reads the text blocks, one per line, or else the structured
    content as JSON text. An answer with a block that is not text (an image,
    a resource) is refused whole, because a step cannot carry that block and
    would otherwise read an answer with a part missing. So is an answer with
    U+0000 in a text block or in the structured content, which the columns
    that hold a step's input cannot store. The text the step takes may not be
    larger than ``max_bytes``, the size a step's input may have.
    """
    name = config.tool_name
    text = "\n".join(answer.text_blocks)
    if answer.is_error:
        # The tool's own text goes to the run error's details, which the
        # run's viewers read; nothing else of a failed answer is kept. An
        # error answer without text leaves the detail out.
        raise _refusal(
            f"Step {step.step_order}: tool '{name}' reported an error.",
            FlowApiErrorCode.TYPED_IO_TOOL_REPORTED_ERROR,
            step_order=step.step_order,
            tool_error_text=_storable_line(text)[:TOOL_ERROR_TEXT_MAX_LENGTH] or None,
        )
    if answer.other_blocks:
        raise _refusal(
            f"Step {step.step_order}: the answer of tool '{name}' has content "
            "that is not text, which a step cannot read.",
            FlowApiErrorCode.TYPED_IO_TOOL_MALFORMED_ANSWER,
            step_order=step.step_order,
        )
    malformed = _refusal(
        f"Step {step.step_order}: the answer of tool '{name}' is empty or not "
        f"{step.input_type}.",
        FlowApiErrorCode.TYPED_IO_TOOL_MALFORMED_ANSWER,
        step_order=step.step_order,
    )
    taken: tuple[str, _JsonContainer | None] | None = None
    try:
        structured = (
            None
            if answer.structured is None
            else _JSON_OBJECT_OR_ARRAY.validate_python(answer.structured)
        )
        is_json = step.input_type == FlowInputType.JSON.value
        if is_json and structured is None and len(answer.text_blocks) == 1:
            structured = _JSON_OBJECT_OR_ARRAY.validate_json(text)
        # Written out before the step's choice, so that structured content
        # with NaN or an infinity refuses the answer also when the text is
        # what a text step takes.
        structured_text = None if structured is None else _json_text(structured)
        if is_json:
            if structured_text is not None:
                taken = structured_text, structured
        elif text.strip():
            taken = text, None
        elif structured_text is not None:
            taken = structured_text, None
    except ValueError:
        # Text that is no JSON object or array (pydantic's error is a
        # ValueError), or NaN or an infinity: JSON has no such number, and
        # neither has the canonical form the answer's evidence is hashed in.
        raise malformed from None
    if (
        taken is None
        or _NUL in text
        or (structured is not None and _holds_nul(structured))
    ):
        raise malformed
    if len(taken[0].encode("utf-8")) > max_bytes:
        raise _refusal(
            f"Step {step.step_order}: the answer of tool '{name}' is more than "
            f"{max_bytes} bytes as the step's input.",
            FlowApiErrorCode.TYPED_IO_TOOL_ANSWER_TOO_LARGE,
            step_order=step.step_order,
        )
    return taken


def _json_text(value: _JsonContainer) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def _holds_nul(value: JsonValue) -> bool:
    if isinstance(value, str):
        return _NUL in value
    if isinstance(value, list):
        return any(_holds_nul(item) for item in value)
    if isinstance(value, dict):
        return any(_NUL in key or _holds_nul(item) for key, item in value.items())
    return False


def _storable_line(text: str) -> str:
    """``text`` on one line, each run of control characters as one space."""
    return _CONTROL_CHARACTERS.sub(" ", text).strip()
