from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, create_autospec
from uuid import uuid4

import pytest

from eneo.authentication.principal_types import PrincipalType
from eneo.files.file_models import FileContentVariant, FileType
from eneo.files.file_service import FileService
from eneo.flows.ai_builder.ai_builder_new_step_compiler import compile_new_step_draft
from eneo.flows.ai_builder.ai_builder_new_step_models import NewStepDraft
from eneo.flows.domain.canonical_json_hash import canonical_json_bytes
from eneo.flows.domain.flow import (
    FlowRun,
    FlowRunStatus,
    FlowStep,
    FlowStepResult,
    FlowStepResultStatus,
)
from eneo.flows.domain.runtime import RunExecutionState, RuntimeStep, StepInputValue
from eneo.flows.domain.step_output import build_text_overflow_metadata
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_input_limits import (
    DEFAULT_MAX_AUDIO_FILES_PER_RUN,
    FlowInputLimits,
)
from eneo.flows.flow_validators import validate_steps
from eneo.flows.runtime.http_orchestration import FlowHttpInputResolution
from eneo.flows.runtime.step_definition_parser import parse_runtime_steps
from eneo.flows.runtime.step_execution_runtime import (
    StepExecutionRuntimeDeps,
    prepare_step_execution,
)
from eneo.flows.runtime.step_input_resolution import (
    StepInputResolutionDeps,
    resolve_step_input,
)
from eneo.flows.variable_resolver import FlowVariableResolver
from eneo.main.exceptions import (
    NotFoundException,
    TypedIOValidationException,
    UnauthorizedException,
)
from tests.flow_snapshot_fixtures import assistant_snapshot


def _file_backed_material(text: str, *, step_order: int = 1):
    payload = text.encode("utf-8")
    file_id = uuid4()
    checksum = hashlib.sha256(payload).hexdigest()
    file = SimpleNamespace(
        id=file_id,
        file_type=FileType.TEXT,
        mimetype="text/plain",
        size=len(payload),
        checksum=checksum,
        text=text,
    )
    reference = SimpleNamespace(
        file_id=file_id,
        variant=FileContentVariant.GENERATED_ARTIFACT,
        ordinal=0,
        size_bytes=len(payload),
        sha256=bytes.fromhex(checksum),
    )
    result = _result(
        step_order=step_order,
        output_payload={
            "text": "preview",
            "text_overflow": build_text_overflow_metadata(
                file_ids=[file_id], preview="preview", full_text=text
            ),
        },
    )
    return result, file, reference


@pytest.mark.asyncio
async def test_file_backed_previous_text_is_complete_with_source_identity():
    text = "Hela dokumentet med åäö.\n" * 100
    result, file, reference = _file_backed_material(text)
    deps = replace(_resolution_deps(files=[file]), max_inline_text_bytes=1024)
    deps.file_service.repo.get_content_references.return_value = [reference]
    deps.file_service.get_file_content.return_value = file

    resolved = await resolve_step_input(
        step=_step(step_order=2, input_source="previous_step"),
        context={},
        run=_run(),
        prior_results=[result],
        deps=deps,
    )

    assert resolved.text.encode("utf-8") == text.encode("utf-8")
    assert resolved.source_text == text
    assert resolved.text != "preview"
    material = resolved.materials[0]
    assert material.source_step_id == result.step_id
    assert material.source_attempt_no == result.current_attempt_no
    assert material.file_id == file.id
    assert material.checksum == file.checksum
    assert material.byte_size == len(text.encode("utf-8"))
    assert resolved.edges[0].selection.sha256 == file.checksum
    deps.file_service.get_file_content.assert_awaited_once_with(file.id)


