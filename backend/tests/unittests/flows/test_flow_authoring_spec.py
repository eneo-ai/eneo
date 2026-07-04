from __future__ import annotations

import inspect

import pytest
from pydantic import Field, ValidationError

from eneo.flows.domain.flow import FlowPersistedJsonObject
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    AssistantSpecLocalRefNotPortableError,
    FlowDraftSpecCore,
    FormFieldSpec,
    InputSource,
    OutputMode,
    StepSpec,
)
from eneo.flows.flow_authoring_variable_rewriting import (
    flow_step_validation_views_from_draft_spec,
)
from eneo.flows.flow_validators import collect_step_graph_issues

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


def test_pydantic_field_supports_exclude_if_for_absent_spec_metadata() -> None:
    assert "exclude_if" in inspect.signature(Field).parameters, (
        "exclude_if removed from Pydantic Field; switch "
        "document_body_writer_step_refs to a @field_serializer fallback."
    )


def test_flow_draft_spec_omits_absent_document_body_writer_refs() -> None:
    spec = FlowDraftSpecCore(flow_name="Demo", steps=[_step()])

    dumped = spec.model_dump(mode="json")
    restored = FlowDraftSpecCore.model_validate(dumped)

    assert "document_body_writer_step_refs" not in dumped
    assert restored.model_dump(mode="json") == dumped


def test_flow_draft_spec_preserves_document_body_writer_refs() -> None:
    spec = FlowDraftSpecCore(
        flow_name="Demo",
        steps=[_step(plan_step_ref="step_a"), _step(plan_step_ref="step_b")],
        document_body_writer_step_refs=("step_b",),
    )

    assert spec.document_body_writer_step_refs == ("step_b",)
    assert spec.model_dump(mode="json")["document_body_writer_step_refs"] == ["step_b"]


def test_document_body_writer_refs_do_not_change_spec_hash() -> None:
    steps = [_step(plan_step_ref="step_a"), _step(plan_step_ref="step_b")]
    base = FlowDraftSpecCore(flow_name="Demo", steps=steps)
    with_refs = FlowDraftSpecCore(
        flow_name="Demo",
        steps=steps,
        document_body_writer_step_refs=("step_b",),
    )

    assert with_refs.spec_hash() == base.spec_hash()


def test_document_body_writer_refs_soft_prune_stale_refs_in_order() -> None:
    spec = FlowDraftSpecCore(
        flow_name="Demo",
        steps=[_step(plan_step_ref="step_a"), _step(plan_step_ref="step_c")],
        document_body_writer_step_refs=("step_a", "step_b", "step_c"),
    )

    assert spec.document_body_writer_step_refs == ("step_a", "step_c")


def test_document_body_writer_refs_prune_to_absent_field() -> None:
    spec = FlowDraftSpecCore(
        flow_name="Demo",
        steps=[_step(plan_step_ref="step_b")],
        document_body_writer_step_refs=("step_a",),
    )

    assert spec.document_body_writer_step_refs is None
    assert "document_body_writer_step_refs" not in spec.model_dump(mode="json")


def test_stale_document_body_writer_refs_are_dropped_on_rehydrate() -> None:
    payload = FlowDraftSpecCore(
        flow_name="Demo",
        steps=[_step(plan_step_ref="step_a"), _step(plan_step_ref="step_c")],
        document_body_writer_step_refs=("step_a", "step_c"),
    ).model_dump(mode="json")
    payload["document_body_writer_step_refs"] = ["step_a", "step_b", "step_c"]

    restored = FlowDraftSpecCore.model_validate(payload)

    assert restored.document_body_writer_step_refs == ("step_a", "step_c")
    assert restored.model_dump(mode="json")["document_body_writer_step_refs"] == [
        "step_a",
        "step_c",
    ]


def test_step_spec_strips_completion_model_ref_for_transcribe_only() -> None:
    step = _step(output_mode=OutputMode.TRANSCRIBE_ONLY, model_ref="model.default")

    assert step.assistant_spec.model_ref is None


def test_step_spec_rejects_malformed_source_refs() -> None:
    with pytest.raises(ValidationError):
        _step(input_bindings={"source_refs": [{"step_ref": "step_a"}]})


def test_source_refs_forward_references_fail_authoring_validation_path() -> None:
    steps = [
        _step(plan_step_ref="step_a"),
        _step(
            plan_step_ref="step_b",
            name="Summarize",
            input_source=InputSource.PREVIOUS_STEP,
            input_bindings={"source_refs": [{"step_ref": "step_b", "output": "text"}]},
        ),
    ]

    issues = collect_step_graph_issues(
        flow_step_validation_views_from_draft_spec(steps)
    )

    assert [issue.message for issue in issues if issue.step_order == 2] == [
        "Input bindings may only reference outputs from earlier steps."
    ]


@pytest.mark.parametrize(
    "output_mode", [OutputMode.PASS_THROUGH, OutputMode.TEMPLATE_FILL]
)
def test_step_spec_keeps_completion_model_ref_when_runtime_uses_completion_model(
    output_mode: OutputMode,
) -> None:
    step = _step(output_mode=output_mode, model_ref="model.default")

    assert step.assistant_spec.model_ref == "model.default"


def _step(
    input_bindings: FlowPersistedJsonObject | None = None,
    *,
    plan_step_ref: str = "collect_input",
    name: str = "Collect input",
    input_source: InputSource = InputSource.FLOW_INPUT,
    output_mode: OutputMode = OutputMode.PASS_THROUGH,
    model_ref: str | None = None,
) -> StepSpec:
    return StepSpec(
        plan_step_ref=plan_step_ref,
        name=name,
        assistant_spec=AssistantSpec(
            instructions="Use the provided input.",
            model_ref=model_ref,
        ),
        input_source=input_source,
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
