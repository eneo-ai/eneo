from __future__ import annotations

from uuid import uuid4

from eneo.flows.ai_builder.ai_builder_domain_models import (
    BuilderPlan,
    ConversationMessage,
    FlowBuilderProposal,
    FlowBuilderProposalContent,
    PlanStatus,
)
from eneo.flows.ai_builder.ai_builder_plan_edit_context import (
    AIBuilderPlanEditContext,
)
from eneo.flows.ai_builder.ai_builder_proposal_policy import (
    format_contextual_quality_feedback,
    format_validation_feedback,
    terminal_output_type_for_conversation,
)
from eneo.flows.ai_builder.ai_builder_validation_common import SpecValidationError
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)


def _make_flow_spec() -> FlowDraftSpecCore:
    return FlowDraftSpecCore(
        flow_name="Grounded flow",
        flow_description="Desc",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Analys",
                assistant_spec=AssistantSpec(instructions="Gor analysen."),
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.TEXT,
            )
        ],
    )


def _structured_fan_in_spec() -> FlowDraftSpecCore:
    return FlowDraftSpecCore(
        flow_name="Structured report",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Extract A",
                assistant_spec=AssistantSpec(instructions="Extract A."),
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.JSON,
                output_contract={
                    "type": "object",
                    "properties": {"summary": {"type": "string"}},
                },
            ),
            StepSpec(
                plan_step_ref="step_b",
                name="Extract B",
                assistant_spec=AssistantSpec(instructions="Extract B."),
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.JSON,
                output_contract={
                    "type": "object",
                    "properties": {"detail": {"type": "string"}},
                },
            ),
            StepSpec(
                plan_step_ref="step_c",
                name="Write report",
                assistant_spec=AssistantSpec(instructions="Write report."),
                input_source=InputSource.ALL_PREVIOUS_STEPS,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.TEXT,
            ),
        ],
    )


def _make_plan(spec: FlowDraftSpecCore) -> BuilderPlan:
    return BuilderPlan(
        id=uuid4(),
        session_id=uuid4(),
        tenant_id=uuid4(),
        status=PlanStatus.PROPOSED,
        proposal=FlowBuilderProposal(content=FlowBuilderProposalContent(spec=spec)),
    )


def test_plan_edit_output_intent_preserves_prior_document_terminal_type() -> None:
    spec = _make_flow_spec()
    spec = spec.model_copy(
        update={
            "steps": [spec.steps[0].model_copy(update={"output_type": OutputType.PDF})]
        }
    )
    plan = _make_plan(spec)
    context = AIBuilderPlanEditContext(
        scope="step",
        plan_id=plan.id,
        target_plan_step_ref="step_a",
    )

    output_type = terminal_output_type_for_conversation(
        [
            ConversationMessage(
                role="user",
                content="Make the language more formal in this section.",
            )
        ],
        plan_edit_context=context,
        prior_plan=plan,
    )

    assert output_type == OutputType.PDF


def test_edit_contextual_quality_feedback_keeps_mechanics_remediation() -> None:
    feedback = format_contextual_quality_feedback(
        conversation=[],
        spec=_structured_fan_in_spec(),
    )

    assert feedback is not None
    assert "input_source" in feedback
    assert "uses_previous_fields" in feedback


def test_format_validation_feedback_does_not_add_step_ref_guidance_for_runtime_alias_error() -> (
    None
):
    spec = FlowDraftSpecCore(
        flow_name="Unit plan",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Extract",
                assistant_spec=AssistantSpec(instructions="Extract."),
                input_source=InputSource.FLOW_INPUT,
            ),
            StepSpec(
                plan_step_ref="step_b",
                name="Summarize",
                assistant_spec=AssistantSpec(instructions="Summarize."),
                input_source=InputSource.PREVIOUS_STEP,
            ),
        ],
    )

    feedback = format_validation_feedback(
        spec=spec,
        errors=[
            SpecValidationError(
                step_ref="step_a",
                code="flow_step_invalid",
                message="Invalid step reference 'step_a' in input bindings.",
            )
        ],
    )

    assert "Invalid step reference 'step_a' in input bindings." in feedback
    assert "Declared step refs in this draft: step_a, step_b" not in feedback


def test_format_validation_feedback_keeps_undeclared_step_ref_visible() -> None:
    spec = FlowDraftSpecCore(
        flow_name="Unit plan",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Extract",
                assistant_spec=AssistantSpec(instructions="Extract."),
                input_source=InputSource.FLOW_INPUT,
            )
        ],
    )

    feedback = format_validation_feedback(
        spec=spec,
        errors=[
            SpecValidationError(
                step_ref="step_a",
                code="invalid_runtime_variable_path",
                message="Invalid step reference 'step_z' in template expression.",
            )
        ],
    )

    assert "Invalid step reference 'step_z' in template expression." in feedback
    assert "Declared step refs in this draft: step_a" not in feedback


def test_plan_edit_output_intent_uses_latest_explicit_document_change() -> None:
    plan = _make_plan(_make_flow_spec())
    context = AIBuilderPlanEditContext(
        scope="step",
        plan_id=plan.id,
        target_plan_step_ref="step_a",
    )

    output_type = terminal_output_type_for_conversation(
        [
            ConversationMessage(
                role="user",
                content="Change the final output so I get a PDF file.",
            )
        ],
        plan_edit_context=context,
        prior_plan=plan,
    )

    assert output_type == OutputType.PDF
