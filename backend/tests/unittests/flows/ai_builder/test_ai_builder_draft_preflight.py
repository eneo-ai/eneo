"""Deterministic preflight over a parsed AI-builder draft.

The preflight runs the existing critic against a compiled draft spec and reports
a typed verdict the proposal pipeline can act on before persisting: whether the
draft passed, whether a violation would block materialization (architecture
invariant) or is a retryable quality issue (semantic invariant), and which
invariant fired.
"""

from __future__ import annotations

from eneo.flows.ai_builder.ai_builder_draft_preflight import (
    PreflightResult,
    run_draft_preflight,
)
from eneo.flows.ai_builder.ai_builder_plan_quality_critic import (
    build_conversation_critic_context,
)
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


def _step(
    ref: str,
    name: str,
    instructions: str,
    *,
    input_source: InputSource = InputSource.FLOW_INPUT,
    input_type: InputType = InputType.TEXT,
    output_type: OutputType = OutputType.TEXT,
    output_mode: OutputMode = OutputMode.PASS_THROUGH,
    output_contract: dict | None = None,
) -> StepSpec:
    return StepSpec(
        plan_step_ref=ref,
        name=name,
        assistant_spec=AssistantSpec(instructions=instructions),
        input_source=input_source,
        input_type=input_type,
        output_mode=output_mode,
        output_type=output_type,
        output_contract=output_contract,
    )


def _preflight(
    spec: FlowDraftSpecCore,
    *,
    conversation: list[dict] | None = None,
) -> PreflightResult:
    context = build_conversation_critic_context(
        conversation or [{"role": "user", "content": "Skapa ett flöde."}],
        spec,
    )
    return run_draft_preflight(context)


def test_preflight_passes_a_clean_single_step_draft() -> None:
    spec = FlowDraftSpecCore(
        flow_name="Sammanfatta text",
        flow_description="",
        steps=[_step("step_a", "Sammanfatta", "Sammanfatta den inmatade texten.")],
    )

    result = _preflight(spec)

    assert isinstance(result, PreflightResult)
    assert result.passed is True
    assert result.blocks_materialization is False
    assert result.critic_invariant_ids == ()
    assert result.critic_invariant_id is None


def test_preflight_flags_form_field_declared_but_never_referenced() -> None:
    spec = FlowDraftSpecCore(
        flow_name="Onboarding",
        flow_description="",
        form_fields=[FormFieldSpec(name="prioritet", type="text", label="Prioritet")],
        steps=[_step("step_a", "Hantera ärende", "Behandla det inkomna ärendet.")],
    )

    result = _preflight(spec)

    assert result.passed is False
    assert result.can_retry is True
    assert "form_fields_declared_must_be_referenced" in result.critic_invariant_ids


def test_preflight_flags_architecture_issue_as_materialization_blocking() -> None:
    # The conversation asks for a PDF, but the terminal step only produces text —
    # a pdf_terminal_output_alignment architecture violation, which the create
    # proposal path rejects via the architecture hard-error path (before
    # materialization) and the planner cannot self-correct.
    conversation = [
        {
            "role": "user",
            "content": "PDF document",
            "metadata": {
                "question_answer": {
                    "question_id": "final_output_mode",
                    "selected_values": ["pdf_document"],
                }
            },
        }
    ]
    spec = FlowDraftSpecCore(
        flow_name="Rapport",
        flow_description="",
        steps=[_step("step_a", "Skriv rapport", "Skriv en rapport.")],
    )

    result = _preflight(spec, conversation=conversation)

    assert result.passed is False
    assert result.blocks_materialization is True
    assert result.can_retry is False
    assert result.architecture_issues
    assert "pdf_terminal_output_alignment" in result.critic_invariant_ids
