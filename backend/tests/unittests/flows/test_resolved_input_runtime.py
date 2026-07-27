from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.authentication.principal_types import PrincipalType
from eneo.flows.domain.canonical_json_hash import canonical_json_bytes
from eneo.flows.domain.flow import (
    FlowRun,
    FlowRunStatus,
    FlowStepResult,
    FlowStepResultStatus,
)
from eneo.flows.domain.runtime import RunExecutionState, RuntimeStep, StepInputValue
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.principal import FlowPrincipal
from eneo.flows.runtime.http_orchestration import FlowHttpInputResolution
from eneo.flows.runtime.step_execution_runtime import (
    StepExecutionRuntimeDeps,
    prepare_step_execution,
)
from eneo.flows.runtime.step_input_resolution import (
    StepInputResolutionDeps,
    resolve_step_input,
)
from eneo.flows.variable_resolver import FlowVariableResolver
from eneo.main.exceptions import TypedIOValidationException


def _result(
    *,
    step_order: int = 1,
    attempt_no: int | None = 2,
    output_payload: dict[str, object] | None = None,
) -> FlowStepResult:
    now = datetime.now(timezone.utc)
    return FlowStepResult(
        id=uuid4(),
        flow_run_id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        step_id=uuid4(),
        step_order=step_order,
        assistant_id=uuid4(),
        current_attempt_no=attempt_no,
        input_payload_json=None,
        effective_prompt="",
        output_payload_json=output_payload or {"text": "resolved result"},
        model_parameters_json={},
        num_tokens_input=1,
        num_tokens_output=1,
        status=FlowStepResultStatus.COMPLETED,
        flow_step_execution_hash="hash",
        created_at=now,
        updated_at=now,
    )


def _run(input_payload: dict[str, object] | None = None) -> FlowRun:
    now = datetime.now(timezone.utc)
    user_id = uuid4()
    return FlowRun(
        id=uuid4(),
        flow_id=uuid4(),
        flow_version=1,
        principal_type=PrincipalType.USER,
        principal_user_id=user_id,
        tenant_id=uuid4(),
        trace_id=uuid4(),
        status=FlowRunStatus.RUNNING,
        input_payload_json=input_payload or {},
        created_at=now,
        updated_at=now,
    )


def _step(
    *,
    step_order: int,
    input_source: str,
    input_bindings: dict[str, object] | None = None,
    input_config: dict[str, object] | None = None,
    input_type: str = "text",
    output_mode: str = "pass_through",
) -> RuntimeStep:
    return RuntimeStep(
        step_id=uuid4(),
        step_order=step_order,
        assistant_id=uuid4(),
        user_description=None,
        input_source=input_source,
        input_bindings=input_bindings,
        input_config=input_config,
        output_mode=output_mode,
        output_config=None,
        input_type=input_type,
    )


def _resolution_deps(
    *,
    run: FlowRun,
    files: list[object] | None = None,
) -> StepInputResolutionDeps:
    return StepInputResolutionDeps(
        variable_resolver=FlowVariableResolver(),
        resolve_http_input_source_text=AsyncMock(
            return_value=FlowHttpInputResolution(
                text="",
                structured=None,
                resolved_input_edges=(),
            )
        ),
        file_repo=SimpleNamespace(
            get_list_by_id_for_owner=AsyncMock(return_value=files or [])
        ),
        principal=FlowPrincipal.from_run(run),
        transcriber=None,
        space_repo=object(),
        flow_run_repo=object(),
        audit_service=None,
        actor=None,
        max_generic_files=None,
        max_audio_files=None,
        max_inline_text_bytes=1024 * 1024,
        logger=MagicMock(),
    )


def test_aliases_record_the_same_flow_input_selection() -> None:
    resolver = FlowVariableResolver()
    context = resolver.build_context_with_evidence(
        {"case_id": "räksmörgås"},
        [],
    )

    bare = resolver.interpolate_with_evidence(
        "{{ case_id }}",
        context,
        binding_ref="input_bindings.question",
    )
    namespaced = resolver.interpolate_with_evidence(
        "{{ flow_input.case_id }}",
        context,
        binding_ref="input_bindings.question",
    )

    assert bare.text == namespaced.text == "räksmörgås"
    assert len(bare.edges) == len(namespaced.edges) == 1
    bare_edge = bare.edges[0]
    namespaced_edge = namespaced.edges[0]
    assert bare_edge.source == namespaced_edge.source
    assert bare_edge.selection == namespaced_edge.selection
    assert bare_edge.source.kind == "flow_input"
    assert bare_edge.source.selector.path == ("case_id",)
    expected = "räksmörgås".encode("utf-8")
    assert bare_edge.selection.encoding == "utf8"
    assert bare_edge.selection.byte_size == len(expected)
    assert bare_edge.selection.sha256 == hashlib.sha256(expected).hexdigest()


