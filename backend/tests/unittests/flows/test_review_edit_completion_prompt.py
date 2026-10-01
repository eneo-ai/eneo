"""The completion call a step sends after a reviewer edited a result it reads."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.completion_models.domain.model_kwargs_capabilities import (
    SupportedModelKwargs,
)
from eneo.flows.domain.review_edit_references import (
    reviewed_results,
)
from eneo.flows.domain.runtime import RunExecutionState, RuntimeStep, StepInputValue
from eneo.flows.flow_run_provenance import (
    FlowResolvedInputJsonPath,
    FlowResolvedInputStepResultSource,
    build_resolved_input_edge,
)
from eneo.flows.runtime.output_formats import resolve_format_spec
from eneo.flows.runtime.output_formats.base import append_output_format_instructions
from eneo.flows.runtime.step_execution_runtime import (
    PreparedStepExecution,
    build_prepared_completion_call,
)

_CONTRACT: dict[str, object] = {
    "type": "object",
    "required": ["beslut"],
    "additionalProperties": False,
    "properties": {"beslut": {"type": "string"}},
}


def _step(*, step_order: int, output_type: str) -> RuntimeStep:
    return RuntimeStep(
        step_id=uuid4(),
        step_order=step_order,
        assistant_id=uuid4(),
        user_description="Analys",
        input_source="previous_step",
        input_bindings=None,
        input_config=None,
        output_mode="pass_through",
        output_config=None,
        output_type=output_type,
        output_contract=_CONTRACT if output_type == "json" else None,
        input_type="json",
    )


def _prepared(*, reviewed_step: RuntimeStep) -> PreparedStepExecution:
    assistant = MagicMock()
    assistant.completion_model = SimpleNamespace(
        id=None,
        name="gpt-4.1",
        provider_type="openai",
        litellm_model_name="openai/gpt-4.1",
        supported_model_kwargs=SupportedModelKwargs(),
    )
    assistant.completion_model_kwargs = ModelKwargs()
    spec = resolve_format_spec("json")
    return PreparedStepExecution(
        assistant=assistant,
        step_input=StepInputValue(
            text='{"utfall": "Bifall"}', input_source="previous_step"
        ),
        effective_prompt=append_output_format_instructions(
            "Write the decision.", spec.prompt_instructions(_CONTRACT)
        ),
        input_payload_for_result={"text": "x"},
        contract_validation=None,
        diagnostics=[],
        llm_files=[],
        resolved_input_edges=(
            build_resolved_input_edge(
                binding_ref="input_source",
                source=FlowResolvedInputStepResultSource(
                    kind="step_result",
                    source_step_id=reviewed_step.step_id,
                    source_attempt_no=1,
                    selector=FlowResolvedInputJsonPath(
                        kind="json_path", path=("output", "structured")
                    ),
                ),
                selected_value={"utfall": "Bifall"},
            ),
        ),
    )


def _state(*, reviewed_step: RuntimeStep) -> RunExecutionState:
    return RunExecutionState(
        completed_by_order={},
        prior_results=[],
        assistant_cache={},
        json_mode_supported={},
        file_cache={},
        reviewed_results=reviewed_results(
            [
                (
                    reviewed_step.step_id,
                    1,
                    {"structured": {"utfall": "Avslag"}},
                    {"structured": {"utfall": "Bifall"}},
                )
            ],
            steps=[reviewed_step],
        ),
    )


def test_native_schema_call_strips_the_schema_and_keeps_the_review_references(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "eneo.completion_models.infrastructure.tenant_model_capabilities.supports_response_schema",
        lambda **kwargs: True,
    )
    monkeypatch.setattr(
        "eneo.flows.runtime.step_execution_runtime.detect_native_json_output_support",
        lambda assistant: True,
    )
    reviewed_step = _step(step_order=1, output_type="json")
    consumer = _step(step_order=2, output_type="json")
    prepared = _prepared(reviewed_step=reviewed_step)
    schema_text = json.dumps(_CONTRACT, sort_keys=True)

    call = build_prepared_completion_call(
        step=consumer, state=_state(reviewed_step=reviewed_step), prepared=prepared
    )

    assert call.preferred_model_kwargs.response_format is not None
    assert call.preferred_model_kwargs.response_format["type"] == "json_schema"
    assert '["utfall"] set by the reviewer' in call.effective_prompt
    assert "Follow this JSON Schema exactly" not in call.effective_prompt
    assert schema_text not in call.effective_prompt
    assert call.capability_fallback_prompt is not None
    assert "Follow this JSON Schema exactly" in call.capability_fallback_prompt
    assert '["utfall"] set by the reviewer' in call.capability_fallback_prompt
    assert "Avslag" not in call.effective_prompt
    assert "Avslag" not in call.capability_fallback_prompt


def test_a_call_without_reviewed_input_is_unchanged():
    reviewed_step = _step(step_order=1, output_type="json")
    consumer = _step(step_order=2, output_type="text")
    prepared = _prepared(reviewed_step=reviewed_step)
    state = _state(reviewed_step=reviewed_step)
    state.reviewed_results = {}

    call = build_prepared_completion_call(step=consumer, state=state, prepared=prepared)

    assert call.effective_prompt == prepared.effective_prompt
