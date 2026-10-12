"""A step whose input source is ``tool`` at run time: what the run asks before
its first step, and what the read asks, sends, takes and records. The happy
paths and the transport failures call a real local MCP endpoint."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field, replace
from functools import partial
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, Request
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response, StreamingResponse

from eneo.audit.domain.outcome import Outcome
from eneo.flows.domain.canonical_json_hash import (
    canonical_json_bytes,
    canonical_json_hash,
)
from eneo.flows.domain.flow import FlowRunStatus
from eneo.flows.domain.runtime import RunExecutionState, RuntimeStep
from eneo.flows.domain.runtime_invariant_exceptions import FlowRuntimeInvariantError
from eneo.flows.enums import FlowRunLifecycleSource
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_run_error import FlowRunErrorDetails
from eneo.flows.flow_run_provenance import (
    group_resolved_input_edges,
    parse_resolved_input_edges,
)
from eneo.flows.output_processing import validate_against_contract
from eneo.flows.runtime import executor as executor_module
from eneo.flows.runtime import tool_argument_check
from eneo.flows.runtime.egress.policy import (
    DestinationUnresolvable,
    FlowDestinationPolicy,
)
from eneo.flows.runtime.executor import FlowRunExecutorConfig
from eneo.flows.runtime.step_deadline import (
    StepDeadline,
    current_step_deadline_scope,
    step_deadline_scope,
)
from eneo.flows.runtime.step_execution_runtime import (
    StepExecutionRuntimeDeps,
    prepare_step_execution,
)
from eneo.flows.runtime.tool_argument_check import (
    ToolArgumentChecker,
    ToolArgumentCheckFailed,
)
from eneo.main.config import Settings, get_settings
from eneo.main.destination_policy import IPAddress
from eneo.main.exceptions import (
    MCPClientError,
    MCPToolAnswerTooLarge,
    MCPToolCallTimedOut,
    OpenAIException,
    TypedIOValidationException,
)
from eneo.mcp_servers.application.unattended_tool_call import (
    EXCHANGE_STOP_GRACE_SECONDS,
    UnattendedToolCaller,
)
from eneo.mcp_servers.application.unattended_tool_use import UnattendedToolFacts
from eneo.mcp_servers.infrastructure.client.mcp_client import MCPToolAnswer
from eneo.mcp_servers.infrastructure.proxy.mcp_proxy_factory import (
    MCPProxySessionFactory,
)
from tests.unit.mcp_test_server import one_tool_app, serve_test_app, tool_result
from tests.unittests.flows.test_flow_executor_runtime import (
    _claimed_step_result,
    _empty_execution_state,
    _execute_setup_for_security,
)
from tests.unittests.flows.test_resolved_input_runtime import _result
from tests.unittests.flows.test_tool_publish_pin import _Facts, _facts
from tests.unittests.flows.test_typed_io_executor import (
    _build_executor,
    _run,
    _runtime_step,
)

pytestmark = pytest.mark.asyncio

_SPACE_ID = uuid4()
_DAYS = ["2026-01-03", "2026-01-09"]
_ANSWER: dict[str, object] = {"rows": [{"day": "2026-01-03", "kwh": 41.5}]}
_SECRET_ARGUMENT = "case-4711-secret"


class _LoopbackToo(FlowDestinationPolicy):
    """The test endpoint listens on loopback, which no setting allows."""

    def allows(self, ip: IPAddress) -> bool:
        return ip.is_loopback or super().allows(ip)


@dataclass
class _Caller:
    """Answers every call with the given answer or failure, and keeps what it
    was asked."""

    answer: MCPToolAnswer | Exception
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def call(
        self,
        server: object,
        tool_name: str,
        arguments: dict[str, object],
        *,
        max_answer_bytes: int,
        timeout_seconds: int,
    ) -> MCPToolAnswer:
        self.calls.append(
            {
                "server": server,
                "tool_name": tool_name,
                "arguments": arguments,
                "max_answer_bytes": max_answer_bytes,
                "timeout_seconds": timeout_seconds,
            }
        )
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def _answered(
    structured: dict[str, object] | None = None,
    blocks: tuple[str, ...] = (),
    other_blocks: int = 0,
) -> _Caller:
    return _Caller(MCPToolAnswer(blocks, other_blocks, structured, is_error=False))


def _tool_config(facts: UnattendedToolFacts, **changes: object) -> dict[str, object]:
    """The pinned configuration publish writes for the tool of ``facts``."""
    assert facts.server is not None and facts.tool is not None
    return {
        "mcp_server_id": str(facts.server.id),
        "tool_id": str(facts.tool.id),
        "arguments": {},
        "tool_name": facts.tool.name,
        "input_schema_sha256": canonical_json_hash(facts.tool.input_schema or {}),
        **changes,
    }


def _tool_step(
    facts: UnattendedToolFacts,
    *,
    input_type: str = "json",
    input_contract: dict[str, object] | None = None,
    **config: object,
) -> RuntimeStep:
    return _runtime_step(
        step_order=2,
        input_source="tool",
        input_type=input_type,
        input_contract=input_contract,
        input_config={"tool": _tool_config(facts, **config)},
    )


def _tool_executor(user, reader: _Facts | None, caller: object | None, **built: Any):
    executor, flow_repo, _, _ = _build_executor(user, **built)
    executor.tool_facts_reader = reader
    executor.tool_caller = caller
    executor.tool_destination_policy = _LoopbackToo(allow_private_networks=True)
    executor.tool_name_resolver = _public_address
    executor.audit_service = AsyncMock()
    flow_repo.get_space_id = AsyncMock(return_value=_SPACE_ID)
    return executor


async def _public_address(host: str, port: int) -> list[str]:
    """Answers for the registered server's name, so no test asks a resolver."""
    return ["93.184.216.34"]


def _real_caller() -> UnattendedToolCaller:
    return UnattendedToolCaller(MCPProxySessionFactory())


def _running(user, input_payload: dict[str, object] | None = None):
    return _run(status=FlowRunStatus.RUNNING, user=user, input_payload=input_payload)


async def _read(executor, step: RuntimeStep, run, prior_results=()):
    return await executor._resolve_step_input(
        step=step, context={}, run=run, prior_results=list(prior_results)
    )


async def _refused(executor, step: RuntimeStep, run) -> TypedIOValidationException:
    with pytest.raises(TypedIOValidationException) as refused:
        await _read(executor, step, run)
    return refused.value


def _audits(executor) -> list[dict[str, Any]]:
    return [call.kwargs for call in executor.audit_service.log_async.await_args_list]


