from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from eneo.completion_models.domain.model_capacity import ModelCapacity
from eneo.flows.domain.flow import FlowRunStatus
from eneo.flows.domain.mapped_execution_policy import FlowMappedExecutionPolicy
from eneo.flows.domain.runtime import RunExecutionState
from eneo.flows.domain.text_processing import SectionManifest
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_run_error import FlowRunErrorDetails
from eneo.flows.runtime.step_deadline import current_step_deadline_scope
from eneo.flows.runtime.step_execution_runtime import build_output_payload
from eneo.flows.runtime.step_handlers.text_sections import (
    prepare_text_processing_call,
    prepare_text_sections,
)
from eneo.main.exceptions import (
    ProviderRejectedRequestException,
    TypedIOValidationException,
)
from eneo.tenants.tenant import TenantInDB
from eneo.users.user import UserInDB
from tests.unittests.flows.test_resolved_input_runtime import _file_backed_material
from tests.unittests.flows.test_typed_io_executor import (
    _build_executor,
    _completed_step_result,
    _context_preflight,
    _mock_assistant_for_execute_step,
    _run,
    _runtime_step,
)


def _case(
    user,
    *,
    prompt="Extract a record.",
    output_size=0,
    fail_at=None,
    failure=None,
    text=None,
    inline=False,
):
    executor, _, run_repo, _ = _build_executor(
        user, max_inline_text_bytes=8 * 1024 * 1024 if inline else 2048
    )
    if text is None:
        text = "".join(f"Å municipal material {index}.\n\t" for index in range(150))
    material, file, reference = _file_backed_material(text)
    if inline:
        material = material.model_copy(update={"output_payload_json": {"text": text}})
    executor.file_service.get_owned_file_infos.side_effect = None
    executor.file_service.get_owned_file_infos.return_value = [file]
    executor.file_service.repo.get_content_references.return_value = [reference]
    executor.file_service.get_file_content.return_value = file
    assistant = _mock_assistant_for_execute_step()
    assistant.has_knowledge.return_value = False
    assistant.get_prompt_text.return_value = prompt
    executor._load_assistant = AsyncMock(return_value=assistant)
    questions = []
    progress = []

    async def preflight(**kwargs):
        measured = (
            len(kwargs["question"].encode())
            + len(kwargs["prompt_override"].encode())
            + 37
        )
        preview = _context_preflight(measured)
        package = replace(preview.preferred, output_cap_tokens=1300 - measured)
        return replace(
            preview,
            capacity=ModelCapacity(1300, 1300),
            preferred=package,
            fallback=package,
            refusal=None if package.fits else "current_request_input_does_not_fit",
        )

    async def respond(**kwargs):
        scope = current_step_deadline_scope()
        progress.append((scope.completed_items, scope.total_items))
        questions.append(kwargs["question"])
        if len(questions) == fail_at:
            if failure is not None:
                raise failure
            raise TypedIOValidationException(
                "Section rejected",
                code=FlowApiErrorCode.TYPED_IO_CONTRACT_VIOLATION.value,
            )
        return SimpleNamespace(
            completion=json.dumps(
                {"records": [{"value": str(len(questions)) + "x" * output_size}]}
            ),
            total_token_count=3,
        )

    assistant.preflight_response_context = AsyncMock(side_effect=preflight)
    assistant.get_response = AsyncMock(side_effect=respond)
    run = _run(status=FlowRunStatus.RUNNING, user=user, input_payload={})
    state = RunExecutionState(
        completed_by_order={1: material},
        prior_results=[material],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
    )
    step = _runtime_step(
        step_order=2,
        input_source="previous_step",
        input_type="text",
        output_type="json",
        input_config={"text_processing": {"mode": "process_each_section"}},
        output_contract={
            "type": "object",
            "properties": {
                "records": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"value": {"type": "string"}},
                        "required": ["value"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["records"],
            "additionalProperties": False,
        },
    )
    return (
        executor,
        run_repo,
        assistant,
        run,
        state,
        step,
        text,
        file,
        questions,
        progress,
    )


async def test_sections_use_measured_packages_and_persist_order_and_provenance(user):
    executor, run_repo, assistant, run, state, step, text, file, questions, progress = (
        _case(user)
    )
    result = await executor._execute_step(step=step, run=run, state=state, attempt_no=1)

    assert len(questions) > 1
    assert "".join(questions) == text
    assert result.output.structured_output == {
        "records": [{"value": str(i)} for i in range(1, len(questions) + 1)]
    }
    manifest = SectionManifest.model_validate(
        result.output.output_payload_extensions["section_manifest"]
    )
    assert manifest.resplit(text) == tuple(questions)
    assert manifest.sources[0].file_id == file.id
    assert manifest.sources[0].checksum == file.checksum
    assert manifest.sources[0].source_step_id == state.prior_results[0].step_id
    assert (
        manifest.sources[0].source_attempt_no
        == state.prior_results[0].current_attempt_no
    )
    assert [s.output_index for s in manifest.sections] == list(range(len(questions)))
    assert progress == [(i, len(questions)) for i in range(len(questions))]
    assert build_output_payload(result.output)[
        "section_manifest"
    ] == manifest.model_dump(mode="json")
    assert executor.file_service.get_file_content.await_count == 1
    assert run_repo.activate_step_attempt.await_count == 1
    for call in assistant.get_response.await_args_list:
        package = call.kwargs["prepared_request"]
        assert package.fits


async def test_longer_prompt_reduces_section_size(user):
    sizes = []
    for prompt in ("Extract a record.", "Extract a record. " * 20):
        executor, _, _, run, state, step, _, _, questions, _ = _case(
            user, prompt=prompt
        )
        await executor._execute_step(step=step, run=run, state=state, attempt_no=1)
        sizes.append(max(len(question.encode()) for question in questions))
    assert sizes[1] < sizes[0]


@pytest.mark.parametrize("inline", [False, True])
async def test_prompt_only_material_preserves_independent_flow_input_question(
    user, inline
):
    executor, _, assistant, run, state, step, text, _, questions, _ = _case(
        user, prompt="Material:\n{{step_1.output.text}}\nDone.", inline=inline
    )
    instruction = "ONLY INCLUDE RECORDS ABOUT SCHOOLS"
    run = run.model_copy(update={"input_payload_json": {"text": instruction}})
    step = replace(step, input_source="flow_input")

    result = await executor._execute_step(step=step, run=run, state=state, attempt_no=1)

    manifest = SectionManifest.model_validate(
        result.output.output_payload_extensions["section_manifest"]
    )
    sections = manifest.resplit(text)
    assert len(sections) > 1
    for section, question, call in zip(
        sections, questions, assistant.get_response.await_args_list, strict=True
    ):
        assert question == instruction
        assert call.kwargs["prompt_override"].split("\nDone.")[0] == (
            "Material:\n" + section
        )


async def test_section_preparation_keeps_selected_text_for_json_consumer(user):
    text = '{"report": "A plain text report encoded as JSON."}'
    executor, _, _, run, state, step, _, _, _, _ = _case(user, text=text)
    step = replace(step, input_type="json")
    base = await executor._preview_assistant_step(
        step=step, run=run, state=state, version_metadata=None, attempt_no=1
    )

    prepared, _ = await prepare_text_processing_call(
        step=step,
        run=run,
        state=state,
        base=base,
        section_text="SLICE",
    )

    assert prepared.prepared.step_input.text == "SLICE"


@pytest.mark.parametrize("input_type", ["text", "json"])
@pytest.mark.parametrize("binding", [None, "{{step_1.output.text}}"])
@pytest.mark.parametrize("structured", [{"records": []}, []])
async def test_sections_refuse_structured_upstream_before_preparation(
    user, input_type, binding, structured
):
    executor, _, assistant, run, state, step, _, _, _, _ = _case(user, inline=True)
    source = state.prior_results[0]
    source.output_payload_json["structured"] = structured
    step = replace(
        step,
        input_type=input_type,
        input_bindings={"question": binding} if binding else None,
    )
    with pytest.raises(TypedIOValidationException) as caught:
        await executor._execute_step(step=step, run=run, state=state, attempt_no=1)
    assert (
        caught.value.code
        == FlowApiErrorCode.TYPED_IO_INVALID_INPUT_SOURCE_COMBINATION.value
    )
    assert "structured" in str(caught.value)
    assistant.preflight_response_context.assert_not_awaited()
    assistant.get_response.assert_not_awaited()


@pytest.mark.parametrize("input_type", ["text", "json"])
async def test_json_looking_inline_text_sections_preserve_implicit_source(
    user, input_type
):
    text = json.dumps({"report": "Municipal records. " * 200})
    executor, _, _, run, state, step, _, _, questions, _ = _case(
        user, text=text, inline=True
    )
    step = replace(step, input_type=input_type)
    result = await executor._execute_step(step=step, run=run, state=state, attempt_no=1)
    manifest = SectionManifest.model_validate(
        result.output.output_payload_extensions["section_manifest"]
    )
    assert 1300 < len(text.encode()) < 8 * 1024 * 1024
    assert len(questions) > 1
    assert tuple(questions) == manifest.resplit(text)


async def test_sections_refuse_older_transcript_with_explained_cause(user):
    executor, _, assistant, run, state, step, text, _, _, _ = _case(user, inline=True)
    run.input_payload_json = {"transkribering": text}
    step = replace(step, input_bindings={"question": "{{transkribering}}"})

    with pytest.raises(TypedIOValidationException) as caught:
        await executor._execute_step(step=step, run=run, state=state, attempt_no=1)

    assert (
        caught.value.code
        == FlowApiErrorCode.TYPED_IO_INVALID_INPUT_SOURCE_COMBINATION.value
    )
    assert "transcript predates the current format" in str(caught.value)
    assistant.preflight_response_context.assert_not_awaited()
    assistant.get_response.assert_not_awaited()


async def test_raw_inline_transcript_after_structured_completion_stays_text(user):
    from eneo.flows.domain.step_output import inline_transcript

    text = "Raw transcript. " * 200
    executor, _, _, run, state, step, _, _, questions, _ = _case(
        user, text=text, inline=True
    )
    source = state.prior_results[0]
    run.input_payload_json = {
        "transkribering": inline_transcript(
            text=text,
            source_step_id=source.step_id,
            source_attempt_no=source.current_attempt_no,
        ).model_dump(mode="json")
    }
    source.output_payload_json = {
        "text": "Transformed completion",
        "structured": {"summary": "Transformed"},
    }
    step = replace(step, input_bindings={"question": "{{transkribering}}"})
    result = await executor._execute_step(step=step, run=run, state=state, attempt_no=1)
    manifest = SectionManifest.model_validate(
        result.output.output_payload_extensions["section_manifest"]
    )
    assert tuple(questions) == manifest.resplit(text)
    assert manifest.sources[0].selector.path == ("input", "text")


@pytest.mark.parametrize("source_count", [0, 2])
async def test_sections_refuse_zero_or_distinct_identical_inline_sources(
    user, source_count
):
    executor, _, assistant, run, state, step, text, _, _, _ = _case(user, inline=True)
    if source_count == 0:
        state.prior_results.clear()
        state.completed_by_order.clear()
    else:
        second = state.prior_results[0].model_copy(
            update={"step_id": uuid4(), "step_order": 2}
        )
        state.prior_results.append(second)
        state.completed_by_order[2] = second
        step = replace(step, step_order=3, input_source="all_previous_steps")
    with pytest.raises(TypedIOValidationException) as caught:
        await executor._execute_step(step=step, run=run, state=state, attempt_no=1)
    assert (
        caught.value.code
        == FlowApiErrorCode.TYPED_IO_INVALID_INPUT_SOURCE_COMBINATION.value
    )
    assert str(caught.value) == "Section processing requires exactly one material."
    assistant.get_response.assert_not_awaited()


async def test_sections_refuse_knowledge_before_preflight_or_provider_calls(user):
    executor, run_repo, assistant, run, state, step, _, _, _, _ = _case(user)
    assistant.has_knowledge.return_value = True
    executor._retrieve_rag_chunks = AsyncMock(return_value=([], None, []))

    with pytest.raises(TypedIOValidationException) as exc_info:
        await executor._execute_step(step=step, run=run, state=state, attempt_no=1)

    assert (
        exc_info.value.code
        == FlowApiErrorCode.TYPED_IO_INVALID_INPUT_SOURCE_COMBINATION.value
    )
    executor._retrieve_rag_chunks.assert_not_awaited()
    assistant.preflight_response_context.assert_not_awaited()
    assistant.get_response.assert_not_awaited()
    run_repo.activate_step_attempt.assert_not_awaited()


async def test_failing_section_reports_completed_and_total_sections(user):
    executor, _, _, run, state, step, _, _, questions, progress = _case(user, fail_at=2)
    with pytest.raises(TypedIOValidationException) as exc_info:
        await executor._execute_step(step=step, run=run, state=state, attempt_no=1)
    assert len(questions) == 2
    details = FlowRunErrorDetails.from_budget_context(exc_info.value.context)
    assert details.completed_items == 1
    assert details.total_items == progress[0][1]
    assert details.total_items > 1


async def test_section_aggregate_overflow_stops_before_the_next_call(user):
    executor, _, _, run, state, step, _, _, questions, progress = _case(
        user, output_size=500
    )
    with pytest.raises(TypedIOValidationException) as exc_info:
        await executor._execute_step(step=step, run=run, state=state, attempt_no=1)
    assert (
        exc_info.value.code
        == FlowApiErrorCode.TYPED_IO_STRUCTURED_OUTPUT_EXCEEDS_LIMIT.value
    )
    details = FlowRunErrorDetails.from_budget_context(exc_info.value.context)
    assert details.completed_items == len(questions) == 4
    assert details.total_items == progress[0][1]
    assert details.total_items > 4
    assert exc_info.value.completed_items == 4
    assert exc_info.value.total_items == details.total_items


@pytest.mark.parametrize("binding", [None, "repeat", "prompt_only"])
@pytest.mark.parametrize("inline", [False, True])
async def test_sections_resplit_material_and_render_each_reference(
    user, binding, inline
):
    text = (
        " \n\t"
        + "".join(f"Å municipal material {index}.\n\t" for index in range(150))
        + "  \n"
    )
    prompt = "First:\n{{step_1.output.text}}\nSecond:\n{{step_1.output.text}}\nDone."
    executor, _, assistant, run, state, step, text, _, questions, _ = _case(
        user, prompt=prompt, text=text, inline=inline
    )
    question_template = {
        "repeat": "Read {{step_1.output.text}} and again {{step_1.output.text}}",
        "prompt_only": "Use the material in the prompt.",
    }.get(binding)
    if question_template is not None:
        step = replace(step, input_bindings={"question": question_template})
    result = await executor._execute_step(step=step, run=run, state=state, attempt_no=1)

    manifest = SectionManifest.model_validate(
        result.output.output_payload_extensions["section_manifest"]
    )
    sections = manifest.resplit(text)
    assert len(sections) > 1
    assert "".join(sections) == text
    assert sections[0].startswith(" \n\t")
    assert sections[-1].endswith("  \n")
    for section, question, call in zip(
        sections, questions, assistant.get_response.await_args_list, strict=True
    ):
        assert question == (
            question_template.replace("{{step_1.output.text}}", section)
            if question_template is not None
            else section
        )
        rendered = call.kwargs["prompt_override"].split("\nDone.")[0]
        assert rendered == f"First:\n{section}\nSecond:\n{section}"
        assert call.kwargs["prepared_request"].fits


@pytest.mark.parametrize("second_file_backed", [True, False])
async def test_sections_refuse_multiple_materials_before_preflight_or_completion(
    user, second_file_backed
):
    executor, run_repo, assistant, run, state, step, _, file, _, _ = _case(
        user, text="First material. " * 20
    )
    second, second_file, reference = _file_backed_material(
        "Second material. " * 20, step_order=2
    )
    if not second_file_backed:
        second = second.model_copy(
            update={"output_payload_json": {"text": "Second material."}}
        )
    state.prior_results.append(second)
    state.completed_by_order[2] = second
    executor.file_service.get_owned_file_infos.return_value = [file, second_file]
    executor.file_service.repo.get_content_references.return_value.append(reference)
    executor.file_service.get_file_content.side_effect = lambda file_id: {
        file.id: file,
        second_file.id: second_file,
    }[file_id]
    step = replace(step, step_order=3, input_source="all_previous_steps")

    with pytest.raises(TypedIOValidationException) as exc_info:
        await executor._execute_step(step=step, run=run, state=state, attempt_no=1)

    assert (
        exc_info.value.code
        == FlowApiErrorCode.TYPED_IO_INVALID_INPUT_SOURCE_COMBINATION.value
    )
    assistant.preflight_response_context.assert_not_awaited()
    assistant.get_response.assert_not_awaited()
    run_repo.activate_step_attempt.assert_not_awaited()


async def test_sections_use_complete_single_file_text_without_source_wrappers(user):
    text = " \n\t" + "".join(f"Å file part {i}.\n" for i in range(45)) + "  \n"
    executor, _, assistant, run, state, step, _, file, questions, _ = _case(
        user, text=text, prompt="Read {{step_input.text}}\nDone."
    )
    state.prior_results.clear()
    state.completed_by_order.clear()
    step = replace(
        step,
        step_order=1,
        input_source="flow_input",
        input_bindings={"question": "Material: {{step_input.text}}"},
        input_config={
            **step.input_config,
            "runtime_input": {"enabled": True, "input_format": "document"},
        },
    )
    executor._list_step_input_file_ids = AsyncMock(return_value=[file.id])
    executor.flow_run_repo.list_retained_input_file_ids.return_value = []
    executor.file_service.get_files_by_ids.return_value = [file]

    result = await executor._execute_step(step=step, run=run, state=state, attempt_no=1)

    manifest = SectionManifest.model_validate(
        result.output.output_payload_extensions["section_manifest"]
    )
    sections = manifest.resplit(text)
    assert len(sections) > 1
    assert manifest.sources[0].file_id == file.id
    assert manifest.sources[0].checksum == file.checksum
    for section, question, call in zip(
        sections, questions, assistant.get_response.await_args_list, strict=True
    ):
        assert question == "Material: " + section
        assert call.kwargs["prompt_override"].split("\nDone.")[0] == "Read " + section


async def test_sections_stop_on_the_shared_step_deadline(user, monkeypatch):
    from eneo.flows.runtime import step_deadline

    clock = {"now": 0.0}
    monkeypatch.setattr(step_deadline, "_now", lambda: clock["now"])
    executor, _, assistant, run, state, step, _, _, questions, progress = _case(user)
    executor._step_deadline_seconds = lambda step: 1.5
    respond = assistant.get_response.side_effect

    async def delayed(**kwargs):
        response = await respond(**kwargs)
        clock["now"] += 1.0
        return response

    assistant.get_response.side_effect = delayed
    with pytest.raises(TypedIOValidationException) as exc_info:
        await executor._execute_step(step=step, run=run, state=state, attempt_no=1)
    assert exc_info.value.code == FlowApiErrorCode.STEP_TIMEOUT.value
    assert len(questions) == 2
    assert exc_info.value.completed_items == 2
    assert exc_info.value.total_items == progress[0][1]


@pytest.mark.parametrize("records", [[], [{"value": "one"}, {"value": "two"}]])
async def test_sections_refuse_other_than_one_record(user, records):
    executor, _, assistant, run, state, step, _, _, _, _ = _case(user)
    assistant.get_response.side_effect = None
    assistant.get_response.return_value = SimpleNamespace(
        completion=json.dumps({"records": records}),
        total_token_count=3,
    )
    with pytest.raises(TypedIOValidationException) as exc_info:
        await executor._execute_step(step=step, run=run, state=state, attempt_no=1)
    assert exc_info.value.context["completed_items"] == 0
    assert assistant.get_response.await_count == 1


async def test_provider_failure_persists_section_progress(user):
    failure = ProviderRejectedRequestException(
        "Provider rejected the section", code="provider_rejected_request"
    )
    executor, _, _, run, state, step, _, _, questions, progress = _case(
        user,
        fail_at=2,
        failure=failure,
    )
    with pytest.raises(ProviderRejectedRequestException):
        await executor._execute_step(step=step, run=run, state=state, attempt_no=1)
    claimed = _completed_step_result(
        run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_order=2,
        text="",
    ).model_copy(update={"step_id": step.step_id})
    executor._terminalize_run = AsyncMock()

    await executor._handle_generic_step_failure(
        run_id=run.id,
        tenant_id=run.tenant_id,
        step=step,
        attempt_no=1,
        claimed=claimed,
        state=state,
        exc=failure,
    )

    error = executor._terminalize_run.await_args.kwargs["error"]
    assert error.code == FlowApiErrorCode.STEP_EXECUTION_FAILED
    assert error.details is not None
    assert error.details.completed_items == len(questions) - 1 == 1
    assert error.details.total_items == progress[0][1]
    assert error.details.phase is None


@st.composite
def _section_cases(draw):
    text = draw(st.text(min_size=8, max_size=256))
    budget = draw(st.integers(min_value=4, max_value=min(128, len(text) - 1)))
    return text, budget


@given(case=_section_cases())
@example(case=("猫Å🙂" * 500, 512))
async def test_section_builder_round_trip(case):
    text, budget = case
    tenant = TenantInDB(id=uuid4(), name="test_tenant", quota_limit=0, quota_used=0)
    user = UserInDB(
        id=uuid4(),
        username="test_user",
        email="test@user.com",
        salt="test_salt",
        password="test_pass",
        tenant_id=tenant.id,
        tenant=tenant,
        state="active",
    )
    executor, _, assistant, run, state, step, _, _, _, _ = _case(user, text=text)

    async def preflight(**kwargs):
        overhead = len(kwargs["prompt_override"].encode()) + 37
        measured = overhead + len(kwargs["question"].encode())
        reserve = kwargs["useful_output_reserve_tokens"]
        capacity = overhead + reserve + budget
        preview = _context_preflight(measured)
        package = replace(preview.preferred, output_cap_tokens=capacity - measured)
        return replace(
            preview,
            capacity=ModelCapacity(capacity, capacity),
            preferred=package,
            fallback=package,
            refusal=None if package.fits else "current_request_input_does_not_fit",
        )

    assistant.preflight_response_context = AsyncMock(side_effect=preflight)
    base = await executor._preview_assistant_step(
        step=step, run=run, state=state, version_metadata=None, attempt_no=1
    )
    prepared = await prepare_text_sections(
        step=step,
        run=run,
        state=state,
        base=base,
        policy=FlowMappedExecutionPolicy(),
    )
    manifest = prepared.manifest
    questions = tuple(call.prepared.step_input.text for call in prepared.calls)
    assert len(questions) > 1
    assert manifest.resplit(text) == tuple(questions)
    assert "".join(questions) == text
    assert "".join(questions).encode() == text.encode()
    assert manifest.resplit(text) == tuple(
        call.prepared.step_input.source_text for call in prepared.calls
    )
    start = 0
    for index, (section, call) in enumerate(
        zip(manifest.sections, prepared.calls, strict=True)
    ):
        assert section.output_index == index
        assert section.core.start_char == start
        assert section.core.end_char > start
        assert (
            call.prepared.step_input.source_text == text[start : section.core.end_char]
        )
        assert len(call.prepared.step_input.source_text.encode()) <= budget
        start = section.core.end_char
    assert start == len(text)
    changed = chr(ord(text[0]) ^ 1) + text[1:]
    assert len(changed) == len(text)
    assert len(changed.encode()) == len(text.encode())
    with pytest.raises(ValueError, match="hash"):
        manifest.resplit(changed)


async def test_linked_inline_material_refuses_inconsistent_selected_bytes(user):
    from eneo.flows.domain.step_output import inline_transcript

    executor, _, assistant, run, state, step, text, _, _, _ = _case(
        user,
        inline=True,
        prompt="{{transkribering}}",
    )
    source = state.prior_results[0]
    source.output_payload_json["text_source_selector"] = {
        "kind": "json_path",
        "path": ["input", "text"],
    }
    run.input_payload_json = {
        "transkribering": inline_transcript(
            text=text + "Changed",
            source_step_id=source.step_id,
            source_attempt_no=source.current_attempt_no,
        ).model_dump(mode="json")
    }
    with pytest.raises(TypedIOValidationException) as caught:
        await executor._execute_step(step=step, run=run, state=state, attempt_no=1)
    assert caught.value.code == FlowApiErrorCode.TYPED_IO_CONTRACT_VIOLATION.value
    assistant.get_response.assert_not_awaited()
