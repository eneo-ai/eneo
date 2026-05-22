from __future__ import annotations

import pytest
from pydantic import ValidationError

from intric.flows.flow_authoring_spec import (
    AssistantSpec,
    AssistantSpecLocalRefNotPortableError,
    FlowDraftSpecCore,
    FormFieldSpec,
    InputSource,
    JsonObject,
    OutputMode,
    StepSpec,
)

_LOCAL_ID = "11111111-1111-4111-8111-111111111111"


def test_assistant_spec_rejects_local_model_ref() -> None:
    with pytest.raises(ValidationError) as exc_info:
        AssistantSpec(instructions="Use a local model.", model_ref=_LOCAL_ID)

    assert _has_local_ref_not_portable_error(exc_info.value)


@pytest.mark.parametrize(
    "field_name",
    ["knowledge_refs", "mcp_server_refs", "mcp_tool_refs"],
)
def test_assistant_spec_rejects_local_resource_refs(field_name: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        AssistantSpec(instructions="Use a local resource.", **{field_name: [_LOCAL_ID]})

    assert _has_local_ref_not_portable_error(exc_info.value)


def test_assistant_spec_rejects_mixed_knowledge_and_mcp_refs() -> None:
    with pytest.raises(ValidationError):
        AssistantSpec(
            instructions="Use incompatible resources.",
            knowledge_refs=["knowledge.local_policy"],
            mcp_tool_refs=["mcp.case_lookup"],
        )


@pytest.mark.parametrize(
    ("raw_type", "normalized_type"),
    [
        ("string", "text"),
        ("dropdown", "select"),
        ("multi-select", "multiselect"),
        ("datetime", "date"),
        ("unsupported", "text"),
    ],
)
def test_form_field_spec_normalizes_supported_input_types(
    raw_type: str,
    normalized_type: str,
) -> None:
    field = FormFieldSpec(name="field", type=raw_type, label="Field")

    assert field.type == normalized_type


def test_flow_draft_spec_hash_is_deterministic() -> None:
    spec = FlowDraftSpecCore(flow_name="Demo", steps=[_step()])

    assert spec.spec_hash() == spec.spec_hash()


def test_flow_draft_spec_hash_is_key_order_independent() -> None:
    first = FlowDraftSpecCore(
        flow_name="Demo",
        steps=[_step(input_bindings={"question": "{{ step_input.text }}", "z": 1})],
    )
    second = FlowDraftSpecCore(
        flow_name="Demo",
        steps=[_step(input_bindings={"z": 1, "question": "{{ step_input.text }}"})],
    )

    assert first.spec_hash() == second.spec_hash()


def test_step_spec_strips_completion_model_ref_for_transcribe_only() -> None:
    step = _step(output_mode=OutputMode.TRANSCRIBE_ONLY, model_ref="model.default")

    assert step.assistant_spec.model_ref is None


@pytest.mark.parametrize(
    "output_mode", [OutputMode.PASS_THROUGH, OutputMode.TEMPLATE_FILL]
)
def test_step_spec_keeps_completion_model_ref_when_runtime_uses_completion_model(
    output_mode: OutputMode,
) -> None:
    step = _step(output_mode=output_mode, model_ref="model.default")

    assert step.assistant_spec.model_ref == "model.default"


def _step(
    input_bindings: JsonObject | None = None,
    *,
    output_mode: OutputMode = OutputMode.PASS_THROUGH,
    model_ref: str | None = None,
) -> StepSpec:
    return StepSpec(
        plan_step_ref="collect_input",
        name="Collect input",
        assistant_spec=AssistantSpec(
            instructions="Use the provided input.",
            model_ref=model_ref,
        ),
        input_source=InputSource.FLOW_INPUT,
        output_mode=output_mode,
        input_bindings=input_bindings,
    )


def _has_local_ref_not_portable_error(exc: ValidationError) -> bool:
    for error in exc.errors():
        context = error.get("ctx")
        if not isinstance(context, dict):
            continue
        if isinstance(context.get("error"), AssistantSpecLocalRefNotPortableError):
            return True
    return False