def _recording(app: FastAPI, calls: list[dict[str, Any]]) -> FastAPI:
    """The app, with the params of every ``tools/call`` it receives kept."""

    async def keep(request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method == "POST":
            payload = await request.json()
            if payload.get("method") == "tools/call":
                calls.append(payload["params"])
        return await call_next(request)

    app.middleware("http")(keep)
    return app


def _endpoint_facts(url: str, **changes: Any) -> UnattendedToolFacts:
    """The allowed tool ``lookup`` of the local test endpoint."""
    return _facts(server={"http_url": url}, tool={"name": "lookup"}, **changes)


async def test_a_bound_list_reaches_the_tool_and_its_structured_answer_is_the_input(
    user,
) -> None:
    # Kills the mutants that write a bound value into the argument as text,
    # drop the structured answer, call more than once, leave out the answer
    # edge or store a value in it, or audit without server and tool (or with
    # the arguments).
    received: list[dict[str, Any]] = []
    app = one_tool_app(
        lambda request_id: tool_result(
            request_id,
            {
                "content": [{"type": "text", "text": "one row"}],
                "structuredContent": _ANSWER,
            },
        )
    )
    run = _running(user, {"case": "A-17"})
    earlier = _result(output_payload={"text": "", "structured": {"days": _DAYS}})
    async with serve_test_app(_recording(app, received)) as url:
        facts = _endpoint_facts(url)
        executor = _tool_executor(user, _Facts(facts), _real_caller())
        step = _tool_step(
            facts,
            arguments={
                "days": "{{step_1.output.structured.days}}",
                "case": "{{flow_input.case}}",
                "note": _SECRET_ARGUMENT,
                "limit": 5,
            },
        )

        resolved = await _read(executor, step, run, [earlier])

    assert received == [
        {
            "name": "lookup",
            "arguments": {
                "days": _DAYS,
                "case": "A-17",
                "note": _SECRET_ARGUMENT,
                "limit": 5,
            },
        }
    ]
    assert resolved.structured == _ANSWER
    assert resolved.text == json.dumps(_ANSWER, ensure_ascii=False)
    assert resolved.input_source == "tool"

    assert facts.server is not None and facts.tool is not None
    answer_bytes = canonical_json_bytes(_ANSWER)
    edges = [edge.model_dump(mode="json") for edge in resolved.edges]
    assert [(edge["binding_ref"], edge["source"]["kind"]) for edge in edges] == [
        ("tool.arguments.days:step_1.output.structured.days", "step_result"),
        ("tool.arguments.case:flow_input.case", "flow_input"),
        ("tool.answer", "tool_answer"),
    ]
    assert edges[2]["source"] == {
        "kind": "tool_answer",
        "mcp_server_id": str(facts.server.id),
        "tool_id": str(facts.tool.id),
        "tool_name": "lookup",
        "selector": {"kind": "json_path", "path": []},
    }
    assert edges[2]["selection"] == {
        "encoding": "canonical_json",
        "sha256": hashlib.sha256(answer_bytes).hexdigest(),
        "byte_size": len(answer_bytes),
    }
    assert "2026-01-03" not in json.dumps(edges)
    # What the attempt stores is read back as tracked evidence, not as corrupt.
    stored = group_resolved_input_edges(resolved.edges).aggregate.model_dump(
        mode="json"
    )
    assert parse_resolved_input_edges(stored).status == "tracked"

    (audit,) = _audits(executor)
    assert audit["outcome"] is Outcome.SUCCESS
    assert audit["entity_id"] == run.id
    extra = audit["metadata"]["extra"]
    assert {key: extra[key] for key in extra if key != "duration_ms"} == {
        "call_type": "tool_input",
        "http_method": "POST",
        "url_host": "http://127.0.0.1",
        "url_path": "/mcp",
        "flow_id": str(run.flow_id),
        "step_order": 2,
        "step_id": str(step.step_id),
        "mcp_server_id": str(facts.server.id),
        "tool_name": "lookup",
    }
    assert extra["duration_ms"] >= 0
    assert _SECRET_ARGUMENT not in repr(audit) and "A-17" not in repr(audit)


_A, _B = '{"a": 1}', '{"b": 2}'


@pytest.mark.parametrize(
    ("input_type", "structured", "blocks", "other_blocks", "expected"),
    [
        pytest.param("json", {"a": 1}, (_B,), 0, (_A, {"a": 1}), id="json"),
        pytest.param("json", {}, (), 0, ("{}", {}), id="json-empty-object"),
        pytest.param("json", None, (_A,), 0, (_A, {"a": 1}), id="json-text"),
        pytest.param("json", None, ("[1, 2]",), 0, ("[1, 2]", [1, 2]), id="json-array"),
        pytest.param("json", None, (_A, _B), 0, None, id="json-from-two-documents"),
        pytest.param("json", None, ("[1,", "2]"), 0, None, id="json-split-in-blocks"),
        pytest.param("json", None, ("seven rows",), 0, None, id="json-from-plain-text"),
        pytest.param("json", None, ("7",), 0, None, id="json-from-a-number"),
        pytest.param("json", None, ('"seven"',), 0, None, id="json-from-a-string"),
        pytest.param("json", None, ("null",), 0, None, id="json-from-null"),
        pytest.param("json", None, (), 0, None, id="json-from-nothing"),
        pytest.param("json", {"a": 1}, (), 1, None, id="json-beside-an-image"),
        pytest.param("json", None, ('{"a": NaN}',), 0, None, id="json-text-with-nan"),
        pytest.param("json", {"a": float("nan")}, (), 0, None, id="json-with-nan"),
        pytest.param("json", {"a": [float("inf")]}, (), 0, None, id="json-infinity"),
        pytest.param("text", {"a": float("nan")}, (), 0, None, id="text-of-nan"),
        pytest.param(
            "text", {"a": float("nan")}, ("seven",), 0, None, id="text-beside-nan"
        ),
        pytest.param(
            "text", {"a": [float("-inf")]}, ("seven",), 0, None, id="text-beside-inf"
        ),
        pytest.param("text", None, ("a\x00b",), 0, None, id="text-with-nul"),
        pytest.param("json", {"a": ["b\x00"]}, (), 0, None, id="json-value-with-nul"),
        pytest.param("json", {"a\x00": 1}, (), 0, None, id="json-key-with-nul"),
        pytest.param("json", None, ('{"a": "\\u0000"}',), 0, None, id="json-text-nul"),
        pytest.param(
            "json",
            {"a": "\\u0000"},
            (),
            0,
            ('{"a": "\\\\u0000"}', {"a": "\\u0000"}),
            id="json-backslash-u0000-is-no-nul",
        ),
        pytest.param("text", {"a": 1}, ("seven",), 0, ("seven", None), id="text"),
        pytest.param(
            "text", None, ("seven", "more"), 0, ("seven\nmore", None), id="text-blocks"
        ),
        pytest.param("text", {"a": 1}, (), 0, (_A, None), id="text-of-structured"),
        pytest.param("text", None, (), 0, None, id="text-from-nothing"),
        pytest.param("text", None, (" \n",), 0, None, id="text-from-blank-blocks"),
        pytest.param("text", None, ("seven",), 1, None, id="text-beside-an-image"),
    ],
)
async def test_the_answer_becomes_the_input_the_step_declares_or_is_refused(
    user,
    input_type: str,
    structured: dict[str, object] | None,
    blocks: tuple[str, ...],
    other_blocks: int,
    expected: tuple[str, object] | None,
) -> None:
    # Kills the mutants that take a JSON scalar or plain text as JSON input,
    # prefer the text over the structured content of a JSON step, read
    # several text blocks as one JSON document or only the first of them as
    # the text, drop an answer that has only structured content for a text
    # step, hand an empty answer on as an empty input, read an answer on
    # without its block that is not text, accept a number JSON does not have
    # (NaN, an infinity), also in structured content beside the text a text
    # step takes: the step would end untyped where the answer's evidence is
    # hashed, or accept U+0000, which the columns that store a
    # step's input cannot hold (the run would end untyped after an audited
    # success).
    facts = _facts()
    caller = _answered(structured, blocks, other_blocks)
    executor = _tool_executor(user, _Facts(facts), caller)
    step = _tool_step(facts, input_type=input_type)

    if expected is None:
        refused = await _refused(executor, step, _running(user))
        assert refused.code == "typed_io_tool_malformed_answer"
        assert [audit["outcome"] for audit in _audits(executor)] == [Outcome.FAILURE]
    else:
        resolved = await _read(executor, step, _running(user))
        assert (resolved.text, resolved.structured) == expected
        assert resolved.edges[-1].selection.encoding == (
            "utf8" if input_type == "text" else "canonical_json"
        )
    assert len(caller.calls) == 1


@pytest.mark.parametrize("value", [1.5, None], ids=["number", "null"])
async def test_a_bound_argument_keeps_the_json_type_of_what_it_names(
    user, value: object
) -> None:
    # Kills the mutant that interpolates a reference as a template does: a
    # list, a number or null would reach the tool as its text.
    facts = _facts()
    caller = _answered({"ok": True})
    executor = _tool_executor(user, _Facts(facts), caller)
    run = _running(user, {"v": value})

    await _read(executor, _tool_step(facts, arguments={"q": "{{flow_input.v}}"}), run)

    (call,) = caller.calls
    assert call["arguments"] == {"q": value}
    assert type(call["arguments"]["q"]) is type(value)
    assert call["tool_name"] == "lookup_case"
    assert call["server"] is facts.server
    assert call["max_answer_bytes"] == executor.max_inline_text_bytes


@pytest.mark.parametrize(
    ("changed", "code", "refusal", "said"),
    [
        pytest.param(
            {"server": {"is_enabled": False}},
            "typed_io_tool_not_allowed",
            "server_disabled",
            "instance administrator",
            id="server-level",
        ),
        pytest.param(
            {"tool": {"requires_approval": True}},
            "typed_io_tool_not_allowed",
            "tool_waiting_for_review",
            "instance administrator",
            id="tool-level",
        ),
        pytest.param(
            {"server_in_space": False},
            "typed_io_tool_not_allowed",
            "server_not_in_space",
            "space administrator",
            id="space-level",
        ),
        pytest.param(
            {"tool": {"name": "delete_case"}},
            "typed_io_tool_changed",
            None,
            "publish the flow again",
            id="another-name",
        ),
        pytest.param(
            {"tool": {"input_schema": {"type": "object", "required": ["id"]}}},
            "typed_io_tool_changed",
            None,
            "publish the flow again",
            id="another-approved-schema",
        ),
    ],
)
async def test_the_read_and_the_preflight_refuse_what_changed_after_publication(
    user, changed: dict[str, Any], code: str, refusal: str | None, said: str
) -> None:
    # Kills the mutants that ask the levels or compare the pin only before the
    # run (or only at the call), compare the name or the schema alone, replace
    # either code by a default, ask about another tenant, space or tool, leave
    # the refusing level out of the run error (the step's or the preflight's),
    # or end the run as an invalid definition.
    pinned = _facts()
    assert pinned.server is not None and pinned.tool is not None
    now = _facts(**changed)
    for entity, pinned_entity in ((now.server, pinned.server), (now.tool, pinned.tool)):
        assert entity is not None
        entity.id = pinned_entity.id
    assert now.tool is not None
    now.tool.mcp_server_id = pinned.server.id
    reader, caller = _Facts(now), _answered({"ok": True})
    ids = {"mcp_server_id": str(pinned.server.id), "tool_id": str(pinned.tool.id)}
    context = {"step_order": 2, **({"refusal": refusal, **ids} if refusal else {})}

    executor = _tool_executor(user, reader, caller)
    run = _running(user)
    at_the_call = await _refused(executor, _tool_step(pinned), run)

    assert (at_the_call.code, at_the_call.context) == (code, context)
    assert said in str(at_the_call)
    details = FlowRunErrorDetails.from_budget_context(at_the_call.context)
    assert (details.tool_refusal if details else None) == refusal
    assert caller.calls == [] and _audits(executor) == []
    assert reader.asked == [
        {
            "tenant_id": run.tenant_id,
            "space_id": _SPACE_ID,
            "mcp_server_id": pinned.server.id,
            "tool_id": pinned.tool.id,
        }
    ]

    executor, flow_run_repo, queued = _execute_setup_for_security(
        user,
        space_level=1,
        model_level=1,
        model_levels=[1, 1],
        step_fields={
            "input_source": "tool",
            "input_type": "json",
            "input_config": {"tool": _tool_config(pinned)},
        },
        step_fields_index=1,
    )
    executor.tool_facts_reader, executor.tool_caller = _Facts(now), caller
    executor.flow_repo.get_space_id = AsyncMock(return_value=_SPACE_ID)

    result = await executor.execute(
        run_id=queued.id,
        flow_id=queued.flow_id,
        tenant_id=user.tenant_id,
        run_revision=queued.revision,
        dispatch_task_id="task-1",
        retry_count=0,
    )

    assert result == {"status": "failed", "error": code}
    error = executor.flow_run_terminalizer.terminalize_run.await_args.kwargs["error"]
    assert (error.code.value, error.step_order) == (code, 2)
    assert error.message == str(at_the_call)
    assert (error.details.tool_refusal if error.details else None) == refusal
    assert error.source is FlowRunLifecycleSource.EXECUTOR_FAILED
    flow_run_repo.claim_step_result.assert_not_awaited()
    executor._execute_step.assert_not_awaited()
    assert executor.tool_facts_reader.asked == [
        {
            "tenant_id": user.tenant_id,
            "space_id": _SPACE_ID,
            "mcp_server_id": pinned.server.id,
            "tool_id": pinned.tool.id,
        }
    ]


async def test_a_run_whose_tool_is_allowed_and_unchanged_passes_the_preflight(
    user,
) -> None:
    # Kills the mutant whose preflight refuses every tool step (or compares the
    # pin against the schema no admin approved).
    facts = _facts(input_schema={"type": "object"})
    executor, flow_run_repo, queued = _execute_setup_for_security(
        user,
        space_level=1,
        model_level=1,
        step_fields={
            "input_source": "tool",
            "input_type": "text",
            "input_config": {"tool": _tool_config(facts)},
        },
    )
    executor.tool_facts_reader, executor.tool_caller = _Facts(facts), _answered()
    executor.flow_repo.get_space_id = AsyncMock(return_value=_SPACE_ID)

    result = await executor.execute(
        run_id=queued.id,
        flow_id=queued.flow_id,
        tenant_id=user.tenant_id,
        run_revision=queued.revision,
        dispatch_task_id="task-1",
        retry_count=0,
    )

    assert result == {"status": "skipped", "reason": "step_already_claimed"}
    flow_run_repo.claim_step_result.assert_awaited_once()
    assert facts.server is not None and facts.tool is not None
    assert executor.tool_facts_reader.asked == [
        {
            "tenant_id": user.tenant_id,
            "space_id": _SPACE_ID,
            "mcp_server_id": facts.server.id,
            "tool_id": facts.tool.id,
        }
    ]


@pytest.mark.parametrize(
    ("step_changes", "field_named"),
    [
        pytest.param({"tool_name": None}, "input_config.tool", id="no-pin"),
        pytest.param(
            {"arguments": {"q": "about {{flow_input.text}}"}},
            "argument 'q'",
            id="composed-argument",
        ),
        pytest.param({"input_type": "document"}, "input_type", id="a-file-type"),
    ],
)
async def test_a_stored_configuration_the_read_cannot_use_is_refused_typed(
    user, step_changes: dict[str, Any], field_named: str
) -> None:
    # Kills the mutants that read an unpinned or composed configuration as far
    # as the facts or the call, or let a tool fill an input type it cannot.
    facts = _facts()
    reader, caller = _Facts(facts), _answered({"ok": True})
    executor = _tool_executor(user, reader, caller)
    step = _tool_step(facts, **step_changes)

    refused = await _refused(executor, step, _running(user))

    assert refused.code == "typed_io_tool_invalid_config"
    assert field_named in str(refused)
    assert reader.asked == [] and caller.calls == []


async def test_an_argument_reference_that_does_not_resolve_fails_before_the_facts(
    user,
) -> None:
    # Kills the mutant that sends null or an empty string for a reference no
    # run value answers.
    facts = _facts()
    reader, caller = _Facts(facts), _answered({"ok": True})
    executor = _tool_executor(user, reader, caller)

    refused = await _refused(
        executor,
        _tool_step(facts, arguments={"q": "{{flow_input.absent}}"}),
        _running(user),
    )

    assert refused.code == "typed_io_variable_resolution_failed"
    assert reader.asked == [] and caller.calls == []


_DAYS_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"days": {"type": "array", "items": {"type": "string"}}},
    "required": ["days"],
    "additionalProperties": False,
}


