from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from eneo.flows.ai_builder.ai_builder_authoring_projection import (
    MaterializedAddStep as AddStep,
)
from eneo.flows.ai_builder.ai_builder_authoring_projection import (
    MaterializedOrderedEditProposal as OrderedEditProposal,
)
from eneo.flows.ai_builder.ai_builder_authoring_projection import (
    compile_ordered_edit_proposal,
    materialize_ordered_edit_proposal,
)
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
)
from eneo.flows.ai_builder.ai_builder_new_step_compiler import (
    compile_step_input_bindings,
)
from eneo.flows.ai_builder.ai_builder_new_step_models import (
    NewStepDraft,
    PreviousFieldRef,
    PreviousOutputRef,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    AddStep as IntentAddStep,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    AssistantSpecPatch,
    ModifyExistingStep,
    SemanticStepIntent,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    OrderedEditProposal as IntentOrderedEditProposal,
)
from eneo.flows.application.flow_authoring_snapshot import (
    current_flow_authoring_spec,
    flow_step_to_authoring_spec,
)
from eneo.flows.assistant_authoring_snapshot import AssistantAuthoringSnapshot
from eneo.flows.domain.flow import FlowStep
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    FormFieldSpec,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)
from eneo.flows.flow_review_policy import FlowStepReviewMode, FlowStepReviewPolicy
from eneo.flows.input_binding_contract_rules import (
    lower_source_refs_to_question_binding,
)
from eneo.main.exceptions import BadRequestException


def _edit_proposal(**kwargs: Any) -> OrderedEditProposal:
    return OrderedEditProposal(plan_rationale="Update the flow.", **kwargs)


def _lowered_question(input_bindings: dict[str, object] | None) -> str:
    lowered = lower_source_refs_to_question_binding(input_bindings)
    assert lowered is not None
    question = lowered.get("question")
    assert isinstance(question, str)
    return question


def test_ordered_edit_proposal_requires_plan_rationale() -> None:
    with pytest.raises(ValidationError, match="plan_rationale"):
        IntentOrderedEditProposal.model_validate({"steps": []})

    with pytest.raises(ValidationError, match="plan_rationale must not be empty"):
        IntentOrderedEditProposal(plan_rationale=" ", steps=[])