def test_consumed_step_result_records_exact_attempt_and_numeric_path() -> None:
    prior = _result(output_payload={"structured": {"rows": [{"title": "A"}]}})
    resolver = FlowVariableResolver()
    context = resolver.build_context_with_evidence({}, [prior])

    resolved = resolver.interpolate_with_evidence(
        "{{ step_1.output.structured.rows.0.title }}",
        context,
        binding_ref="assistant_prompt",
    )

    assert resolved.text == "A"
    edge = resolved.edges[0]
    assert edge.source.kind == "step_result"
    assert edge.source.source_step_id == prior.step_id
    assert edge.source.source_attempt_no == 2
    assert edge.source.selector.path == ("output", "structured", "rows", 0, "title")


def test_only_consumed_step_result_requires_attempt_identity() -> None:
    prior = _result(attempt_no=None)
    resolver = FlowVariableResolver()
    context = resolver.build_context_with_evidence({"case_id": "A"}, [prior])

    unrelated = resolver.interpolate_with_evidence(
        "{{ flow_input.case_id }}",
        context,
        binding_ref="assistant_prompt",
    )
    assert unrelated.text == "A"

    with pytest.raises(TypedIOValidationException) as exc_info:
        resolver.interpolate_with_evidence(
            "{{ step_1.output.text }}",
            context,
            binding_ref="assistant_prompt",
        )

    assert exc_info.value.code == FlowApiErrorCode.TYPED_IO_CONTRACT_VIOLATION.value


def test_system_value_and_structured_selection_use_distinct_hash_encodings() -> None:
    resolver = FlowVariableResolver()
    context = resolver.build_context_with_evidence(
        {"payload": {"b": 2, "a": 1}},
        [],
    )

    system = resolver.interpolate_with_evidence(
        "{{ datum }}",
        context,
        binding_ref="assistant_prompt",
    )
    structured = resolver.interpolate_with_evidence(
        "{{ flow_input.payload }}",
        context,
        binding_ref="assistant_prompt",
    )

    assert system.edges[0].source.kind == "system_value"
    assert system.edges[0].source.name == "datum"
    expected = canonical_json_bytes({"b": 2, "a": 1})
    assert structured.edges[0].selection.encoding == "canonical_json"
    assert structured.edges[0].selection.byte_size == len(expected)
    assert structured.edges[0].selection.sha256 == hashlib.sha256(expected).hexdigest()


def test_current_step_metadata_is_a_runtime_input_source() -> None:
    resolver = FlowVariableResolver()
    context = resolver.build_context_with_evidence(
        {},
        [],
        current_step_order=1,
        current_step_input={"files": [{"checksum": "opaque"}]},
    )

    resolved = resolver.interpolate_with_evidence(
        "{{ step_input.files.0.checksum }}",
        context,
        binding_ref="input_bindings.question",
    )

    assert resolved.text == "opaque"
    assert resolved.edges[0].source.kind == "runtime_input"
    assert resolved.edges[0].source.selector.path == ("files", 0, "checksum")


@pytest.mark.asyncio
async def test_explicit_question_discards_replaced_implicit_previous_step() -> None:
    run = _run({"case_id": "A-17"})
    prior = _result(output_payload={"text": "must not be selected"})

    resolved = await resolve_step_input(
        step=_step(
            step_order=2,
            input_source="previous_step",
            input_bindings={"question": "Case {{ flow_input.case_id }}"},
        ),
        context={},
        run=run,
        prior_results=[prior],
        deps=_resolution_deps(run=run),
    )

    assert resolved.text == "Case A-17"
    assert len(resolved.edges) == 1
    assert resolved.edges[0].source.kind == "flow_input"


@pytest.mark.asyncio
async def test_implicit_previous_step_records_exact_current_attempt() -> None:
    run = _run()
    prior = _result(attempt_no=4, output_payload={"text": "actual rerun output"})

    resolved = await resolve_step_input(
        step=_step(step_order=2, input_source="previous_step"),
        context={},
        run=run,
        prior_results=[prior],
        deps=_resolution_deps(run=run),
    )

    assert resolved.text == "actual rerun output"
    assert len(resolved.edges) == 1
    edge = resolved.edges[0]
    assert edge.source.kind == "step_result"
    assert edge.source.source_step_id == prior.step_id
    assert edge.source.source_attempt_no == 4
    assert edge.source.selector.path == ("output", "text")


