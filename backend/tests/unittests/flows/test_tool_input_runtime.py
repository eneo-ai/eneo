"""A step whose input source is ``tool`` at run time: what the run asks before
its first step, and what the read asks, sends, takes and records. The happy
paths and the transport failures call a real local MCP endpoint."""

from __future__ import annotations

import asyncio
import hashlib
import json
import socket
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field, replace
from functools import partial
from types import SimpleNamespace
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
    FlowResolvedInputJsonPath,
    FlowResolvedInputToolAnswerSource,
    group_resolved_input_edges,
    parse_resolved_input_edges,
)
from eneo.flows.output_processing import validate_against_contract
from eneo.flows.runtime import executor as executor_module
from eneo.flows.runtime import tool_argument_check
from eneo.flows.runtime import tool_input as tool_input_module
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
    ArgumentCheckUnfinished,
    ToolArgumentChecker,
    ToolArgumentCheckFailed,
)
from eneo.main.config import Settings, get_settings
from eneo.main.destination_policy import IPAddress
from eneo.main.exceptions import (
    BadRequestException,
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
from tests.unittests.flows.async_test_support import until_task_reaches
from tests.unittests.flows.test_flow_executor_runtime import (
    _claimed_step_result,
    _empty_execution_state,
    _execute_setup_for_security,
    _security_assistant,
    _security_space,
    _stub_security_assistants,
)
from tests.unittests.flows.test_resolved_input_runtime import _result
from tests.unittests.flows.test_tool_publish_pin import _Facts, _facts
from tests.unittests.flows.test_typed_io_executor import (
    _build_executor,
    _mock_assistant_for_execute_step,
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
    journal: list[tuple[str, dict[str, Any] | None]] | None = None

    async def call(
        self,
        server: object,
        tool_name: str,
        arguments: dict[str, object],
        *,
        max_answer_bytes: int,
        timeout_seconds: int,
        http_client_factory: object,
    ) -> MCPToolAnswer:
        if self.journal is not None:
            self.journal.append(("call", None))
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
    # the arguments, or with the path and query of the server's address,
    # where a token can be).
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
        facts = _endpoint_facts(f"{url}?key=server-token")
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
        "server_classification_level": None,
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
        "url_host": url.removesuffix("/mcp"),
        "flow_id": str(run.flow_id),
        "step_order": 2,
        "step_id": str(step.step_id),
        "mcp_server_id": str(facts.server.id),
        "tool_name": "lookup",
    }
    assert extra["duration_ms"] >= 0
    assert audit["description"] == f"Flow HTTP tool_input POST to {extra['url_host']}"
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


@pytest.mark.parametrize(
    ("value", "required", "sent"),
    [
        pytest.param(1.5, [], True, id="number"),
        pytest.param(None, ["q"], True, id="null-required"),
        pytest.param(None, [], False, id="null-optional-left-out"),
    ],
)
async def test_a_bound_argument_keeps_the_json_type_of_what_it_names(
    user, value: object, required: list[str], sent: bool
) -> None:
    # Kills the mutant that interpolates a reference as a template does (a
    # number or null would reach the tool as its text), and the one that
    # sends null for an argument the tool does not require: a run-form field
    # left empty would then fail every run whose schema takes no null.
    facts = _facts(
        input_schema={
            "type": "object",
            "properties": {"q": {"type": ["number", "null"]}},
            "required": required,
        }
    )
    caller = _answered({"ok": True})
    executor = _tool_executor(user, _Facts(facts), caller)
    run = _running(user, {"v": value})

    resolved = await _read(
        executor, _tool_step(facts, arguments={"q": "{{flow_input.v}}"}), run
    )

    (call,) = caller.calls
    assert call["arguments"] == ({"q": value} if sent else {})
    assert type(call["arguments"].get("q")) is type(value)
    assert [edge.binding_ref for edge in resolved.edges] == [
        *(["tool.arguments.q:flow_input.v"] if sent else []),
        "tool.answer",
    ]
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
    # One read serves the classification rule and the decision.
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
    # No tool step is completed, so no recorded level is read.
    flow_run_repo.list_completed_tool_answers.assert_not_awaited()
    # One read serves the classification rule and the decision.
    assert executor.tool_facts_reader.asked == [
        {
            "tenant_id": user.tenant_id,
            "space_id": _SPACE_ID,
            "mcp_server_id": facts.server.id,
            "tool_id": facts.tool.id,
        }
    ]


def _level(level: int) -> SimpleNamespace:
    return SimpleNamespace(security_level=level)


_PASSED = {"status": "skipped", "reason": "step_already_claimed"}
_INVALID = {"status": "failed", "error": "flow_definition_invalid"}


@pytest.mark.parametrize(
    ("server_level", "enabled", "result", "said"),
    [
        pytest.param(
            1,
            True,
            _INVALID,
            "the tool's server does not meet",
            id="arguments-above",
        ),
        pytest.param(2, True, _PASSED, None, id="arguments-at-the-server-level"),
        pytest.param(
            3, True, _INVALID, "assistant model does not meet", id="model-below"
        ),
        pytest.param(
            None,
            True,
            {"status": "failed", "error": "typed_io_tool_not_allowed"},
            "no longer exists",
            id="deleted-server",
        ),
        pytest.param(
            -1,
            True,
            {"status": "failed", "error": "typed_io_tool_not_allowed"},
            "not added to this space",
            id="server-outside-the-space",
        ),
        pytest.param(1, False, _PASSED, None, id="classification-off"),
    ],
)
async def test_the_preflight_counts_the_tool_server_before_it_asks_the_chain(
    user,
    server_level: int | None,
    enabled: bool,
    result: dict[str, str],
    said: str | None,
) -> None:
    # Kills the mutants whose preflight leaves the server's level out of the
    # step's level or does not compare it with what the arguments send, refuse
    # a deleted server as an unclassified one instead of leaving it to the
    # decision, compare the level of a server the space has not activated (-1
    # here: a level-1 server outside the space), read and apply the server's
    # level while classifications are off, ask the rule and the decision about
    # different tenants or spaces, or read the tool's facts once for the rule
    # and again for the decision (the two could then judge different rows).
    # Step 1's output sits at the space's level, 2, and step 2 sends it to the
    # tool on a level-2 model.
    stored = _facts(
        server={"security_classification": _level(abs(server_level or 0))},
        server_in_space=server_level != -1,
    )
    now = stored if server_level is not None else replace(stored, server=None)
    executor, flow_run_repo, queued = _execute_setup_for_security(
        user,
        space_level=2,
        model_level=2,
        model_levels=[2, 2],
        step_fields={
            "input_source": "tool",
            "input_type": "json",
            "input_config": {
                "tool": _tool_config(
                    stored, arguments={"case": "{{step_1.output.text}}"}
                )
            },
        },
        step_fields_index=1,
    )
    executor.security_classification_enabled = enabled
    executor.tool_facts_reader, executor.tool_caller = _Facts(now), _answered()
    executor.flow_repo.get_space_id = AsyncMock(return_value=_SPACE_ID)

    outcome = await executor.execute(
        run_id=queued.id,
        flow_id=queued.flow_id,
        tenant_id=user.tenant_id,
        run_revision=queued.revision,
        dispatch_task_id="task-1",
        retry_count=0,
    )

    assert outcome == result
    assert [
        (asked["tenant_id"], asked["space_id"])
        for asked in executor.tool_facts_reader.asked
    ] == [(user.tenant_id, _SPACE_ID)]
    if said is None:
        flow_run_repo.claim_step_result.assert_awaited_once()
        return
    error = executor.flow_run_terminalizer.terminalize_run.await_args.kwargs["error"]
    assert said in error.message and error.step_order == 2
    flow_run_repo.claim_step_result.assert_not_awaited()
    executor._execute_step.assert_not_awaited()


async def test_the_runs_evidence_level_counts_the_level_of_the_tools_server(
    user,
) -> None:
    # Kills the mutant that keeps the answer of a level-3 server at the
    # space's level in what the run records for its evidence.
    facts = _facts(server={"security_classification": _level(3)})
    executor, flow_run_repo, queued = _execute_setup_for_security(
        user,
        space_level=1,
        model_level=3,
        step_fields={
            "input_source": "tool",
            "input_type": "json",
            "input_config": {"tool": _tool_config(facts)},
        },
    )
    executor.tool_facts_reader, executor.tool_caller = _Facts(facts), _answered()
    executor.flow_repo.get_space_id = AsyncMock(return_value=_SPACE_ID)

    await executor.execute(
        run_id=queued.id,
        flow_id=queued.flow_id,
        tenant_id=user.tenant_id,
        run_revision=queued.revision,
        dispatch_task_id="task-1",
        retry_count=0,
    )

    flow_run_repo.record_evidence_classification_level.assert_awaited_once_with(
        run_id=queued.id, tenant_id=user.tenant_id, level=3, has_completed_steps=False
    )


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

    assert refused.code == "typed_io_contract_not_checked"
    assert str(refused) == (
        "Step 2: the tool's arguments could not be checked against its input "
        "schema within the time limit, which a larger value or a contract with "
        "more work per item reaches sooner; it was not found invalid."
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

    assert refused.code == "typed_io_contract_not_checked"
    assert str(refused) == (
        "Step 2: the tool's arguments could not be checked against its input "
        "schema; it was not found invalid."
    )


@pytest.mark.parametrize("timed_out", [True, False])
async def test_an_unfinished_argument_check_is_not_the_servers_schema_fault(
    user, monkeypatch, timed_out: bool
) -> None:
    # An argument check that did not finish (queued behind a slow check, or
    # raised in its process) says nothing about the MCP server's schema: it
    # is typed_io_contract_not_checked, as for a step's contract.
    monkeypatch.setattr(
        tool_input_module,
        "check_tool_arguments",
        AsyncMock(return_value=ArgumentCheckUnfinished(timed_out=timed_out)),
    )
    facts = _facts(input_schema={"type": "object"})
    caller = _answered({"ok": True})
    executor = _tool_executor(user, _Facts(facts), caller)

    refused = await _refused(executor, _tool_step(facts), _running(user))

    assert refused.code == "typed_io_contract_not_checked"
    assert "it was not found invalid" in str(refused)
    assert ("within the time limit" in str(refused)) is timed_out
    assert caller.calls == []


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
            "typed_io_input_too_large",
            id="bound-600-deep",
        ),
        pytest.param({"value": float("nan")}, None, _ARGUMENTS, id="fixed-nan"),
    ],
)
async def test_arguments_go_to_the_check_as_json_text(
    user,
    arguments: dict[str, object],
    run_input: dict[str, object] | None,
    refusal_code: str,
) -> None:
    # Kills the mutants that send the check as a pickle (at 600 levels it
    # raises RecursionError, untyped) and that let arguments JSON text cannot
    # hold raise untyped. Arguments the check passes but the attempt's record
    # of the call cannot hold whole (nested deeper than its reader reads) are
    # not sent: kills the mutant that calls without a readable record.
    facts = _facts(input_schema={"type": "object"})
    caller = _answered({"ok": True})
    executor = _tool_executor(user, _Facts(facts), caller)
    step = _tool_step(facts, arguments=arguments)
    run = _running(user, run_input)

    refused = await _refused(executor, step, run)
    assert refused.code == refusal_code
    assert caller.calls == []
    executor.flow_run_repo.write_attempt_tool_call_evidence.assert_not_awaited()


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
        "Flow step 2 failed because this worker could not run its schema check; "
        "the step produced no result."
    )