@pytest.mark.parametrize("input_source", ["all_previous_steps", "previous_step"])
@pytest.mark.asyncio
async def test_file_backed_text_is_read_once_per_resolution(input_source):
    text = "Complete material.\n" * 100
    result, file, reference = _file_backed_material(text)
    deps = replace(_resolution_deps(files=[file]), max_inline_text_bytes=1024)
    deps.file_service.repo.get_content_references.return_value = [reference]
    deps.file_service.get_file_content.return_value = file
    bindings = (
        {"question": "{{step_1.output.text}}\n{{step_1.output.text}}"}
        if input_source == "previous_step"
        else None
    )
    state = RunExecutionState(
        completed_by_order={1: result},
        prior_results=[result],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
    )
    for attempt in range(2):
        resolved = await resolve_step_input(
            step=_step(
                step_order=2, input_source=input_source, input_bindings=bindings
            ),
            context={},
            run=_run(),
            prior_results=[result],
            state=state,
            deps=deps,
        )
        expected = (
            f"{text}\n{text}"
            if bindings
            else f"<step_1_output>\n{text}\n</step_1_output>\n"
        )
        assert resolved.text == expected
        assert deps.file_service.get_file_content.await_count == attempt + 1
        assert len(resolved.materials) == 1
        assert result.output_payload_json["text"] == "preview"
        assert state.completed_by_order[1] is result


@pytest.mark.parametrize("missing_at", ["metadata", "read", "unauthorized"])
@pytest.mark.asyncio
async def test_file_backed_text_unavailable_is_typed(missing_at):
    result, file, reference = _file_backed_material("Complete material.\n" * 100)
    deps = _resolution_deps(files=[] if missing_at == "metadata" else [file])
    deps.file_service.repo.get_content_references.return_value = [reference]
    deps.file_service.get_file_content.side_effect = (
        UnauthorizedException("Not owned")
        if missing_at == "unauthorized"
        else NotFoundException("Missing artifact")
    )
    with pytest.raises(TypedIOValidationException) as exc:
        await resolve_step_input(
            step=_step(step_order=2, input_source="previous_step"),
            context={},
            run=_run(),
            prior_results=[result],
            deps=deps,
        )
    assert exc.value.code == FlowApiErrorCode.TYPED_IO_FILE_NOT_FOUND.value
    if missing_at == "metadata":
        deps.file_service.get_file_content.assert_not_awaited()


@pytest.mark.parametrize("corruption", ["size", "checksum", "reference_size"])
@pytest.mark.asyncio
async def test_file_backed_text_integrity_is_verified(corruption):
    result, file, reference = _file_backed_material("Complete material.\n" * 100)
    deps = _resolution_deps(files=[file])
    if corruption == "size":
        file.text = file.text[:-1]
    elif corruption == "checksum":
        file.text = "X" + file.text[1:]
    else:
        reference.size_bytes += 1
    deps.file_service.repo.get_content_references.return_value = [reference]
    deps.file_service.get_file_content.return_value = file
    with pytest.raises(TypedIOValidationException) as exc:
        await resolve_step_input(
            step=_step(step_order=2, input_source="previous_step"),
            context={},
            run=_run(),
            prior_results=[result],
            deps=deps,
        )
    assert exc.value.code == FlowApiErrorCode.TYPED_IO_CONTRACT_VIOLATION.value
    if corruption == "reference_size":
        deps.file_service.get_file_content.assert_not_awaited()


@pytest.mark.asyncio
async def test_aggregate_material_admission_precedes_any_content_read():
    first = _file_backed_material("A" * 600, step_order=1)
    second = _file_backed_material("B" * 600, step_order=2)
    deps = replace(
        _resolution_deps(files=[first[1], second[1]]),
        input_limits=FlowInputLimits(
            file_max_size_bytes=1000, audio_max_size_bytes=1000
        ),
    )
    deps.file_service.repo.get_content_references.return_value = [first[2], second[2]]
    with pytest.raises(TypedIOValidationException) as exc:
        await resolve_step_input(
            step=_step(step_order=3, input_source="all_previous_steps"),
            context={},
            run=_run(),
            prior_results=[first[0], second[0]],
            deps=deps,
        )
    assert exc.value.code == FlowApiErrorCode.RUN_INPUT_EXCEEDS_LIMIT.value
    deps.file_service.get_file_content.assert_not_awaited()


