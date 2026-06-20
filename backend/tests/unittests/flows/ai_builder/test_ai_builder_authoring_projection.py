from __future__ import annotations

from uuid import uuid4

import pytest

from intric.flows.ai_builder.ai_builder_authoring_projection import (
    AddStep,
    AssistantSpecPatch,
    ModifyExistingStep,
    OrderedEditProposal,
    compile_ordered_edit_proposal,
    flow_step_to_authoring_spec,
    flow_steps_to_authoring_specs,
)
from intric.flows.assistant_authoring_snapshot import AssistantAuthoringSnapshot
from intric.flows.domain.flow import FlowStep
from intric.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)
from intric.flows.flow_review_policy import FlowStepReviewMode, FlowStepReviewPolicy
from intric.main.exceptions import BadRequestException


def test_edit_overlay_omitted_assistant_fields_preserve_snapshot() -> None:
    result = compile_ordered_edit_proposal(
        base_spec=_base_spec(),
        proposal=OrderedEditProposal(
            steps=[
                ModifyExistingStep(
                    existing_step_ref="existing_step_1",
                    assistant_spec=AssistantSpecPatch(instructions="New prompt"),
                )
            ],
        ),
    )

    assistant = result.steps[0].assistant_spec
    assert assistant.instructions == "New prompt"
    assert assistant.model_ref == "model-a"
    assert assistant.knowledge_refs == ["kb-a"]
    assert assistant.mcp_server_refs == []
    assert assistant.mcp_tool_refs == []


def test_edit_overlay_explicit_model_clear_is_not_omission() -> None:
    preserved = compile_ordered_edit_proposal(
        base_spec=_base_spec(),
        proposal=OrderedEditProposal(
            steps=[ModifyExistingStep(existing_step_ref="existing_step_1")],
        ),
    )
    cleared = compile_ordered_edit_proposal(
        base_spec=_base_spec(),
        proposal=OrderedEditProposal(
            steps=[
                ModifyExistingStep(
                    existing_step_ref="existing_step_1",
                    assistant_spec=AssistantSpecPatch(model_ref=None),
                )
            ],
        ),
    )

    assert preserved.steps[0].assistant_spec.model_ref == "model-a"
    assert cleared.steps[0].assistant_spec.model_ref is None


def test_edit_overlay_explicit_resource_detach_and_mcp_selection() -> None:
    detached = compile_ordered_edit_proposal(
        base_spec=_base_spec(),
        proposal=OrderedEditProposal(
            steps=[
                ModifyExistingStep(
                    existing_step_ref="existing_step_1",
                    assistant_spec=AssistantSpecPatch(knowledge_refs=[]),
                )
            ],
        ),
    )
    mcp_selected = compile_ordered_edit_proposal(
        base_spec=_base_spec(),
        proposal=OrderedEditProposal(
            steps=[
                ModifyExistingStep(
                    existing_step_ref="existing_step_1",
                    assistant_spec=AssistantSpecPatch(mcp_server_refs=["server-a"]),
                )
            ],
        ),
    )

    assert detached.steps[0].assistant_spec.knowledge_refs == []
    assert mcp_selected.steps[0].assistant_spec.knowledge_refs == []
    assert mcp_selected.steps[0].assistant_spec.mcp_server_refs == ["server-a"]


def test_edit_overlay_requires_step_coverage_or_removal() -> None:
    base = _base_spec(
        _step("step_a", "existing_step_1", "First"),
        _step("step_b", "existing_step_2", "Second"),
    )

    with pytest.raises(BadRequestException) as missing_exc:
        compile_ordered_edit_proposal(
            base_spec=base,
            proposal=OrderedEditProposal(
                steps=[ModifyExistingStep(existing_step_ref="existing_step_1")],
            ),
        )
    assert missing_exc.value.context == {
        "reason": "missing_existing_step_ref",
        "missing_refs": ["existing_step_2"],
    }

    with pytest.raises(BadRequestException) as overlap_exc:
        compile_ordered_edit_proposal(
            base_spec=base,
            proposal=OrderedEditProposal(
                steps=[
                    ModifyExistingStep(existing_step_ref="existing_step_1"),
                    ModifyExistingStep(existing_step_ref="existing_step_2"),
                ],
                removed_existing_step_refs=frozenset({"existing_step_2"}),
            ),
        )
    assert overlap_exc.value.context == {
        "reason": "preserved_and_removed_existing_step_ref",
        "overlap_refs": ["existing_step_2"],
    }