async def test_a_copy_of_a_tool_answer_whose_check_cannot_run_names_no_tool_claim(
    user, monkeypatch
) -> None:
    # Kills a host-fault sentence that says the step called no tool: a copy
    # step's contract check runs after its tool has answered.
    monkeypatch.setattr(
        tool_argument_check,
        "_CONTRACT_CHECKER",
        ToolArgumentChecker(tool_argument_check.contract_check_limit_seconds),
    )
    monkeypatch.setattr(tool_argument_check, "_START_TIMEOUT_SECONDS", 0.0)
    facts = _facts()
    caller = _answered({"ok": True})
    executor = _tool_executor(user, _Facts(facts), caller)
    assistant = _mock_assistant_for_execute_step()
    assistant.get_prompt_text.return_value = ""
    executor._load_assistant = AsyncMock(return_value=assistant)
    step = replace(
        _tool_step(facts),
        output_type="json",
        output_mode="copy_input",
        output_contract={"type": "object"},
    )
    run = _running(user)
    with pytest.raises(ToolArgumentCheckFailed) as failed:
        await executor._execute_step(step=step, run=run, attempt_no=1)
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

    assert len(caller.calls) == 1
    assert executor._terminalize_run.await_args.kwargs["error"].message == (
        "Flow step 2 failed because this worker could not run its schema check; "
        "the step produced no result."
    )