_ARGUMENTS = "typed_io_tool_invalid_arguments"


@pytest.mark.parametrize(
    ("input_schema", "arguments", "refusal_code"),
    [
        pytest.param(_DAYS_SCHEMA, {"days": _DAYS}, None, id="fits"),
        pytest.param(
            _DAYS_SCHEMA, {"days": _SECRET_ARGUMENT}, _ARGUMENTS, id="wrong-type"
        ),
        pytest.param(_DAYS_SCHEMA, {}, _ARGUMENTS, id="required-absent"),
        pytest.param(
            _DAYS_SCHEMA, {"days": _DAYS, "all": True}, _ARGUMENTS, id="not-declared"
        ),
        pytest.param(
            {"$ref": "https://example.org/schema.json"},
            {"days": _DAYS},
            "typed_io_tool_invalid_schema",
            id="schema-that-cannot-be-evaluated",
        ),
        pytest.param(
            {"$schema": "https://example.invalid/not-a-draft", "type": "object"},
            {"days": _DAYS},
            "typed_io_tool_invalid_schema",
            id="schema-of-an-unknown-draft",
        ),
        pytest.param(None, {"anything": [1, {"a": None}]}, None, id="no-schema"),
    ],
)
async def test_arguments_are_checked_against_the_approved_schema_before_the_call(
    user,
    input_schema: dict[str, object] | None,
    arguments: dict[str, object],
    refusal_code: str | None,
) -> None:
    # Kills the mutants that call without validating, validate against the
    # schema that waits for review, refuse a tool that declares no schema,
    # quote the refused value in the message, blame the step's arguments for
    # a schema that cannot be evaluated, or check the arguments by the default
    # draft's rules when the schema names a draft the library does not have.
    facts = _facts(input_schema=input_schema)
    caller = _answered({"ok": True})
    executor = _tool_executor(user, _Facts(facts), caller)
    step = _tool_step(facts, arguments=arguments)

    if refusal_code is None:
        await _read(executor, step, _running(user))
        assert [call["arguments"] for call in caller.calls] == [arguments]
    else:
        refused = await _refused(executor, step, _running(user))
        assert refused.code == refusal_code
        assert _SECRET_ARGUMENT not in str(refused)
        assert caller.calls == [] and _audits(executor) == []