@pytest.mark.asyncio
async def test_parsed_json_text_keeps_the_actual_step_text_source() -> None:
    run = _run()
    prior = _result(
        attempt_no=4,
        output_payload={"text": '{"decision":"Approve"}'},
    )

    resolved = await resolve_step_input(
        step=_step(step_order=2, input_source="previous_step", input_type="json"),
        context={},
        run=run,
        prior_results=[prior],
        deps=_resolution_deps(run=run),
    )

    assert resolved.structured == {"decision": "Approve"}
    assert len(resolved.edges) == 1
    assert resolved.edges[0].source.kind == "step_result"
    assert resolved.edges[0].source.selector.path == ("output", "text")
    assert resolved.edges[0].selection.encoding == "utf8"


@pytest.mark.asyncio
async def test_compose_source_ref_records_the_selected_structured_field() -> None:
    run = _run()
    prior = _result(
        attempt_no=5,
        output_payload={"structured": {"decision": {"label": "Approve"}}},
    )

    resolved = await resolve_step_input(
        step=_step(
            step_order=2,
            input_source="previous_step",
            output_mode="compose_text",
            input_bindings={
                "source_refs": [
                    {
                        "step_ref": "step_1",
                        "output": "structured",
                        "field_path": "decision.label",
                    }
                ]
            },
        ),
        context={},
        run=run,
        prior_results=[prior],
        deps=_resolution_deps(run=run),
    )

    assert resolved.text == "Approve"
    assert len(resolved.edges) == 1
    edge = resolved.edges[0]
    assert edge.source.kind == "step_result"
    assert edge.source.source_attempt_no == 5
    assert edge.source.selector.path == (
        "output",
        "structured",
        "decision",
        "label",
    )


@pytest.mark.asyncio
async def test_runtime_file_edge_contains_opaque_identity_without_content() -> None:
    run = _run()
    file_id = uuid4()
    runtime_file = SimpleNamespace(
        id=file_id,
        checksum="opaque-checksum-token",
        size=321,
        name="source.txt",
        text="highly sensitive source content",
        mimetype="text/plain",
        file_type="text",
        transcription=None,
    )

    resolved = await resolve_step_input(
        step=_step(
            step_order=1,
            input_source="flow_input",
            input_config={
                "runtime_input": {"enabled": True, "input_format": "document"}
            },
            input_type="document",
        ),
        context={},
        run=run,
        prior_results=[],
        requested_file_ids=[file_id],
        deps=_resolution_deps(run=run, files=[runtime_file]),
    )

    file_edges = [edge for edge in resolved.edges if edge.source.kind == "runtime_file"]
    assert len(file_edges) == 1
    file_source = file_edges[0].source
    assert file_source.input_file_ordinal == 0
    assert file_source.file_id == file_id
    assert file_source.checksum == "opaque-checksum-token"
    assert file_source.byte_size == 321
    assert "sensitive" not in str(file_edges[0].model_dump(mode="json"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("prompt", "expected_edge_count"),
    [("Review {{ flow_input.case_id }}", 1), ("Review the supplied case", 0)],
)
async def test_prepared_execution_adds_only_actual_prompt_substitutions(
    prompt: str,
    expected_edge_count: int,
) -> None:
    run = _run({"case_id": "A-17"})
    step = _step(step_order=1, input_source="flow_input")
    assistant = MagicMock()
    assistant.get_prompt_text.return_value = prompt
    deps = StepExecutionRuntimeDeps(
        variable_resolver=FlowVariableResolver(),
        completion_service=object(),
        load_assistant=AsyncMock(return_value=assistant),
        resolve_step_input=AsyncMock(
            return_value=StepInputValue(
                text="A-17", source_text="A-17", input_source="flow_input"
            )
        ),
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

    prepared = await prepare_step_execution(
        step=step,
        run=run,
        state=state,
        version_metadata=None,
        requested_file_ids=(),
        deps=deps,
    )

    assert len(prepared.resolved_input_edges) == expected_edge_count
    if expected_edge_count:
        assert prepared.resolved_input_edges[0].source.kind == "flow_input"