async def test_an_output_check_that_cannot_run_after_the_model_answered_discloses_it(
    user, monkeypatch
) -> None:
    # Kills a host-fault sentence that says no model was called: a model
    # step's output contract check runs after its model has answered.
    monkeypatch.setattr(
        tool_argument_check,
        "_CONTRACT_CHECKER",
        ToolArgumentChecker(tool_argument_check.contract_check_limit_seconds),
    )
    monkeypatch.setattr(tool_argument_check, "_START_TIMEOUT_SECONDS", 0.0)
    facts = _facts()
    executor = _tool_executor(user, _Facts(facts), _answered({"ok": True}))
    assistant = _mock_assistant_for_execute_step(response_text='{"ok": true}')
    executor._load_assistant = AsyncMock(return_value=assistant)
    step = replace(
        _tool_step(facts), output_type="json", output_contract={"type": "object"}
    )
    with pytest.raises(ToolArgumentCheckFailed) as failed:
        await executor._execute_step(step=step, run=_running(user), attempt_no=1)
    claimed = _failing(executor, user, step)
    stored = _empty_execution_state()
    stored.activated_attempts.add((step.step_id, 1))

    await executor._handle_generic_step_failure(
        run_id=claimed.flow_run_id,
        tenant_id=user.tenant_id,
        step=step,
        attempt_no=1,
        claimed=claimed,
        state=stored,
        exc=failed.value,
    )

    assert assistant.get_response.await_count == 1
    assert executor._terminalize_run.await_args.kwargs["error"].message == (
        "Flow step 2 failed because this worker could not run its schema check; "
        "the step produced no result. "
        f"{executor_module._PROVIDER_WORK_AMBIGUITY_DISCLOSURE}"
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
    caplog: pytest.LogCaptureFixture,
    allow_private: bool | None,
    http_url: str,
    answered: list[str] | Exception,
    code: str | None,
) -> None:
    # Kills the mutants that vet with the HTTP setting (private networks off by
    # default), ignore the tool setting, vet another host or port than the
    # server's, report an unresolved name as a refused address, leave a
    # refused server out of the audit, or log a refused address as one of
    # flow HTTP.
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
        assert (
            "Flow MCP tool call refused destination mcp.internal" in caplog.text
        ) is (code == "typed_io_tool_destination_blocked" and bool(asked))
        (audit,) = _audits(executor)
        assert audit["outcome"] is Outcome.FAILURE
        assert "secret" not in str(refused) + repr(audit)
        assert caller.calls == []
    assert asked in ([("mcp.internal", 443)], [])
    assert bool(asked) is ("user:secret" not in http_url)


@pytest.mark.parametrize(
    ("http_url", "auth_type", "refusal"),
    [
        ("http://mcp.internal/mcp", "bearer", "server_credential_needs_https"),
        ("http://mcp.internal/mcp", "none", None),
        ("https://mcp.internal/mcp", "bearer", None),
    ],
)
async def test_a_credential_goes_to_the_server_only_over_https(
    user, http_url: str, auth_type: str, refusal: str | None
) -> None:
    # Kills the mutants that call a server whose credential would go over
    # plain http, and that ask https of a server that takes none. The decision
    # refuses before the address is vetted: nothing goes out, so nothing is
    # audited as an outbound call.
    facts = _facts(server={"http_url": http_url, "http_auth_type": auth_type})
    caller = _answered({"ok": True})
    executor = _tool_executor(user, _Facts(facts), caller)

    if refusal is None:
        await _read(executor, _tool_step(facts), _running(user))
        assert len(caller.calls) == 1
    else:
        refused = await _refused(executor, _tool_step(facts), _running(user))
        assert (refused.code, (refused.context or {}).get("refusal")) == (
            "typed_io_tool_not_allowed",
            refusal,
        )
        assert (caller.calls, _audits(executor)) == ([], [])