_SLOW = "^(a+)+$"
# Python's re backtracks on this for seconds; each character more doubles it.
_SLOW_NAME = "a" * 27 + "!"


@pytest.mark.parametrize(
    ("input_schema", "arguments"),
    [
        pytest.param(
            {"patternProperties": {_SLOW: {}}, "additionalProperties": False},
            {_SLOW_NAME: 1},
            id="pattern-names-under-additionalProperties",
        ),
        pytest.param(
            {"patternProperties": {_SLOW: {}}, "unevaluatedProperties": False},
            {_SLOW_NAME: 1},
            id="pattern-names-under-unevaluatedProperties",
        ),
        pytest.param(
            {
                "properties": {
                    "code": {
                        "$schema": "http://json-schema.org/draft-07/schema#",
                        "pattern": _SLOW,
                    }
                }
            },
            {"code": _SLOW_NAME},
            id="pattern-in-a-subschema-of-another-draft",
        ),
    ],
)
async def test_an_argument_check_past_its_limit_ends_off_the_event_loop(
    user,
    monkeypatch,
    input_schema: dict[str, object],
    arguments: dict[str, object],
) -> None:
    # Kills the mutants that check the arguments in the worker's process (re
    # holds the GIL while it backtracks: the heartbeat stops, also on a
    # thread, and the check takes seconds) and that do not end the check at
    # its limit.
    limit = 0.5
    monkeypatch.setattr(
        tool_argument_check, "TOOL_ARGUMENT_CHECK_TIMEOUT_SECONDS", limit
    )
    facts = _facts(input_schema=input_schema)
    caller = _answered({"ok": True})
    executor = _tool_executor(user, _Facts(facts), caller)
    step = _tool_step(facts, arguments=arguments)
    beats: list[float] = []

    async def heartbeat() -> None:
        while True:
            beats.append(time.monotonic())
            await asyncio.sleep(0.01)

    beating = asyncio.create_task(heartbeat())
    started = time.monotonic()
    refused = await _refused(executor, step, _running(user))
    elapsed = time.monotonic() - started
    beating.cancel()

    assert refused.code == "typed_io_tool_invalid_schema"
    assert str(refused) == (
        "Step 2: the tool's arguments could not be checked against its input "
        "schema within the time limit."
    )
    # The check's limit, and the start of a new child (about 0.15 s).
    assert elapsed < limit + 1.0
    assert max(b - a for a, b in zip(beats, beats[1:], strict=False)) < limit / 2
    assert caller.calls == [] and _audits(executor) == []


@pytest.mark.parametrize(
    ("input_schema", "arguments"),
    [
        pytest.param(
            {"properties": {"people": {"additionalProperties": {"type": "integer"}}}},
            {"people": {"19800101-1234": "not a number"}},
            id="cut-before-a-key-of-data",
        ),
        pytest.param({"properties": {"days": False}}, {"days": _DAYS}, id="no-rule"),
        pytest.param({"required": ["days"]}, {}, id="required"),
    ],
)
async def test_a_refused_argument_has_the_place_and_rule_of_the_in_process_check(
    user, input_schema: dict[str, object], arguments: dict[str, object]
) -> None:
    # Kills the mutants that build the refusal's place and rule from the
    # child's finding other than validate_against_contract builds them for a
    # step's contract.
    with pytest.raises(TypedIOValidationException) as in_process:
        validate_against_contract(arguments, input_schema, label="L", side="input")
    facts = _facts(input_schema=input_schema)
    executor = _tool_executor(user, _Facts(facts), _answered({"ok": True}))

    refused = await _refused(
        executor, _tool_step(facts, arguments=arguments), _running(user)
    )

    keys = ("json_pointer", "schema_rule", "contract_side")
    expected = in_process.value.context or {}
    assert refused.code == _ARGUMENTS
    assert {key: (refused.context or {}).get(key) for key in keys} == {
        key: expected.get(key) for key in keys
    }


