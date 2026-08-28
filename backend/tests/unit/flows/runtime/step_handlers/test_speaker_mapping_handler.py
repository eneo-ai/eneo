from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.flows.domain.runtime import StepExecutionOutput, StepInputValue
from eneo.flows.runtime.step_execution_runtime import (
    PreparedCompletionCall,
    PreparedStepExecution,
    StepExecutionRuntimeDeps,
)
from eneo.flows.runtime.step_handlers import speaker_mapping as handler_module
from eneo.flows.runtime.step_handlers.base import PreparedAssistantStep
from eneo.flows.runtime.step_handlers.speaker_mapping import SpeakerMappingStepHandler
from eneo.main.exceptions import TypedIOValidationException

SOURCE = "\n".join(
    [
        "[00:00:00 - 00:00:04] SPEAKER_00: Hej, jag heter Anna.",
        "[00:00:05 - 00:00:09] SPEAKER_01: Hej Anna, Bo här.",
    ]
)
PROPOSAL = {
    "speakers": [
        {
            "label": "SPEAKER_00",
            "name": "Anna",
            "confidence": "high",
            "evidence": "intro",
        },
        {"label": "SPEAKER_01", "name": None, "confidence": "low", "evidence": ""},
    ]
}


def _step(**overrides):
    base = dict(
        step_id=uuid4(),
        step_order=2,
        input_source="previous_step",
        input_type="text",
        output_type="json",
        output_mode="speaker_mapping",
        output_config={"speaker_mapping": {"participants_field": "deltagare"}},
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _prepared(text: str) -> PreparedStepExecution:
    return PreparedStepExecution(
        assistant=SimpleNamespace(),
        step_input=StepInputValue(text=text, input_source="previous_step"),
        effective_prompt="Du är en assistent.",
        input_payload_for_result={},
        contract_validation=None,
        diagnostics=[],
        llm_files=[],
    )


def _deps(max_inline_text_bytes: int | None = 10_000) -> StepExecutionRuntimeDeps:
    return StepExecutionRuntimeDeps(
        variable_resolver=SimpleNamespace(),  # type: ignore[arg-type]
        completion_service=SimpleNamespace(),  # type: ignore[arg-type]
        load_assistant=AsyncMock(),
        resolve_step_input=AsyncMock(),
        retrieve_rag_chunks=AsyncMock(),
        process_typed_output=AsyncMock(),
        apply_output_cap=AsyncMock(side_effect=lambda *, text, run, step: (text, [])),
        max_inline_text_bytes=max_inline_text_bytes,
    )


def _output(structured) -> StepExecutionOutput:
    return StepExecutionOutput(
        input_text="q",
        source_text="",
        input_source="previous_step",
        used_question_binding=False,
        full_text="{}",
        persisted_text="{}",
        generated_file_ids=[],
        tool_calls_metadata=None,
        num_tokens_input=1,
        num_tokens_output=1,
        effective_prompt="",
        model_parameters_json={},
        structured_output=structured,
    )


@pytest.fixture
def harness(monkeypatch):
    calls: dict[str, object] = {}

    def fake_call(*, step, state, prepared):
        calls["question"] = prepared.step_input.text
        calls["prompt"] = prepared.effective_prompt
        return PreparedCompletionCall(
            question=prepared.step_input.text,
            effective_prompt=prepared.effective_prompt,
            preferred_model_kwargs=SimpleNamespace(),  # type: ignore[arg-type]
            preferred_model_parameters={},
            capability_fallback_model_kwargs=None,
            capability_fallback_model_parameters=None,
            assistant_context_version=1,
            preferred_native_json_object=False,
        )

    monkeypatch.setattr(handler_module, "build_prepared_completion_call", fake_call)

    async def fake_complete(*, step, run, state, prepared, deps):
        calls["deps"] = deps
        return _output(calls.get("structured", PROPOSAL))

    monkeypatch.setattr(handler_module, "complete_step_execution", fake_complete)

    async def activate(run, step, state, attempt_no, prepared_steps):
        calls["activated"] = prepared_steps
        return tuple(prepared_steps)

    return calls, activate


def _handler(activate, prepared_text: str = SOURCE, deps=None):
    preview = AsyncMock(
        return_value=PreparedAssistantStep(
            prepared=_prepared(prepared_text), deps=deps or _deps()
        )
    )
    persist = AsyncMock()
    return (
        SpeakerMappingStepHandler(
            preview_assistant_step=preview,
            activate_prepared_assistant_steps=activate,
            activate_resolved_input_edges=AsyncMock(),
            persist_transcript=persist,
        ),
        persist,
    )


def _state():
    previous = SimpleNamespace(
        step_id=uuid4(),
        current_attempt_no=3,
        input_payload_json={"transcription": {"diarization": "external"}},
    )
    return SimpleNamespace(completed_by_order={1: previous}), previous


async def test_proposal_renames_transcript_and_records_provenance(harness) -> None:
    calls, activate = harness
    handler, persist = _handler(activate)
    state, previous = _state()
    run = SimpleNamespace(
        id=uuid4(),
        input_payload_json={"deltagare": "Anna, Bo", "transkribering": SOURCE},
    )

    result = await handler.execute(
        step=_step(), run=run, state=state, version_metadata=None, attempt_no=1
    )

    output = result.output
    assert (
        output.full_text.splitlines()[0]
        == "[00:00:00 - 00:00:04] Anna: Hej, jag heter Anna."
    )
    assert "SPEAKER_01: Hej Anna, Bo här." in output.full_text
    assert output.structured_output == PROPOSAL
    extension = output.output_payload_extensions["speaker_mapping"]
    assert extension["participants"] == ["Anna", "Bo"]
    assert extension["source_step_id"] == str(previous.step_id)
    assert extension["source_attempt_no"] == 3
    assert [entry["label"] for entry in extension["inventory"]] == [
        "SPEAKER_00",
        "SPEAKER_01",
    ]
    # The model sees the inventory and participants, plus the fixed instructions.
    assert '"Anna"' in calls["question"] and "SPEAKER_01" in calls["question"]
    assert calls["prompt"].startswith("Du är en assistent.")
    assert "Respond with JSON only" in calls["prompt"]
    assert calls["activated"][0].prepared.completion_call is not None
    # Knowledge retrieval is skipped for this step.
    assert calls["deps"].retrieve_rag_chunks is handler_module._no_rag
    assert any(d.code == "speaker_mapping_unmapped_labels" for d in output.diagnostics)
    persist.assert_awaited_once_with(run, output.full_text)


async def test_run_transcript_is_left_alone_when_it_differs(harness) -> None:
    _, activate = harness
    handler, persist = _handler(activate)
    state, _ = _state()
    run = SimpleNamespace(id=uuid4(), input_payload_json={"transkribering": "other"})

    await handler.execute(
        step=_step(), run=run, state=state, version_metadata=None, attempt_no=1
    )

    persist.assert_not_awaited()


async def test_skipped_upstream_diarization_passes_transcript_through(harness) -> None:
    _, activate = harness
    handler, persist = _handler(activate, prepared_text="Bara text utan talare.")
    previous = SimpleNamespace(
        step_id=uuid4(),
        current_attempt_no=1,
        input_payload_json={
            "transcription": {"diarization": "skipped:empty_transcript"}
        },
    )
    state = SimpleNamespace(completed_by_order={1: previous})

    result = await handler.execute(
        step=_step(),
        run=SimpleNamespace(id=uuid4(), input_payload_json={}),
        state=state,
        version_metadata=None,
        attempt_no=1,
    )

    assert result.output.full_text == "Bara text utan talare."
    assert result.output.structured_output == {"speakers": []}
    assert result.output.output_payload_extensions["speaker_mapping"]["skipped"] is True
    assert any(d.code == "speaker_mapping_skipped" for d in result.output.diagnostics)
    persist.assert_not_awaited()


async def test_input_without_speaker_labels_fails_typed(harness) -> None:
    _, activate = harness
    handler, _ = _handler(activate, prepared_text="Bara text utan talare.")
    state, _ = _state()

    with pytest.raises(TypedIOValidationException):
        await handler.execute(
            step=_step(),
            run=SimpleNamespace(id=uuid4(), input_payload_json={}),
            state=state,
            version_metadata=None,
            attempt_no=1,
        )


async def test_invalid_proposal_fails_typed(harness) -> None:
    calls, activate = harness
    calls["structured"] = {"speakers": [{"label": "SPEAKER_00", "name": "Nobody"}]}
    handler, _ = _handler(activate)
    state, _ = _state()

    with pytest.raises(TypedIOValidationException):
        await handler.execute(
            step=_step(),
            run=SimpleNamespace(id=uuid4(), input_payload_json={"deltagare": "Anna"}),
            state=state,
            version_metadata=None,
            attempt_no=1,
        )


async def test_oversized_renamed_transcript_fails_instead_of_overflowing(
    harness,
) -> None:
    _, activate = harness
    handler, _ = _handler(activate, deps=_deps(max_inline_text_bytes=10))
    state, _ = _state()

    with pytest.raises(TypedIOValidationException) as excinfo:
        await handler.execute(
            step=_step(),
            run=SimpleNamespace(id=uuid4(), input_payload_json={"deltagare": "Anna"}),
            state=state,
            version_metadata=None,
            attempt_no=1,
        )
    assert excinfo.value.code == "typed_io_transcript_too_large"


async def test_wrong_io_tuple_fails_before_any_model_call(harness) -> None:
    _, activate = harness
    handler, _ = _handler(activate)
    state, _ = _state()

    with pytest.raises(TypedIOValidationException):
        await handler.execute(
            step=_step(input_source="flow_input"),
            run=SimpleNamespace(id=uuid4(), input_payload_json={}),
            state=state,
            version_metadata=None,
            attempt_no=1,
        )