async def test_the_call_connects_only_to_an_address_the_policy_allows_then(
    user, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Kills the mutant that lets the MCP client connect with an HTTP client of
    # its own, which resolves the server's name again when it connects: this
    # name answers a public address to the check before the call and loopback
    # to every later question, and that client reaches the server on loopback.
    name = "mcp.rebinding.example"
    lookups: list[str] = []

    def answer() -> str:
        lookups.append(name)
        return "93.184.216.34" if len(lookups) == 1 else "127.0.0.1"

    async def resolver(host: str, port: int) -> list[str]:
        assert host == name
        return [answer()]

    ask_the_system = socket.getaddrinfo

    def getaddrinfo(host: str | bytes | None, *rest: Any, **named: Any) -> Any:
        # The same name server, asked the way the operating system asks it.
        asked = host.decode() if isinstance(host, bytes) else host
        return ask_the_system(answer() if asked == name else host, *rest, **named)

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    reached: list[str] = []

    async def note(request: Request, call_next: RequestResponseEndpoint) -> Response:
        reached.append(request.method)
        return await call_next(request)

    app = one_tool_app(lambda request_id: tool_result(request_id, {"content": []}))
    app.middleware("http")(note)
    async with serve_test_app(app) as url:
        facts = _endpoint_facts(url.replace("127.0.0.1", name))
        executor = _tool_executor(user, _Facts(facts), _real_caller())
        executor.tool_destination_policy = FlowDestinationPolicy(
            allow_private_networks=True
        )
        executor.tool_name_resolver = resolver

        refused = await _refused(
            executor, _tool_step(facts, input_type="text"), _running(user)
        )

    assert reached == []
    assert refused.code == "typed_io_tool_connection_error"


async def test_a_connection_the_policy_refused_is_not_followed_by_a_question(
    user,
) -> None:
    # Kills the mutant that lets the client ask the server why the connect
    # failed after the policy refused the connection: the question resolves
    # the name again, this name then answers an allowed address, and the
    # question reaches the server with the credential and reports it as
    # reachable.
    answers = iter(["127.0.0.1", "169.254.169.254"])
    lookups: list[str] = []

    async def resolver(host: str, port: int) -> list[str]:
        lookups.append(host)
        return [next(answers, "127.0.0.1")]

    reached: list[str] = []

    async def note(request: Request, call_next: RequestResponseEndpoint) -> Response:
        reached.append(request.method)
        return await call_next(request)

    app = one_tool_app(lambda request_id: tool_result(request_id, {"content": []}))
    app.middleware("http")(note)
    async with serve_test_app(app) as url:
        facts = _endpoint_facts(url.replace("127.0.0.1", "mcp.probe.example"))
        executor = _tool_executor(user, _Facts(facts), _real_caller())
        executor.tool_name_resolver = resolver

        refused = await _refused(
            executor, _tool_step(facts, input_type="text"), _running(user)
        )

    assert (reached, len(lookups)) == ([], 2)
    assert refused.code == "typed_io_tool_connection_error"


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


@dataclass
class _Journal:
    """What the read did, in order: each stored call record, each commit and
    the call itself."""

    events: list[tuple[str, dict[str, Any] | None]] = field(default_factory=list)

    def watch(self, executor, caller: _Caller, *, failing_write: int | None) -> None:
        async def write(**kwargs: Any) -> str:
            result = kwargs["result"]
            record = {
                "start": kwargs["start"].model_dump(mode="json"),
                "result": None if result is None else result.model_dump(mode="json"),
            }
            self.events.append(("write", record))
            if self.kinds.count("write") == failing_write:
                raise ConnectionResetError("the database went away")
            return "written"

        async def commit() -> None:
            self.events.append(("commit", None))

        executor.flow_run_repo.write_attempt_tool_call_evidence.side_effect = write
        executor.session.commit.side_effect = commit
        caller.journal = self.events

    @property
    def kinds(self) -> list[str]:
        return [kind for kind, _ in self.events]

    @property
    def results(self) -> list[dict[str, Any] | None]:
        return [record["result"] for kind, record in self.events if record]


async def _no_address(host: str, port: int) -> list[str]:
    raise DestinationUnresolvable(host)


_STORED_CALL = ["write", "commit", "call", "write", "commit"]
_ANSWERED_NOTHING = MCPToolAnswer((), 0, {"rows": []}, is_error=False)


@pytest.mark.parametrize(
    ("ending", "kinds", "code"),
    [
        pytest.param("answered", _STORED_CALL, None, id="answered"),
        pytest.param("timed_out", _STORED_CALL, "typed_io_tool_timeout", id="failed"),
        pytest.param(
            "unresolvable", [], "typed_io_tool_connection_error", id="name-unresolved"
        ),
        pytest.param("too_large", [], "typed_io_input_too_large", id="args-too-large"),
        pytest.param("start_not_stored", ["write"], None, id="no-start"),
        pytest.param(
            "result_not_stored",
            ["write", "commit", "call", "write"],
            None,
            id="no-result",
        ),
    ],
)
async def test_the_call_is_recorded_before_it_is_sent_and_ended_before_it_is_read(
    user, ending: str, kinds: list[str], code: str | None
) -> None:
    # Kills the mutants that store the start after the call or do not commit
    # it before, that call although the start was not stored (its write
    # failed, it is too large for the inline budget, or the read was refused
    # before), that leave out the result of a
    # failed call or give it another code, whose answered result is not the
    # answer the step reads (size and hash of its tool_answer edge), or that
    # return the step's input although its result could not be stored, so
    # that the step would go on to its model.
    facts = _facts(input_schema={"type": "object"})
    caller = (
        _Caller(MCPToolCallTimedOut("late"))
        if ending == "timed_out"
        else _answered(structured={"rows": [1, 2]})
    )
    executor = _tool_executor(
        user,
        _Facts(facts),
        caller,
        max_inline_text_bytes=600 if ending == "too_large" else 1024 * 1024,
    )
    if ending == "unresolvable":
        executor.tool_name_resolver = _no_address
    journal = _Journal()
    journal.watch(
        executor,
        caller,
        failing_write={"start_not_stored": 1, "result_not_stored": 2}.get(ending),
    )
    arguments = {"q": "x" * (1000 if ending == "too_large" else 3), "n": None}
    step = _tool_step(facts, arguments={**arguments, "case": "{{flow_input.case}}"})

    ended: Exception | None = None
    try:
        await _read(executor, step, _running(user, {"case": "A-17"}))
    except Exception as exc:
        ended = exc

    assert journal.kinds == kinds
    assert len(caller.calls) == kinds.count("call")
    if ending == "answered":
        assert ended is None
    elif ending in {"start_not_stored", "result_not_stored"}:
        assert isinstance(ended, ConnectionResetError)
    else:
        assert isinstance(ended, TypedIOValidationException)
        assert ended.code == code
    if not kinds:
        return
    assert facts.server is not None and facts.tool is not None
    start = journal.events[0][1]
    assert start == {
        "start": {
            "mcp_server_id": str(facts.server.id),
            "tool_id": str(facts.tool.id),
            "tool_name": "lookup_case",
            "published_input_schema_sha256": canonical_json_hash({"type": "object"}),
            "current_input_schema_sha256": canonical_json_hash({"type": "object"}),
            "arguments": {**arguments, "case": "A-17"},
        },
        "result": None,
    }
    if ending == "start_not_stored":
        return
    assert caller.calls[0]["arguments"] == start["start"]["arguments"]
    (result,) = journal.results[1:]
    assert result is not None and result["duration_ms"] >= 0
    if ending == "timed_out":
        assert {**result, "duration_ms": 0} == {
            "outcome": "failed",
            "duration_ms": 0,
            "error_code": code,
            "answer_byte_size": None,
            "answer_sha256": None,
        }
        return
    answer_bytes = canonical_json_bytes({"rows": [1, 2]})
    assert (result["outcome"], result["answer_byte_size"], result["error_code"]) == (
        "answered",
        len(answer_bytes),
        None,
    )
    assert result["answer_sha256"] == hashlib.sha256(answer_bytes).hexdigest()


async def test_a_call_whose_attempt_has_closed_is_not_made(user) -> None:
    # Kills the mutant that sends the call although the start found the
    # attempt closed (the run ended or was recovered first), and the one
    # that reports that as a failure of the step instead of the run's own
    # outcome.
    from eneo.flows.domain.flow_run_exceptions import FlowStepAttemptClosed

    facts = _facts()
    caller = _answered(structured={"rows": []})
    executor = _tool_executor(user, _Facts(facts), caller)
    executor.flow_run_repo.write_attempt_tool_call_evidence.return_value = (
        "attempt_closed"
    )

    with pytest.raises(FlowStepAttemptClosed):
        await _read(executor, _tool_step(facts), _running(user))

    assert caller.calls == []
    executor.session.commit.assert_not_awaited()


_STOPPED = "The call was stopped before it ended."
_UNTYPED = "The call ended with an error that has no typed code."
_STOPPED_UNSENT = "The read was stopped before its request was sent."
_UNTYPED_UNSENT = (
    "The read ended with an error that has no typed code before its request was sent."
)


@dataclass
class _Hanging(_Caller):
    """Holds the call open until the read is cancelled."""

    entered: asyncio.Event = field(default_factory=asyncio.Event)

    async def call(self, *args: Any, **kwargs: Any) -> MCPToolAnswer:
        self.calls.append(kwargs)
        self.entered.set()
        await asyncio.Event().wait()
        raise AssertionError("the call was not cancelled")


@pytest.mark.parametrize(
    ("ending", "outcome", "message", "calls"),
    [
        pytest.param("untyped", Outcome.FAILURE, _UNTYPED, 1, id="untyped-error"),
        pytest.param("cancelled", Outcome.FAILURE, _STOPPED, 1, id="cancelled"),
        pytest.param(
            "closed", Outcome.FAILURE, _STOPPED_UNSENT, 0, id="attempt-closed"
        ),
        pytest.param(
            "start_not_stored", Outcome.FAILURE, _UNTYPED_UNSENT, 0, id="no-start"
        ),
        pytest.param("result_not_stored", Outcome.SUCCESS, None, 1, id="no-result"),
    ],
)
async def test_a_read_that_ends_without_a_typed_result_is_audited_once(
    user, ending: str, outcome: Outcome, message: str | None, calls: int
) -> None:
    # Kills the mutants that write no audit record for a read that was
    # cancelled, stopped by its closed attempt or ended by an error without a
    # typed code, that audit such a read with the error's own text (which can
    # quote the server or the arguments) or as a call when nothing was sent,
    # and that audit a read twice when storing its result fails after its
    # success was audited.
    facts = _facts()
    caller: _Caller = (
        _Hanging(_ANSWERED_NOTHING)
        if ending == "cancelled"
        else _Caller(RuntimeError(f"server said {_SECRET_ARGUMENT}"))
        if ending == "untyped"
        else _answered(structured={"rows": []})
    )
    executor = _tool_executor(user, _Facts(facts), caller)
    write = executor.flow_run_repo.write_attempt_tool_call_evidence
    if ending == "closed":
        write.return_value = "attempt_closed"
    elif ending == "start_not_stored":
        write.side_effect = ConnectionResetError(_SECRET_ARGUMENT)
    elif ending == "result_not_stored":
        write.side_effect = ["written", ConnectionResetError(_SECRET_ARGUMENT)]
    step = _tool_step(facts, arguments={"q": _SECRET_ARGUMENT})

    read = asyncio.create_task(_read(executor, step, _running(user)))
    if isinstance(caller, _Hanging):
        await until_task_reaches(caller.entered, read)
        read.cancel()
    with pytest.raises(BaseException) as ended:
        await read

    assert not isinstance(ended.value, TypedIOValidationException)
    assert len(caller.calls) == calls
    (audit,) = _audits(executor)
    assert (audit["outcome"], audit["error_message"]) == (outcome, message)
    assert _SECRET_ARGUMENT not in repr(audit)


@pytest.mark.parametrize(
    ("ending", "queue_answers", "events"),
    [
        pytest.param("closed", False, ["rollback", "audit"], id="stopped-at-start"),
        pytest.param("typed", False, ["audit"], id="typed-failure"),
        pytest.param("stopped", True, ["audit", "queued"], id="stopped-while-queued"),
    ],
)
async def test_a_tool_read_releases_the_rows_and_waits_little_for_its_one_audit(
    user, monkeypatch, ending: str, queue_answers: bool, events: list[str]
) -> None:
    # Kills the mutants that audit a read stopped by its closed attempt while
    # the write still holds the run and attempt row locks (no rollback before
    # the audit), that wait for the audit log without a limit after a stop or
    # a typed failure (here its enqueue never returns), and that drop the
    # success record being queued when the read is stopped.
    from eneo.flows.domain.flow_run_exceptions import FlowStepAttemptClosed
    from eneo.flows.runtime import http_audit

    monkeypatch.setattr(http_audit, "READ_AUDIT_TIMEOUT_SECONDS", 0.05)
    facts = _facts()
    caller = _answered() if ending == "typed" else _answered(structured={})
    executor = _tool_executor(user, _Facts(facts), caller)
    if ending == "closed":
        executor.flow_run_repo.write_attempt_tool_call_evidence.return_value = (
            "attempt_closed"
        )
    seen: list[str] = []
    queueing, answered = asyncio.Event(), asyncio.Event()

    async def rollback() -> None:
        seen.append("rollback")

    async def enqueue(**_: object) -> None:
        seen.append("audit")
        queueing.set()
        await answered.wait()
        seen.append("queued")

    executor.session.rollback.side_effect = rollback
    executor.audit_service.log_async.side_effect = enqueue
    read = asyncio.create_task(_read(executor, _tool_step(facts), _running(user)))
    if ending == "stopped":
        await until_task_reaches(queueing, read)
        read.cancel()
    if queue_answers:
        answered.set()

    done, _ = await asyncio.wait({read}, timeout=5)

    assert done == {read}
    if ending == "stopped":
        assert read.cancelled()
    else:
        ended = {"closed": FlowStepAttemptClosed, "typed": TypedIOValidationException}
        assert isinstance(read.exception(), ended[ending])
    assert seen == events


@pytest.mark.parametrize("opens", [True, False], ids=["opened", "cannot-open"])
async def test_a_tool_read_queues_its_audit_with_the_read_audit_service(
    user, opens: bool
) -> None:
    # Kills the mutants that queue a read's audit with the run's own audit
    # service (on the run's database session) instead of the read audit
    # service the worker opens on a session of its own, and that fail an
    # answered read because that service could not be opened.
    from contextlib import asynccontextmanager

    facts = _facts()
    executor = _tool_executor(user, _Facts(facts), _answered(structured={}))
    own = AsyncMock()

    @asynccontextmanager
    async def read_audit_service():
        if not opens:
            raise ConnectionRefusedError("no database connection")
        yield own

    executor.read_audit_service = read_audit_service

    resolution = await _read(executor, _tool_step(facts), _running(user))

    assert resolution.structured == {}
    executor.audit_service.log_async.assert_not_awaited()
    assert own.log_async.await_count == (1 if opens else 0)


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

    async def preflight() -> None:
        await executor._refuse_unusable_tools(
            [step],
            run=run,
            state=state,
            tool_preflight=await executor._tool_preflight([step], run=run, state=state),
        )

    with pytest.raises(TypedIOValidationException) as refused:
        await preflight()
    assert refused.value.code == "typed_io_tool_not_allowed"

    state.completed_by_order[step.step_order] = _result(step_order=step.step_order)
    executor.flow_run_repo.list_completed_tool_answers = AsyncMock(
        return_value={step.step_order: _recorded_answer(None)}
    )
    await preflight()
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

    steps = [third, second, first]
    with pytest.raises(TypedIOValidationException) as refused:
        await executor._refuse_unusable_tools(
            steps,
            run=run,
            state=state,
            tool_preflight=await executor._tool_preflight(steps, run=run, state=state),
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


@pytest.mark.parametrize(
    ("counted", "now", "changed"),
    [
        pytest.param(3, 1, True, id="lowered"),
        pytest.param(1, 3, True, id="raised"),
        pytest.param(3, None, True, id="removed"),
        pytest.param(None, 2, True, id="added"),
        pytest.param(3, 3, False, id="unchanged"),
        pytest.param(None, None, False, id="unclassified-as-counted"),
    ],
)
async def test_the_read_refuses_a_server_whose_level_is_not_the_one_the_run_counted(
    user, counted: int | None, now: int | None, changed: bool
) -> None:
    # Kills the mutants that send the step's arguments to a server whose
    # classification was lowered or removed after the preflight counted it, or
    # read the answer of one that was raised above what the step's model was
    # held to, and the one that leaves the counted level off the answer's
    # evidence edge.
    facts = _facts(
        server={"security_classification": None if now is None else _level(now)}
    )
    caller = _answered({"ok": True})
    executor = _tool_executor(user, _Facts(facts), caller)
    state = replace(_empty_execution_state(), counted_tool_server_levels={2: counted})

    async def read() -> Any:
        return await executor._resolve_step_input(
            step=_tool_step(facts, arguments={"case": _SECRET_ARGUMENT}),
            context={},
            run=_running(user),
            prior_results=[],
            state=state,
        )

    if changed:
        with pytest.raises(TypedIOValidationException) as refused:
            await read()
        assert refused.value.code == "typed_io_tool_classification_changed"
        assert str(refused.value) == (
            "Step 2: the security classification of the tool's server changed "
            "after the run started. Start the run again."
        )
        assert caller.calls == [] and _audits(executor) == []
    else:
        answer_edge = (await read()).edges[-1]
        assert answer_edge.source.server_classification_level == counted
        assert len(caller.calls) == 1


async def test_a_server_unclassified_after_the_preflight_gets_nothing_of_the_run(
    user,
) -> None:
    # Kills the mutant whose preflight does not keep the level it counted: the
    # read would compare with nothing and send step 1's level-3 text to a
    # server whose classification was removed while step 1 ran. Also the
    # mutant that keeps a level while classifications are off.
    counted = _facts(server={"security_classification": _level(3)})
    unclassified = _facts()
    for now, then in (
        (unclassified.server, counted.server),
        (unclassified.tool, counted.tool),
    ):
        assert now is not None and then is not None
        now.id = then.id
    assert unclassified.tool is not None and counted.server is not None
    unclassified.tool.mcp_server_id = counted.server.id
    for enabled in (True, False):
        reader, caller = _Facts(counted), _answered({"ok": True})
        executor = _tool_executor(user, reader, caller)
        executor.security_classification_enabled = enabled
        assistants = [_security_assistant(uuid4(), model_level=3) for _ in range(2)]
        _stub_security_assistants(
            executor,
            _security_space(space_id=uuid4(), assistants=assistants, security_level=3),
        )
        first = replace(_runtime_step(step_order=1), assistant_id=assistants[0].id)
        tool = replace(
            _tool_step(counted, arguments={"case": "{{step_1.output.text}}"}),
            assistant_id=assistants[1].id,
        )
        run, state = _running(user), _empty_execution_state()
        steps = [first, tool]

        await executor._resolve_step_output_levels(
            steps=steps,
            state=state,
            run=run,
            tool_preflight=await executor._tool_preflight(steps, run=run, state=state),
        )
        reader.facts = unclassified
        secret = _result(step_order=1, output_payload={"text": "LEVEL-3 SECRET"})

        async def read() -> Any:
            return await executor._resolve_step_input(
                step=tool, context={}, run=run, prior_results=[secret], state=state
            )

        if enabled:
            assert state.counted_tool_server_levels == {2: 3}
            with pytest.raises(TypedIOValidationException) as refused:
                await read()
            assert refused.value.code == "typed_io_tool_classification_changed"
            assert caller.calls == []
        else:
            assert state.counted_tool_server_levels == {}
            await read()
            assert len(caller.calls) == 1


async def test_the_rule_and_the_decision_of_one_preflight_judge_the_same_read(
    user,
) -> None:
    # Kills the mutant that reads the facts once for the rule and again for
    # the decision: the first read sees a server outside the space (no level
    # to count), the second a level-3 server inside it (allowed), and a run on
    # level-1 models would start with an answer nothing counted.
    stored = _facts(server={"security_classification": _level(3)})
    outside = replace(stored, server_in_space=False)

    class _ChangesAfterTheFirstRead:
        asked = 0

        async def read(self, **_: object) -> UnattendedToolFacts:
            self.asked += 1
            return outside if self.asked == 1 else stored

    executor, flow_run_repo, queued = _execute_setup_for_security(
        user,
        space_level=1,
        model_level=1,
        step_fields={
            "input_source": "tool",
            "input_type": "json",
            "input_config": {"tool": _tool_config(stored)},
        },
    )
    reader = _ChangesAfterTheFirstRead()
    executor.tool_facts_reader, executor.tool_caller = reader, _answered()
    executor.flow_repo.get_space_id = AsyncMock(return_value=_SPACE_ID)

    outcome = await executor.execute(
        run_id=queued.id,
        flow_id=queued.flow_id,
        tenant_id=user.tenant_id,
        run_revision=queued.revision,
        dispatch_task_id="task-1",
        retry_count=0,
    )

    assert outcome == {"status": "failed", "error": "typed_io_tool_not_allowed"}
    assert reader.asked == 1
    flow_run_repo.record_evidence_classification_level.assert_not_awaited()


def _recorded_answer(level: int | None) -> FlowResolvedInputToolAnswerSource:
    """The ``tool_answer`` source a completed tool step recorded at ``level``."""
    return FlowResolvedInputToolAnswerSource(
        kind="tool_answer",
        mcp_server_id=uuid4(),
        tool_id=uuid4(),
        tool_name="lookup_case",
        server_classification_level=level,
        selector=FlowResolvedInputJsonPath(kind="json_path", path=()),
    )


def _resumed_after_a_tool_step(user, changed: dict[str, Any], *, later_model: int):
    """A run taken up again: step 1 read a tool of a level-3 server and is
    completed, step 2 reads step 1 on a model of ``later_model``. The space
    is level 1, and the tool's facts have ``changed`` since the read."""
    then = _facts()
    now = replace(then, **changed)
    reader = _Facts(now)
    executor = _tool_executor(user, reader, _answered())
    assistants = [
        _security_assistant(uuid4(), model_level=level) for level in (3, later_model)
    ]
    _stub_security_assistants(
        executor,
        _security_space(space_id=uuid4(), assistants=assistants, security_level=1),
    )
    tool = replace(_tool_step(then), step_order=1, assistant_id=assistants[0].id)
    later = replace(
        _runtime_step(step_order=2, input_source="previous_step"),
        assistant_id=assistants[1].id,
    )
    state = _empty_execution_state()
    state.completed_by_order[1] = _result(step_order=1)
    executor.flow_run_repo.list_completed_tool_answers = AsyncMock(
        return_value={1: _recorded_answer(3)}
    )
    return executor, reader, [tool, later], state


async def _preflight(executor, steps: list[RuntimeStep], state, run):
    tool_preflight = await executor._tool_preflight(steps, run=run, state=state)
    levels = await executor._resolve_step_output_levels(
        steps=steps, state=state, run=run, tool_preflight=tool_preflight
    )
    await executor._refuse_unusable_tools(
        steps, run=run, state=state, tool_preflight=tool_preflight
    )
    return levels


@pytest.mark.parametrize(
    "now",
    [
        pytest.param({"server_in_space": False}, id="server-removed-from-the-space"),
        pytest.param({"server": None}, id="server-deleted"),
        pytest.param({}, id="classification-removed"),
    ],
)
async def test_a_resumed_run_counts_a_completed_tool_step_at_its_recorded_level(
    user, now: dict[str, Any]
) -> None:
    # Kills the mutant that counts a completed tool step from the server as
    # it is when the run is taken up again: the level-3 answer is already the
    # step's stored input, and the run's evidence level and the requirement
    # of the steps that read it would drop to the space's level 1. Also the
    # mutants that ask the facts or the decision about a step that calls
    # nothing more, or read the recorded level for another run or step.
    executor, reader, steps, state = _resumed_after_a_tool_step(
        user, now, later_model=3
    )
    run = _running(user)

    levels = await _preflight(executor, steps, state, run)

    assert levels == {1: 3, 2: 3}
    assert reader.asked == []
    executor.flow_run_repo.list_completed_tool_answers.assert_awaited_once_with(
        run_id=run.id, tenant_id=run.tenant_id
    )

    executor, _, steps, state = _resumed_after_a_tool_step(user, now, later_model=1)
    with pytest.raises(BadRequestException) as refused:
        await _preflight(executor, steps, state, run)
    assert refused.value.code == "flow_step_security_classification_mismatch"
    assert (refused.value.context or {})["required_level"] == 3


@pytest.mark.parametrize(
    "recorded",
    [
        pytest.param(2, id="server-lowered-after-the-call"),
        pytest.param(None, id="read-while-classifications-were-off"),
    ],
)
async def test_a_resumed_run_is_not_refused_for_what_a_completed_tool_step_sent(
    user, recorded: int | None
) -> None:
    # Kills the mutants that compare what a completed tool step sent with a
    # server level again, the server's as it is now (lowered to 1 after the
    # call) or the recorded one (none, for a read made while classifications
    # were off): the step sends nothing any more, so neither may fail the run
    # that is taken up again.
    lowered = _facts(server={"security_classification": _level(1)})
    reader = _Facts(lowered)
    executor = _tool_executor(user, reader, _answered())
    assistants = [_security_assistant(uuid4(), model_level=2) for _ in range(2)]
    _stub_security_assistants(
        executor,
        _security_space(space_id=uuid4(), assistants=assistants, security_level=2),
    )
    first = replace(_runtime_step(step_order=1), assistant_id=assistants[0].id)
    tool = replace(
        _tool_step(lowered, arguments={"case": "{{step_1.output.text}}"}),
        assistant_id=assistants[1].id,
    )
    state = _empty_execution_state()
    state.completed_by_order.update(
        {order: _result(step_order=order) for order in (1, 2)}
    )
    executor.flow_run_repo.list_completed_tool_answers = AsyncMock(
        return_value={2: _recorded_answer(recorded)}
    )

    levels = await _preflight(executor, [first, tool], state, _running(user))

    assert levels == {1: 2, 2: 2}
    assert reader.asked == []


async def test_a_completed_tool_step_without_its_answer_edge_is_an_invariant_failure(
    user,
) -> None:
    # Kills the mutant that counts a completed tool step whose attempt holds
    # no tool_answer edge as a step without a level: a step cannot complete
    # without that edge, so the run's record is not what the run wrote.
    executor, _, steps, state = _resumed_after_a_tool_step(user, {}, later_model=3)
    executor.flow_run_repo.list_completed_tool_answers = AsyncMock(return_value={})

    with pytest.raises(FlowRuntimeInvariantError):
        await executor._tool_preflight(steps, run=_running(user), state=state)