async def test_a_check_that_raises_in_its_process_could_not_check_the_arguments(
    user,
) -> None:
    # Kills the mutants that let an exception inside the check end the child
    # (a host fault, flow_step_execution_failed) or give it the sentence of a
    # schema that cannot be evaluated, which blames the server.
    schema: dict[str, object] = {"properties": {"x": {"multipleOf": 0.5}}}
    facts = _facts(input_schema=schema)
    executor = _tool_executor(user, _Facts(facts), _answered({"ok": True}))
    step = _tool_step(facts, arguments={"x": 10**400})

    refused = await _refused(executor, step, _running(user))

    assert refused.code == "typed_io_tool_invalid_schema"
    assert str(refused) == (
        "Step 2: the tool's arguments could not be checked against its input schema."
    )


def _nested(depth: int) -> object:
    value: object = 1
    for _ in range(depth):
        value = [value]
    return value


@pytest.mark.parametrize(
    ("arguments", "run_input", "refusal_code"),
    [
        pytest.param(
            {"value": "{{flow_input.value}}"},
            {"value": _nested(600)},
            None,
            id="bound-600-deep",
        ),
        pytest.param({"value": float("nan")}, None, _ARGUMENTS, id="fixed-nan"),
    ],
)
async def test_arguments_go_to_the_check_as_json_text(
    user,
    arguments: dict[str, object],
    run_input: dict[str, object] | None,
    refusal_code: str | None,
) -> None:
    # Kills the mutants that send the check as a pickle (at 600 levels it
    # raises RecursionError, untyped) and that let arguments JSON text cannot
    # hold raise untyped.
    facts = _facts(input_schema={"type": "object"})
    caller = _answered({"ok": True})
    executor = _tool_executor(user, _Facts(facts), caller)
    step = _tool_step(facts, arguments=arguments)
    run = _running(user, run_input)

    if refusal_code is None:
        await _read(executor, step, run)
        assert len(caller.calls) == 1
    else:
        refused = await _refused(executor, step, run)
        assert refused.code == refusal_code
        assert caller.calls == []


async def test_a_check_whose_process_does_not_start_fails_the_step_as_the_host(
    user, monkeypatch
) -> None:
    # Kills the mutant that gives a child that does not start in time the
    # schema's code: the fault is the host's, and the run must not tell the
    # flow's editor to take the schema up with the MCP server.
    monkeypatch.setattr(tool_argument_check, "_CHECKER", ToolArgumentChecker())
    monkeypatch.setattr(tool_argument_check, "_START_TIMEOUT_SECONDS", 0.0)
    facts = _facts(input_schema={"type": "object"})
    caller = _answered({"ok": True})
    executor = _tool_executor(user, _Facts(facts), caller)
    step = _tool_step(facts)
    with pytest.raises(ToolArgumentCheckFailed) as failed:
        await _read(executor, step, _running(user))
    claimed = _failing(executor, user, step)

    await executor._handle_generic_step_failure(
        run_id=claimed.flow_run_id,
        tenant_id=user.tenant_id,
        step=step,
        attempt_no=1,
        claimed=claimed,
        state=_empty_execution_state(),
        exc=failed.value,
    )

    error = executor._terminalize_run.await_args.kwargs["error"]
    assert caller.calls == []
    assert error.code is FlowApiErrorCode.STEP_EXECUTION_FAILED
    # Not retryable: an earlier tool step of the run may have been called.
    assert error.retryable is False
    assert error.message == (
        "Flow step 2 failed because this worker could not run the check of the "
        "tool's arguments; the tool was not called."
    )


async def test_a_refused_argument_is_located_without_a_key_of_run_data(user) -> None:
    # Kills the mutant that builds the refusal from the validator's message:
    # its full location names the keys of a bound object, which are run data
    # (here a personal identity number), and the message is stored and logged.
    schema: dict[str, object] = {
        "type": "object",
        "properties": {
            "people": {"type": "object", "additionalProperties": {"type": "integer"}}
        },
    }
    facts = _facts(input_schema=schema)
    executor = _tool_executor(user, _Facts(facts), _answered({"ok": True}))
    run = _running(user, {"people": {"19800101-1234": "not a number"}})
    step = _tool_step(facts, arguments={"people": "{{flow_input.people}}"})

    refused = await _refused(executor, step, run)

    assert refused.code == _ARGUMENTS
    assert str(refused) == (
        "Step 2: the tool's arguments do not fit its input schema at '/people' "
        "(rule 'type')."
    )


async def test_the_default_policy_refuses_a_loopback_server_before_any_request(
    user,
) -> None:
    # Kills the mutant that calls without vetting the server's address: the
    # endpoint is real and would answer.
    received: list[dict[str, Any]] = []
    app = one_tool_app(lambda request_id: tool_result(request_id, {"content": []}))
    async with serve_test_app(_recording(app, received)) as url:
        facts = _endpoint_facts(url)
        executor, flow_repo, _, _ = _build_executor(user)
        executor.tool_facts_reader = _Facts(facts)
        executor.tool_caller = _real_caller()
        executor.audit_service = AsyncMock()
        flow_repo.get_space_id = AsyncMock(return_value=_SPACE_ID)

        refused = await _refused(
            executor, _tool_step(facts, input_type="text"), _running(user)
        )

    assert refused.code == "typed_io_tool_destination_blocked"
    assert received == []
    (audit,) = _audits(executor)
    assert (audit["outcome"], audit["error_message"]) == (Outcome.FAILURE, str(refused))