@pytest.mark.asyncio
async def test_material_and_runtime_files_share_processing_admission():
    prior, artifact, reference = _file_backed_material("A" * 600)
    binary = SimpleNamespace(
        id=uuid4(), file_type=FileType.IMAGE, mimetype="image/png", size=600
    )
    deps = replace(
        _resolution_deps(files=[artifact, binary]),
        input_limits=FlowInputLimits(
            file_max_size_bytes=1000, audio_max_size_bytes=1000
        ),
    )
    deps.file_service.repo.get_content_references.return_value = [reference]
    deps.file_service.get_file_content.side_effect = AssertionError(
        "content hydrated before aggregate admission"
    )
    with pytest.raises(TypedIOValidationException) as exc:
        await resolve_step_input(
            step=_step(
                step_order=2,
                input_source="previous_step",
                input_config={
                    "runtime_input": {"enabled": True, "input_format": "document"}
                },
            ),
            context={},
            run=_run(),
            prior_results=[prior],
            requested_file_ids=[binary.id],
            deps=deps,
        )
    assert exc.value.code == FlowApiErrorCode.RUN_INPUT_EXCEEDS_LIMIT.value
    deps.file_service.get_file_content.assert_not_awaited()
    deps.file_service.get_files_by_ids.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "inline_ceiling,expected_code",
    [
        (2000, FlowApiErrorCode.RUN_INPUT_EXCEEDS_LIMIT),
        (400, FlowApiErrorCode.TYPED_IO_INPUT_TOO_LARGE),
    ],
)
async def test_material_admission_counts_inline_prompt_before_hydration(
    inline_ceiling, expected_code
):
    prior, artifact, reference = _file_backed_material("A" * 600)
    deps = replace(
        _resolution_deps(files=[artifact]),
        input_limits=FlowInputLimits(
            file_max_size_bytes=1000, audio_max_size_bytes=1000
        ),
        max_inline_text_bytes=inline_ceiling,
    )
    deps.file_service.repo.get_content_references.return_value = [reference]
    deps.file_service.get_file_content.side_effect = AssertionError(
        "content hydrated before aggregate admission"
    )
    with pytest.raises(TypedIOValidationException) as exc:
        await resolve_step_input(
            step=_step(step_order=2, input_source="previous_step"),
            prompt_template="P" * 500,
            context={},
            run=_run(),
            prior_results=[prior],
            deps=deps,
        )
    assert exc.value.code == expected_code.value
    deps.file_service.get_file_content.assert_not_awaited()


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
    files: list[object] | None = None,
) -> StepInputResolutionDeps:
    file_service = create_autospec(FileService, instance=True)
    file_service.get_files_by_ids.return_value = files or []
    file_service.get_owned_file_infos.return_value = files or []
    file_service.repo = AsyncMock()
    file_service.repo.get_content_references.return_value = []
    run_repo = AsyncMock()
    run_repo.list_step_results.return_value = []
    run_repo.list_retained_input_file_ids.return_value = []
    return StepInputResolutionDeps(
        apply_output_cap=AsyncMock(side_effect=lambda **kw: (kw["text"], [])),
        variable_resolver=FlowVariableResolver(),
        resolve_http_input_source_text=AsyncMock(
            return_value=FlowHttpInputResolution(
                text="",
                structured=None,
                resolved_input_edges=(),
            )
        ),
        file_service=file_service,
        transcriber=None,
        space_repo=object(),
        flow_run_repo=run_repo,
        audit_service=None,
        actor=None,
        max_generic_files=None,
        max_audio_files=DEFAULT_MAX_AUDIO_FILES_PER_RUN,
        max_inline_text_bytes=1024 * 1024,
        input_limits=FlowInputLimits(
            file_max_size_bytes=100_000_000, audio_max_size_bytes=100_000_000
        ),
        logger=MagicMock(),
    )


