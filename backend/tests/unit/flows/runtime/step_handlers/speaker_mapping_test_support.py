"""The speaker mapping handler, with its completion faked to return a proposal.

Shared by the handler's own tests and by tests that run it on other inputs.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.flows.domain.runtime import StepExecutionOutput, StepInputValue
from eneo.flows.domain.speaker_labels import SPEAKER_MAPPING_OUTPUT_CONTRACT
from eneo.flows.output_processing import validate_against_contract
from eneo.flows.runtime.step_execution_runtime import (
    PreparedCompletionCall,
    PreparedStepExecution,
    StepExecutionRuntimeDeps,
)
from eneo.flows.runtime.step_handlers import speaker_mapping as handler_module
from eneo.flows.runtime.step_handlers.base import PreparedAssistantStep
from eneo.flows.runtime.step_handlers.speaker_mapping import SpeakerMappingStepHandler

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


def speaker_step(**overrides):
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


def prepared_execution(text: str) -> PreparedStepExecution:
    return PreparedStepExecution(
        assistant=SimpleNamespace(),
        step_input=StepInputValue(text=text, input_source="previous_step"),
        effective_prompt="Du är en assistent.",
        input_payload_for_result={},
        contract_validation=None,
        diagnostics=[],
        llm_files=[],
    )


def runtime_deps(
    max_inline_text_bytes: int | None = 10_000,
) -> StepExecutionRuntimeDeps:
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


def proposal_output(structured) -> StepExecutionOutput:
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
            preferred_native_json_format=False,
        )

    monkeypatch.setattr(handler_module, "build_prepared_completion_call", fake_call)

    async def fake_complete(*, step, run, state, prepared, deps):
        calls["deps"] = deps
        structured = calls.get("structured", PROPOSAL)
        validate_against_contract(
            structured, SPEAKER_MAPPING_OUTPUT_CONTRACT, label="Step 2 output"
        )
        return proposal_output(structured)

    monkeypatch.setattr(handler_module, "complete_step_execution", fake_complete)

    async def activate(run, step, state, attempt_no, prepared_steps):
        calls["activated"] = prepared_steps
        return tuple(prepared_steps)

    return calls, activate


def speaker_handler(activate, prepared_text: str = SOURCE, deps=None):
    from eneo.flows.domain.transcript_source import transcript_source_reference

    preview = AsyncMock(
        return_value=PreparedAssistantStep(
            prepared=prepared_execution(prepared_text), deps=deps or runtime_deps()
        )
    )
    persist = AsyncMock()
    return (
        SpeakerMappingStepHandler(
            preview_assistant_step=preview,
            activate_prepared_assistant_steps=activate,
            activate_resolved_input_edges=AsyncMock(),
            persist_transcript=persist,
            transcript_source_for_step=AsyncMock(
                side_effect=lambda run, previous: transcript_source_reference(
                    previous.input_payload_json
                )
            ),
        ),
        persist,
    )