def test_edit_overlay_omitted_assistant_fields_preserve_snapshot() -> None:
    result = compile_ordered_edit_proposal(
        base_spec=_base_spec(),
        proposal=_edit_proposal(
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


def test_edit_overlay_explicit_model_clear_is_not_omission() -> None:
    preserved = compile_ordered_edit_proposal(
        base_spec=_base_spec(),
        proposal=_edit_proposal(
            steps=[ModifyExistingStep(existing_step_ref="existing_step_1")],
        ),
    )
    cleared = compile_ordered_edit_proposal(
        base_spec=_base_spec(),
        proposal=_edit_proposal(
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


def test_edit_overlay_explicit_resource_detach() -> None:
    detached = compile_ordered_edit_proposal(
        base_spec=_base_spec(),
        proposal=_edit_proposal(
            steps=[
                ModifyExistingStep(
                    existing_step_ref="existing_step_1",
                    assistant_spec=AssistantSpecPatch(knowledge_refs=[]),
                )
            ],
        ),
    )
    assert detached.steps[0].assistant_spec.knowledge_refs == []


def test_edit_overlay_omitted_review_mode_preserves_existing_policy() -> None:
    review_policy = FlowStepReviewPolicy(mode=FlowStepReviewMode.VIEW)

    result = compile_ordered_edit_proposal(
        base_spec=_base_spec(_step_with_review_policy(review_policy)),
        proposal=_edit_proposal(
            steps=[ModifyExistingStep(existing_step_ref="existing_step_1")],
        ),
    )

    assert result.steps[0].review_policy == review_policy


def test_edit_overlay_explicit_null_review_mode_clears_existing_policy() -> None:
    result = compile_ordered_edit_proposal(
        base_spec=_base_spec(
            _step_with_review_policy(FlowStepReviewPolicy(mode=FlowStepReviewMode.VIEW))
        ),
        proposal=_edit_proposal(
            steps=[
                ModifyExistingStep.model_validate(
                    {
                        "existing_step_ref": "existing_step_1",
                        "review_mode": None,
                    }
                )
            ],
        ),
    )

    assert result.steps[0].review_policy is None


def test_edit_overlay_review_mode_replaces_existing_policy() -> None:
    result = compile_ordered_edit_proposal(
        base_spec=_base_spec(
            _step_with_review_policy(FlowStepReviewPolicy(mode=FlowStepReviewMode.VIEW))
        ),
        proposal=_edit_proposal(
            steps=[
                ModifyExistingStep(
                    existing_step_ref="existing_step_1",
                    review_mode=FlowStepReviewMode.EDIT,
                )
            ],
        ),
    )

    assert result.steps[0].review_policy == FlowStepReviewPolicy(
        mode=FlowStepReviewMode.EDIT
    )


def test_edit_overlay_rejects_raw_review_policy_patch() -> None:
    with pytest.raises(ValueError):
        ModifyExistingStep.model_validate(
            {
                "existing_step_ref": "existing_step_1",
                "review_policy": {"mode": "view"},
            }
        )


def test_edit_overlay_compiles_form_field_refs_without_shadow_policy() -> None:
    result = compile_ordered_edit_proposal(
        base_spec=_base_spec(
            _step(
                "step_a",
                "existing_step_1",
                "Extract JSON",
                output_type=OutputType.JSON,
                output_contract={
                    "type": "object",
                    "properties": {"summary": {"type": "string"}},
                },
            ),
            _step(
                "step_b",
                "existing_step_2",
                "Write report",
                input_source=InputSource.PREVIOUS_STEP,
            ),
        ),
        proposal=_edit_proposal(
            steps=[
                ModifyExistingStep(existing_step_ref="existing_step_1"),
                ModifyExistingStep(
                    existing_step_ref="existing_step_2",
                    uses_form_fields=["text"],
                ),
            ],
        ),
    )

    assert result.steps[1].input_bindings == {
        "question": "text: {{ flow_input.text }}",
        "source_refs": [{"step_ref": "step_a", "output": "structured"}],
    }
    assert _lowered_question(result.steps[1].input_bindings) == (
        "text: {{ flow_input.text }}\n\n{{ step_a.output.structured }}"
    )


def test_edit_overlay_requires_step_coverage_or_removal() -> None:
    base = _base_spec(
        _step("step_a", "existing_step_1", "First"),
        _step("step_b", "existing_step_2", "Second"),
    )

    with pytest.raises(BadRequestException) as missing_exc:
        compile_ordered_edit_proposal(
            base_spec=base,
            proposal=_edit_proposal(
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
            proposal=_edit_proposal(
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
        _step("step_c", "existing_step_3", "Third"),
        document_body_writer_step_refs=("step_b",),
    )
    result = compile_ordered_edit_proposal(
        base_spec=base,
        proposal=_edit_proposal(
            steps=[
                AddStep(step=_new_step("Inserted first")),
                ModifyExistingStep(existing_step_ref="existing_step_2"),
                ModifyExistingStep(existing_step_ref="existing_step_1"),
            ],
            removed_existing_step_refs=frozenset({"existing_step_3"}),
        ),
    )

    assert [step.existing_step_ref for step in result.steps] == [
        None,
        "existing_step_2",
        "existing_step_1",
    ]
    assert [step.plan_step_ref for step in result.steps] == [
        "step_a",
        "step_b",
        "step_c",
    ]
    assert result.steps[0].name == "Inserted first"
    assert result.document_body_writer_step_refs == ("step_b",)


def test_edit_overlay_add_first_step_derives_flow_input_when_omitted() -> None:
    result = compile_ordered_edit_proposal(
        base_spec=_base_spec(_step("step_a", "existing_step_1", "Remove")),
        proposal=_edit_proposal(
            steps=[
                AddStep(
                    step=NewStepDraft.model_validate(
                        {
                            "name": "New first",
                            "instructions": "New prompt",
                        }
                    )
                )
            ],
            removed_existing_step_refs=frozenset({"existing_step_1"}),
        ),
    )

    assert result.steps[0].input_source == InputSource.FLOW_INPUT


def test_edit_overlay_add_later_step_derives_previous_step_when_omitted() -> None:
    result = compile_ordered_edit_proposal(
        base_spec=_base_spec(_step("step_a", "existing_step_1", "First")),
        proposal=_edit_proposal(
            steps=[
                ModifyExistingStep(existing_step_ref="existing_step_1"),
                AddStep(
                    step=NewStepDraft.model_validate(
                        {
                            "name": "New second",
                            "instructions": "New prompt",
                        }
                    )
                ),
            ],
        ),
    )

    assert result.steps[1].input_source == InputSource.PREVIOUS_STEP


def test_edit_overlay_add_step_preserves_explicit_all_previous_steps() -> None:
    result = compile_ordered_edit_proposal(
        base_spec=_base_spec(_step("step_a", "existing_step_1", "First")),
        proposal=_edit_proposal(
            steps=[
                ModifyExistingStep(existing_step_ref="existing_step_1"),
                AddStep(
                    step=NewStepDraft.model_validate(
                        {
                            "name": "Summarize all",
                            "instructions": "New prompt",
                            "input_source": "all_previous_steps",
                        }
                    )
                ),
            ],
        ),
    )

    assert result.steps[1].input_source == InputSource.ALL_PREVIOUS_STEPS


def test_edit_overlay_add_step_uses_ui_language_for_input_reference_hint() -> None:
    result = compile_ordered_edit_proposal(
        base_spec=_base_spec(
            _step(
                "step_a",
                "existing_step_1",
                "Extract",
                output_type=OutputType.JSON,
                output_contract={
                    "type": "object",
                    "properties": {"summary": {"type": "string"}},
                },
            )
        ),
        proposal=_edit_proposal(
            steps=[
                ModifyExistingStep(existing_step_ref="existing_step_1"),
                AddStep(
                    step=_new_step(
                        "Compare summaries",
                        input_source=InputSource.ALL_PREVIOUS_STEPS,
                        uses_previous_fields=[
                            PreviousFieldRef(from_step=1, field_path="summary")
                        ],
                    )
                ),
            ],
        ),
        ui_language="en",
    )

    instructions = result.steps[1].assistant_spec.instructions
    assert "Pay particular attention to these structured source fields:" in instructions
    assert (
        "Beakta särskilt följande strukturerade fält i underlaget:" not in instructions
    )


def test_edit_overlay_add_step_uses_form_field_with_shared_new_step_compiler() -> None:
    result = compile_ordered_edit_proposal(
        base_spec=_base_spec(
            form_fields=[
                FormFieldSpec(
                    name="case_id",
                    type="text",
                    label="Case ID",
                )
            ],
        ),
        proposal=_edit_proposal(
            steps=[
                ModifyExistingStep(existing_step_ref="existing_step_1"),
                AddStep(
                    step=_new_step(
                        "Use case id",
                        uses_form_fields=["case_id"],
                    )
                ),
            ],
        ),
    )

    assert result.steps[1].input_bindings == {
        "question": "case_id: {{ flow_input.case_id }}",
        "source_refs": [{"step_ref": "step_a", "output": "text"}],
    }
    assert _lowered_question(result.steps[1].input_bindings) == (
        "case_id: {{ flow_input.case_id }}\n\n{{ step_a.output.text }}"
    )


def test_edit_overlay_add_first_step_uses_form_field_without_source_reference() -> None:
    result = compile_ordered_edit_proposal(
        base_spec=_base_spec(
            _step("step_a", "existing_step_1", "Remove"),
            form_fields=[
                FormFieldSpec(
                    name="case_id",
                    type="text",
                    label="Case ID",
                )
            ],
        ),
        proposal=_edit_proposal(
            steps=[
                AddStep(
                    step=_new_step(
                        "Use case id",
                        uses_form_fields=["case_id"],
                    )
                )
            ],
            removed_existing_step_refs=frozenset({"existing_step_1"}),
        ),
    )

    assert result.steps[0].input_bindings == {
        "question": "case_id: {{ flow_input.case_id }}"
    }


def test_edit_overlay_modify_step_uses_form_field_with_shared_input_compiler() -> None:
    result = compile_ordered_edit_proposal(
        base_spec=_base_spec(
            _step(
                "step_a",
                "existing_step_1",
                "Answer",
                input_source=InputSource.PREVIOUS_STEP,
            ),
            form_fields=[
                FormFieldSpec(
                    name="case_id",
                    type="text",
                    label="Case ID",
                )
            ],
        ),
        proposal=_edit_proposal(
            steps=[
                ModifyExistingStep.model_validate(
                    {
                        "existing_step_ref": "existing_step_1",
                        "uses_form_fields": ["case_id"],
                    }
                )
            ],
        ),
    )

    assert result.steps[0].input_bindings == {
        "question": "case_id: {{ flow_input.case_id }}"
    }


def test_edit_overlay_add_step_uses_previous_structured_field_from_preserved_step() -> (
    None
):
    result = compile_ordered_edit_proposal(
        base_spec=_base_spec(
            _step(
                "step_a",
                "existing_step_1",
                "Extract",
                output_type=OutputType.JSON,
                output_contract={
                    "type": "object",
                    "properties": {"answer": {"type": "string"}},
                },
            )
        ),
        proposal=_edit_proposal(
            steps=[
                ModifyExistingStep(existing_step_ref="existing_step_1"),
                AddStep(
                    step=_new_step(
                        "Use answer",
                        uses_previous_fields=[
                            PreviousFieldRef(from_step=1, field_path="answer")
                        ],
                    )
                ),
            ],
        ),
    )

    assert result.steps[1].input_bindings == {
        "source_refs": [
            {
                "step_ref": "step_a",
                "output": "structured",
                "field_path": "answer",
                "label": "answer",
            }
        ]
    }
    assert (
        _lowered_question(result.steps[1].input_bindings)
        == "answer: {{ step_a.output.structured.answer }}"
    )


def test_step_input_bindings_emit_source_refs_for_previous_output() -> None:
    bindings = compile_step_input_bindings(
        input_source=InputSource.PREVIOUS_STEP,
        input_type=InputType.TEXT,
        uses_form_fields=[],
        uses_previous_fields=[],
        uses_previous_outputs=[PreviousOutputRef(from_step=1)],
        prior_steps=[_step("step_a", None, "Draft")],
    )

    assert bindings == {
        "source_refs": [
            {"step_ref": "step_a", "output": "text", "label": "Step 1 output"},
        ]
    }
    assert _lowered_question(bindings) == "Step 1 output: {{ step_a.output.text }}"


def test_step_input_bindings_dedupe_source_refs_without_dropping_form_fields() -> None:
    bindings = compile_step_input_bindings(
        input_source=InputSource.PREVIOUS_STEP,
        input_type=InputType.TEXT,
        uses_form_fields=["case_id"],
        uses_previous_fields=[],
        uses_previous_outputs=[PreviousOutputRef(from_step=1)],
        prior_steps=[_step("step_a", None, "Draft")],
    )

    assert bindings == {
        "question": "case_id: {{ flow_input.case_id }}",
        "source_refs": [
            {"step_ref": "step_a", "output": "text", "label": "Step 1 output"}
        ],
    }
    assert _lowered_question(bindings) == (
        "case_id: {{ flow_input.case_id }}\n\nStep 1 output: {{ step_a.output.text }}"
    )


def test_step_input_bindings_emit_source_refs_for_implicit_structured_blob() -> None:
    bindings = compile_step_input_bindings(
        input_source=InputSource.PREVIOUS_STEP,
        input_type=InputType.TEXT,
        uses_form_fields=[],
        uses_previous_fields=[],
        uses_previous_outputs=[],
        prior_steps=[_step("step_a", None, "Extract", output_type=OutputType.JSON)],
    )

    assert bindings == {"source_refs": [{"step_ref": "step_a", "output": "structured"}]}
    assert _lowered_question(bindings) == "{{ step_a.output.structured }}"


def test_step_input_bindings_keep_immediate_field_suppression() -> None:
    bindings = compile_step_input_bindings(
        input_source=InputSource.PREVIOUS_STEP,
        input_type=InputType.TEXT,
        uses_form_fields=[],
        uses_previous_fields=[PreviousFieldRef(from_step=1, field_path="items.0.name")],
        uses_previous_outputs=[],
        prior_steps=[_step("step_a", None, "Extract", output_type=OutputType.JSON)],
    )

    assert bindings == {
        "source_refs": [
            {
                "step_ref": "step_a",
                "output": "structured",
                "field_path": "items.0.name",
                "label": "name",
            }
        ]
    }
    assert (
        _lowered_question(bindings)
        == "name: {{ step_a.output.structured.items.0.name }}"
    )


def test_step_input_bindings_collapse_broad_field_refs_to_structured_ref() -> None:
    bindings = compile_step_input_bindings(
        input_source=InputSource.PREVIOUS_STEP,
        input_type=InputType.TEXT,
        uses_form_fields=[],
        uses_previous_fields=[
            PreviousFieldRef(from_step=1, field_path="summary"),
            PreviousFieldRef(from_step=1, field_path="details"),
        ],
        uses_previous_outputs=[],
        prior_steps=[
            _step(
                "step_a",
                None,
                "Extract",
                output_type=OutputType.JSON,
                output_contract={
                    "type": "object",
                    "properties": {
                        "summary": {"type": "string"},
                        "details": {"type": "string"},
                    },
                },
            )
        ],
    )

    assert bindings == {"source_refs": [{"step_ref": "step_a", "output": "structured"}]}
    assert _lowered_question(bindings) == "{{ step_a.output.structured }}"


def test_step_input_bindings_keep_non_immediate_structured_source_ref() -> None:
    bindings = compile_step_input_bindings(
        input_source=InputSource.PREVIOUS_STEP,
        input_type=InputType.TEXT,
        uses_form_fields=[],
        uses_previous_fields=[PreviousFieldRef(from_step=1, field_path="answer")],
        uses_previous_outputs=[],
        prior_steps=[
            _step("step_a", None, "Extract answer", output_type=OutputType.JSON),
            _step("step_b", None, "Extract summary", output_type=OutputType.JSON),
        ],
    )

    assert bindings == {
        "source_refs": [
            {"step_ref": "step_b", "output": "structured"},
            {
                "step_ref": "step_a",
                "output": "structured",
                "field_path": "answer",
                "label": "answer",
            },
        ]
    }
    assert _lowered_question(bindings) == (
        "{{ step_b.output.structured }}\n\n"
        "answer: {{ step_a.output.structured.answer }}"
    )


def test_step_input_bindings_fall_back_to_question_for_template_labels() -> None:
    bindings = compile_step_input_bindings(
        input_source=InputSource.PREVIOUS_STEP,
        input_type=InputType.TEXT,
        uses_form_fields=[],
        uses_previous_fields=[
            PreviousFieldRef(
                from_step=1,
                field_path="answer",
                label="{{ bad }}",
            )
        ],
        uses_previous_outputs=[],
        prior_steps=[_step("step_a", None, "Extract", output_type=OutputType.JSON)],
    )

    assert bindings == {"question": "{{ bad }}: {{ step_a.output.structured.answer }}"}


def test_edit_overlay_add_step_rejects_unresolvable_previous_output_ref() -> None:
    proposal = IntentOrderedEditProposal(
        plan_rationale="Add a step.",
        steps=[
            ModifyExistingStep(existing_step_ref="existing_step_1"),
            IntentAddStep(
                step=SemanticStepIntent(
                    name="Use prior result",
                    instructions="Use a prior result.",
                    uses_previous_fields=[
                        PreviousFieldRef(from_step=1, field_path="answer")
                    ],
                    uses_previous_outputs=[PreviousOutputRef(from_step=2)],
                )
            ),
        ],
    )

    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        compile_ordered_edit_proposal(
            base_spec=_base_spec(
                _step(
                    "step_a",
                    "existing_step_1",
                    "Extract",
                    output_type=OutputType.JSON,
                    output_contract={
                        "type": "object",
                        "properties": {"answer": {"type": "string"}},
                    },
                )
            ),
            proposal=materialize_ordered_edit_proposal(proposal),
        )

    assert exc_info.value.code is AIBuilderErrorCode.INVALID_PLAN_STEP_REF
    assert exc_info.value.context == {
        "ref_kind": "uses_previous_outputs",
        "from_step": 2,
        "prior_step_count": 1,
    }


def test_edit_overlay_modify_step_uses_compiled_prior_step_frame_after_reorder() -> (
    None
):
    result = compile_ordered_edit_proposal(
        base_spec=_base_spec(
            _step("step_a", "existing_step_1", "First"),
            _step(
                "step_b",
                "existing_step_2",
                "Extract",
                output_type=OutputType.JSON,
                output_contract={
                    "type": "object",
                    "properties": {"answer": {"type": "string"}},
                },
            ),
            _step(
                "step_c",
                "existing_step_3",
                "Write",
                input_source=InputSource.PREVIOUS_STEP,
            ),
        ),
        proposal=_edit_proposal(
            steps=[
                ModifyExistingStep(existing_step_ref="existing_step_2"),
                ModifyExistingStep.model_validate(
                    {
                        "existing_step_ref": "existing_step_3",
                        "uses_previous_fields": [
                            {"from_step": 1, "field_path": "answer"}
                        ],
                    }
                ),
            ],
            removed_existing_step_refs=frozenset({"existing_step_1"}),
        ),
    )

    assert (
        _lowered_question(result.steps[1].input_bindings)
        == "answer: {{ step_a.output.structured.answer }}"
    )


def test_edit_overlay_rejects_unresolvable_previous_field_ref_before_hint_compilation() -> (
    None
):
    base = _base_spec(
        _step(
            "step_a",
            "existing_step_1",
            "Extract",
            output_type=OutputType.JSON,
        ),
        _step(
            "step_b",
            "existing_step_2",
            "Summarize",
            input_source=InputSource.ALL_PREVIOUS_STEPS,
        ),
    )

    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        compile_ordered_edit_proposal(
            base_spec=base,
            proposal=_edit_proposal(
                steps=[
                    ModifyExistingStep(existing_step_ref="existing_step_1"),
                    ModifyExistingStep(
                        existing_step_ref="existing_step_2",
                        uses_previous_fields=[
                            PreviousFieldRef(from_step=2, field_path="phantom")
                        ],
                    ),
                ],
            ),
        )

    assert exc_info.value.code is AIBuilderErrorCode.INVALID_PLAN_STEP_REF
    assert exc_info.value.context == {
        "ref_kind": "uses_previous_fields",
        "from_step": 2,
        "prior_step_count": 1,
    }
    assert base.steps[1].assistant_spec.instructions == "Original prompt"


def test_edit_overlay_rejects_previous_field_missing_from_output_contract() -> None:
    base = _base_spec(
        _step(
            "step_a",
            "existing_step_1",
            "Extract",
            output_type=OutputType.JSON,
            output_contract={
                "type": "object",
                "properties": {"answer": {"type": "string"}},
            },
        ),
        _step(
            "step_b",
            "existing_step_2",
            "Summarize",
            input_source=InputSource.ALL_PREVIOUS_STEPS,
        ),
    )

    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        compile_ordered_edit_proposal(
            base_spec=base,
            proposal=_edit_proposal(
                steps=[
                    ModifyExistingStep(existing_step_ref="existing_step_1"),
                    ModifyExistingStep(
                        existing_step_ref="existing_step_2",
                        uses_previous_fields=[
                            PreviousFieldRef(from_step=1, field_path="missing")
                        ],
                    ),
                ],
            ),
        )

    assert exc_info.value.code is AIBuilderErrorCode.INVALID_PLAN_STEP_REF
    assert exc_info.value.context == {
        "ref_kind": "uses_previous_fields",
        "from_step": 1,
        "field_path": "missing",
        "missing_path": "missing",
        "source_step_ref": "step_a",
    }
    assert base.steps[1].assistant_spec.instructions == "Original prompt"


def test_edit_overlay_add_step_derives_audio_output_mode_with_shared_compiler() -> None:
    result = compile_ordered_edit_proposal(
        base_spec=_base_spec(),
        proposal=_edit_proposal(
            steps=[
                AddStep(
                    step=_new_step(
                        "Transcribe",
                        input_source=InputSource.FLOW_INPUT,
                        input_type=InputType.AUDIO,
                        output_type=OutputType.TEXT,
                    )
                ),
                ModifyExistingStep(existing_step_ref="existing_step_1"),
            ],
        ),
    )

    assert result.steps[0].output_mode == OutputMode.TRANSCRIBE_ONLY


def test_edit_overlay_modify_step_uses_document_delivery_mode_derivation() -> None:
    result = compile_ordered_edit_proposal(
        base_spec=_base_spec(
            _step(
                "step_a",
                "existing_step_1",
                "Fill template",
                output_mode=OutputMode.TEMPLATE_FILL,
                output_type=OutputType.DOCX,
            )
        ),
        proposal=_edit_proposal(
            steps=[
                ModifyExistingStep.model_validate(
                    {
                        "existing_step_ref": "existing_step_1",
                        "document_delivery_mode": "generated",
                    }
                )
            ],
        ),
    )

    assert result.steps[0].output_mode == OutputMode.RENDER_VERBATIM


def test_edit_overlay_drops_document_body_writer_ref_when_writer_step_is_removed() -> (
    None
):
    result = compile_ordered_edit_proposal(
        base_spec=_base_spec(
            _step("step_a", "existing_step_1", "Keep"),
            _step("step_b", "existing_step_2", "Writer"),
            document_body_writer_step_refs=("step_b",),
        ),
        proposal=_edit_proposal(
            steps=[ModifyExistingStep(existing_step_ref="existing_step_1")],
            removed_existing_step_refs=frozenset({"existing_step_2"}),
        ),
    )

    assert result.document_body_writer_step_refs is None


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


def test_current_flow_authoring_spec_preserves_signature_vocabulary() -> None:
    result = current_flow_authoring_spec(
        current_steps=[
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
            ),
        ],
        flow_name="Signature flow",
        flow_description="Existing description",
        assistant_snapshots=None,
    )

    assert [step.plan_step_ref for step in result.steps] == [
        "existing_step_1",
        "existing_step_2",
    ]
    assert result.steps[0].input_source == InputSource.ALL_PREVIOUS_STEPS
    assert result.steps[0].input_type == InputType.JSON
    assert result.steps[-1].output_mode == OutputMode.TEMPLATE_FILL
    assert result.steps[-1].output_type == OutputType.DOCX


def _base_spec(
    *steps: StepSpec,
    document_body_writer_step_refs: tuple[str, ...] | None = None,
    form_fields: list[FormFieldSpec] | None = None,
) -> FlowDraftSpecCore:
    return FlowDraftSpecCore(
        flow_name="Existing flow",
        flow_description="Existing description",
        steps=list(steps) or [_step("step_a", "existing_step_1", "First")],
        document_body_writer_step_refs=document_body_writer_step_refs,
        form_fields=form_fields,
    )


def _step(
    plan_ref: str,
    existing_ref: str | None,
    name: str,
    *,
    input_source: InputSource = InputSource.FLOW_INPUT,
    input_type: InputType = InputType.TEXT,
    output_mode: OutputMode = OutputMode.PASS_THROUGH,
    output_type: OutputType = OutputType.TEXT,
    output_contract: dict[str, object] | None = None,
    review_policy: FlowStepReviewPolicy | None = None,
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
        input_source=input_source,
        input_type=input_type,
        output_mode=output_mode,
        output_type=output_type,
        output_contract=output_contract,
        review_policy=review_policy,
    )


def _step_with_review_policy(review_policy: FlowStepReviewPolicy) -> StepSpec:
    return _step(
        "step_a",
        "existing_step_1",
        "First",
        review_policy=review_policy,
    )


def _new_step(
    name: str,
    *,
    input_source: InputSource = InputSource.PREVIOUS_STEP,
    input_type: InputType = InputType.TEXT,
    output_type: OutputType = OutputType.TEXT,
    uses_form_fields: list[str] | None = None,
    uses_previous_fields: list[PreviousFieldRef] | None = None,
) -> NewStepDraft:
    return NewStepDraft(
        name=name,
        instructions="New prompt",
        input_source=input_source,
        input_type=input_type,
        output_type=output_type,
        uses_form_fields=uses_form_fields or [],
        uses_previous_fields=uses_previous_fields or [],
    )