def _publish_step(step: RuntimeStep) -> FlowStep:
    return FlowStep(
        id=step.step_id,
        assistant_id=step.assistant_id,
        step_order=step.step_order,
        user_description=step.user_description,
        input_source=step.input_source,
        input_type=step.input_type,
        input_contract=step.input_contract,
        output_mode=step.output_mode,
        output_type=step.output_type,
        output_contract=step.output_contract,
        input_bindings=step.input_bindings,
        input_config=step.input_config,
        output_config=step.output_config,
        review_policy=step.review_policy,
        timeout_seconds=step.timeout_seconds,
    )


def _depth_four_output_contract() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "documents": {
                "type": "array",
                "title": "Documents",
                "description": "Source documents.",
                "items": {
                    "type": "object",
                    "properties": {
                        "group": {
                            "type": "object",
                            "title": "Group",
                            "description": "A source group.",
                            "properties": {
                                "entries": {
                                    "type": "array",
                                    "title": "Entries",
                                    "description": "Grouped entries.",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "leaf": {
                                                "type": "string",
                                                "title": "Leaf",
                                                "description": "Captured detail.",
                                            }
                                        },
                                        "additionalProperties": False,
                                        "required": ["leaf"],
                                    },
                                }
                            },
                            "additionalProperties": False,
                            "required": ["entries"],
                        }
                    },
                    "additionalProperties": False,
                    "required": ["group"],
                },
            }
        },
        "additionalProperties": False,
        "required": ["documents"],
    }


def _depth_four_runtime_steps(
    output_contract: dict[str, object],
) -> list[RuntimeStep]:
    properties = output_contract["properties"]
    assert isinstance(properties, dict)
    documents_contract = properties["documents"]
    assert isinstance(documents_contract, dict)
    assistant_id = uuid4()
    return parse_runtime_steps(
        {
            "steps": [
                {
                    "step_id": str(uuid4()),
                    "step_order": 1,
                    "assistant_id": str(assistant_id),
                    "assistant_snapshot": assistant_snapshot(assistant_id),
                    "plan_step_ref": "step_1",
                    "input_source": "flow_input",
                    "input_type": "text",
                    "output_mode": "pass_through",
                    "output_type": "json",
                    "output_contract": output_contract,
                },
                {
                    "step_id": str(uuid4()),
                    "step_order": 2,
                    "assistant_id": str(assistant_id),
                    "assistant_snapshot": assistant_snapshot(assistant_id),
                    "input_source": "previous_step",
                    "input_type": "json",
                    "input_bindings": {
                        "source_refs": [
                            {
                                "step_ref": "step_1",
                                "output": "structured",
                                "field_path": "documents",
                            }
                        ]
                    },
                    "input_contract": {
                        "type": "object",
                        "properties": {"documents": documents_contract},
                        "required": ["documents"],
                        "additionalProperties": False,
                    },
                    "output_mode": "pass_through",
                    "output_type": "text",
                },
                {
                    "step_id": str(uuid4()),
                    "step_order": 3,
                    "assistant_id": str(assistant_id),
                    "assistant_snapshot": assistant_snapshot(assistant_id),
                    "input_source": "previous_step",
                    "input_type": "text",
                    "input_bindings": {
                        "source_refs": [{"step_ref": "step_1", "output": "structured"}]
                    },
                    "output_mode": "pass_through",
                    "output_type": "text",
                },
            ]
        }
    )