@pytest.mark.parametrize(
    ("allow_private", "http_url", "answered", "code"),
    [
        pytest.param(
            None, "https://mcp.internal/mcp", ["10.0.0.5"], None, id="default"
        ),
        pytest.param(
            False,
            "https://mcp.internal/mcp",
            ["10.0.0.5"],
            "typed_io_tool_destination_blocked",
            id="private-switched-off",
        ),
        pytest.param(
            None,
            "https://mcp.internal/mcp",
            ["10.0.0.5", "169.254.169.254"],
            "typed_io_tool_destination_blocked",
            id="one-metadata-address",
        ),
        pytest.param(
            None,
            "https://user:secret@mcp.internal/mcp",
            ["10.0.0.5"],
            "typed_io_tool_destination_blocked",
            id="address-that-is-not-a-plain-url",
        ),
        pytest.param(
            None,
            "https://mcp.internal/mcp",
            DestinationUnresolvable("mcp.internal"),
            "typed_io_tool_connection_error",
            id="name-does-not-resolve",
        ),
    ],
)
async def test_the_servers_address_is_vetted_with_the_tool_setting(
    user,
    monkeypatch: pytest.MonkeyPatch,
    allow_private: bool | None,
    http_url: str,
    answered: list[str] | Exception,
    code: str | None,
) -> None:
    # Kills the mutants that vet with the HTTP setting (private networks off by
    # default), ignore the tool setting, vet another host or port than the
    # server's, report an unresolved name as a refused address, or leave a
    # refused server out of the audit.
    assert Settings.model_fields["flow_tool_allow_private_networks"].default is True
    if allow_private is not None:
        changed = get_settings().model_copy(
            update={"flow_tool_allow_private_networks": allow_private}
        )
        monkeypatch.setattr(executor_module, "get_settings", lambda: changed)
    asked: list[tuple[str, int]] = []

    async def resolver(host: str, port: int) -> list[str]:
        asked.append((host, port))
        if isinstance(answered, Exception):
            raise answered
        return answered

    facts = _facts(server={"http_url": http_url})
    caller = _answered({"ok": True})
    executor, flow_repo, _, _ = _build_executor(user)
    executor.tool_facts_reader, executor.tool_caller = _Facts(facts), caller
    executor.tool_name_resolver = resolver
    executor.audit_service = AsyncMock()
    flow_repo.get_space_id = AsyncMock(return_value=_SPACE_ID)

    if code is None:
        await _read(executor, _tool_step(facts), _running(user))
        assert len(caller.calls) == 1
    else:
        refused = await _refused(executor, _tool_step(facts), _running(user))
        assert refused.code == code
        (audit,) = _audits(executor)
        assert audit["outcome"] is Outcome.FAILURE
        assert "secret" not in str(refused) + repr(audit)
        assert caller.calls == []
    assert asked in ([("mcp.internal", 443)], [])
    assert bool(asked) is ("user:secret" not in http_url)


async def test_the_executor_config_reads_the_tool_settings_of_the_deployment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Kills the mutants that leave the tool-call ceiling or the private-network
    # switch at a constant instead of the deployment's settings.
    changed = get_settings().model_copy(
        update={
            "flow_tool_allow_private_networks": False,
            "mcp_client_call_timeout_seconds": 17,
        }
    )
    monkeypatch.setattr(executor_module, "get_settings", lambda: changed)

    config = FlowRunExecutorConfig.from_settings(max_inline_text_bytes=1024)

    assert (config.tool_allow_private_networks, config.tool_call_timeout_seconds) == (
        False,
        17,
    )


@pytest.mark.parametrize(
    ("seconds_left", "ceiling", "budget"),
    [
        pytest.param(30.5, 60, 29, id="the-step-leaves-less"),
        pytest.param(300.5, 60, 60, id="the-deployment-ceiling"),
        pytest.param(2.5, 60, 1, id="one-second-left"),
        pytest.param(1.5, 60, None, id="only-the-grace-left"),
        pytest.param(0.0, 60, None, id="spent"),
        pytest.param(None, 60, 60, id="outside-an-attempt"),
    ],
)
async def test_the_call_gets_what_the_step_has_left_after_the_callers_grace(
    user, seconds_left: float | None, ceiling: int, budget: int | None
) -> None:
    # Kills the mutants that give the call the deployment's ceiling whatever
    # the step has left, forget the second the caller may take to report a
    # spent budget, pass a budget of zero, call although the step's time is
    # spent, or audit a call for a step that made none.
    assert EXCHANGE_STOP_GRACE_SECONDS == 1.0
    facts = _facts()
    caller = _answered({"ok": True})
    executor = _tool_executor(user, _Facts(facts), caller)
    executor.tool_call_timeout_seconds = ceiling
    step = _tool_step(facts)

    if seconds_left is None:
        await _read(executor, step, _running(user))
    else:
        now = asyncio.get_running_loop().time()
        deadline = StepDeadline(
            budget_seconds=600.0, started_at=now, expires_at=now + seconds_left
        )
        with step_deadline_scope(deadline, step_order=2):
            if budget is None:
                refused = await _refused(executor, step, _running(user))
                assert refused.code == "flow_step_timeout"
                assert "the tool call" in str(refused)
            else:
                await _read(executor, step, _running(user))

    assert [call["timeout_seconds"] for call in caller.calls] == (
        [] if budget is None else [budget]
    )
    assert len(_audits(executor)) == len(caller.calls)


async def test_resolving_the_servers_name_gets_what_the_step_has_left(user) -> None:
    # Kills the mutant that resolves the name with the deployment's ceiling
    # whatever the step has left: this name never resolves, and the step
    # would wait a minute for it.
    async def never(_: str, __: int) -> list[str]:
        await asyncio.Event().wait()
        return []

    facts = _facts()
    caller = _answered({"ok": True})
    executor = _tool_executor(user, _Facts(facts), caller)
    executor.tool_call_timeout_seconds = 60
    executor.tool_name_resolver = never
    now = asyncio.get_running_loop().time()
    deadline = StepDeadline(budget_seconds=600.0, started_at=now, expires_at=now + 2.5)

    with step_deadline_scope(deadline, step_order=2):
        refused = await asyncio.wait_for(
            _refused(executor, _tool_step(facts), _running(user)), timeout=5
        )

    assert refused.code == "typed_io_tool_connection_error"
    assert caller.calls == []


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        pytest.param(MCPToolCallTimedOut("late"), "typed_io_tool_timeout", id="time"),
        pytest.param(
            MCPToolAnswerTooLarge("big"), "typed_io_tool_answer_too_large", id="size"
        ),
        pytest.param(
            MCPClientError(f"refused {_SECRET_ARGUMENT}"),
            "typed_io_tool_connection_error",
            id="any-other-client-error",
        ),
    ],
)
async def test_a_failed_call_fails_the_attempt_with_its_own_code_and_is_audited(
    user, failure: Exception, code: str
) -> None:
    # Kills the mutants that report every failed call with one code, retry,
    # skip the audit of a failed call, or copy the client's error text (which
    # can quote the server) into what is stored and audited.
    facts = _facts()
    caller = _Caller(failure)
    executor = _tool_executor(user, _Facts(facts), caller)

    refused = await _refused(
        executor, _tool_step(facts, arguments={"q": _SECRET_ARGUMENT}), _running(user)
    )

    assert refused.code == code
    assert len(caller.calls) == 1
    (audit,) = _audits(executor)
    assert audit["outcome"] is Outcome.FAILURE
    assert audit["error_message"] == str(refused)
    assert audit["metadata"]["extra"]["tool_name"] == "lookup_case"
    assert _SECRET_ARGUMENT not in repr(audit) + str(refused)


def _slow(release: asyncio.Event) -> Callable[[object], Awaitable[Response]]:
    async def answer(request_id: object) -> Response:
        await release.wait()
        return tool_result(request_id, {"content": []})

    return answer


def _oversized(request_id: object) -> Response:
    async def body() -> AsyncIterator[bytes]:
        yield (
            b'{"jsonrpc":"2.0","id":'
            + json.dumps(request_id).encode()
            + b',"result":{"content":[{"type":"text","text":"'
        )
        for _ in range(64):
            yield b"x" * 4096
        yield b'"}]}}'

    return StreamingResponse(body(), media_type="application/json")