def test_edit_overlay_step_order_and_insertion() -> None:
    base = _base_spec(
        _step("step_a", "existing_step_1", "First"),
        _step("step_b", "existing_step_2", "Second"),
        document_body_writer_step_refs=("step_b",),
    )
    result = compile_ordered_edit_proposal(
        base_spec=base,
        proposal=OrderedEditProposal(
            steps=[
                ModifyExistingStep(existing_step_ref="existing_step_2"),
                AddStep(step=_step("inserted_step", None, "Inserted")),
                ModifyExistingStep(existing_step_ref="existing_step_1"),
            ],
        ),
    )

    assert [step.existing_step_ref for step in result.steps] == [
        "existing_step_2",
        None,
        "existing_step_1",
    ]
    assert [step.plan_step_ref for step in result.steps] == [
        "step_a",
        "step_b",
        "step_c",
    ]
    assert result.steps[1].name == "Inserted"
    assert result.document_body_writer_step_refs == ("step_a",)


def test_flow_to_authoring_projection_preserves_authoring_fields() -> None:
    mapped_fields = {
        "user_description",
        "input_source",
        "input_type",
        "input_contract",
        "output_mode",
        "output_type",
        "output_contract",
        "input_bindings",
        "mcp_policy",
        "input_config",
        "output_config",
        "review_policy",
    }
    non_authoring_fields = {
        "id",
        "flow_id",
        "tenant_id",
        "assistant_id",
        "step_order",
        "timeout_seconds",
        "output_classification_override",
        "created_at",
        "updated_at",
    }
    assert set(FlowStep.model_fields) == mapped_fields | non_authoring_fields

    review_policy = FlowStepReviewPolicy(mode=FlowStepReviewMode.EDIT)
    flow_step = FlowStep(
        id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        assistant_id=uuid4(),
        step_order=3,
        user_description="Existing",
        input_source="previous_step",
        input_type="json",
        input_bindings={"question": "{{step_a.answer}}"},
        input_contract={"type": "object"},
        output_mode="pass_through",
        output_type="json",
        output_contract={
            "type": "object",
            "properties": {"answer": {"type": "string"}},
        },
        input_config={"runtime_input": {"enabled": False}},
        output_config={"citation_mode": "inline_inref_sidecar"},
        review_policy=review_policy,
        mcp_policy="inherit",
    )

    projected = flow_step_to_authoring_spec(
        flow_step,
        "step_c",
        assistant_snapshots={
            flow_step.assistant_id: AssistantAuthoringSnapshot(
                instructions="Existing prompt"
            )
        },
    )

    assert projected.existing_step_ref == "existing_step_3"
    assert projected.assistant_spec.instructions == "Existing prompt"
    assert projected.input_bindings == flow_step.input_bindings
    assert projected.input_contract == flow_step.input_contract
    assert projected.output_contract == flow_step.output_contract
    assert projected.input_config == flow_step.input_config
    assert projected.output_config == flow_step.output_config
    assert projected.review_policy == review_policy


def test_flow_steps_to_authoring_specs_preserves_signature_vocabulary() -> None:
    result = flow_steps_to_authoring_specs(
        [
            FlowStep(
                id=uuid4(),
                flow_id=uuid4(),
                tenant_id=uuid4(),
                assistant_id=uuid4(),
                step_order=1,
                user_description="Read input",
                input_source="all_previous_steps",
                input_type="json",
                output_mode="pass_through",
                output_type="text",
                mcp_policy="inherit",
            ),
            FlowStep(
                id=uuid4(),
                flow_id=uuid4(),
                tenant_id=uuid4(),
                assistant_id=uuid4(),
                step_order=2,
                user_description="Write report",
                input_source="previous_step",
                input_type="text",
                output_mode="template_fill",
                output_type="docx",
                mcp_policy="inherit",
            ),
        ]
    )

    assert [step.plan_step_ref for step in result] == [
        "existing_step_1",
        "existing_step_2",
    ]
    assert result[0].input_source == InputSource.ALL_PREVIOUS_STEPS
    assert result[0].input_type == InputType.JSON
    assert result[-1].output_mode == OutputMode.TEMPLATE_FILL
    assert result[-1].output_type == OutputType.DOCX


def _base_spec(
    *steps: StepSpec,
    document_body_writer_step_refs: tuple[str, ...] | None = None,
) -> FlowDraftSpecCore:
    return FlowDraftSpecCore(
        flow_name="Existing flow",
        flow_description="Existing description",
        steps=list(steps) or [_step("step_a", "existing_step_1", "First")],
        document_body_writer_step_refs=document_body_writer_step_refs,
    )


def _step(
    plan_ref: str,
    existing_ref: str | None,
    name: str,
) -> StepSpec:
    return StepSpec(
        plan_step_ref=plan_ref,
        existing_step_ref=existing_ref,
        name=name,
        assistant_spec=AssistantSpec(
            instructions="Original prompt",
            model_ref="model-a",
            knowledge_refs=["kb-a"],
        ),
        input_source=InputSource.FLOW_INPUT,
        input_type=InputType.TEXT,
        output_mode=OutputMode.PASS_THROUGH,
        output_type=OutputType.TEXT,
    )