def test_compiler_emits_publishable_depth_four_contract() -> None:
    producer = compile_new_step_draft(
        step_draft=NewStepDraft.model_validate(
            {
                "name": "Group source material",
                "instructions": "Group the source material.",
                "output_type": "json",
                "output_fields": [
                    {
                        "name": "documents",
                        "field_type": "array",
                        "description": "Source documents.",
                        "item_fields": [
                            {
                                "name": "group",
                                "field_type": "object",
                                "description": "A source group.",
                                "fields": [
                                    {
                                        "name": "entries",
                                        "field_type": "array",
                                        "description": "Grouped entries.",
                                        "item_fields": [
                                            {
                                                "name": "leaf",
                                                "field_type": "string",
                                                "description": "Captured detail.",
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ),
        plan_step_ref="step_1",
        prior_steps=[],
    )

    assert producer.output_contract == _depth_four_output_contract()
    runtime_steps = _depth_four_runtime_steps(producer.output_contract)
    validate_steps(
        [_publish_step(step) for step in runtime_steps],
        require_complete_template_fill_config=True,
    )


@pytest.mark.asyncio
async def test_depth_four_structured_output_survives_publish_and_source_refs() -> None:
    output_contract = _depth_four_output_contract()
    runtime_steps = _depth_four_runtime_steps(output_contract)
    validate_steps(
        [_publish_step(step) for step in runtime_steps],
        require_complete_template_fill_config=True,
    )
    assert runtime_steps[0].output_contract == output_contract

    payload = {
        "documents": [{"group": {"entries": [{"leaf": "Captured municipal detail"}]}}]
    }
    prior = _result(output_payload={"structured": payload})
    run = _run()

    documents = await resolve_step_input(
        step=runtime_steps[1],
        context={},
        run=run,
        prior_results=[prior],
        deps=_resolution_deps(),
    )
    assert documents.structured == payload
    assert json.loads(documents.text) == payload

    whole = await resolve_step_input(
        step=runtime_steps[2],
        context={},
        run=run,
        prior_results=[prior],
        deps=_resolution_deps(),
    )
    assert json.loads(whole.text) == payload

    crossing_step = replace(
        runtime_steps[1],
        input_bindings={
            "source_refs": [
                {
                    "step_ref": "step_1",
                    "output": "structured",
                    "field_path": "documents.group",
                }
            ]
        },
    )
    with pytest.raises(TypedIOValidationException, match="object value"):
        await resolve_step_input(
            step=crossing_step,
            context={},
            run=run,
            prior_results=[prior],
            deps=_resolution_deps(),
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
        deps=_resolution_deps(),
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
        deps=_resolution_deps(),
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
        deps=_resolution_deps(),
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
        deps=_resolution_deps(),
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
        deps=_resolution_deps(files=[runtime_file]),
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
        max_inline_text_bytes=1_000_000,
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


@pytest.mark.asyncio
async def test_followup_writer_source_refs_deliver_narrative_and_extraction() -> None:
    # The compiler binds a terminal writer after an inserted follow-up
    # extraction step to BOTH sources via text source_refs. Compiled refs are
    # only half the proof: this pins the runtime boundary where source_refs
    # lower to an effective question and interpolate both materials.
    run = _run()
    narrative = _result(
        step_order=1,
        output_payload={"text": "Lättläst transkript av mötet."},
    )
    extraction = _result(
        step_order=2,
        output_payload={
            "text": '{"decisions": ["Beslut 1"], "actions": ["Åtgärd 1"]}',
            "structured": {"decisions": ["Beslut 1"], "actions": ["Åtgärd 1"]},
        },
    )

    resolved = await resolve_step_input(
        step=_step(
            step_order=3,
            input_source="previous_step",
            input_bindings={
                "source_refs": [
                    {
                        "step_ref": "step_1",
                        "output": "text",
                        "label": "Lättläst transkript",
                    },
                    {
                        "step_ref": "step_2",
                        "output": "text",
                        "label": "Uppföljningspunkter",
                    },
                ]
            },
        ),
        context={},
        run=run,
        prior_results=[narrative, extraction],
        deps=_resolution_deps(),
    )

    assert "Lättläst transkript av mötet." in resolved.text
    assert '"decisions"' in resolved.text
    step_result_sources = {
        edge.source.source_step_id
        for edge in resolved.edges
        if edge.source.kind == "step_result"
    }
    assert step_result_sources == {narrative.step_id, extraction.step_id}