@pytest.mark.parametrize(
    ("endpoint", "code"),
    [
        pytest.param("slow", "typed_io_tool_timeout", id="no-answer-in-time"),
        pytest.param("oversized", "typed_io_tool_answer_too_large", id="too-large"),
    ],
)
async def test_transport_failures_of_a_real_endpoint_reach_the_run_as_typed_codes(
    user, endpoint: str, code: str
) -> None:
    # Kills the mutants that pass the caller another ceiling than the step's
    # inline limit or another time than the budget (the real caller would not
    # stop the answer or the wait), and the mapping mutants on the real
    # exceptions of the MCP module.
    release = asyncio.Event()
    respond = {"slow": _slow(release), "oversized": _oversized}
    async with serve_test_app(one_tool_app(respond[endpoint])) as url:
        facts = _endpoint_facts(url)
        executor = _tool_executor(
            user, _Facts(facts), _real_caller(), max_inline_text_bytes=64 * 1024
        )
        executor.tool_call_timeout_seconds = 1

        refused = await _refused(
            executor, _tool_step(facts, input_type="text"), _running(user)
        )
        release.set()

    assert refused.code == code
    (audit,) = _audits(executor)
    assert audit["outcome"] is Outcome.FAILURE


async def test_a_tool_that_says_it_failed_fails_the_step_and_keeps_only_its_text(
    user,
) -> None:
    # Kills the mutants that hand a tool's failure text to the step as input,
    # put that text into the message (which is logged and audited), keep it
    # unbounded, or drop it on the way to the run error.
    said = "no such case: " + "x" * 600
    app = one_tool_app(
        lambda request_id: tool_result(
            request_id,
            {
                "content": [{"type": "text", "text": said}],
                "structuredContent": {"reason": _SECRET_ARGUMENT},
                "isError": True,
            },
        )
    )
    async with serve_test_app(app) as url:
        facts = _endpoint_facts(url)
        executor = _tool_executor(user, _Facts(facts), _real_caller())

        refused = await _refused(executor, _tool_step(facts), _running(user))

    assert refused.code == "typed_io_tool_reported_error"
    assert refused.context == {"step_order": 2, "tool_error_text": said[:512]}
    details = FlowRunErrorDetails.from_budget_context(refused.context)
    assert details is not None and details.tool_error_text == said[:512]
    (audit,) = _audits(executor)
    assert audit["outcome"] is Outcome.FAILURE
    assert "no such case" not in str(refused) + repr(audit)
    assert _SECRET_ARGUMENT not in repr(refused.context) + repr(audit)


@pytest.mark.parametrize(
    ("blocks", "kept"),
    [
        pytest.param((), None, id="no-text"),
        pytest.param(("  \n ",), None, id="blank-text"),
        pytest.param(("bad\x00case\r\n", "\x1bline"), "bad case line", id="controls"),
    ],
)
async def test_the_text_of_a_failed_tool_is_kept_without_control_characters(
    user, blocks: tuple[str, ...], kept: str | None
) -> None:
    # Kills the mutants that store an empty or blank text as the tool's own
    # words (a detail that says nothing), or keep a control character in it:
    # U+0000 cannot be stored, so the run would lose its typed error.
    facts = _facts()
    caller = _Caller(MCPToolAnswer(blocks, 0, None, is_error=True))
    executor = _tool_executor(user, _Facts(facts), caller)

    refused = await _refused(executor, _tool_step(facts), _running(user))

    assert refused.code == "typed_io_tool_reported_error"
    details = FlowRunErrorDetails.from_budget_context(refused.context)
    assert (details.tool_error_text if details else None) == kept


async def test_a_resumed_run_is_not_refused_for_a_tool_step_it_has_completed(
    user,
) -> None:
    # Kills the mutant that asks the levels about every tool step each time a
    # run is taken up: a run waiting for review after its tool step would fail
    # when the space removes the tool's server, though it calls nothing more.
    removed = _facts(server_in_space=False)
    reader = _Facts(removed)
    executor = _tool_executor(user, reader, _answered({"ok": True}))
    step, run, state = _tool_step(removed), _running(user), _empty_execution_state()

    with pytest.raises(TypedIOValidationException) as refused:
        await executor._refuse_unusable_tools([step], run=run, state=state)
    assert refused.value.code == "typed_io_tool_not_allowed"

    state.completed_by_order[step.step_order] = _result(step_order=step.step_order)
    await executor._refuse_unusable_tools([step], run=run, state=state)
    assert len(reader.asked) == 1


async def test_the_input_contract_is_checked_on_the_tools_answer(user) -> None:
    # Kills the mutant that returns the answer past the step's own input
    # contract: a model would read what the step declared it does not take.
    facts = _facts()
    executor = _tool_executor(user, _Facts(facts), _answered({"days": "monday"}))
    step = _tool_step(
        facts,
        input_contract={
            "type": "object",
            "properties": {"days": {"type": "array"}},
            "required": ["days"],
        },
    )
    assistant = MagicMock()
    assistant.get_prompt_text.return_value = ""
    deps = StepExecutionRuntimeDeps(
        max_inline_text_bytes=1024 * 1024,
        variable_resolver=executor.variable_resolver,
        completion_service=object(),
        load_assistant=AsyncMock(return_value=assistant),
        resolve_step_input=partial(executor._resolve_step_input, attempt_no=1),
        retrieve_rag_chunks=AsyncMock(),
        process_typed_output=AsyncMock(),
        apply_output_cap=AsyncMock(),
    )
    state = RunExecutionState(
        completed_by_order={},
        prior_results=[],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
    )

    with pytest.raises(TypedIOValidationException) as refused:
        await prepare_step_execution(
            step=step,
            run=_running(user),
            state=state,
            version_metadata=None,
            requested_file_ids=(),
            deps=deps,
        )

    assert refused.value.code == "typed_io_contract_violation"


async def test_a_tool_step_without_its_dependencies_is_a_wiring_error(user) -> None:
    # Kills the mutant that runs a tool step on an executor built without the
    # facts reader or the caller as if the tool were allowed.
    facts = _facts()
    executor = _tool_executor(user, None, _answered({"ok": True}))

    with pytest.raises(FlowRuntimeInvariantError):
        await _read(executor, _tool_step(facts), _running(user))


async def test_an_answer_larger_than_a_step_takes_is_refused_before_the_audit(
    user,
) -> None:
    # Kills the mutant that measures only the server's response: this answer
    # is 48 kB as sent and 72 kB as the JSON text the step takes, so an
    # audited success would then fail on the step's own size limit.
    facts = _facts()
    caller = _answered({"r": [1] * 24000})
    executor = _tool_executor(
        user, _Facts(facts), caller, max_inline_text_bytes=64 * 1024
    )

    refused = await _refused(executor, _tool_step(facts), _running(user))

    assert refused.code == "typed_io_tool_answer_too_large"
    assert [audit["outcome"] for audit in _audits(executor)] == [Outcome.FAILURE]


async def test_the_call_gets_what_the_step_has_left_after_the_name_is_resolved(
    user,
) -> None:
    # Kills the mutant that gives the call the budget counted before the
    # server's name was resolved: a slow lookup would let the call outlive
    # the step's deadline.
    facts = _facts()
    caller = _answered({"ok": True})
    executor = _tool_executor(user, _Facts(facts), caller)
    now = asyncio.get_running_loop().time()

    async def slow_lookup(_: str, __: int) -> list[str]:
        scope = current_step_deadline_scope()
        assert scope is not None
        # Twenty seconds of the step's time pass while the name resolves.
        scope.deadline = replace(scope.deadline, expires_at=now + 10.5)
        return ["93.184.216.34"]

    executor.tool_name_resolver = slow_lookup
    deadline = StepDeadline(budget_seconds=600.0, started_at=now, expires_at=now + 30.5)

    with step_deadline_scope(deadline, step_order=2):
        await _read(executor, _tool_step(facts), _running(user))

    assert [call["timeout_seconds"] for call in caller.calls] == [9]


async def test_the_preflight_asks_about_every_tool_step_in_step_order(user) -> None:
    # Kills the mutants whose preflight asks about the first tool step only,
    # or in another order than the steps': a run would start although a later
    # tool step is refused, or report the later of two refused steps.
    allowed, refused_facts = _facts(), _facts(server_in_space=False)

    class _ByServer:
        async def read(
            self, *, mcp_server_id: UUID, **_: object
        ) -> UnattendedToolFacts:
            assert allowed.server is not None
            return allowed if mcp_server_id == allowed.server.id else refused_facts

    executor = _tool_executor(user, None, _answered())
    executor.tool_facts_reader = _ByServer()
    run, state = _running(user), _empty_execution_state()
    first = replace(_tool_step(allowed), step_order=1)
    second = replace(_tool_step(refused_facts), step_order=2)
    third = replace(_tool_step(refused_facts), step_order=3)

    with pytest.raises(TypedIOValidationException) as refused:
        await executor._refuse_unusable_tools(
            [third, second, first], run=run, state=state
        )

    assert (refused.value.context or {})["step_order"] == 2


async def test_the_space_of_a_deleted_flow_is_still_read_for_its_run(user) -> None:
    # Kills the mutant that looks the space up among live flows only: a run
    # that is finishing after its flow was deleted would end with "Flow not
    # found" instead of the tool's answer or its typed refusal.
    facts = _facts()
    executor = _tool_executor(user, _Facts(facts), _answered({"ok": True}))
    run = _running(user)

    await _read(executor, _tool_step(facts), run)

    executor.flow_repo.get_space_id.assert_awaited_once_with(
        flow_id=run.flow_id, tenant_id=run.tenant_id, include_deleted=True
    )


def _rate_limited() -> OpenAIException:
    return OpenAIException("rate limit reached", code="provider_rate_limited")


def _failing(executor, user, step: RuntimeStep):
    """The executor's failure handlers with the storage they write to faked;
    returns the claimed result of ``step``."""
    executor.flow_run_repo.finish_attempt = AsyncMock()
    executor.flow_run_repo.save_step_result = AsyncMock()
    executor._terminalize_run = AsyncMock()
    executor._rollback = AsyncMock()
    return _claimed_step_result(
        run_id=uuid4(),
        flow_id=uuid4(),
        tenant_id=user.tenant_id,
        step_id=step.step_id,
        assistant_id=step.assistant_id,
    )


@pytest.mark.parametrize(
    ("tool_step_orders", "completed", "retryable"),
    [
        pytest.param({1}, {1}, False, id="after-a-completed-tool-step"),
        pytest.param({2}, set(), False, id="at-the-tool-step"),
        pytest.param({3}, set(), True, id="before-the-tool-step"),
        pytest.param({3}, {3}, False, id="a-later-tool-step-already-completed"),
        pytest.param(set(), {1}, True, id="a-flow-without-a-tool-step"),
    ],
)
async def test_a_rate_limited_run_is_not_retryable_after_a_possible_tool_call(
    user, tool_step_orders: set[int], completed: set[int], retryable: bool
) -> None:
    # Kills the mutant that reports the provider's rate limit at step 2 as
    # safe to run again although a tool step ran first: a new run calls the
    # tool again, and a tool can change something.
    executor = _tool_executor(user, None, None)
    step = _runtime_step(step_order=2)
    claimed = _failing(executor, user, step)
    state = replace(
        _empty_execution_state(),
        tool_step_orders=frozenset(tool_step_orders),
        completed_by_order={order: _result(step_order=order) for order in completed},
    )

    await executor._handle_generic_step_failure(
        run_id=claimed.flow_run_id,
        tenant_id=user.tenant_id,
        step=step,
        attempt_no=1,
        claimed=claimed,
        state=state,
        exc=_rate_limited(),
    )

    error = executor._terminalize_run.await_args.kwargs["error"]
    assert error.code is FlowApiErrorCode.PROVIDER_RATE_LIMITED
    assert error.retryable is retryable
    assert (error.details.tool_call_possible if error.details else None) is (
        None if retryable else True
    )


async def test_an_attempt_that_cannot_start_after_a_tool_step_is_not_retryable(
    user,
) -> None:
    # Kills the mutant that marks only the provider's rate limit: the other
    # code a run may be started again for would stay retryable after a tool
    # step completed.
    executor = _tool_executor(user, None, None)
    step = _runtime_step(step_order=2)
    claimed = _failing(executor, user, step)
    state = replace(_empty_execution_state(), tool_step_orders=frozenset({1}))

    await executor._handle_attempt_start_failure(
        run_id=claimed.flow_run_id,
        tenant_id=user.tenant_id,
        step=step,
        claimed=claimed,
        state=state,
    )

    error = executor._terminalize_run.await_args.kwargs["error"]
    assert error.code is FlowApiErrorCode.STEP_ATTEMPT_START_FAILED
    assert error.retryable is False


async def test_the_run_error_of_a_refusal_at_the_step_carries_the_typed_reason(
    user,
) -> None:
    # Kills the mutants that leave the refusing level or the broken schema
    # rule out of the run error of a step that was refused at its read, or
    # say of that step that provider work may have started: it asked no
    # provider for anything.
    refused_facts = _facts(server_in_space=False)
    schema: dict[str, object] = {
        "type": "object",
        "properties": {"days": {"type": "array"}},
    }
    allowed = _facts(input_schema=schema)
    errors = []
    for facts, arguments in ((refused_facts, {}), (allowed, {"days": "monday"})):
        executor = _tool_executor(user, _Facts(facts), _answered({"ok": True}))
        step = _tool_step(facts, arguments=arguments)
        refused = await _refused(executor, step, _running(user))
        claimed = _failing(executor, user, step)

        await executor._handle_typed_step_failure(
            run_id=claimed.flow_run_id,
            tenant_id=user.tenant_id,
            step=step,
            attempt_no=1,
            claimed=claimed,
            typed_exc=refused,
            failed_input_payload=None,
            state=_empty_execution_state(),
        )
        errors.append(executor._terminalize_run.await_args.kwargs["error"])

    not_allowed, invalid_arguments = errors
    assert not_allowed.message == (
        "Step 2: The instance or the space does not allow the step's tool in "
        "the flow's space (typed_io_tool_not_allowed)."
    )
    assert not_allowed.details.tool_refusal == "server_not_in_space"
    assert invalid_arguments.message == (
        "Step 2: The resolved tool arguments do not fit the tool's approved "
        "input schema, or cannot be written as JSON text "
        "(typed_io_tool_invalid_arguments)."
    )
    assert invalid_arguments.details.contract_violation.model_dump() == {
        "side": "input",
        "schema_rule": "type",
        "json_pointer": "/days",
    }
