from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from eneo.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from eneo.flows.ai_builder.ai_builder_create_compile_context import (
    create_compile_context_from_planning_state,
)
from eneo.flows.ai_builder.ai_builder_critic_invariant_kinds import (
    CRITIC_INVARIANT_KINDS,
)
from eneo.flows.ai_builder.ai_builder_critic_invariants import (
    CRITIC_INVARIANTS,
    enforce_architecture_critic_invariants,
    evaluate_critic_invariants,
)
from eneo.flows.ai_builder.ai_builder_event_models import (
    RequirementsSummaryPayload,
)
from eneo.flows.ai_builder.ai_builder_plan_quality_critic import (
    build_conversation_aware_quality_feedback,
    build_conversation_critic_context,
    build_quality_feedback_from_critic_context,
)
from eneo.flows.ai_builder.ai_builder_schema_evidence import build_schema_evidence
from eneo.flows.ai_builder.planning_state import (
    CheckpointIntent,
    PlanningSignal,
    PlanningState,
    ResolvedSlot,
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
from eneo.flows.flow_review_policy import FlowStepReviewMode, FlowStepReviewPolicy

if TYPE_CHECKING:
    from eneo.flows.ai_builder.ai_builder_critic_invariants import CriticContext
    from eneo.flows.ai_builder.ai_builder_input_architecture_policy import (
        PrimaryRuntimeInput,
    )
    from eneo.flows.ai_builder.planning_state import AggregationIntent
    from eneo.flows.domain.flow import Flow


def test_critic_requires_typed_checkpoint_on_the_actual_report_producer() -> None:
    planning_state = PlanningState.empty()
    planning_state.checkpoint_intents = [
        CheckpointIntent(
            evidence_level="explicit",
            producer_kind="report_text",
            operation="set",
            mode=FlowStepReviewMode.EDIT,
            confidence="high",
            evidence=["quote:user_message:1:Edit the report before delivery."],
        )
    ]
    draft_step = _step("step_a", "Draft report", "Draft the report.")
    final_step = _step(
        "step_b",
        "Finalize report",
        "Finalize the report.",
        input_source=InputSource.PREVIOUS_STEP,
    )
    wrong_target = FlowDraftSpecCore(
        flow_name="Reviewed report",
        steps=[
            draft_step.model_copy(
                update={
                    "review_policy": FlowStepReviewPolicy(mode=FlowStepReviewMode.EDIT)
                }
            ),
            final_step,
        ],
        document_body_writer_step_refs=("step_b",),
    )
    matching = wrong_target.model_copy(
        update={
            "steps": [
                draft_step,
                final_step.model_copy(
                    update={
                        "review_policy": FlowStepReviewPolicy(
                            mode=FlowStepReviewMode.EDIT
                        )
                    }
                ),
            ]
        }
    )

    wrong_issues = evaluate_critic_invariants(
        build_conversation_critic_context(
            [],
            wrong_target,
            planning_state=planning_state,
            compile_context=create_compile_context_from_planning_state(planning_state),
        )
    )
    matching_issues = evaluate_critic_invariants(
        build_conversation_critic_context(
            [],
            matching,
            planning_state=planning_state,
            compile_context=create_compile_context_from_planning_state(planning_state),
        )
    )

    assert any(issue.id == "checkpoint_intent_mismatch" for issue in wrong_issues)
    assert not any(
        issue.id == "checkpoint_intent_mismatch" for issue in matching_issues
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
    input_bindings: dict | None = None,
    output_config: dict | None = None,
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
        input_bindings=input_bindings,
        output_config=output_config,
    )


def _edit_flow() -> "Flow":
    from uuid import uuid4

    from eneo.flows.domain.flow import Flow, FlowStep

    return Flow(
        id=uuid4(),
        tenant_id=uuid4(),
        space_id=uuid4(),
        name="Existing flow",
        steps=[
            FlowStep(
                assistant_id=uuid4(),
                step_order=1,
                user_description="Existing step",
                input_source="flow_input",
                input_type="text",
                output_mode="pass_through",
                output_type="text",
            )
        ],
    )


def _requirements(**overrides: object) -> RequirementsSummaryPayload:
    payload = {
        "summary": "Skapa ett mötesprotokoll.",
        "key_decisions": [
            {"topic": "Indata", "decision": "Mötesljud vid körning."},
            {"topic": "Utdata", "decision": "DOCX-protokoll."},
        ],
        "input_description": "Primär indata vid körning behöver granskas.",
        "output_description": "Huvudsakligt slutresultat behöver granskas.",
        "assumptions": ["Inga extra fält."],
        "manual_setup_notes": ["Koppla transkriberingsmodellen."],
        "requirements_version": "0" * 64,
    }
    payload.update(overrides)
    return RequirementsSummaryPayload.model_validate(payload)


def test_action_followup_critic_uses_typed_goal_and_declared_schema_leaves() -> None:
    planning_state = PlanningState.empty()
    planning_state.resolved_slots["post_processing_goal"] = ResolvedSlot(
        name="post_processing_goal",
        value="action_followup",
        source="structured_answer",
        confidence="high",
        evidence=["question_answer:post_processing_goal"],
    )
    incomplete_spec = FlowDraftSpecCore(
        flow_name="Follow-up",
        steps=[
            _step(
                "step_a",
                "Process source",
                "Process the supplied material.",
                output_type=OutputType.JSON,
                output_contract={
                    "type": "object",
                    "properties": {
                        "decisions": {"type": "array"},
                        "actions": {"type": "array"},
                        "owners": {"type": "array"},
                        "deadlines": {"type": "array"},
                    },
                },
            )
        ],
    )
    complete_step = incomplete_spec.steps[0].model_copy(
        update={
            "output_contract": {
                "type": "object",
                "properties": {
                    "decisions": {"type": "array"},
                    "actions": {"type": "array"},
                    "owners": {"type": "array"},
                    "deadlines": {"type": "array"},
                    "open_questions": {"type": "array"},
                },
            }
        }
    )
    complete_spec = incomplete_spec.model_copy(update={"steps": [complete_step]})

    incomplete_issues = evaluate_critic_invariants(
        build_conversation_critic_context(
            [{"role": "user", "content": "Use this material."}],
            incomplete_spec,
            planning_state=planning_state,
        )
    )
    complete_issues = evaluate_critic_invariants(
        build_conversation_critic_context(
            [{"role": "user", "content": "Use this material."}],
            complete_spec,
            planning_state=planning_state,
        )
    )

    assert "action_followup_requires_followup_fields" in {
        issue.id for issue in incomplete_issues
    }
    assert "action_followup_requires_followup_fields" not in {
        issue.id for issue in complete_issues
    }


def test_field_reuse_requires_a_downstream_structured_reference() -> None:
    # Terminal JSON bound only to earlier TEXT: nothing consumes the JSON
    # producer's fields, so a reuse request is not satisfied.
    unsatisfied_spec = FlowDraftSpecCore(
        flow_name="Reuse",
        steps=[
            _step(
                "step_a",
                "Extrahera",
                "Extrahera specifika fälten.",
                output_type=OutputType.JSON,
                output_contract={
                    "type": "object",
                    "properties": {"beslut": {"type": "array"}},
                },
            ),
            _step(
                "step_b",
                "Sammanställ",
                "Använd fälten i nästa steg.",
                input_source=InputSource.PREVIOUS_STEP,
                output_type=OutputType.TEXT,
            ),
        ],
    )
    satisfied_step = unsatisfied_spec.steps[1].model_copy(
        update={
            "input_bindings": {
                "source_refs": [
                    {
                        "step_ref": "step_a",
                        "output": "structured",
                        "field_path": "beslut",
                    }
                ]
            }
        }
    )
    text_only_step = unsatisfied_spec.steps[1].model_copy(
        update={
            "input_bindings": {
                "source_refs": [{"step_ref": "step_a", "output": "text"}]
            }
        }
    )
    satisfied_spec = unsatisfied_spec.model_copy(
        update={"steps": [unsatisfied_spec.steps[0], satisfied_step]}
    )
    text_only_spec = unsatisfied_spec.model_copy(
        update={"steps": [unsatisfied_spec.steps[0], text_only_step]}
    )
    conversation = [
        {"role": "user", "content": "Extrahera specifika fälten och använd fälten."}
    ]

    unsatisfied_issues = evaluate_critic_invariants(
        build_conversation_critic_context(conversation, unsatisfied_spec)
    )
    satisfied_issues = evaluate_critic_invariants(
        build_conversation_critic_context(conversation, satisfied_spec)
    )

    assert "field_reuse_requires_input_bindings" in {
        issue.id for issue in unsatisfied_issues
    }
    assert "field_reuse_requires_input_bindings" not in {
        issue.id for issue in satisfied_issues
    }
    # A text-output reference to the producer is not structured reuse.
    text_only_issues = evaluate_critic_invariants(
        build_conversation_critic_context(conversation, text_only_spec)
    )
    assert "field_reuse_requires_input_bindings" in {
        issue.id for issue in text_only_issues
    }


def test_field_reuse_with_only_a_terminal_producer_is_unsatisfiable() -> None:
    # The reviewer's probe: TEXT -> terminal JSON, reuse requested, terminal
    # step bound only to the earlier text. Nothing can consume the fields.
    spec = FlowDraftSpecCore(
        flow_name="Reuse",
        steps=[
            _step("step_a", "Läs", "Läs materialet.", output_type=OutputType.TEXT),
            _step(
                "step_b",
                "Extrahera",
                "Extrahera specifika fälten.",
                input_source=InputSource.PREVIOUS_STEP,
                output_type=OutputType.JSON,
                output_contract={
                    "type": "object",
                    "properties": {"beslut": {"type": "array"}},
                },
                input_bindings={"text": "step_a.output.text"},
            ),
        ],
    )

    issues = evaluate_critic_invariants(
        build_conversation_critic_context(
            [
                {
                    "role": "user",
                    "content": "Extrahera specifika fälten och använd fälten i nästa steg.",
                }
            ],
            spec,
        )
    )

    assert "field_reuse_requires_input_bindings" in {issue.id for issue in issues}


def test_declared_terminal_json_contract_satisfies_explicit_request() -> None:
    planning_state = PlanningState.empty()
    planning_state.resolved_slots["terminal_output"] = ResolvedSlot(
        name="terminal_output",
        value="structured_json",
        source="structured_answer",
        confidence="high",
        evidence=["question_answer:terminal_output"],
    )
    terminal_json_spec = FlowDraftSpecCore(
        flow_name="Extraktion",
        steps=[
            _step(
                "step_a",
                "Extrahera",
                "Extrahera fälten.",
                output_type=OutputType.JSON,
                output_contract={
                    "type": "object",
                    "properties": {"beslut": {"type": "array"}},
                },
            )
        ],
    )

    issues = evaluate_critic_invariants(
        build_conversation_critic_context(
            [{"role": "user", "content": "Jag vill ha JSON."}],
            terminal_json_spec,
            planning_state=planning_state,
        )
    )

    assert "explicit_json_contract_request_without_step" not in {
        issue.id for issue in issues
    }


def test_action_followup_roles_must_survive_into_the_outcome_contract() -> None:
    planning_state = PlanningState.empty()
    planning_state.resolved_slots["post_processing_goal"] = ResolvedSlot(
        name="post_processing_goal",
        value="action_followup",
        source="structured_answer",
        confidence="high",
        evidence=["question_answer:post_processing_goal"],
    )
    # decisions/actions only in step one; the terminal contract drops them —
    # a union across steps would wrongly accept this lossy topology.
    split_spec = FlowDraftSpecCore(
        flow_name="Follow-up",
        steps=[
            _step(
                "step_a",
                "Extract decisions",
                "Extract decisions and actions.",
                output_type=OutputType.JSON,
                output_contract={
                    "type": "object",
                    "properties": {
                        "decisions": {"type": "array"},
                        "actions": {"type": "array"},
                    },
                },
            ),
            _step(
                "step_b",
                "Assign follow-up",
                "Assign owners and deadlines.",
                input_source=InputSource.PREVIOUS_STEP,
                output_type=OutputType.JSON,
                output_contract={
                    "type": "object",
                    "properties": {
                        "owners": {"type": "array"},
                        "deadlines": {"type": "array"},
                        "open_questions": {"type": "array"},
                    },
                },
            ),
        ],
    )

    issues = evaluate_critic_invariants(
        build_conversation_critic_context(
            [{"role": "user", "content": "Use this material."}],
            split_spec,
            planning_state=planning_state,
        )
    )

    assert "action_followup_requires_followup_fields" in {issue.id for issue in issues}


def test_create_critic_leaves_sectioned_form_field_placement_to_assembly() -> None:
    spec = FlowDraftSpecCore(
        flow_name="Formulär till rapport",
        flow_description="",
        steps=[
            _step(
                "step_a",
                "Sammanställ rapport",
                "Sammanställ användarens svar.",
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
                output_type=OutputType.TEXT,
            )
        ],
    )
    planning_state = PlanningState.empty()
    planning_state.signals = [
        PlanningSignal(
            question_id="form_intake_pattern",
            value="sectioned_form_intake",
            confidence="high",
            source="model",
            provenance=["quote:fritext under varje rubrik"],
        )
    ]
    context = build_conversation_critic_context(
        [{"role": "user", "content": "Bygg flödet enligt beskrivningen."}],
        spec,
        planning_state=planning_state,
    )

    issue_ids = {issue.id for issue in evaluate_critic_invariants(context)}
    assert "sectioned_form_intake_requires_form_fields" not in issue_ids


def test_unreferenced_form_field_guard_is_edit_only() -> None:
    spec = FlowDraftSpecCore(
        flow_name="Onboarding",
        form_fields=[FormFieldSpec(name="prioritet", type="text", label="Prioritet")],
        steps=[_step("step_a", "Hantera ärende", "Behandla ärendet.")],
    )
    create_context = build_conversation_critic_context([], spec)
    edit_context = build_conversation_critic_context([], spec, flow=_edit_flow())

    assert "form_fields_declared_must_be_referenced" not in {
        issue.id for issue in evaluate_critic_invariants(create_context)
    }
    assert "form_fields_declared_must_be_referenced" in {
        issue.id for issue in evaluate_critic_invariants(edit_context)
    }


def _pdf_mismatch_context() -> "CriticContext":
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
        steps=[
            _step(
                "step_a",
                "Skriv rapport",
                "Skriv en rapport.",
                output_type=OutputType.TEXT,
            )
        ],
    )
    return build_conversation_critic_context(conversation, spec, flow=_edit_flow())


_CREATE_GATED_ARCHITECTURE_INVARIANT_IDS = (
    "pdf_terminal_output_alignment",
    "docx_terminal_output_alignment",
    "standalone_audio_requires_transcription_step",
    "multi_document_compare_requires_all_previous_steps",
)


def _create_gated_architecture_context(
    invariant_id: str,
    *,
    flow: "Flow | None",
) -> "CriticContext":
    from eneo.flows.ai_builder.ai_builder_critic_invariants import CriticContext
    from eneo.flows.ai_builder.ai_builder_framework_policy import (
        OutputIntentResolution,
    )

    terminal_output: str | None = None
    primary_runtime_input = "unknown"
    aggregation_intent = "linear"

    match invariant_id:
        case "pdf_terminal_output_alignment":
            terminal_output = "pdf_document"
            spec = FlowDraftSpecCore(
                flow_name="Rapport",
                steps=[_step("step_a", "Skriv rapport", "Skriv rapporten.")],
            )
        case "docx_terminal_output_alignment":
            terminal_output = "docx_document"
            spec = FlowDraftSpecCore(
                flow_name="Rapport",
                steps=[_step("step_a", "Skriv rapport", "Skriv rapporten.")],
            )
        case "standalone_audio_requires_transcription_step":
            primary_runtime_input = "audio"
            spec = FlowDraftSpecCore(
                flow_name="Mötesrapport",
                steps=[_step("step_a", "Sammanfatta", "Sammanfatta texten.")],
            )
        case "multi_document_compare_requires_all_previous_steps":
            aggregation_intent = "compare"
            spec = FlowDraftSpecCore(
                flow_name="Jämför dokument",
                steps=[
                    _step("step_a", "Läs första dokumentet", "Extrahera första delen."),
                    _step(
                        "step_b",
                        "Jämför dokument",
                        "Jämför dokumenten.",
                        input_source=InputSource.PREVIOUS_STEP,
                    ),
                ],
            )
        case _:
            raise AssertionError(f"Unhandled invariant id: {invariant_id}")

    return CriticContext(
        spec=spec,
        flow=flow,
        answer_signals={},
        text="",
        sectioned_form_intake=False,
        runtime_form_fields_requested=False,
        runtime_form_fields_evidence=(),
        simple_text_transform=False,
        output_intent=OutputIntentResolution(terminal_output=terminal_output),
        mixed_audio_doc_input=False,
        primary_runtime_input=cast("PrimaryRuntimeInput", primary_runtime_input),
        aggregation_intent=cast("AggregationIntent", aggregation_intent),
    )


@pytest.mark.parametrize("invariant_id", _CREATE_GATED_ARCHITECTURE_INVARIANT_IDS)
def test_create_context_suppresses_edit_only_architecture_invariant(
    invariant_id: str,
) -> None:
    context = _create_gated_architecture_context(invariant_id, flow=None)

    issue_ids = {issue.id for issue in evaluate_critic_invariants(context)}

    assert invariant_id not in issue_ids


@pytest.mark.parametrize("invariant_id", _CREATE_GATED_ARCHITECTURE_INVARIANT_IDS)
def test_edit_context_keeps_edit_only_architecture_invariant(
    invariant_id: str,
) -> None:
    context = _create_gated_architecture_context(invariant_id, flow=_edit_flow())

    issue_ids = {issue.id for issue in evaluate_critic_invariants(context)}

    assert invariant_id in issue_ids


def test_critic_invariant_registry_has_stable_kind_map() -> None:
    """The kinds table is the canonical classification; the registry obeys it.

    Equality both ways: the release gate reads the table alone (importing the
    evaluator would drag the application into an offline statistics tool), so a
    registry entry the table does not know, or the reverse, is a silent
    misclassification of what a release verdict scores.
    """

    assert {invariant.id: invariant.kind for invariant in CRITIC_INVARIANTS} == dict(
        CRITIC_INVARIANT_KINDS
    )


def test_evaluate_critic_invariants_returns_issue_metadata() -> None:
    issues = evaluate_critic_invariants(_pdf_mismatch_context())

    assert [(issue.id, issue.kind) for issue in issues] == [
        ("pdf_terminal_output_alignment", "architecture")
    ]
    assert "PDF" in issues[0].remediation


def test_enforce_architecture_critic_invariants_raises_typed_error() -> None:
    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        enforce_architecture_critic_invariants(_pdf_mismatch_context())

    assert exc_info.value.public_code == "architecture_critic_invariant_failed"
    assert (
        exc_info.value.log_context["critic_issue_ids"]
        == "pdf_terminal_output_alignment"
    )


def test_quality_feedback_from_context_can_exclude_architecture_issues() -> None:
    context = _pdf_mismatch_context()

    assert (
        build_quality_feedback_from_critic_context(
            context,
            include_architecture=False,
        )
        is None
    )
    assert (
        build_quality_feedback_from_critic_context(
            context,
            include_architecture=True,
        )
        is not None
    )


def test_quality_feedback_from_context_keeps_semantic_issues() -> None:
    conversation = [
        {
            "role": "user",
            "content": "Add basic metadata",
            "metadata": {
                "question_answer": {
                    "question_id": "runtime_metadata_fields",
                    "selected_values": ["basic_runtime_metadata"],
                }
            },
        }
    ]
    spec = FlowDraftSpecCore(
        flow_name="Dokumentanalys",
        steps=[
            _step(
                "step_a",
                "Analysera dokument",
                "Sammanfatta ärendet.",
                input_type=InputType.DOCUMENT,
            )
        ],
    )
    context = build_conversation_critic_context(
        conversation,
        spec,
        flow=_edit_flow(),
    )

    feedback = build_quality_feedback_from_critic_context(
        context,
        include_architecture=False,
    )

    assert feedback is not None
    assert "form_fields" in feedback


def test_negated_document_artifacts_do_not_trigger_terminal_alignment_for_json() -> (
    None
):
    prompt = (
        "Build a flow that reads a long procurement document and returns strict "
        "JSON with ranked offers, risk flags, and missing information. Do not "
        "create Word, DOCX, PDF, or a document output."
    )
    context = build_conversation_critic_context(
        [{"role": "user", "content": prompt}],
        FlowDraftSpecCore(
            flow_name="Offer ranking",
            steps=[
                _step(
                    "step_json",
                    "Rank offers",
                    "Return ranked offers, risks, and missing information as JSON.",
                    output_type=OutputType.JSON,
                )
            ],
        ),
    )

    issues = evaluate_critic_invariants(context)
    issue_ids = {issue.id for issue in issues}

    assert context.output_intent.terminal_output == "structured_json"
    assert "docx_terminal_output_alignment" not in issue_ids
    assert "pdf_terminal_output_alignment" not in issue_ids


def test_committed_terminal_outranks_negation_blind_text_heuristic() -> None:
    """Committed planning state owns output intent; raw text is fallback only.

    Live repro (declared_terminal_everyday_bygglovsremiss_text, 3/3): the
    prompt names DOCX only to reject it — "ingen PDF, ingen DOCX-mall" —
    and the keyword heuristic resolved docx_document + template_fill_docx.
    The critic then killed a correct text plan for missing a template-fill
    step. The classifier had already committed the terminal correctly.
    """

    prompt = (
        "Vi skickar bygglovsremisser till miljökontoret. Vid körning laddar "
        "jag upp alla inkomna remissvar och vill ha löpande text tillbaka. "
        "Slutresultatet ska vara text — ingen PDF, ingen DOCX-mall och "
        "ingen JSON-fil."
    )
    planning_state = PlanningState.empty()
    planning_state.resolved_slots["terminal_output"] = ResolvedSlot(
        name="terminal_output",
        value="structured_text",
        source="requirements_summary",
        evidence=["requirements_summary.resolved_requirements:terminal_output"],
        confidence="high",
    )
    spec = FlowDraftSpecCore(
        flow_name="Jämför remissyttranden",
        steps=[
            _step(
                "step_text",
                "Jämför yttranden",
                "Jämför remissvaren och skriv löpande text.",
                output_type=OutputType.TEXT,
            )
        ],
    )

    context = build_conversation_critic_context(
        [{"role": "user", "content": prompt}],
        spec,
        planning_state=planning_state,
    )
    issues = evaluate_critic_invariants(context)

    assert context.output_intent.terminal_output == "structured_text"
    assert context.output_intent.docx_output_mode is None
    assert "template_fill_docx_requires_template_fill_step" not in {
        issue.id for issue in issues
    }


def test_committed_docx_mode_outranks_text_heuristic() -> None:
    # Committed generated_docx must silence the template-fill invariant even
    # when the conversation mentions a template it rejects.
    prompt = (
        "Leverera ett DOCX-underlag som genereras ur texten — vi har ingen "
        "bidragsmall att fylla i."
    )
    planning_state = PlanningState.empty()
    planning_state.resolved_slots["terminal_output"] = ResolvedSlot(
        name="terminal_output",
        value="docx_document",
        source="requirements_summary",
        evidence=["requirements_summary.resolved_requirements:terminal_output"],
        confidence="high",
    )
    planning_state.resolved_slots["docx_output_mode"] = ResolvedSlot(
        name="docx_output_mode",
        value="generated_docx",
        source="requirements_summary",
        evidence=["requirements_summary.resolved_requirements:docx_output_mode"],
        confidence="high",
    )
    spec = FlowDraftSpecCore(
        flow_name="Kulturbidrag",
        steps=[
            _step(
                "step_docx",
                "Skriv underlag",
                "Generera ett DOCX-underlag ur texten.",
                output_type=OutputType.DOCX,
            )
        ],
    )

    context = build_conversation_critic_context(
        [{"role": "user", "content": prompt}],
        spec,
        planning_state=planning_state,
    )

    assert context.output_intent.terminal_output == "docx_document"
    assert context.output_intent.docx_output_mode == "generated_docx"


def test_uncommitted_state_keeps_text_derived_intent() -> None:
    # With nothing committed, the heuristic remains the only signal.
    prompt = "Skapa en PDF-rapport av dokumentet."
    context = build_conversation_critic_context(
        [{"role": "user", "content": prompt}],
        FlowDraftSpecCore(
            flow_name="Rapport",
            steps=[
                _step(
                    "step_pdf",
                    "Skriv rapport",
                    "Skriv en rapport.",
                    output_type=OutputType.PDF,
                )
            ],
        ),
        planning_state=PlanningState.empty(),
    )

    assert context.output_intent.terminal_output == "pdf_document"


def test_runtime_metadata_form_field_guard_is_edit_only() -> None:
    conversation = [
        {
            "role": "user",
            "content": "Add basic metadata",
            "metadata": {
                "question_answer": {
                    "question_id": "runtime_metadata_fields",
                    "selected_values": ["basic_runtime_metadata"],
                }
            },
        }
    ]
    spec = FlowDraftSpecCore(
        flow_name="Dokumentanalys",
        steps=[
            _step(
                "step_a",
                "Analysera dokument",
                "Sammanfatta ärendet.",
                input_type=InputType.DOCUMENT,
            )
        ],
    )

    create_context = build_conversation_critic_context(conversation, spec)
    edit_context = build_conversation_critic_context(
        conversation,
        spec,
        flow=_edit_flow(),
    )

    assert "runtime_metadata_requires_form_fields" not in {
        issue.id for issue in evaluate_critic_invariants(create_context)
    }
    assert "runtime_metadata_requires_form_fields" in {
        issue.id for issue in evaluate_critic_invariants(edit_context)
    }


def test_no_input_fields_instruction_does_not_request_runtime_form_fields() -> None:
    conversation = [
        {
            "role": "user",
            "content": (
                "Jag vill bygga ett flöde där användaren skickar in mötesljud, "
                "flödet transkriberar ljudet och skapar en Word-rapport med "
                "rubriker. Inmatningsfält behövs inte."
            ),
        }
    ]
    spec = FlowDraftSpecCore(
        flow_name="Mötesrapport",
        steps=[
            _step(
                "step_a",
                "Transkribera ljud",
                "Transkribera mötesljudet.",
                input_type=InputType.AUDIO,
            ),
            _step(
                "step_b",
                "Skapa Word-rapport",
                "Skapa Word-rapporten från transkriptionen.",
                input_source=InputSource.PREVIOUS_STEP,
                output_type=OutputType.DOCX,
            ),
        ],
    )
    context = build_conversation_critic_context(conversation, spec)

    issue_ids = {issue.id for issue in evaluate_critic_invariants(context)}

    assert "runtime_metadata_requires_form_fields" not in issue_ids


def test_audio_docx_report_fields_from_transcript_do_not_request_runtime_form_fields() -> (
    None
):
    conversation = [
        {
            "role": "user",
            "content": (
                "Bygg ett generellt transkriptionsflöde. Användaren laddar upp "
                "en ljudfil vid körning. Flödet ska transkribera ljudet, "
                "extrahera fakta från transkriptionen och skapa en DOCX-rapport. "
                "Användaren ska inte fylla i extra formulärfält, metadatafält "
                "eller inmatningsfält vid körning. Alla rapportfält ska hämtas "
                "från ljudet/transkriberingen: datum, källa, språk i ljudet, "
                "ljudkvalitet, namn, kontaktuppgifter, risker och osäkerheter. "
                "Om något saknas ska rapporten skriva Ej nämnt i underlaget."
            ),
        }
    ]
    spec = FlowDraftSpecCore(
        flow_name="Transkriptionsrapport",
        steps=[
            _step(
                "step_audio",
                "Transkribera ljud",
                "Transkribera ljudfilen.",
                input_type=InputType.AUDIO,
                output_type=OutputType.TEXT,
                output_mode=OutputMode.TRANSCRIBE_ONLY,
            ),
            _step(
                "step_extract",
                "Extrahera rapportfakta",
                (
                    "Extrahera datum, källa, språk, ljudkvalitet, namn, "
                    "kontaktuppgifter, risker och osäkerheter från transkriptionen. "
                    "Skriv Ej nämnt i underlaget när uppgift saknas."
                ),
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_type=OutputType.JSON,
                output_contract={
                    "type": "object",
                    "required": ["rapportfakta"],
                    "properties": {"rapportfakta": {"type": "object"}},
                    "additionalProperties": False,
                },
            ),
            _step(
                "step_docx",
                "Skapa DOCX-rapport",
                "Skapa DOCX-rapporten från extraherade rapportfakta.",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.JSON,
                output_type=OutputType.DOCX,
            ),
        ],
    )

    feedback = build_conversation_aware_quality_feedback(conversation, spec)

    assert feedback is None


def test_edit_flags_missing_form_fields_for_sectioned_rubric_intake_flows() -> None:
    conversation = [
        {
            "role": "user",
            "content": (
                "Visa en sektion i taget, be användaren om fritext för varje sektion, "
                "spara innehållet separat per rubrik och skapa sedan ett DOCX-dokument."
            ),
        }
    ]
    spec = FlowDraftSpecCore(
        flow_name="Sammanställning",
        steps=[
            _step(
                "step_a",
                "Samla in sektion 1",
                "Be användaren skriva om första rubriken.",
                input_type=InputType.TEXT,
                output_type=OutputType.JSON,
                output_contract={
                    "type": "object",
                    "properties": {
                        "sektion_1": {"type": "string"},
                    },
                },
            ),
            _step(
                "step_b",
                "Generera DOCX",
                "Skapa slutligt DOCX.",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.JSON,
                output_type=OutputType.DOCX,
            ),
        ],
    )

    feedback = build_conversation_aware_quality_feedback(
        conversation,
        spec,
        flow=_edit_flow(),
    )

    assert feedback is not None
    assert "form_fields" in feedback
    assert "rubrik" in feedback.lower()


def test_does_not_flag_form_fields_for_output_only_heading_requirements() -> None:
    conversation = [
        {
            "role": "user",
            "content": (
                "Slutrapporten ska innehålla rubrikerna Planering och hälsa, "
                "Tidigare insatser och Ekonomi."
            ),
        }
    ]
    spec = FlowDraftSpecCore(
        flow_name="Rapport",
        steps=[
            _step(
                "step_a",
                "Skriv rapport",
                "Skriv rapport med dessa rubriker.",
                output_type=OutputType.DOCX,
            )
        ],
    )

    feedback = build_conversation_aware_quality_feedback(conversation, spec)

    assert feedback is None


def test_does_not_flag_form_fields_for_swedish_source_document_sections() -> None:
    conversation = [
        {
            "role": "user",
            "content": (
                "Skapa ett flöde som ska få ett worddokument uppladdat som input. "
                "Därefter ska detta dokument analyseras för att skriva olika "
                "rubriker och underliggande texter, där varje rubrik och text "
                "skall skrivas utifrån det ursprungliga dokumentet som helhet "
                "varje gång. Rubrik: Resursåtgång i form av tidsuppskattning "
                "och personella resurser. Ange i nedan tabell vilka roller och "
                "kompetenser som behövs. Rubrik: Ekonomisk nytta och kostnader. "
                "Om en nyttokalkyl EJ upprättas ska istället följande anges i "
                "detta avsnitt: Ange beräknad totalkostnad för genomförandet av "
                "lösningsförslaget. När alla steg är klara så ska det i "
                "slutändan skapas ett worddokument som output."
            ),
        }
    ]
    spec = FlowDraftSpecCore(
        flow_name="Utvecklingsärende",
        steps=[
            _step(
                "step_extract",
                "Extrahera utvecklingsärende",
                "Extrahera rubriker och underlag från det uppladdade dokumentet.",
                input_type=InputType.DOCUMENT,
                output_type=OutputType.JSON,
                output_contract={
                    "type": "object",
                    "required": ["sections"],
                    "properties": {
                        "sections": {
                            "type": "array",
                            "items": {"type": "object"},
                        }
                    },
                    "additionalProperties": False,
                },
            ),
            _step(
                "step_docx",
                "Skapa Word-dokument",
                "Skapa slutligt Word-dokument från extraherade sektioner.",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.JSON,
                output_type=OutputType.DOCX,
            ),
        ],
    )

    feedback = build_conversation_aware_quality_feedback(conversation, spec)

    assert feedback is None


def test_does_not_flag_sectioned_rubric_intake_when_form_fields_are_present() -> None:
    conversation = [
        {
            "role": "user",
            "content": (
                "Visa en sektion i taget, be användaren om fritext för varje sektion, "
                "spara innehållet separat per rubrik och skapa sedan ett DOCX-dokument."
            ),
        }
    ]
    spec = FlowDraftSpecCore(
        flow_name="Sammanställning",
        form_fields=[
            FormFieldSpec(
                name="planering_och_halsa", type="text", label="Planering och hälsa"
            ),
            FormFieldSpec(
                name="tidigare_insatser", type="text", label="Tidigare insatser"
            ),
        ],
        steps=[
            _step(
                "step_a",
                "Sammanställ underlag",
                (
                    "Sammanställ sektionerna {{ planering_och_halsa }} "
                    "och {{ tidigare_insatser }} till ett DOCX."
                ),
                output_type=OutputType.DOCX,
            )
        ],
    )

    feedback = build_conversation_aware_quality_feedback(conversation, spec)

    assert feedback is None


def test_flags_output_mismatch_against_explicit_pdf_choice() -> None:
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
        steps=[
            _step(
                "step_a",
                "Skriv rapport",
                "Skriv en rapport.",
                output_type=OutputType.TEXT,
            )
        ],
    )

    feedback = build_conversation_aware_quality_feedback(
        conversation,
        spec,
        flow=_edit_flow(),
    )
    assert feedback is not None
    assert "PDF" in feedback


def test_flags_template_fill_when_generated_docx_was_explicitly_selected() -> None:
    conversation = [
        {
            "role": "user",
            "content": "ändra så att jag får ut en word dokument istället för en pdf",
            "metadata": {"ui_language": "sv"},
        },
        {
            "role": "user",
            "content": "Genererat Word-dokument utan mall",
            "metadata": {
                "question_answer": {
                    "question_id": "docx_output_mode",
                    "selected_value": "generated_docx",
                    "answer": "generated_docx",
                }
            },
        },
    ]
    spec = FlowDraftSpecCore(
        flow_name="Rapport",
        steps=[
            _step(
                "step_a",
                "Generera rapport",
                "Skapa ett Word-dokument.",
                output_type=OutputType.DOCX,
                output_mode=OutputMode.TEMPLATE_FILL,
            )
        ],
    )

    feedback = build_conversation_aware_quality_feedback(conversation, spec)
    assert feedback is not None
    assert "genererad DOCX" in feedback
    assert "template_fill" in feedback


def test_flags_missing_structured_extraction_when_user_asked_for_structured_fields() -> (
    None
):
    conversation = [
        {
            "role": "user",
            "content": (
                "Flödet ska extrahera viktiga fakta, risker, möjligheter och rekommendationer "
                "och använda strukturerad data där det förbättrar kvaliteten."
            ),
        }
    ]
    spec = FlowDraftSpecCore(
        flow_name="Dokumentanalys",
        steps=[
            _step(
                "step_a",
                "Läs dokument",
                "Läs dokumentet och skriv en lång text.",
                input_type=InputType.DOCUMENT,
            ),
            _step(
                "step_b",
                "Skriv slutrapport",
                "Skriv en slutrapport baserat på föregående steg.",
                input_source=InputSource.PREVIOUS_STEP,
            ),
        ],
    )

    feedback = build_conversation_aware_quality_feedback(conversation, spec)
    assert feedback is not None
    assert "json" in feedback.lower()
    assert "output_contract" in feedback


def test_does_not_overstructure_simple_single_step_summary() -> None:
    conversation = [
        {"role": "user", "content": "Summarize one uploaded document as plain text."}
    ]
    spec = FlowDraftSpecCore(
        flow_name="Kort sammanfattning",
        steps=[_step("step_a", "Sammanfatta", "Skriv en kort sammanfattning.")],
    )

    assert build_conversation_aware_quality_feedback(conversation, spec) is None


def test_flags_direct_text_transform_with_unrequested_json_and_steps() -> None:
    conversation = [
        {
            "role": "user",
            "content": "Översätt den här meningen till engelska: Vi ses imorgon.",
        }
    ]
    spec = FlowDraftSpecCore(
        flow_name="Översättning",
        steps=[
            _step(
                "step_a",
                "Analysera språk",
                "Identifiera språk och ton.",
                output_type=OutputType.JSON,
                output_contract={"type": "object", "properties": {}},
            ),
            _step(
                "step_b",
                "Översätt",
                "Översätt till engelska.",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.JSON,
            ),
        ],
    )

    issues = evaluate_critic_invariants(
        build_conversation_critic_context(conversation, spec)
    )

    assert [
        issue.id
        for issue in issues
        if issue.id == "simple_text_transform_must_remain_single_step"
    ] == ["simple_text_transform_must_remain_single_step"]


def test_direct_text_transform_accepts_single_text_step() -> None:
    conversation = [
        {
            "role": "user",
            "content": "Translate this sentence to English: Vi ses imorgon.",
        }
    ]
    spec = FlowDraftSpecCore(
        flow_name="Translate sentence",
        steps=[_step("step_a", "Translate", "Translate the supplied text to English.")],
    )

    assert build_conversation_aware_quality_feedback(conversation, spec) is None


def test_direct_text_transform_restraint_does_not_collapse_quality_chain() -> None:
    conversation = [
        {
            "role": "user",
            "content": (
                "Translate the paragraph, let a separate critique step review "
                "clarity, and write a final version using the critique."
            ),
        }
    ]
    spec = FlowDraftSpecCore(
        flow_name="Reviewed translation",
        steps=[
            _step("step_a", "Translate", "Translate the paragraph."),
            _step(
                "step_b",
                "Critique",
                "Review clarity and factuality.",
                input_source=InputSource.PREVIOUS_STEP,
            ),
            _step(
                "step_c",
                "Final version",
                "Revise using the critique.",
                input_source=InputSource.PREVIOUS_STEP,
            ),
        ],
    )

    issues = evaluate_critic_invariants(
        build_conversation_critic_context(conversation, spec)
    )

    assert not any(
        issue.id == "simple_text_transform_must_remain_single_step" for issue in issues
    )


def test_direct_text_transform_restraint_ignores_form_field_driven_transform() -> None:
    conversation = [
        {
            "role": "user",
            "content": "Translate the text provided in the runtime input field target_text.",
        }
    ]
    spec = FlowDraftSpecCore(
        flow_name="Translate runtime text",
        form_fields=[
            FormFieldSpec(
                name="target_text",
                label="Target text",
                type="text",
            )
        ],
        steps=[_step("step_a", "Translate", "Translate the target_text value.")],
    )

    issues = evaluate_critic_invariants(
        build_conversation_critic_context(conversation, spec)
    )

    assert not any(
        issue.id == "simple_text_transform_must_remain_single_step" for issue in issues
    )


def test_direct_text_transform_restraint_applies_in_edit_context() -> None:
    from uuid import uuid4

    from eneo.flows.domain.flow import Flow, FlowStep

    flow = Flow(
        id=uuid4(),
        tenant_id=uuid4(),
        space_id=uuid4(),
        name="Translate text",
        steps=[
            FlowStep(
                assistant_id=uuid4(),
                step_order=1,
                user_description="Translate text",
                input_source="flow_input",
                input_type="text",
                output_mode="pass_through",
                output_type="text",
            )
        ],
    )
    conversation = [
        {
            "role": "user",
            "content": "Ändra flödet så att det översätter meningen till franska.",
        }
    ]
    spec = FlowDraftSpecCore(
        flow_name="Translate text",
        steps=[
            _step(
                "step_a",
                "Analysera språk",
                "Identifiera språk innan översättning.",
                output_type=OutputType.JSON,
                output_contract={"type": "object", "properties": {}},
            ),
            _step(
                "step_b",
                "Translate",
                "Translate to French.",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.JSON,
            ),
        ],
    )

    issues = evaluate_critic_invariants(
        build_conversation_critic_context(conversation, spec, flow=flow)
    )

    assert any(
        issue.id == "simple_text_transform_must_remain_single_step" for issue in issues
    )


def test_flags_edit_plan_that_fakes_audio_transcription_by_downgrading_to_generic_file() -> (
    None
):
    from uuid import uuid4

    from eneo.flows.domain.flow import Flow, FlowStep

    flow = Flow(
        id=uuid4(),
        tenant_id=uuid4(),
        space_id=uuid4(),
        name="Dokumentanalys",
        steps=[
            FlowStep(
                assistant_id=uuid4(),
                step_order=1,
                user_description="Analysera dokument",
                input_source="flow_input",
                input_type="document",
                output_mode="pass_through",
                output_type="json",
            ),
            FlowStep(
                assistant_id=uuid4(),
                step_order=2,
                user_description="Skriv rapport",
                input_source="previous_step",
                input_type="json",
                output_mode="pass_through",
                output_type="pdf",
            ),
        ],
    )
    conversation = [
        {
            "role": "user",
            "content": (
                "Behåll samma flöde men lägg till ljudfiler och transkribera samtalet först, "
                "och skicka sedan in dokument som vanligt. Jag vill fortfarande ha PDF ut."
            ),
        }
    ]
    spec = FlowDraftSpecCore(
        flow_name="Dokumentanalys",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                existing_step_ref="existing_step_1",
                name="Analysera underlag",
                assistant_spec=AssistantSpec(
                    instructions=(
                        "Läs ett blandat underlag med samtal och dokument, återge samtalet "
                        "och returnera giltig JSON."
                    )
                ),
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.FILE,
                output_type=OutputType.JSON,
            ),
            StepSpec(
                plan_step_ref="step_b",
                existing_step_ref="existing_step_2",
                name="Skriv rapport",
                assistant_spec=AssistantSpec(instructions="Skriv PDF-rapport."),
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.JSON,
                output_type=OutputType.PDF,
            ),
        ],
    )

    feedback = build_conversation_aware_quality_feedback(conversation, spec, flow=flow)

    assert feedback is not None
    assert 'input_type="file"' in feedback
    assert "transkriberingssteg" in feedback
    assert "flow_input" in feedback


def test_allows_audio_first_edit_when_plan_uses_real_transcription_step() -> None:
    from uuid import uuid4

    from eneo.flows.domain.flow import Flow, FlowStep

    flow = Flow(
        id=uuid4(),
        tenant_id=uuid4(),
        space_id=uuid4(),
        name="Dokumentanalys",
        steps=[
            FlowStep(
                assistant_id=uuid4(),
                step_order=1,
                user_description="Analysera dokument",
                input_source="flow_input",
                input_type="document",
                output_mode="pass_through",
                output_type="json",
            ),
            FlowStep(
                assistant_id=uuid4(),
                step_order=2,
                user_description="Skriv rapport",
                input_source="previous_step",
                input_type="json",
                output_mode="pass_through",
                output_type="pdf",
            ),
        ],
    )
    conversation = [
        {
            "role": "user",
            "content": "Byt till ljud som primär indata och transkribera först. Behåll PDF ut.",
            "metadata": {
                "question_answer": {
                    "question_id": "flow_input_architecture",
                    "selected_value": "audio_primary_input",
                }
            },
        }
    ]
    spec = FlowDraftSpecCore(
        flow_name="Dokumentanalys",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Transkribera ljud",
                assistant_spec=AssistantSpec(instructions="Transkribera ljudet."),
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.AUDIO,
                output_mode=OutputMode.TRANSCRIBE_ONLY,
                output_type=OutputType.TEXT,
            ),
            StepSpec(
                plan_step_ref="step_b",
                name="Analysera samtalet",
                assistant_spec=AssistantSpec(
                    instructions="Analysera transkriberingen."
                ),
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_type=OutputType.PDF,
            ),
        ],
    )

    assert (
        build_conversation_aware_quality_feedback(conversation, spec, flow=flow) is None
    )


# ── R7: Anti-over-structuring guardrail ──────────────────────────────────


def test_anti_over_structuring_simple_summary_no_json_warning() -> None:
    """R7: Simple summary -> text output, NO JSON warning."""
    conversation = [{"role": "user", "content": "Sammanfatta dokument som text."}]
    spec = FlowDraftSpecCore(
        flow_name="Sammanfattning",
        steps=[
            _step(
                "step_a",
                "Sammanfatta",
                "Skriv en kort sammanfattning.",
                output_type=OutputType.TEXT,
            )
        ],
    )
    assert build_conversation_aware_quality_feedback(conversation, spec) is None


def test_json_contract_critic_uses_typed_schema_and_result_goal() -> None:
    spec = FlowDraftSpecCore(
        flow_name="Process material",
        steps=[
            _step(
                "step_a",
                "Process source",
                "Process the supplied material.",
                input_type=InputType.DOCUMENT,
            )
        ],
    )
    planning_state = PlanningState.empty()
    planning_state.resolved_slots = {
        "terminal_output": ResolvedSlot(
            name="terminal_output",
            value="structured_text",
            source="structured_answer",
            confidence="high",
            evidence=["question_answer:terminal_output"],
        ),
        "post_processing_goal": ResolvedSlot(
            name="post_processing_goal",
            value="extract_key_information",
            source="structured_answer",
            confidence="high",
            evidence=["question_answer:post_processing_goal"],
        ),
    }
    planning_state.output_schema_evidence = build_schema_evidence(
        json_schema={
            "type": "object",
            "properties": {"result": {"type": "string"}},
        },
        source="declared_schema",
        confidence="high",
        evidence=("message:test-source",),
    )
    summarize_state = PlanningState.empty()
    summarize_state.resolved_slots["terminal_output"] = ResolvedSlot(
        name="terminal_output",
        value="structured_text",
        source="structured_answer",
        confidence="high",
        evidence=["question_answer:terminal_output"],
    )
    summarize_state.resolved_slots["post_processing_goal"] = ResolvedSlot(
        name="post_processing_goal",
        value="summarize_or_overview",
        source="structured_answer",
        confidence="high",
        evidence=["question_answer:post_processing_goal"],
    )
    structured_json_summary_state = summarize_state.model_copy(deep=True)
    structured_json_summary_state.resolved_slots["terminal_output"] = ResolvedSlot(
        name="terminal_output",
        value="structured_json",
        source="structured_answer",
        confidence="high",
        evidence=["question_answer:terminal_output"],
    )
    explicit_schema_summary_state = planning_state.model_copy(deep=True)
    explicit_schema_summary_state.resolved_slots["post_processing_goal"] = ResolvedSlot(
        name="post_processing_goal",
        value="summarize_or_overview",
        source="structured_answer",
        confidence="high",
        evidence=["question_answer:post_processing_goal"],
    )
    structured_io_summary_state = summarize_state.model_copy(deep=True)
    structured_io_summary_state.resolved_slots["structured_io_contract"] = ResolvedSlot(
        name="structured_io_contract",
        value="map_to_new_schema",
        source="structured_answer",
        confidence="high",
        evidence=["question_answer:structured_io_contract"],
    )
    heuristic_structured_io_state = PlanningState.empty()
    heuristic_structured_io_state.resolved_slots = {
        "terminal_output": ResolvedSlot(
            name="terminal_output",
            value="structured_text",
            source="structured_answer",
            confidence="high",
            evidence=["question_answer:terminal_output"],
        ),
        "post_processing_goal": ResolvedSlot(
            name="post_processing_goal",
            value="extract_key_information",
            source="structured_answer",
            confidence="high",
            evidence=["question_answer:post_processing_goal"],
        ),
        "structured_io_contract": ResolvedSlot(
            name="structured_io_contract",
            value="map_to_new_schema",
            source="heuristic",
            confidence="high",
            evidence=["heuristic:structured output wording"],
        ),
    }

    extraction_issues = evaluate_critic_invariants(
        build_conversation_critic_context(
            [{"role": "user", "content": "Use this material."}],
            spec,
            planning_state=planning_state,
        )
    )
    summary_issues = evaluate_critic_invariants(
        build_conversation_critic_context(
            [{"role": "user", "content": "Use this material."}],
            spec,
            planning_state=summarize_state,
        )
    )
    structured_json_summary_issues = evaluate_critic_invariants(
        build_conversation_critic_context(
            [{"role": "user", "content": "Use this material."}],
            spec,
            planning_state=structured_json_summary_state,
        )
    )
    explicit_schema_summary_issues = evaluate_critic_invariants(
        build_conversation_critic_context(
            [{"role": "user", "content": "Use this material."}],
            spec,
            planning_state=explicit_schema_summary_state,
        )
    )
    structured_io_summary_issues = evaluate_critic_invariants(
        build_conversation_critic_context(
            [{"role": "user", "content": "Use this material."}],
            spec,
            planning_state=structured_io_summary_state,
        )
    )
    heuristic_structured_io_issues = evaluate_critic_invariants(
        build_conversation_critic_context(
            [{"role": "user", "content": "Use this material."}],
            spec,
            planning_state=heuristic_structured_io_state,
        )
    )

    assert "explicit_json_contract_request_without_step" in {
        issue.id for issue in extraction_issues
    }
    assert "explicit_json_contract_request_without_step" not in {
        issue.id for issue in summary_issues
    }
    assert "explicit_json_contract_request_without_step" in {
        issue.id for issue in structured_json_summary_issues
    }
    assert "explicit_json_contract_request_without_step" in {
        issue.id for issue in explicit_schema_summary_issues
    }
    assert "explicit_json_contract_request_without_step" in {
        issue.id for issue in structured_io_summary_issues
    }
    assert "explicit_json_contract_request_without_step" not in {
        issue.id for issue in heuristic_structured_io_issues
    }


def test_no_json_warning_when_spec_already_has_json_step() -> None:
    """No warning when the spec already has a JSON contract step."""
    conversation = [
        {"role": "user", "content": "Extrahera fält som JSON och skicka vidare."}
    ]
    spec = FlowDraftSpecCore(
        flow_name="Extraktion",
        steps=[
            _step(
                "step_a",
                "Extrahera",
                "Extrahera.",
                input_type=InputType.DOCUMENT,
                output_type=OutputType.JSON,
                output_contract={
                    "type": "object",
                    "properties": {"risk": {"type": "string"}},
                },
            ),
            _step(
                "step_b",
                "Rapport",
                "Skriv rapport.",
                input_source=InputSource.PREVIOUS_STEP,
            ),
        ],
    )
    assert build_conversation_aware_quality_feedback(conversation, spec) is None


def test_flags_missing_input_bindings_for_field_reuse() -> None:
    conversation = [
        {
            "role": "user",
            "content": "Extrahera fält som JSON och använd de specifika fälten i nästa steg.",
        }
    ]
    spec = FlowDraftSpecCore(
        flow_name="Fältåteranvändning",
        steps=[
            _step(
                "step_a",
                "Extrahera",
                "Extrahera.",
                input_type=InputType.DOCUMENT,
                output_type=OutputType.JSON,
                output_contract={
                    "type": "object",
                    "properties": {"risk": {"type": "string"}},
                },
            ),
            _step(
                "step_b",
                "Rapport",
                "Skriv rapport baserat på JSON.",
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
            ),
        ],
    )
    feedback = build_conversation_aware_quality_feedback(conversation, spec)
    assert feedback is not None
    assert "uses_previous_fields" in feedback


def test_flags_missing_explicit_fan_in_for_multi_document_compare() -> None:
    conversation = [
        {
            "role": "user",
            "content": "Jämför flera dokument i samma körning och skriv en sammanfattning.",
        }
    ]
    spec = FlowDraftSpecCore(
        flow_name="Jämförelse",
        steps=[
            _step(
                "step_a",
                "Analysera",
                "Analysera dokument.",
                input_type=InputType.DOCUMENT,
            ),
            _step(
                "step_b",
                "Sammanfatta",
                "Skriv sammanfattning.",
                input_source=InputSource.PREVIOUS_STEP,
            ),
        ],
    )
    feedback = build_conversation_aware_quality_feedback(
        conversation,
        spec,
        flow=_edit_flow(),
        aggregation_intent="compare",
    )
    assert feedback is not None
    assert "source_refs" in feedback


def test_accepts_source_refs_fan_in_for_multi_document_compare() -> None:
    conversation = [
        {
            "role": "user",
            "content": "Jämför flera dokument i samma körning och skriv en sammanfattning.",
        }
    ]
    spec = FlowDraftSpecCore(
        flow_name="Jämförelse",
        steps=[
            _step(
                "step_a",
                "Extrahera avtal A",
                "Extrahera viktiga villkor från första avtalet.",
                input_type=InputType.DOCUMENT,
                output_type=OutputType.JSON,
                output_contract={
                    "type": "object",
                    "properties": {
                        "terms": {"type": "array", "items": {"type": "string"}}
                    },
                },
            ),
            _step(
                "step_b",
                "Extrahera avtal B",
                "Extrahera viktiga villkor från andra avtalet.",
                input_source=InputSource.PREVIOUS_STEP,
                output_type=OutputType.JSON,
                output_contract={
                    "type": "object",
                    "properties": {
                        "terms": {"type": "array", "items": {"type": "string"}}
                    },
                },
            ),
            _step(
                "step_c",
                "Jämför avtalen",
                "Jämför villkoren och skriv en kort sammanfattning.",
                input_source=InputSource.PREVIOUS_STEP,
                input_bindings={
                    "source_refs": [
                        {"step_ref": "step_a", "output": "structured"},
                        {"step_ref": "step_b", "output": "structured"},
                    ]
                },
            ),
        ],
    )

    context = build_conversation_critic_context(
        conversation,
        spec,
        flow=_edit_flow(),
        aggregation_intent="compare",
    )
    issue_ids = {issue.id for issue in evaluate_critic_invariants(context)}

    assert "multi_document_compare_requires_all_previous_steps" not in issue_ids


def test_does_not_require_explicit_fan_in_for_aggregate_intent() -> None:
    conversation = [
        {
            "role": "user",
            "content": "Skapa ett samlat PDF- eller Word-underlag från dokumentet.",
        }
    ]
    spec = FlowDraftSpecCore(
        flow_name="Samlad rapport",
        steps=[
            _step(
                "step_a",
                "Analysera",
                "Analysera dokument.",
                input_type=InputType.DOCUMENT,
            ),
            _step(
                "step_b",
                "Sammanfatta",
                "Skriv sammanfattning.",
                input_source=InputSource.PREVIOUS_STEP,
            ),
        ],
    )
    feedback = build_conversation_aware_quality_feedback(
        conversation,
        spec,
        aggregation_intent="aggregate",
    )
    assert feedback is None or "source_refs" not in feedback


def test_does_not_infer_fan_in_from_conversation_words_without_architecture() -> None:
    conversation = [
        {
            "role": "user",
            "content": "Jämför flera dokument i samma körning och skriv en sammanfattning.",
        }
    ]
    spec = FlowDraftSpecCore(
        flow_name="Jämförelse",
        steps=[
            _step(
                "step_a",
                "Analysera",
                "Analysera dokument.",
                input_type=InputType.DOCUMENT,
            ),
            _step(
                "step_b",
                "Sammanfatta",
                "Skriv sammanfattning.",
                input_source=InputSource.PREVIOUS_STEP,
            ),
        ],
    )

    assert build_conversation_aware_quality_feedback(conversation, spec) is None


def test_flags_missing_audio_step_when_conversation_mentions_transcription() -> None:
    """Warns when audio/transcription is mentioned but no step handles audio."""
    conversation = [
        {"role": "user", "content": "Transkribera ljudinspelningen och sammanfatta."}
    ]
    spec = FlowDraftSpecCore(
        flow_name="Transkribering",
        steps=[_step("step_a", "Sammanfatta", "Sammanfatta texten.")],
    )
    feedback = build_conversation_aware_quality_feedback(
        conversation,
        spec,
        flow=_edit_flow(),
    )
    assert feedback is not None
    assert "audio" in feedback.lower() or "transcribe_only" in feedback


def test_no_audio_warning_when_spec_has_transcription_step() -> None:
    """No warning when the spec already has a proper audio step."""
    conversation = [
        {"role": "user", "content": "Transkribera ljudinspelningen och sammanfatta."}
    ]
    spec = FlowDraftSpecCore(
        flow_name="Transkribering",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Transkribera",
                assistant_spec=AssistantSpec(instructions="Transkribera."),
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.AUDIO,
                output_mode=OutputMode.TRANSCRIBE_ONLY,
                output_type=OutputType.TEXT,
            ),
            _step(
                "step_b",
                "Sammanfatta",
                "Sammanfatta.",
                input_source=InputSource.PREVIOUS_STEP,
            ),
        ],
    )
    assert build_conversation_aware_quality_feedback(conversation, spec) is None


def test_does_not_require_template_fill_after_conversation_shifts_to_pdf_summary() -> (
    None
):
    conversation = [
        {
            "role": "user",
            "content": (
                "Jag vill ha ett flöde som transkriberar samtal och sammanfattar "
                "och sedan fyller i en pdf mall med transkriberingen."
            ),
        },
        {
            "role": "user",
            "content": "ja exakt transkribera först men sedan ska jag få ut en pdf sammanfattning",
            "metadata": {
                "question_answer": {
                    "question_id": "final_output_mode",
                    "selected_values": ["pdf_document"],
                }
            },
        },
    ]
    spec = FlowDraftSpecCore(
        flow_name="Samtalssammanfattning",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Transkribera samtal",
                assistant_spec=AssistantSpec(instructions="Transkribera ljudfilen."),
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.AUDIO,
                output_mode=OutputMode.TRANSCRIBE_ONLY,
                output_type=OutputType.TEXT,
            ),
            StepSpec(
                plan_step_ref="step_b",
                name="Skapa PDF-sammanfattning",
                assistant_spec=AssistantSpec(
                    instructions="Skriv en strukturerad PDF-sammanfattning."
                ),
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_type=OutputType.PDF,
            ),
        ],
    )

    feedback = build_conversation_aware_quality_feedback(conversation, spec)

    assert feedback is None or "template_fill" not in feedback


def test_still_requires_template_fill_for_explicit_docx_template_request() -> None:
    conversation = [
        {
            "role": "user",
            "content": "Skapa ett Word-dokument från en mall med fält från analysen.",
            "metadata": {
                "question_answer": {
                    "question_id": "final_output_mode",
                    "selected_values": ["docx_document"],
                }
            },
        }
    ]
    spec = FlowDraftSpecCore(
        flow_name="Mallstyrd DOCX",
        steps=[
            _step(
                "step_a",
                "Extrahera innehåll",
                "Analysera underlaget.",
                input_type=InputType.DOCUMENT,
                output_type=OutputType.JSON,
                output_contract={
                    "type": "object",
                    "properties": {"summary": {"type": "string"}},
                },
            ),
            _step(
                "step_b",
                "Skriv dokument",
                "Skriv ett DOCX-dokument.",
                input_source=InputSource.PREVIOUS_STEP,
                output_type=OutputType.DOCX,
            ),
        ],
    )

    feedback = build_conversation_aware_quality_feedback(conversation, spec)

    assert feedback is not None
    assert "template_fill" in feedback


def test_quality_feedback_prefers_confirmed_docx_output_over_pdf_input_mentions() -> (
    None
):
    conversation = [
        {
            "role": "user",
            "content": (
                "Bygg ett flöde som tar ett uppladdat PDF-dokument och genererar en DOCX-rapport."
            ),
        },
        {
            "role": "tool",
            "content": "Requirements presented to user. Awaiting confirmation.",
            "metadata": {
                "requirements_summary": {
                    "output_description": "En genererad DOCX-rapport baserad på PDF-underlaget."
                }
            },
        },
    ]
    spec = FlowDraftSpecCore(
        flow_name="Felaktig PDF-plan",
        steps=[
            _step(
                "step_a",
                "Läs PDF",
                "Läs PDF-underlaget.",
                input_type=InputType.DOCUMENT,
                output_type=OutputType.TEXT,
            ),
            _step(
                "step_b",
                "Skriv rapport",
                "Skriv rapporten.",
                input_source=InputSource.PREVIOUS_STEP,
                output_type=OutputType.PDF,
            ),
        ],
    )

    feedback = build_conversation_aware_quality_feedback(
        conversation,
        spec,
        flow=_edit_flow(),
    )

    assert feedback is not None
    assert "DOCX" in feedback
    assert "PDF som slutartefakt" not in feedback


def test_flags_non_terminal_docx_conversion_for_output_only_edit() -> None:
    from uuid import uuid4

    from eneo.flows.domain.flow import Flow, FlowStep

    flow = Flow(
        id=uuid4(),
        tenant_id=uuid4(),
        space_id=uuid4(),
        name="Transkribering och tolkning",
        steps=[
            FlowStep(
                assistant_id=uuid4(),
                step_order=1,
                user_description="Transkribera ljud",
                input_source="flow_input",
                input_type="audio",
                output_mode="transcribe_only",
                output_type="text",
            ),
            FlowStep(
                assistant_id=uuid4(),
                step_order=2,
                user_description="Tematisk sammanfattning",
                input_source="previous_step",
                input_type="text",
                output_mode="pass_through",
                output_type="text",
            ),
            FlowStep(
                assistant_id=uuid4(),
                step_order=3,
                user_description="Psykologisk och sociologisk tolkning",
                input_source="previous_step",
                input_type="text",
                output_mode="pass_through",
                output_type="pdf",
            ),
        ],
    )
    conversation = [
        {
            "role": "user",
            "content": "ändra så att jag får ut en word dokument istället för en pdf",
        }
    ]
    spec = FlowDraftSpecCore(
        flow_name="Transkribering och tolkning",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                existing_step_ref="existing_step_1",
                name="Transkribera ljud",
                assistant_spec=AssistantSpec(instructions="Transkribera ljudet."),
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.AUDIO,
                output_mode=OutputMode.TRANSCRIBE_ONLY,
                output_type=OutputType.TEXT,
            ),
            StepSpec(
                plan_step_ref="step_b",
                existing_step_ref="existing_step_2",
                name="Tematisk sammanfattning",
                assistant_spec=AssistantSpec(
                    instructions="Sammanfatta transkriptionen."
                ),
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_mode=OutputMode.TEMPLATE_FILL,
                output_type=OutputType.DOCX,
            ),
            StepSpec(
                plan_step_ref="step_c",
                existing_step_ref="existing_step_3",
                name="Psykologisk och sociologisk tolkning",
                assistant_spec=AssistantSpec(instructions="Skriv Word-dokumentet."),
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_mode=OutputMode.TEMPLATE_FILL,
                output_type=OutputType.DOCX,
            ),
        ],
    )

    feedback = build_conversation_aware_quality_feedback(conversation, spec, flow=flow)

    assert feedback is not None
    assert "mellanliggande" in feedback.casefold()
    assert "template_fill" in feedback


def test_document_conversion_invariant_fires_without_template_fill() -> None:
    """An output-only edit that converts an intermediate step to DOCX is
    rejected even when no step uses `template_fill`, so the sibling
    template-fill invariant cannot account for the rejection."""
    from uuid import uuid4

    from eneo.flows.domain.flow import FlowStep

    flow = _edit_flow()
    flow.steps.append(
        FlowStep(
            assistant_id=uuid4(),
            step_order=2,
            user_description="Existing PDF report",
            input_source="previous_step",
            input_type="text",
            output_mode="pass_through",
            output_type="pdf",
        )
    )
    planning_state = PlanningState.empty()
    planning_state.resolved_slots["terminal_output"] = ResolvedSlot(
        name="terminal_output",
        value="docx_document",
        source="structured_answer",
        confidence="high",
        evidence=["question_answer:terminal_output"],
    )
    spec = FlowDraftSpecCore(
        flow_name="Existing flow",
        steps=[
            _step(
                "step_a",
                "Existing analysis",
                "Keep the analysis.",
                output_type=OutputType.DOCX,
            ),
            _step(
                "step_b",
                "Existing report",
                "Change the final report to DOCX.",
                input_source=InputSource.PREVIOUS_STEP,
                output_type=OutputType.DOCX,
            ),
        ],
    )
    context = build_conversation_critic_context(
        [],
        spec,
        flow=flow,
        planning_state=planning_state,
    )

    issues = evaluate_critic_invariants(context)

    assert [
        (issue.id, issue.kind)
        for issue in issues
        if issue.id.startswith("non_terminal_step_")
    ] == [("non_terminal_step_document_conversion_forbidden", "architecture")]


def test_template_fill_invariant_fires_without_document_conversion() -> None:
    """An output-only edit that gives an already-DOCX intermediate step
    `template_fill` is rejected on its own, so the sibling document-conversion
    invariant cannot account for the rejection."""
    from uuid import uuid4

    from eneo.flows.domain.flow import Flow, FlowStep

    flow = Flow(
        id=uuid4(),
        tenant_id=uuid4(),
        space_id=uuid4(),
        name="Existing flow",
        steps=[
            FlowStep(
                assistant_id=uuid4(),
                step_order=1,
                user_description="Existing analysis",
                input_source="flow_input",
                input_type="text",
                output_mode="pass_through",
                output_type="text",
            ),
            FlowStep(
                assistant_id=uuid4(),
                step_order=2,
                user_description="Existing DOCX draft",
                input_source="previous_step",
                input_type="text",
                output_mode="pass_through",
                output_type="docx",
            ),
            FlowStep(
                assistant_id=uuid4(),
                step_order=3,
                user_description="Existing PDF report",
                input_source="previous_step",
                input_type="text",
                output_mode="pass_through",
                output_type="pdf",
            ),
        ],
    )
    planning_state = PlanningState.empty()
    planning_state.resolved_slots["terminal_output"] = ResolvedSlot(
        name="terminal_output",
        value="docx_document",
        source="structured_answer",
        confidence="high",
        evidence=["question_answer:terminal_output"],
    )
    spec = FlowDraftSpecCore(
        flow_name="Existing flow",
        steps=[
            _step(
                "step_a",
                "Existing analysis",
                "Keep the analysis.",
                output_type=OutputType.TEXT,
            ),
            _step(
                "step_b",
                "Existing DOCX draft",
                "Keep the draft.",
                input_source=InputSource.PREVIOUS_STEP,
                output_type=OutputType.DOCX,
                output_mode=OutputMode.TEMPLATE_FILL,
            ),
            _step(
                "step_c",
                "Existing report",
                "Change the final report to DOCX.",
                input_source=InputSource.PREVIOUS_STEP,
                output_type=OutputType.DOCX,
            ),
        ],
    )
    context = build_conversation_critic_context(
        [],
        spec,
        flow=flow,
        planning_state=planning_state,
    )

    issues = evaluate_critic_invariants(context)

    assert [
        (issue.id, issue.kind)
        for issue in issues
        if issue.id.startswith("non_terminal_step_")
    ] == [("non_terminal_step_template_fill_forbidden", "architecture")]


class TestCriticInvariantLoop:
    """The critic delegates to a CRITIC_INVARIANTS registry whose entries
    carry their own evidence (callable) and remediation (Swedish prose),
    rather than hard-coded substring checks in the main function body.
    Covered here: the explicit-PDF-terminal-mismatch invariant.
    """

    def test_render_critic_issues_fires_pdf_terminal_alignment_on_mismatch(
        self,
    ) -> None:
        """The loop runs the pdf-terminal-alignment evidence and returns its
        remediation when the user chose PDF but the terminal step does not
        output PDF."""
        from eneo.flows.ai_builder.ai_builder_critic_invariants import (
            CriticContext,
            render_critic_issues,
        )
        from eneo.flows.ai_builder.ai_builder_framework_policy import (
            OutputIntentResolution,
        )

        spec = FlowDraftSpecCore(
            flow_name="Rapport",
            steps=[
                _step("step_a", "Skriv rapport", "Skriv.", output_type=OutputType.TEXT)
            ],
        )
        context = CriticContext(
            spec=spec,
            flow=_edit_flow(),
            answer_signals={},
            text="",
            sectioned_form_intake=False,
            runtime_form_fields_requested=False,
            runtime_form_fields_evidence=(),
            simple_text_transform=False,
            output_intent=OutputIntentResolution(terminal_output="pdf_document"),
            mixed_audio_doc_input=False,
        )

        issues = render_critic_issues(context)

        assert any("PDF" in issue for issue in issues)

    def test_render_critic_issues_stays_silent_when_terminal_matches(self) -> None:
        """The invariant must not fire when the terminal step already produces PDF."""
        from eneo.flows.ai_builder.ai_builder_critic_invariants import (
            CriticContext,
            render_critic_issues,
        )
        from eneo.flows.ai_builder.ai_builder_framework_policy import (
            OutputIntentResolution,
        )

        spec = FlowDraftSpecCore(
            flow_name="Rapport",
            steps=[
                _step(
                    "step_a",
                    "Generera PDF",
                    "Skapa PDF.",
                    output_type=OutputType.PDF,
                )
            ],
        )
        context = CriticContext(
            spec=spec,
            flow=_edit_flow(),
            answer_signals={},
            text="",
            sectioned_form_intake=False,
            runtime_form_fields_requested=False,
            runtime_form_fields_evidence=(),
            simple_text_transform=False,
            output_intent=OutputIntentResolution(terminal_output="pdf_document"),
            mixed_audio_doc_input=False,
        )

        assert render_critic_issues(context) == []

    def test_render_critic_issues_stays_silent_without_pdf_intent(self) -> None:
        """The invariant requires explicit PDF intent; absent it, no issue fires."""
        from eneo.flows.ai_builder.ai_builder_critic_invariants import (
            CriticContext,
            render_critic_issues,
        )
        from eneo.flows.ai_builder.ai_builder_framework_policy import (
            OutputIntentResolution,
        )

        spec = FlowDraftSpecCore(
            flow_name="Rapport",
            steps=[_step("step_a", "Skriv", "Skriv.", output_type=OutputType.TEXT)],
        )
        context = CriticContext(
            spec=spec,
            flow=_edit_flow(),
            answer_signals={},
            text="",
            sectioned_form_intake=False,
            runtime_form_fields_requested=False,
            runtime_form_fields_evidence=(),
            simple_text_transform=False,
            output_intent=OutputIntentResolution(terminal_output=None),
            mixed_audio_doc_input=False,
        )

        assert render_critic_issues(context) == []


_FINAL_TEXT_STEP_INVARIANT_ID = (
    "final_text_step_must_reference_relevant_structured_outputs"
)
_TERMINAL_REVIEW_ONLY_INVARIANT_ID = (
    "terminal_renderer_must_not_consume_review_only_step"
)
_REDUNDANT_TERMINAL_JSON_TAIL_INVARIANT_ID = (
    "redundant_terminal_json_format_tail_after_final_text_composer"
)


def _final_text_step_critic_context(
    spec: FlowDraftSpecCore,
    *,
    aggregation_intent: str = "linear",
    terminal_output: str | None = None,
    text: str = "",
    typed_schema_request: bool = False,
    flow: "Flow | None" = None,
) -> "CriticContext":
    from eneo.flows.ai_builder.ai_builder_critic_invariants import (
        CriticContext,
    )
    from eneo.flows.ai_builder.ai_builder_framework_policy import (
        OutputIntentResolution,
    )
    from eneo.flows.ai_builder.ai_builder_result_contract import ResultContract

    return CriticContext(
        spec=spec,
        flow=flow,
        answer_signals={},
        text=text.casefold(),
        sectioned_form_intake=False,
        runtime_form_fields_requested=False,
        runtime_form_fields_evidence=(),
        simple_text_transform=False,
        output_intent=OutputIntentResolution(terminal_output=terminal_output),
        mixed_audio_doc_input=False,
        aggregation_intent=cast("AggregationIntent", aggregation_intent),
        result_contract=(
            ResultContract(
                terminal_output=terminal_output,
                post_processing_goal="extract_key_information",
            )
            if typed_schema_request
            else None
        ),
        output_schema_evidence=(
            build_schema_evidence(
                json_schema={
                    "type": "object",
                    "properties": {"result": {"type": "string"}},
                },
                source="declared_schema",
                confidence="high",
                evidence=("message:test-source",),
            )
            if typed_schema_request
            else None
        ),
    )


def _json_contract(field_name: str) -> dict:
    return {
        "type": "object",
        "properties": {field_name: {"type": "string"}},
    }


def _quality_chain_with_redundant_terminal_json_tail(
    *,
    terminal_text_unwrap: bool = True,
    tail_input_bindings: dict | None = None,
) -> FlowDraftSpecCore:
    steps = [
        _step(
            "step_a",
            "Skriv utkast",
            "Skriv ett kort svar.",
            output_type=OutputType.TEXT,
        ),
        _step(
            "step_b",
            "Granska utkast",
            "Bedöm tydlighet och faktakoll som JSON.",
            input_source=InputSource.PREVIOUS_STEP,
            output_type=OutputType.JSON,
            output_contract=_json_contract("critique"),
        ),
        _step(
            "step_c",
            "Skriv slutversion",
            "Skriv en förbättrad slutversion.",
            input_source=InputSource.PREVIOUS_STEP,
            output_type=OutputType.TEXT,
            input_bindings={
                "question": (
                    "Utkast: {{ step_a.output.text }}\n"
                    "Kritik: {{ step_b.output.structured.critique }}\n"
                    "Skriv slutversionen."
                )
            },
        ),
        _step(
            "step_d",
            "Formatera svar",
            "Packa slutversionen i JSON.",
            input_source=InputSource.PREVIOUS_STEP,
            output_type=OutputType.JSON,
            output_contract=_json_contract("answer"),
            input_bindings=tail_input_bindings,
        ),
    ]
    if terminal_text_unwrap:
        steps.append(
            _step(
                "step_e",
                "Returnera svar",
                "Returnera svaret som text.",
                input_source=InputSource.PREVIOUS_STEP,
                output_type=OutputType.TEXT,
            )
        )
    return FlowDraftSpecCore(flow_name="Kvalitetskedja", steps=steps)


class TestRedundantTerminalJsonFormatTailAfterFinalTextComposer:
    @pytest.mark.parametrize("terminal_text_unwrap", [False, True])
    def test_redundant_terminal_json_tail_fires_after_final_text_composer(
        self, terminal_text_unwrap: bool
    ) -> None:
        spec = _quality_chain_with_redundant_terminal_json_tail(
            terminal_text_unwrap=terminal_text_unwrap
        )

        issues = evaluate_critic_invariants(_final_text_step_critic_context(spec))

        assert any(
            issue.id == _REDUNDANT_TERMINAL_JSON_TAIL_INVARIANT_ID for issue in issues
        )
        assert not any(issue.id == _FINAL_TEXT_STEP_INVARIANT_ID for issue in issues)

    def test_silent_on_three_step_text_revision_quality_chain(self) -> None:
        spec = FlowDraftSpecCore(
            flow_name="Kvalitetskedja utan svans",
            steps=_quality_chain_with_redundant_terminal_json_tail(
                terminal_text_unwrap=False
            ).steps[:3],
        )

        issues = evaluate_critic_invariants(_final_text_step_critic_context(spec))

        assert not any(
            issue.id == _REDUNDANT_TERMINAL_JSON_TAIL_INVARIANT_ID for issue in issues
        )

    def test_silent_when_structured_json_is_requested_terminal_output(self) -> None:
        spec = _quality_chain_with_redundant_terminal_json_tail(
            terminal_text_unwrap=False
        )
        planning_state = PlanningState.empty()
        planning_state.resolved_slots = {
            "terminal_output": ResolvedSlot(
                name="terminal_output",
                value="structured_json",
                source="structured_answer",
                confidence="high",
                evidence=["question_answer:terminal_output"],
            ),
            "post_processing_goal": ResolvedSlot(
                name="post_processing_goal",
                value="summarize_or_overview",
                source="structured_answer",
                confidence="high",
                evidence=["question_answer:post_processing_goal"],
            ),
        }

        issues = evaluate_critic_invariants(
            build_conversation_critic_context(
                [{"role": "user", "content": "Use this material."}],
                spec,
                planning_state=planning_state,
                compile_context=create_compile_context_from_planning_state(
                    planning_state
                ),
            )
        )

        assert not any(
            issue.id == _REDUNDANT_TERMINAL_JSON_TAIL_INVARIANT_ID for issue in issues
        )

    def test_silent_when_typed_schema_requests_structured_terminal_data(
        self,
    ) -> None:
        spec = _quality_chain_with_redundant_terminal_json_tail(
            terminal_text_unwrap=False
        )

        issues = evaluate_critic_invariants(
            _final_text_step_critic_context(
                spec,
                text="Use this material.",
                typed_schema_request=True,
            )
        )

        assert not any(
            issue.id == _REDUNDANT_TERMINAL_JSON_TAIL_INVARIANT_ID for issue in issues
        )

    def test_incidental_json_mention_does_not_silence_redundant_tail(
        self,
    ) -> None:
        spec = _quality_chain_with_redundant_terminal_json_tail(
            terminal_text_unwrap=False
        )

        issues = evaluate_critic_invariants(
            _final_text_step_critic_context(
                spec,
                text=(
                    "Använd JSON internt där det hjälper, men returnera en "
                    "vanlig text till användaren."
                ),
            )
        )

        assert any(
            issue.id == _REDUNDANT_TERMINAL_JSON_TAIL_INVARIANT_ID for issue in issues
        )

    def test_redundant_terminal_silent_when_no_prior_json_contract_exists(
        self,
    ) -> None:
        spec = FlowDraftSpecCore(
            flow_name="Textkedja med JSON-slut",
            steps=[
                _step("step_a", "Skriv del", "Skriv del."),
                _step(
                    "step_b",
                    "Skriv mer",
                    "Skriv mer.",
                    input_source=InputSource.PREVIOUS_STEP,
                ),
                _step(
                    "step_c",
                    "Skriv sluttext",
                    "Skriv sluttext.",
                    input_source=InputSource.PREVIOUS_STEP,
                ),
                _step(
                    "step_d",
                    "Skapa JSON",
                    "Skapa JSON.",
                    input_source=InputSource.PREVIOUS_STEP,
                    output_type=OutputType.JSON,
                    output_contract=_json_contract("answer"),
                ),
            ],
        )

        issues = evaluate_critic_invariants(_final_text_step_critic_context(spec))

        assert not any(
            issue.id == _REDUNDANT_TERMINAL_JSON_TAIL_INVARIANT_ID for issue in issues
        )

    def test_redundant_terminal_silent_when_json_tail_reads_all_previous_steps(
        self,
    ) -> None:
        spec = _quality_chain_with_redundant_terminal_json_tail(
            terminal_text_unwrap=False
        )
        spec.steps[-1] = spec.steps[-1].model_copy(
            update={"input_source": InputSource.ALL_PREVIOUS_STEPS}
        )

        issues = evaluate_critic_invariants(_final_text_step_critic_context(spec))

        assert not any(
            issue.id == _REDUNDANT_TERMINAL_JSON_TAIL_INVARIANT_ID for issue in issues
        )

    def test_redundant_terminal_silent_when_json_tail_has_no_output_contract(
        self,
    ) -> None:
        spec = _quality_chain_with_redundant_terminal_json_tail(
            terminal_text_unwrap=False
        )
        spec.steps[-1] = spec.steps[-1].model_copy(update={"output_contract": None})

        issues = evaluate_critic_invariants(_final_text_step_critic_context(spec))

        assert not any(
            issue.id == _REDUNDANT_TERMINAL_JSON_TAIL_INVARIANT_ID for issue in issues
        )

    def test_silent_on_compare_topology(self) -> None:
        spec = _quality_chain_with_redundant_terminal_json_tail(
            terminal_text_unwrap=True
        )

        issues = evaluate_critic_invariants(
            _final_text_step_critic_context(spec, aggregation_intent="compare")
        )

        assert not any(
            issue.id == _REDUNDANT_TERMINAL_JSON_TAIL_INVARIANT_ID for issue in issues
        )

    def test_fires_on_aggregate_topology(self) -> None:
        spec = _quality_chain_with_redundant_terminal_json_tail(
            terminal_text_unwrap=True
        )

        issues = evaluate_critic_invariants(
            _final_text_step_critic_context(spec, aggregation_intent="aggregate")
        )

        assert any(
            issue.id == _REDUNDANT_TERMINAL_JSON_TAIL_INVARIANT_ID for issue in issues
        )

    def test_silent_when_terminal_output_is_document_renderer(self) -> None:
        spec = FlowDraftSpecCore(
            flow_name="Rapport med renderer",
            steps=[
                *_quality_chain_with_redundant_terminal_json_tail(
                    terminal_text_unwrap=False
                ).steps[:3],
                _step(
                    "step_d",
                    "Skapa Word-rapport",
                    "Skapa ett dokument från slutversionen.",
                    input_source=InputSource.PREVIOUS_STEP,
                    output_type=OutputType.DOCX,
                ),
            ],
        )

        issues = evaluate_critic_invariants(_final_text_step_critic_context(spec))

        assert not any(
            issue.id == _REDUNDANT_TERMINAL_JSON_TAIL_INVARIANT_ID for issue in issues
        )

    def test_silent_when_json_tail_is_driven_by_form_field(self) -> None:
        spec = FlowDraftSpecCore(
            flow_name="Formstyrd JSON",
            form_fields=[
                FormFieldSpec(
                    name="schema_choice",
                    type="select",
                    label="Schema",
                    required=True,
                    options=["compact", "full"],
                )
            ],
            steps=_quality_chain_with_redundant_terminal_json_tail(
                terminal_text_unwrap=False,
                tail_input_bindings={
                    "question": (
                        "Schema: {{ schema_choice }}\n"
                        "Slutversion: {{ step_c.output.text }}"
                    )
                },
            ).steps,
        )

        issues = evaluate_critic_invariants(_final_text_step_critic_context(spec))

        assert not any(
            issue.id == _REDUNDANT_TERMINAL_JSON_TAIL_INVARIANT_ID for issue in issues
        )
        assert not any(
            issue.id == "form_fields_declared_must_be_referenced" for issue in issues
        )

    def test_redundant_terminal_json_tail_fires_in_edit_context(self) -> None:
        from uuid import uuid4

        from eneo.flows.domain.flow import Flow, FlowStep

        flow = Flow(
            id=uuid4(),
            tenant_id=uuid4(),
            space_id=uuid4(),
            name="Kvalitetskedja",
            steps=[
                FlowStep(
                    assistant_id=uuid4(),
                    step_order=1,
                    user_description="Skriv utkast",
                    input_source="flow_input",
                    input_type="text",
                    output_mode="pass_through",
                    output_type="text",
                ),
                FlowStep(
                    assistant_id=uuid4(),
                    step_order=2,
                    user_description="Granska utkast",
                    input_source="previous_step",
                    input_type="text",
                    output_mode="pass_through",
                    output_type="json",
                    output_contract=_json_contract("critique"),
                ),
                FlowStep(
                    assistant_id=uuid4(),
                    step_order=3,
                    user_description="Skriv slutversion",
                    input_source="previous_step",
                    input_type="text",
                    output_mode="pass_through",
                    output_type="text",
                ),
            ],
        )
        conversation = [
            {
                "role": "user",
                "content": "Ändra flödet med minsta möjliga strukturförändring.",
            }
        ]
        spec = _quality_chain_with_redundant_terminal_json_tail(
            terminal_text_unwrap=True
        )

        issues = evaluate_critic_invariants(
            build_conversation_critic_context(conversation, spec, flow=flow)
        )

        assert any(
            issue.id == _REDUNDANT_TERMINAL_JSON_TAIL_INVARIANT_ID for issue in issues
        )


class TestTerminalRendererRejectsReviewOnlyPreviousStep:
    def test_fires_when_docx_renders_review_notes_instead_of_report_body(self) -> None:
        spec = FlowDraftSpecCore(
            flow_name="Meeting report",
            steps=[
                _step(
                    "step_a",
                    "Skriv rapport",
                    "Skriv rapporten.",
                    output_type=OutputType.TEXT,
                ),
                _step(
                    "step_b",
                    "Granska kvalitet och luckor",
                    "Granska analysen för saknad information och kvalitetsproblem.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_type=OutputType.TEXT,
                ),
                _step(
                    "step_c",
                    "Skapa DOCX",
                    "Skapa Word-dokument.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_type=OutputType.DOCX,
                ),
            ],
        )

        issues = evaluate_critic_invariants(_final_text_step_critic_context(spec))

        assert any(issue.id == _TERMINAL_REVIEW_ONLY_INVARIANT_ID for issue in issues)

    def test_template_fill_fires_when_binding_consumes_review_notes_alias(
        self,
    ) -> None:
        spec = FlowDraftSpecCore(
            flow_name="Template report",
            steps=[
                _step(
                    "step_a",
                    "Skriv rapport",
                    "Skriv rapporten.",
                    output_type=OutputType.TEXT,
                ),
                _step(
                    "step_b",
                    "Granska kvalitet och luckor",
                    "Granska rapporten och lista kvalitetsproblem.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_type=OutputType.TEXT,
                ),
                _step(
                    "step_c",
                    "Fyll DOCX-mall",
                    "Fyll dokumentmallen.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_type=OutputType.DOCX,
                    output_mode=OutputMode.TEMPLATE_FILL,
                    output_config={"bindings": {"comments": "{{ föregående_steg }}"}},
                ),
            ],
        )

        issues = evaluate_critic_invariants(_final_text_step_critic_context(spec))

        assert any(issue.id == _TERMINAL_REVIEW_ONLY_INVARIANT_ID for issue in issues)

    def test_template_fill_fires_when_binding_directly_consumes_review_notes(
        self,
    ) -> None:
        spec = FlowDraftSpecCore(
            flow_name="Template report",
            steps=[
                _step(
                    "step_a",
                    "Skriv rapport",
                    "Skriv rapporten.",
                    output_type=OutputType.TEXT,
                ),
                _step(
                    "step_b",
                    "Granska kvalitet och luckor",
                    "Granska rapporten och lista kvalitetsproblem.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_type=OutputType.TEXT,
                ),
                _step(
                    "step_c",
                    "Fyll DOCX-mall",
                    "Fyll dokumentmallen.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_type=OutputType.DOCX,
                    output_mode=OutputMode.TEMPLATE_FILL,
                    output_config={
                        "bindings": {"comments": "{{ step_b.output.text }}"}
                    },
                ),
            ],
        )

        issues = evaluate_critic_invariants(_final_text_step_critic_context(spec))

        assert any(issue.id == _TERMINAL_REVIEW_ONLY_INVARIANT_ID for issue in issues)

    def test_typed_writer_ref_overrides_review_markers_before_docx(self) -> None:
        spec = FlowDraftSpecCore(
            flow_name="Meeting report",
            steps=[
                _step(
                    "step_a",
                    "Skriv rapport",
                    "Skriv rapporten.",
                    output_type=OutputType.TEXT,
                ),
                _step(
                    "step_b",
                    "Granska kvalitet och luckor",
                    "Granska analysen för saknad information och kvalitetsproblem.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_type=OutputType.TEXT,
                ),
                _step(
                    "step_c",
                    "Skapa DOCX",
                    "Skapa Word-dokument.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_type=OutputType.DOCX,
                ),
            ],
            document_body_writer_step_refs=("step_b",),
        )

        issues = evaluate_critic_invariants(_final_text_step_critic_context(spec))

        assert not any(
            issue.id == _TERMINAL_REVIEW_ONLY_INVARIANT_ID for issue in issues
        )

    def test_fires_for_paraphrased_validation_step_before_docx(self) -> None:
        spec = FlowDraftSpecCore(
            flow_name="Meeting report",
            steps=[
                _step(
                    "step_a",
                    "Skriv rapport",
                    "Skriv rapporten.",
                    output_type=OutputType.TEXT,
                ),
                _step(
                    "step_b",
                    "Validera rapporten",
                    (
                        "Validera kvaliteten på rapporten innan den slutliga "
                        "versionen sätts samman."
                    ),
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_type=OutputType.TEXT,
                ),
                _step(
                    "step_c",
                    "Skapa DOCX",
                    "Skapa Word-dokument.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_type=OutputType.DOCX,
                ),
            ],
        )

        issues = evaluate_critic_invariants(_final_text_step_critic_context(spec))

        assert any(issue.id == _TERMINAL_REVIEW_ONLY_INVARIANT_ID for issue in issues)

    def test_silent_when_review_step_outputs_revised_final_body(self) -> None:
        spec = FlowDraftSpecCore(
            flow_name="Meeting report",
            steps=[
                _step(
                    "step_a",
                    "Skriv rapport",
                    "Skriv rapporten.",
                    output_type=OutputType.TEXT,
                ),
                _step(
                    "step_b",
                    "Kvalitetsgranska och harmonisera rapporten",
                    (
                        "Granska rapporten och skriv en reviderad slutversion "
                        "redo för Word-dokument."
                    ),
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_type=OutputType.TEXT,
                ),
                _step(
                    "step_c",
                    "Skapa DOCX",
                    "Skapa Word-dokument.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_type=OutputType.DOCX,
                ),
            ],
        )

        issues = evaluate_critic_invariants(_final_text_step_critic_context(spec))

        assert not any(
            issue.id == _TERMINAL_REVIEW_ONLY_INVARIANT_ID for issue in issues
        )

    def test_silent_when_review_only_step_is_not_before_renderer(self) -> None:
        spec = FlowDraftSpecCore(
            flow_name="Meeting report",
            steps=[
                _step(
                    "step_a",
                    "Skriv rapport",
                    "Skriv rapporten.",
                    output_type=OutputType.TEXT,
                ),
                _step(
                    "step_b",
                    "Validera rapporten",
                    "Validera kvaliteten innan rapporten sätts samman.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_type=OutputType.TEXT,
                ),
                _step(
                    "step_c",
                    "Sammanställ slutrapport",
                    "Sammanställ en färdig rapport.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_type=OutputType.TEXT,
                ),
            ],
        )

        issues = evaluate_critic_invariants(_final_text_step_critic_context(spec))

        assert not any(
            issue.id == _TERMINAL_REVIEW_ONLY_INVARIANT_ID for issue in issues
        )


class TestFinalTextStepReferencesRelevantStructuredOutputs:
    """`final_text_step_must_reference_relevant_structured_outputs` is the
    remaining under-bound critic check. Broad `all_previous_steps`
    topology is compiler-owned; this rule fires when a final text
    composer reads `input_source=previous_step` and only sees the most
    recent JSON predecessor even though earlier predecessors also emit
    structured fields the composer almost certainly needs.

    Pattern: parallel multi-aspect extractions that fan-in to a single
    text rendering. Each prior step extracts a distinct structured slice
    of the source; a `previous_step` composer that does not pull
    `{{ step_n.output.structured.* }}` selectors from at least two
    of those priors is silently dropping data on the floor. The
    upstream auto-binder usually rewrites this in create-mode, but the
    invariant exists for the cases where the auto-binder cannot fire:
    edit-mode, planner-authored selectors that miss priors, or future
    create-mode shapes the auto-binder does not yet cover.

    Suppression mirrors the remaining semantic exceptions:
    - `aggregation_intent` in {aggregate, compare}: compare flows go through
      the explicit fan-in invariant, while aggregate intent is frequently
      inferred from document-output language.
    - All priors are text-typed: there are no structured fields to
      pull, so no nudge is possible.
    - The composer's `input_bindings.question` already targets ≥2
      distinct prior structured fields: the spec is already doing the
      right thing despite the nominal `previous_step` source.
    """

    def test_silent_when_refinement_chain_consumes_json_on_composer_ancestry(
        self,
    ) -> None:
        spec = FlowDraftSpecCore(
            flow_name="Refine structured evidence",
            steps=[
                _step(
                    "step_a",
                    "Extract evidence",
                    "Extract evidence from the document.",
                    input_type=InputType.DOCUMENT,
                    output_type=OutputType.JSON,
                    output_contract=_json_contract("evidence"),
                ),
                _step(
                    "step_b",
                    "Refine evidence",
                    "Refine the extracted evidence.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.JSON,
                    output_type=OutputType.JSON,
                    output_contract=_json_contract("refined_evidence"),
                    input_bindings={
                        "source_refs": [{"step_ref": "step_a", "output": "structured"}]
                    },
                ),
                _step(
                    "step_c",
                    "Compose report",
                    "Compose the final report.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_type=OutputType.TEXT,
                    output_mode=OutputMode.COMPOSE_TEXT,
                    input_bindings={
                        "question": (
                            "Use {{ step_b.output.structured.refined_evidence }} "
                            "to compose the report."
                        )
                    },
                ),
                _step(
                    "step_d",
                    "Render PDF",
                    "Render the report as PDF.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_type=OutputType.PDF,
                    output_mode=OutputMode.RENDER_VERBATIM,
                ),
            ],
        )

        issues = evaluate_critic_invariants(_final_text_step_critic_context(spec))

        assert not any(issue.id == _FINAL_TEXT_STEP_INVARIANT_ID for issue in issues)

    def test_silent_when_previous_text_ancestor_consumes_json_fan_in(self) -> None:
        spec = FlowDraftSpecCore(
            flow_name="Structured fan-in before final composition",
            steps=[
                _step(
                    "step_a",
                    "Extract product",
                    "Extract product data.",
                    output_type=OutputType.JSON,
                    output_contract=_json_contract("product"),
                ),
                _step(
                    "step_b",
                    "Extract customer",
                    "Extract customer data.",
                    output_type=OutputType.JSON,
                    output_contract=_json_contract("customer"),
                ),
                _step(
                    "step_c",
                    "Draft report",
                    "Draft a report from the structured data.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_type=OutputType.TEXT,
                    input_bindings={
                        "question": (
                            "Use {{ step_a.output.structured.product }} and "
                            "{{ step_b.output.structured.customer }} to draft "
                            "the report."
                        )
                    },
                ),
                _step(
                    "step_d",
                    "Finalize report",
                    "Finalize the report.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_type=OutputType.TEXT,
                ),
            ],
        )

        issues = evaluate_critic_invariants(_final_text_step_critic_context(spec))

        assert not any(issue.id == _FINAL_TEXT_STEP_INVARIANT_ID for issue in issues)

    @pytest.mark.parametrize(
        ("flow", "required_text", "forbidden_text"),
        [
            (None, "följer efter", "uses_previous_fields"),
            (_edit_flow(), "uses_previous_fields", None),
        ],
        ids=("create", "edit"),
    )
    def test_remediation_matches_authoring_mode(
        self,
        flow: "Flow | None",
        required_text: str,
        forbidden_text: str | None,
    ) -> None:
        spec = FlowDraftSpecCore(
            flow_name="Implicit structured refinement",
            steps=[
                _step(
                    "step_a",
                    "Extract product",
                    "Extract product data.",
                    output_type=OutputType.JSON,
                    output_contract=_json_contract("product"),
                ),
                _step(
                    "step_b",
                    "Extract customer",
                    "Extract customer data.",
                    input_source=InputSource.PREVIOUS_STEP,
                    output_type=OutputType.JSON,
                    output_contract=_json_contract("customer"),
                ),
                _step(
                    "step_c",
                    "Compose summary",
                    "Compose the final summary.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_type=OutputType.TEXT,
                ),
            ],
        )

        issue = next(
            issue
            for issue in evaluate_critic_invariants(
                _final_text_step_critic_context(spec, flow=flow)
            )
            if issue.id == _FINAL_TEXT_STEP_INVARIANT_ID
        )

        assert required_text in issue.remediation
        if forbidden_text is not None:
            assert forbidden_text not in issue.remediation

    def test_fires_on_previous_step_composer_with_multiple_json_priors(
        self,
    ) -> None:
        """The user-reported regression: a multi-step extraction chain ends
        in a `previous_step` composer that only sees the immediate predecessor.
        The composer should read at least two priors' structured fields."""

        spec = FlowDraftSpecCore(
            flow_name="Sammanställ extraktioner",
            steps=[
                _step(
                    "step_a",
                    "Extrahera produktdata",
                    "Extrahera produktdata som JSON.",
                    output_type=OutputType.JSON,
                    output_contract={
                        "type": "object",
                        "properties": {"produkt": {"type": "string"}},
                    },
                ),
                _step(
                    "step_b",
                    "Extrahera kunddata",
                    "Extrahera kunddata som JSON.",
                    input_source=InputSource.PREVIOUS_STEP,
                    output_type=OutputType.JSON,
                    output_contract={
                        "type": "object",
                        "properties": {"kund": {"type": "string"}},
                    },
                ),
                _step(
                    "step_c",
                    "Extrahera leveransdata",
                    "Extrahera leveransdata som JSON.",
                    input_source=InputSource.PREVIOUS_STEP,
                    output_type=OutputType.JSON,
                    output_contract={
                        "type": "object",
                        "properties": {"leverans": {"type": "string"}},
                    },
                ),
                _step(
                    "step_d",
                    "Skriv sammanfattning",
                    "Skriv en kort sammanfattning.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_type=OutputType.TEXT,
                ),
            ],
        )

        issues = evaluate_critic_invariants(_final_text_step_critic_context(spec))

        assert any(issue.id == _FINAL_TEXT_STEP_INVARIANT_ID for issue in issues), (
            "rule must nudge a previous_step composer with two JSON priors "
            "to pull structured fields from earlier predecessors"
        )

    def test_compiler_report_exemption_rejects_unbound_downstream_producer(
        self,
    ) -> None:
        spec = FlowDraftSpecCore(
            flow_name="Source risk report",
            steps=[
                _step(
                    "step_a",
                    "Read documents",
                    "Extract source evidence.",
                    input_type=InputType.DOCUMENT,
                    output_type=OutputType.JSON,
                    output_contract={
                        "type": "object",
                        "properties": {
                            "documents": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {"summary": {"type": "string"}},
                                },
                            }
                        },
                    },
                ),
                _step(
                    "step_b",
                    "Build source sections",
                    "Build source sections.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.JSON,
                    output_type=OutputType.JSON,
                    output_contract={
                        "type": "object",
                        "properties": {
                            "source_sections": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "section_title": {"type": "string"},
                                        "section_body": {"type": "string"},
                                        "source_label": {"type": "string"},
                                    },
                                },
                            }
                        },
                    },
                ),
                _step(
                    "step_c",
                    "Assess risks",
                    "Assess risks across source sections.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.JSON,
                    output_type=OutputType.JSON,
                    output_contract=_json_contract("risk_assessment"),
                ),
                _step(
                    "step_d",
                    "Compose report",
                    "Compose the report.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.JSON,
                    output_type=OutputType.TEXT,
                    output_mode=OutputMode.COMPOSE_TEXT,
                    input_bindings={
                        "question": "# Source report",
                        "source_refs": [
                            {
                                "step_ref": "step_b",
                                "output": "structured",
                                "field_path": "source_sections",
                                "item_template": (
                                    "## {section_title}\n\n{section_body}\n\n"
                                    "Source: {source_label}"
                                ),
                            }
                        ],
                    },
                ),
                _step(
                    "step_e",
                    "Render PDF",
                    "Render the report.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_type=OutputType.PDF,
                    output_mode=OutputMode.RENDER_VERBATIM,
                ),
            ],
            document_body_writer_step_refs=("step_d",),
        )

        issues = evaluate_critic_invariants(_final_text_step_critic_context(spec))

        assert any(issue.id == _FINAL_TEXT_STEP_INVARIANT_ID for issue in issues)

    def test_template_fill_alias_still_omits_earlier_structured_producer(
        self,
    ) -> None:
        spec = self._template_fill_structured_spec(
            bindings={"summary": "{{ föregående_steg }}"}
        )

        issues = evaluate_critic_invariants(_final_text_step_critic_context(spec))

        assert any(issue.id == _FINAL_TEXT_STEP_INVARIANT_ID for issue in issues)

    def test_template_fill_direct_structured_bindings_cover_producers(self) -> None:
        spec = self._template_fill_structured_spec(
            bindings={
                "product": "{{ step_a.output.structured.product }}",
                "customer": "{{ step_b.output.structured.customer }}",
            }
        )

        issues = evaluate_critic_invariants(_final_text_step_critic_context(spec))

        assert not any(issue.id == _FINAL_TEXT_STEP_INVARIANT_ID for issue in issues)

    def test_template_fill_accepts_two_consumed_of_three_structured_producers(
        self,
    ) -> None:
        spec = FlowDraftSpecCore(
            flow_name="Structured template report",
            steps=[
                _step(
                    "step_a",
                    "Extract product",
                    "Extract product data.",
                    output_type=OutputType.JSON,
                    output_contract=_json_contract("product"),
                ),
                _step(
                    "step_b",
                    "Extract customer",
                    "Extract customer data.",
                    input_source=InputSource.PREVIOUS_STEP,
                    output_type=OutputType.JSON,
                    output_contract=_json_contract("customer"),
                ),
                _step(
                    "step_c",
                    "Extract delivery",
                    "Extract delivery data.",
                    input_source=InputSource.PREVIOUS_STEP,
                    output_type=OutputType.JSON,
                    output_contract=_json_contract("delivery"),
                ),
                _step(
                    "step_d",
                    "Write report",
                    "Write the report.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_type=OutputType.TEXT,
                ),
                _step(
                    "step_e",
                    "Fill template",
                    "Fill the template.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_type=OutputType.DOCX,
                    output_mode=OutputMode.TEMPLATE_FILL,
                    output_config={
                        "bindings": {
                            "product": "{{ step_a.output.structured.product }}",
                            "summary": "{{ föregående_steg }}",
                        }
                    },
                ),
            ],
        )

        issues = evaluate_critic_invariants(_final_text_step_critic_context(spec))

        assert not any(issue.id == _FINAL_TEXT_STEP_INVARIANT_ID for issue in issues)

    @staticmethod
    def _template_fill_structured_spec(
        *, bindings: dict[str, str]
    ) -> FlowDraftSpecCore:
        return FlowDraftSpecCore(
            flow_name="Structured template report",
            steps=[
                _step(
                    "step_a",
                    "Extract product",
                    "Extract product data.",
                    output_type=OutputType.JSON,
                    output_contract=_json_contract("product"),
                ),
                _step(
                    "step_b",
                    "Extract customer",
                    "Extract customer data.",
                    input_source=InputSource.PREVIOUS_STEP,
                    output_type=OutputType.JSON,
                    output_contract=_json_contract("customer"),
                ),
                _step(
                    "step_c",
                    "Write report",
                    "Write the report.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_type=OutputType.TEXT,
                ),
                _step(
                    "step_d",
                    "Fill template",
                    "Fill the template.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_type=OutputType.DOCX,
                    output_mode=OutputMode.TEMPLATE_FILL,
                    output_config={"bindings": bindings},
                ),
            ],
        )

    def test_silent_on_single_json_prior_refinement_chain(self) -> None:
        """The classic 2-step refinement (extract → render) only has one
        JSON prior. There is no fan-in — `previous_step` is the canonical
        shape and the rule must not fire."""

        spec = FlowDraftSpecCore(
            flow_name="Enkel raffineringskedja",
            steps=[
                _step(
                    "step_a",
                    "Extrahera fakta",
                    "Extrahera fakta som JSON.",
                    output_type=OutputType.JSON,
                    output_contract={
                        "type": "object",
                        "properties": {"summary": {"type": "string"}},
                    },
                ),
                _step(
                    "step_b",
                    "Skriv rapport",
                    "Skriv en kort rapport.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_type=OutputType.TEXT,
                ),
            ],
        )

        issues = evaluate_critic_invariants(_final_text_step_critic_context(spec))

        assert not any(issue.id == _FINAL_TEXT_STEP_INVARIANT_ID for issue in issues)

    def test_silent_when_question_already_targets_two_prior_structured_fields(
        self,
    ) -> None:
        """When the composer's `input_bindings.question` already references
        at least two distinct prior steps' structured fields via
        `{{ step_n.output.structured.field }}`, the spec is doing what
        the rule would suggest. The rule must stay silent."""

        spec = FlowDraftSpecCore(
            flow_name="Redan riktade selektorer",
            steps=[
                _step(
                    "step_a",
                    "Extrahera produktdata",
                    "Extrahera produktdata.",
                    output_type=OutputType.JSON,
                    output_contract={
                        "type": "object",
                        "properties": {"produkt": {"type": "string"}},
                    },
                ),
                _step(
                    "step_b",
                    "Extrahera kunddata",
                    "Extrahera kunddata.",
                    input_source=InputSource.PREVIOUS_STEP,
                    output_type=OutputType.JSON,
                    output_contract={
                        "type": "object",
                        "properties": {"kund": {"type": "string"}},
                    },
                ),
                StepSpec(
                    plan_step_ref="step_c",
                    name="Skriv sammanfattning",
                    assistant_spec=AssistantSpec(
                        instructions="Skriv en kort sammanfattning."
                    ),
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_mode=OutputMode.PASS_THROUGH,
                    output_type=OutputType.TEXT,
                    input_bindings={
                        "question": (
                            "Använd {{ step_a.output.structured.produkt }} "
                            "och {{ step_b.output.structured.kund }} för att "
                            "skriva en kort sammanfattning."
                        )
                    },
                ),
            ],
        )

        issues = evaluate_critic_invariants(_final_text_step_critic_context(spec))

        assert not any(issue.id == _FINAL_TEXT_STEP_INVARIANT_ID for issue in issues)

    def test_fires_when_question_targets_only_one_prior_structured_field(
        self,
    ) -> None:
        """A composer that pulls a selector from only ONE prior is still
        dropping data — the rule must fire. Suppression requires ≥2
        distinct prior steps referenced."""

        spec = FlowDraftSpecCore(
            flow_name="Bara en selektor",
            steps=[
                _step(
                    "step_a",
                    "Extrahera produktdata",
                    "Extrahera produktdata.",
                    output_type=OutputType.JSON,
                    output_contract={
                        "type": "object",
                        "properties": {"produkt": {"type": "string"}},
                    },
                ),
                _step(
                    "step_b",
                    "Extrahera kunddata",
                    "Extrahera kunddata.",
                    input_source=InputSource.PREVIOUS_STEP,
                    output_type=OutputType.JSON,
                    output_contract={
                        "type": "object",
                        "properties": {"kund": {"type": "string"}},
                    },
                ),
                StepSpec(
                    plan_step_ref="step_c",
                    name="Skriv sammanfattning",
                    assistant_spec=AssistantSpec(
                        instructions="Skriv en kort sammanfattning."
                    ),
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_mode=OutputMode.PASS_THROUGH,
                    output_type=OutputType.TEXT,
                    input_bindings={
                        "question": (
                            "Använd {{ step_b.output.structured.kund }} för att "
                            "skriva en kort sammanfattning."
                        )
                    },
                ),
            ],
        )

        issues = evaluate_critic_invariants(_final_text_step_critic_context(spec))

        assert any(issue.id == _FINAL_TEXT_STEP_INVARIANT_ID for issue in issues)

    def test_silent_on_compare_intent(self) -> None:
        """The compare fan-in invariant owns true compare cases. This rule
        must defer rather than nudge toward `previous_step` against the
        compare-shape requirement."""

        spec = FlowDraftSpecCore(
            flow_name="Aggregeringsflöde",
            steps=[
                _step(
                    "step_a",
                    "Extrahera produktdata",
                    "Extrahera produktdata.",
                    output_type=OutputType.JSON,
                    output_contract={
                        "type": "object",
                        "properties": {"produkt": {"type": "string"}},
                    },
                ),
                _step(
                    "step_b",
                    "Extrahera kunddata",
                    "Extrahera kunddata.",
                    input_source=InputSource.PREVIOUS_STEP,
                    output_type=OutputType.JSON,
                    output_contract={
                        "type": "object",
                        "properties": {"kund": {"type": "string"}},
                    },
                ),
                _step(
                    "step_c",
                    "Skriv sammanfattning",
                    "Skriv en kort sammanfattning.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_type=OutputType.TEXT,
                ),
            ],
        )

        issues = evaluate_critic_invariants(
            _final_text_step_critic_context(spec, aggregation_intent="compare")
        )

        assert not any(issue.id == _FINAL_TEXT_STEP_INVARIANT_ID for issue in issues)

    def test_fires_on_aggregate_intent(self) -> None:
        spec = FlowDraftSpecCore(
            flow_name="Aggregeringsflöde",
            steps=[
                _step(
                    "step_a",
                    "Extrahera produktdata",
                    "Extrahera produktdata.",
                    output_type=OutputType.JSON,
                    output_contract={
                        "type": "object",
                        "properties": {"produkt": {"type": "string"}},
                    },
                ),
                _step(
                    "step_b",
                    "Extrahera kunddata",
                    "Extrahera kunddata.",
                    input_source=InputSource.PREVIOUS_STEP,
                    output_type=OutputType.JSON,
                    output_contract={
                        "type": "object",
                        "properties": {"kund": {"type": "string"}},
                    },
                ),
                _step(
                    "step_c",
                    "Skriv sammanfattning",
                    "Skriv en kort sammanfattning.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_type=OutputType.TEXT,
                ),
            ],
        )

        issues = evaluate_critic_invariants(
            _final_text_step_critic_context(spec, aggregation_intent="aggregate")
        )

        assert any(issue.id == _FINAL_TEXT_STEP_INVARIANT_ID for issue in issues)

    def test_silent_when_priors_are_text(self) -> None:
        """Priors that emit plain text expose no structured fields. The
        composer cannot pull `{{ step_n.output.structured.* }}` from them.
        `previous_step` is the only sensible source — the rule stays silent."""

        spec = FlowDraftSpecCore(
            flow_name="Texter ihop",
            steps=[
                _step(
                    "step_a",
                    "Skriv del 1",
                    "Skriv del 1.",
                    output_type=OutputType.TEXT,
                ),
                _step(
                    "step_b",
                    "Skriv del 2",
                    "Skriv del 2.",
                    input_source=InputSource.PREVIOUS_STEP,
                    output_type=OutputType.TEXT,
                ),
                _step(
                    "step_c",
                    "Sammanställ",
                    "Sammanställ båda.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_type=OutputType.TEXT,
                ),
            ],
        )

        issues = evaluate_critic_invariants(_final_text_step_critic_context(spec))

        assert not any(issue.id == _FINAL_TEXT_STEP_INVARIANT_ID for issue in issues)

    def test_fires_when_many_text_priors_still_drop_structured_json_priors(
        self,
    ) -> None:
        text_priors = [
            _step(
                f"step_{chr(ord('a') + idx)}",
                f"Skriv del {idx + 1}",
                "Skriv del.",
                input_source=InputSource.PREVIOUS_STEP
                if idx > 0
                else InputSource.FLOW_INPUT,
                output_type=OutputType.TEXT,
            )
            for idx in range(7)
        ]
        json_anchors = [
            _step(
                "step_h",
                "Extrahera fakta A",
                "Extrahera fakta.",
                input_source=InputSource.PREVIOUS_STEP,
                output_type=OutputType.JSON,
                output_contract={
                    "type": "object",
                    "properties": {"a": {"type": "string"}},
                },
            ),
            _step(
                "step_i",
                "Extrahera fakta B",
                "Extrahera fakta.",
                input_source=InputSource.PREVIOUS_STEP,
                output_type=OutputType.JSON,
                output_contract={
                    "type": "object",
                    "properties": {"b": {"type": "string"}},
                },
            ),
        ]
        spec = FlowDraftSpecCore(
            flow_name="För många textpriors",
            steps=[
                *text_priors,
                *json_anchors,
                _step(
                    "step_j",
                    "Skriv sammanfattning",
                    "Skriv en kort sammanfattning.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_type=OutputType.TEXT,
                ),
            ],
        )

        issues = evaluate_critic_invariants(_final_text_step_critic_context(spec))

        assert any(issue.id == _FINAL_TEXT_STEP_INVARIANT_ID for issue in issues), (
            "the old text-prior cap must not suppress a previous_step composer "
            "that still drops structured JSON priors"
        )

    def test_fires_when_many_json_priors_are_available(self) -> None:
        transcription = _step(
            "step_a",
            "Transkribera",
            "Transkribera ljudet.",
            input_type=InputType.AUDIO,
            output_type=OutputType.TEXT,
            output_mode=OutputMode.TRANSCRIBE_ONLY,
        )
        json_priors = [
            _step(
                f"step_{chr(ord('b') + idx)}",
                f"Extrahera del {idx + 1}",
                "Extrahera del.",
                input_source=InputSource.PREVIOUS_STEP,
                output_type=OutputType.JSON,
                output_contract={
                    "type": "object",
                    "properties": {f"f_{idx}": {"type": "string"}},
                },
            )
            for idx in range(8)
        ]
        spec = FlowDraftSpecCore(
            flow_name="Många JSON-extraktioner",
            steps=[
                transcription,
                *json_priors,
                _step(
                    "step_j",
                    "Skriv sammanfattning",
                    "Skriv en kort sammanfattning.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_type=OutputType.TEXT,
                ),
            ],
        )

        issues = evaluate_critic_invariants(_final_text_step_critic_context(spec))

        assert any(issue.id == _FINAL_TEXT_STEP_INVARIANT_ID for issue in issues), (
            "rule must fire when many JSON priors are available even past the "
            "old all-priors cap; the composer is dropping fields from earlier "
            "predecessors"
        )

    def test_silent_when_input_source_is_all_previous_steps(self) -> None:
        """Broad fan-in topology is compiler-owned. This rule fires only on
        the under-bind shape (`previous_step` with ≥2 JSON priors)."""

        spec = FlowDraftSpecCore(
            flow_name="All previous steps shape",
            steps=[
                _step(
                    "step_a",
                    "Extrahera produktdata",
                    "Extrahera produktdata.",
                    output_type=OutputType.JSON,
                    output_contract={
                        "type": "object",
                        "properties": {"produkt": {"type": "string"}},
                    },
                ),
                _step(
                    "step_b",
                    "Extrahera kunddata",
                    "Extrahera kunddata.",
                    input_source=InputSource.PREVIOUS_STEP,
                    output_type=OutputType.JSON,
                    output_contract={
                        "type": "object",
                        "properties": {"kund": {"type": "string"}},
                    },
                ),
                _step(
                    "step_c",
                    "Skriv sammanfattning",
                    "Skriv en kort sammanfattning.",
                    input_source=InputSource.ALL_PREVIOUS_STEPS,
                    input_type=InputType.TEXT,
                    output_type=OutputType.TEXT,
                ),
            ],
        )

        issues = evaluate_critic_invariants(_final_text_step_critic_context(spec))

        assert not any(issue.id == _FINAL_TEXT_STEP_INVARIANT_ID for issue in issues)

    def test_silent_when_terminal_is_renderer_and_composer_has_no_priors(
        self,
    ) -> None:
        """A 2-step DOCX-fill flow has the renderer as the terminal step
        but the composer is step 0 — there are no priors before it.
        The rule must not fire on this canonical 2-step shape."""

        spec = FlowDraftSpecCore(
            flow_name="DOCX-fill med en JSON-extraktion",
            steps=[
                _step(
                    "step_a",
                    "Extrahera fakta",
                    "Extrahera fakta.",
                    output_type=OutputType.JSON,
                    output_contract={
                        "type": "object",
                        "properties": {"summary": {"type": "string"}},
                    },
                ),
                _step(
                    "step_b",
                    "Fyll mall",
                    "Fyll DOCX-mallen.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_type=OutputType.DOCX,
                    output_mode=OutputMode.TEMPLATE_FILL,
                ),
            ],
        )

        issues = evaluate_critic_invariants(_final_text_step_critic_context(spec))

        assert not any(issue.id == _FINAL_TEXT_STEP_INVARIANT_ID for issue in issues)


class TestStandaloneAudioInvariant:
    """In edit context, `standalone_audio_requires_transcription_step` fires when
    the slot classifier has resolved the runtime input to `audio` and the spec
    has no transcription step.

    The invariant defers to the slot classifier
    (`resolve_input_intent.primary_runtime_input`) instead of doing its
    own keyword scan. This keeps the architecture rule and the discovery
    layer aligned: a prompt that the slot classifier reads as text input
    (e.g. "indata: originaltranskribering") is a text flow, not a
    forgotten transcription. The user is responsible for declaring audio
    explicitly when they want the recording to enter the flow as audio
    (e.g. "ladda upp ljudfilen", "audio file upload"). When they do, the
    slot flips to `audio` and this invariant catches a missing
    transcription step.
    """

    def _build_context(
        self,
        spec: FlowDraftSpecCore,
        *,
        primary_runtime_input: str = "unknown",
        mixed_audio_doc_input: bool = False,
        text: str = "",
        flow: "Flow | None" = None,
    ) -> "CriticContext":
        from eneo.flows.ai_builder.ai_builder_critic_invariants import (
            CriticContext,
        )
        from eneo.flows.ai_builder.ai_builder_framework_policy import (
            OutputIntentResolution,
        )

        return CriticContext(
            spec=spec,
            flow=flow,
            answer_signals={},
            text=text,
            sectioned_form_intake=False,
            runtime_form_fields_requested=False,
            runtime_form_fields_evidence=(),
            simple_text_transform=False,
            output_intent=OutputIntentResolution(terminal_output=None),
            mixed_audio_doc_input=mixed_audio_doc_input,
            primary_runtime_input=cast("PrimaryRuntimeInput", primary_runtime_input),
        )

    def test_fires_when_primary_runtime_input_is_audio_and_no_audio_step(
        self,
    ) -> None:
        issues = evaluate_critic_invariants(
            self._build_context(
                FlowDraftSpecCore(
                    flow_name="Sammanfatta möte",
                    steps=[
                        _step(
                            "step_a",
                            "Sammanfatta",
                            "Sammanfatta innehållet.",
                            input_type=InputType.TEXT,
                            output_type=OutputType.TEXT,
                        )
                    ],
                ),
                primary_runtime_input="audio",
                flow=_edit_flow(),
            )
        )

        assert any(
            issue.id == "standalone_audio_requires_transcription_step"
            for issue in issues
        )

    def test_silent_when_primary_runtime_input_is_text_even_with_transcription_word(
        self,
    ) -> None:
        """Regression for the user-reported failure: a prompt whose slot
        classifier reading is "text" (e.g. "indata: originaltranskribering",
        "läs hela den transkriberade mötestexten") must NOT trigger the
        audio rule. The user has named transcribed text as their data,
        not audio as their input. Firing here would push the planner to
        graft an audio step onto a text flow and surface as
        `architecture_critic_invariant_failed` to the end user.
        """
        issues = evaluate_critic_invariants(
            self._build_context(
                FlowDraftSpecCore(
                    flow_name="Mötesrapport från transkribering",
                    steps=[
                        _step(
                            "step_a",
                            "Etablera möteskontext",
                            "Läs hela den transkriberade mötestexten.",
                            input_type=InputType.TEXT,
                            output_type=OutputType.JSON,
                            output_contract={"type": "object"},
                        ),
                        _step(
                            "step_b",
                            "Skriv mötesrapport",
                            "Skriv en strukturerad mötesrapport.",
                            input_source=InputSource.PREVIOUS_STEP,
                            input_type=InputType.TEXT,
                            output_type=OutputType.TEXT,
                        ),
                    ],
                ),
                primary_runtime_input="text",
                text=(
                    "mötesrapport från transkribering. indata: "
                    "originaltranskribering. läs hela den transkriberade "
                    "mötestexten."
                ),
            )
        )

        assert not any(
            issue.id == "standalone_audio_requires_transcription_step"
            for issue in issues
        )

    def test_silent_when_primary_runtime_input_is_unknown(self) -> None:
        """Default-state contexts (no slot resolution) must not fire.
        The invariant only acts on a positive `audio` resolution — a
        soft contract that protects every other test fixture from
        accidentally tripping the audio rule.
        """
        issues = evaluate_critic_invariants(
            self._build_context(
                FlowDraftSpecCore(
                    flow_name="Generic flow",
                    steps=[
                        _step(
                            "step_a",
                            "Sammanfatta",
                            "Sammanfatta innehållet.",
                            input_type=InputType.TEXT,
                            output_type=OutputType.TEXT,
                        )
                    ],
                ),
                primary_runtime_input="unknown",
            )
        )

        assert not any(
            issue.id == "standalone_audio_requires_transcription_step"
            for issue in issues
        )

    def test_silent_when_spec_already_has_audio_step(self) -> None:
        """An explicit audio step (`input_type=audio` or
        `output_mode=transcribe_only`) satisfies the invariant even when
        the slot classifier resolves to `audio`.
        """
        issues = evaluate_critic_invariants(
            self._build_context(
                FlowDraftSpecCore(
                    flow_name="Transkribera och sammanfatta",
                    steps=[
                        _step(
                            "step_a",
                            "Transkribera",
                            "Transkribera ljudet.",
                            input_type=InputType.AUDIO,
                            output_type=OutputType.TEXT,
                            output_mode=OutputMode.TRANSCRIBE_ONLY,
                        ),
                        _step(
                            "step_b",
                            "Sammanfatta",
                            "Sammanfatta transkriptet.",
                            input_source=InputSource.PREVIOUS_STEP,
                            input_type=InputType.TEXT,
                            output_type=OutputType.TEXT,
                        ),
                    ],
                ),
                primary_runtime_input="audio",
            )
        )

        assert not any(
            issue.id == "standalone_audio_requires_transcription_step"
            for issue in issues
        )

    def test_silent_when_mixed_audio_doc_input_handles_clarification(self) -> None:
        """Mixed audio+document prompts are handled by the dedicated
        mixed-input invariants. The standalone rule must yield to them
        rather than double-firing on the same root cause.
        """
        issues = evaluate_critic_invariants(
            self._build_context(
                FlowDraftSpecCore(
                    flow_name="Sammanfatta möte",
                    steps=[
                        _step(
                            "step_a",
                            "Sammanfatta",
                            "Sammanfatta innehållet.",
                            input_type=InputType.TEXT,
                            output_type=OutputType.TEXT,
                        )
                    ],
                ),
                primary_runtime_input="audio",
                mixed_audio_doc_input=True,
            )
        )

        assert not any(
            issue.id == "standalone_audio_requires_transcription_step"
            for issue in issues
        )


class TestCriticInvariantRegistry:
    """The flat `CRITIC_INVARIANTS` tuple is the sole public registry.

    Ordering matters because the planner reads issues in the order the critic
    surfaces them; a regression test here pins that contract so a future
    reorder must be deliberate.
    """

    def test_critic_invariants_registered_in_stable_order(self) -> None:
        """Full flat-registry ordering lockdown. Any intentional reorder must
        update this list and justify the shift in the commit message.
        """
        from eneo.flows.ai_builder.ai_builder_critic_invariants import (
            CRITIC_INVARIANTS,
        )

        assert [inv.id for inv in CRITIC_INVARIANTS] == [
            "checkpoint_intent_mismatch",
            "runtime_metadata_requires_form_fields",
            "sectioned_form_intake_requires_form_fields",
            "rich_workflow_requires_json_contract_step",
            "pdf_terminal_output_alignment",
            "docx_terminal_output_alignment",
            "non_terminal_step_document_conversion_forbidden",
            "non_terminal_step_template_fill_forbidden",
            "structured_extraction_requires_json_contract_step",
            "explicit_json_contract_request_without_step",
            "standalone_audio_requires_transcription_step",
            "source_reader_required_fields_must_be_captured",
            "action_followup_requires_followup_fields",
            "field_reuse_requires_input_bindings",
            "multi_document_compare_requires_all_previous_steps",
            "simple_text_transform_must_remain_single_step",
            "document_renderer_must_immediately_follow_body_writer",
            "terminal_renderer_must_not_consume_review_only_step",
            "redundant_terminal_json_format_tail_after_final_text_composer",
            "final_text_step_must_reference_relevant_structured_outputs",
            "form_fields_declared_must_be_referenced",
            "template_fill_docx_requires_template_fill_step",
            "generated_docx_rejects_template_fill",
            "mixed_audio_doc_rejects_file_degradation",
            "mixed_audio_doc_rejects_pseudo_transcription",
            "mixed_audio_doc_requires_real_transcription_step",
        ]


class TestTypedDocumentWorkflowInvariants:
    """Fire/quiet coverage for the JSON-contract rule on document workflows.

    Eligibility is typed: commit-grade `primary_runtime_input` plus a result
    contract that delivers a document artefact. The phrase-derived twin that
    the form-field and multi-step rules once consumed is gone — those rules
    read display prose, so identical typed state produced different plans per
    UI language. Runtime fields are owned by
    `runtime_metadata_requires_form_fields`, and analysis depth by
    `ResultContract`.

    The `generated_docx_without_structure` case exists because a user who asks
    for a plain generated DOCX must not be nagged about JSON steps — that is
    the most common false-positive shape.
    """

    def _typed_document_workflow_context(
        self,
        spec: FlowDraftSpecCore,
        *,
        flow: "Flow | None" = None,
        rich: bool = True,
        structured_result_requested: bool = False,
    ) -> CriticContext:
        from eneo.flows.ai_builder.ai_builder_critic_invariants import (
            CriticContext,
        )
        from eneo.flows.ai_builder.ai_builder_framework_policy import (
            OutputIntentResolution,
        )
        from eneo.flows.ai_builder.ai_builder_result_contract import ResultContract

        output_schema_evidence = (
            build_schema_evidence(
                json_schema={
                    "type": "object",
                    "properties": {"result": {"type": "string"}},
                },
                source="declared_schema",
                confidence="high",
                evidence=("message:test-source",),
            )
            if rich and structured_result_requested
            else None
        )

        return CriticContext(
            spec=spec,
            flow=flow,
            answer_signals={},
            text="",
            sectioned_form_intake=False,
            runtime_form_fields_requested=False,
            runtime_form_fields_evidence=(),
            simple_text_transform=False,
            output_intent=OutputIntentResolution(terminal_output=None),
            mixed_audio_doc_input=False,
            result_contract=(
                ResultContract(
                    terminal_output="docx_document",
                    post_processing_goal="extract_key_information",
                )
                if rich
                else None
            ),
            resolved_slots=(
                {
                    "primary_runtime_input": ResolvedSlot(
                        name="primary_runtime_input",
                        value="documents",
                        source="structured_answer",
                        confidence="high",
                        evidence=["question_answer:primary_runtime_input"],
                    )
                }
                if rich
                else {}
            ),
            output_schema_evidence=output_schema_evidence,
        )

    def test_create_rich_workflow_leaves_form_fields_to_assembly(
        self,
    ) -> None:
        from eneo.flows.ai_builder.ai_builder_critic_invariants import (
            render_critic_issues,
        )

        spec = FlowDraftSpecCore(
            flow_name="Rapport",
            steps=[
                _step(
                    "step_a",
                    "Analysera dokument",
                    "Läs dokumentet och skriv rapport.",
                    input_type=InputType.DOCUMENT,
                )
            ],
        )
        context = self._typed_document_workflow_context(spec)

        issues = render_critic_issues(context)

        assert not any("form_fields" in issue for issue in issues)

    def test_transcript_derived_headings_do_not_require_form_fields(self) -> None:
        prompt = (
            "Bygg ett flöde där användaren laddar upp en ljudfil vid körning. "
            "Ljudfilen är en inspelning från ett kommunfullmäktigemöte. Flödet "
            "ska först transkribera ljudfilen till svensk text. Därefter ska "
            "transkriptionen analyseras och struktureras till ett "
            "mötesprotokoll. Rubrikerna ska inte vara inmatningsfält för "
            "användaren, utan ska skapas och fyllas i utifrån transkriptionen. "
            "Om mötestitel, organisationsnamn eller sekreterare inte framgår "
            "tydligt av transkriptionen ska flödet skriva “Ej angivet i "
            "transkriptionen” i rätt sektion, inte fråga användaren om det vid "
            "körning. Slutresultatet ska vara ett Word-dokument."
        )
        spec = FlowDraftSpecCore(
            flow_name="Mötesprotokoll",
            steps=[
                _step(
                    "step_audio",
                    "Transkribera ljud",
                    "Transkribera ljudfilen till svensk text.",
                    input_type=InputType.AUDIO,
                    output_type=OutputType.TEXT,
                    output_mode=OutputMode.TRANSCRIBE_ONLY,
                ),
                _step(
                    "step_protocol",
                    "Strukturera mötesprotokoll",
                    (
                        "Skapa rubriker från transkriptionen och skriv "
                        "Ej angivet i transkriptionen när uppgift saknas."
                    ),
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_type=OutputType.JSON,
                    output_contract={
                        "type": "object",
                        "required": ["protocol_sections"],
                        "properties": {"protocol_sections": {"type": "object"}},
                        "additionalProperties": False,
                    },
                ),
                _step(
                    "step_docx",
                    "Skapa DOCX",
                    "Skapa ett Word-dokument från mötesprotokollet.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.JSON,
                    output_type=OutputType.DOCX,
                ),
            ],
        )

        feedback = build_conversation_aware_quality_feedback(
            [{"role": "user", "content": prompt}],
            spec,
        )

        assert feedback is None

    def test_rich_workflow_requires_json_contract_step_fires_when_missing(
        self,
    ) -> None:
        from eneo.flows.ai_builder.ai_builder_critic_invariants import (
            render_critic_issues,
        )

        spec = FlowDraftSpecCore(
            flow_name="Rapport",
            steps=[
                _step(
                    "step_a",
                    "Analysera dokument",
                    "Läs och skriv rapport direkt.",
                    input_type=InputType.DOCUMENT,
                    output_type=OutputType.DOCX,
                )
            ],
        )
        context = self._typed_document_workflow_context(
            spec, structured_result_requested=True
        )

        issues = render_critic_issues(context)

        assert any(
            "output_contract" in issue or "JSON-steg" in issue for issue in issues
        )

    def test_rich_workflow_critic_rejects_audio_docx_extraction_without_json_contract_step(
        self,
    ) -> None:
        conversation = [
            {
                "role": "user",
                "content": (
                    "Create a flow that transcribes meeting audio, extracts ten "
                    "topic sections, and produces a DOCX meeting report."
                ),
            }
        ]
        spec = FlowDraftSpecCore(
            flow_name="Meeting report",
            steps=[
                _step(
                    "step_a",
                    "Transcribe audio",
                    "Transcribe the meeting audio.",
                    input_type=InputType.AUDIO,
                    output_mode=OutputMode.TRANSCRIBE_ONLY,
                    output_type=OutputType.TEXT,
                ),
                _step(
                    "step_b",
                    "Write DOCX",
                    "Write the meeting report from the transcript.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_type=OutputType.DOCX,
                ),
            ],
        )
        planning_state = PlanningState.empty()
        planning_state.resolved_slots = {
            "primary_runtime_input": ResolvedSlot(
                name="primary_runtime_input",
                value="audio",
                source="structured_answer",
                confidence="high",
                evidence=["question_answer:primary_runtime_input"],
            ),
            "terminal_output": ResolvedSlot(
                name="terminal_output",
                value="docx_document",
                source="structured_answer",
                confidence="high",
                evidence=["question_answer:terminal_output"],
            ),
            "post_processing_goal": ResolvedSlot(
                name="post_processing_goal",
                value="extract_key_information",
                source="structured_answer",
                confidence="high",
                evidence=["question_answer:post_processing_goal"],
            ),
        }
        planning_state.output_schema_evidence = build_schema_evidence(
            json_schema={
                "type": "object",
                "properties": {"topic_sections": {"type": "array"}},
            },
            source="declared_schema",
            confidence="high",
            evidence=("message:test-source",),
        )

        issues = evaluate_critic_invariants(
            build_conversation_critic_context(
                conversation,
                spec,
                planning_state=planning_state,
                compile_context=create_compile_context_from_planning_state(
                    planning_state
                ),
            )
        )

        assert "rich_workflow_requires_json_contract_step" in {
            issue.id for issue in issues
        }

    def test_rich_workflow_audio_widening_keeps_simple_audio_docx_out_of_json_contract_critic(
        self,
    ) -> None:
        conversation = [
            {
                "role": "user",
                "content": (
                    "Create a flow that transcribes meeting audio and produces "
                    "a DOCX file with the transcription."
                ),
            }
        ]
        spec = FlowDraftSpecCore(
            flow_name="Meeting transcript",
            steps=[
                _step(
                    "step_a",
                    "Transcribe audio",
                    "Transcribe the meeting audio.",
                    input_type=InputType.AUDIO,
                    output_mode=OutputMode.TRANSCRIBE_ONLY,
                    output_type=OutputType.TEXT,
                ),
                _step(
                    "step_b",
                    "Create DOCX transcript",
                    "Create a DOCX transcript from the transcription.",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_type=InputType.TEXT,
                    output_type=OutputType.DOCX,
                ),
            ],
        )

        issues = evaluate_critic_invariants(
            build_conversation_critic_context(conversation, spec)
        )
        issue_ids = {issue.id for issue in issues}

        assert "rich_workflow_requires_json_contract_step" not in issue_ids

    def test_rich_workflow_requires_json_contract_step_silent_for_generated_docx_without_structure(
        self,
    ) -> None:
        """Edge case: a plain generated DOCX with no structured-intermediate
        signal must not be nagged about JSON steps. This is the most
        common false-positive shape — user wants a simple
        document-in/document-out workflow, planner obliged, no
        downstream reuse was ever requested.
        """
        from eneo.flows.ai_builder.ai_builder_critic_invariants import (
            render_critic_issues,
        )

        spec = FlowDraftSpecCore(
            flow_name="Rapport",
            steps=[
                _step(
                    "step_a",
                    "Analysera dokument",
                    "Skriv rapport direkt från dokumentet.",
                    input_type=InputType.DOCUMENT,
                    output_type=OutputType.DOCX,
                )
            ],
        )
        context = self._typed_document_workflow_context(
            spec, structured_result_requested=False
        )

        issues = render_critic_issues(context)

        assert not any("output_contract" in issue for issue in issues)
        assert not any("JSON-steg" in issue for issue in issues)


class TestSourceReaderRequiredFieldsCaptured:
    """Required-capture satisfaction uses the shared canonical match."""

    def _context(
        self,
        spec: FlowDraftSpecCore,
        *,
        required: frozenset[str],
    ) -> "CriticContext":
        from eneo.flows.ai_builder.ai_builder_critic_invariants import (
            CriticContext,
        )
        from eneo.flows.ai_builder.ai_builder_framework_policy import (
            OutputIntentResolution,
        )

        return CriticContext(
            spec=spec,
            flow=None,
            answer_signals={},
            text="",
            sectioned_form_intake=False,
            runtime_form_fields_requested=False,
            runtime_form_fields_evidence=(),
            simple_text_transform=False,
            output_intent=OutputIntentResolution(terminal_output=None),
            mixed_audio_doc_input=False,
            source_reader_required_field_names=required,
        )

    def _reader_spec(self, *leaf_names: str) -> FlowDraftSpecCore:
        return FlowDraftSpecCore(
            flow_name="Källäsare",
            steps=[
                _step(
                    "step_a",
                    "Läs källor",
                    "Läs och strukturera källorna.",
                    input_type=InputType.DOCUMENT,
                    output_type=OutputType.JSON,
                    output_contract={
                        "type": "object",
                        "properties": {name: {"type": "string"} for name in leaf_names},
                        "required": list(leaf_names),
                        "additionalProperties": False,
                    },
                )
            ],
        )

    def test_verbatim_swedish_names_satisfy_canonical_requirements(self) -> None:
        # Regression 2026-08-06: after names stopped being rewritten to
        # canonical English, this invariant compared exact names and fired
        # on four live cases whose readers declared Swedish wording.
        issues = evaluate_critic_invariants(
            self._context(
                self._reader_spec("sammanfattning", "titel", "datum"),
                required=frozenset({"summary", "title", "date_or_year"}),
            )
        )

        assert not any(
            issue.id == "source_reader_required_fields_must_be_captured"
            for issue in issues
        )

    def test_truly_missing_required_field_still_fires(self) -> None:
        issues = evaluate_critic_invariants(
            self._context(
                self._reader_spec("sammanfattning"),
                required=frozenset({"summary", "date_or_year"}),
            )
        )

        assert any(
            issue.id == "source_reader_required_fields_must_be_captured"
            for issue in issues
        )


class TestRuntimeMetadataRemediationNamesTheFields:
    def test_remediation_quotes_the_slot_evidence(self) -> None:
        from eneo.flows.ai_builder.ai_builder_critic_invariants import (
            CriticContext,
            _runtime_metadata_requires_form_fields_remediation,
        )
        from eneo.flows.ai_builder.ai_builder_framework_policy import (
            OutputIntentResolution,
        )
        from eneo.flows.ai_builder.planning_state import ResolvedSlot

        context = CriticContext(
            spec=FlowDraftSpecCore(
                flow_name="Driftstörning",
                steps=[
                    _step(
                        "step_a",
                        "Strukturera",
                        "Strukturera felrapporten.",
                        output_type=OutputType.JSON,
                        output_contract={
                            "type": "object",
                            "properties": {"analys": {"type": "string"}},
                            "required": ["analys"],
                            "additionalProperties": False,
                        },
                    )
                ],
            ),
            flow=_edit_flow(),
            answer_signals={"runtime_metadata_fields": {"wants_input_fields"}},
            text="",
            sectioned_form_intake=False,
            runtime_form_fields_requested=False,
            runtime_form_fields_evidence=(),
            simple_text_transform=False,
            output_intent=OutputIntentResolution(terminal_output=None),
            mixed_audio_doc_input=False,
            resolved_slots={
                "runtime_metadata_fields": ResolvedSlot(
                    name="runtime_metadata_fields",
                    value="wants_input_fields",
                    source="model",
                    evidence=[
                        "quote:user_message:msg-1:fyller i område, beräknad klartid och kontaktväg"
                    ],
                    confidence="high",
                    evidence_level="explicit",
                )
            },
        )

        remediation = _runtime_metadata_requires_form_fields_remediation(context)

        assert '"fyller i område, beräknad klartid och kontaktväg"' in remediation
        assert "user_message:" not in remediation
        assert "input_field" in remediation


def _disclosure_conversation(planning_state: PlanningState, ui_language: str) -> list:
    """A conversation whose assistant turn carries the rendered disclosure."""

    from eneo.flows.ai_builder.ai_builder_requirements_disclosure import (
        build_requirements_disclosure,
    )

    payload = build_requirements_disclosure(planning_state, ui_language=ui_language)
    return [
        {
            "role": "user",
            "content": "Vi laddar upp underlag och vill ha en färdig rapport som DOCX.",
        },
        {
            "role": "assistant",
            "content": "Summary",
            "metadata": {
                "requirements_summary": payload.model_dump(mode="json"),
                "requirements_version": payload.requirements_version,
            },
        },
        {
            "role": "user",
            "content": "",
            "metadata": {
                "requirements_confirmed": True,
                "requirements_version": payload.requirements_version,
            },
        },
    ]


def test_ui_language_does_not_change_critic_issues() -> None:
    """The disclosure is display. Rendering it in English must not change the plan.

    A committed transcript checkpoint renders the English topic "Transcript
    review"; the Swedish topic is "Granskning av transkribering". While the
    critic scanned that prose for structural markers, the English rendering of
    identical typed state invented an extra review step.
    """

    planning_state = PlanningState.empty()
    planning_state.resolved_slots = {
        name: ResolvedSlot(
            name=name,
            value=value,
            source="structured_answer",
            confidence="high",
            evidence=[f"question_answer:{name}"],
        )
        for name, value in (
            ("primary_runtime_input", "documents"),
            ("terminal_output", "docx_document"),
            ("post_processing_goal", "extract_key_information"),
        )
    }
    planning_state.checkpoint_intents = [
        CheckpointIntent(
            evidence_level="explicit",
            producer_kind="transcript",
            operation="set",
            mode=FlowStepReviewMode.VIEW,
            confidence="high",
            evidence=["quote:user_message:1:I want to approve the transcript."],
        )
    ]
    spec = FlowDraftSpecCore(
        flow_name="Mötesprotokoll",
        steps=[
            _step(
                "step_a",
                "Transkribera",
                "Transkribera mötesljudet.",
                input_type=InputType.AUDIO,
                output_mode=OutputMode.TRANSCRIBE_ONLY,
            ),
            _step(
                "step_b",
                "Skriv protokoll",
                "Skriv protokollet.",
                input_source=InputSource.PREVIOUS_STEP,
                output_type=OutputType.DOCX,
            ),
        ],
    )

    issues_by_locale = {
        locale: {
            issue.id
            for issue in evaluate_critic_invariants(
                build_conversation_critic_context(
                    _disclosure_conversation(planning_state, locale),
                    spec,
                    planning_state=planning_state,
                )
            )
        }
        for locale in ("sv", "en")
    }

    assert issues_by_locale["sv"] == issues_by_locale["en"]


def test_committed_no_extra_fields_answer_silences_sectioned_form_intake() -> None:
    """The user's own answer outranks a phrase that sounds like form intake.

    "No extra fields" is a committed discovery answer, so it is read from the
    resolved slot. It used to be recovered by scanning the Swedish sentence the
    disclosure rendered from that very slot.
    """

    spec = FlowDraftSpecCore(
        flow_name="Formulär till rapport",
        steps=[_step("step_a", "Sammanställ rapport", "Sammanställ svaren.")],
    )
    planning_state = PlanningState.empty()
    planning_state.signals = [
        PlanningSignal(
            question_id="form_intake_pattern",
            value="sectioned_form_intake",
            confidence="high",
            source="model",
            provenance=["quote:fritext under varje rubrik"],
        )
    ]
    planning_state.resolved_slots = {
        "runtime_metadata_fields": ResolvedSlot(
            name="runtime_metadata_fields",
            value="no_extra_metadata",
            source="structured_answer",
            confidence="high",
            evidence=["question_answer:runtime_metadata_fields"],
        )
    }
    conversation = [{"role": "user", "content": "Bygg flödet enligt beskrivningen."}]

    silenced = evaluate_critic_invariants(
        build_conversation_critic_context(
            conversation, spec, flow=_edit_flow(), planning_state=planning_state
        )
    )
    planning_state.resolved_slots = {}
    still_firing = evaluate_critic_invariants(
        build_conversation_critic_context(
            conversation, spec, flow=_edit_flow(), planning_state=planning_state
        )
    )

    assert "sectioned_form_intake_requires_form_fields" not in {
        issue.id for issue in silenced
    }
    assert "sectioned_form_intake_requires_form_fields" in {
        issue.id for issue in still_firing
    }


def test_typed_form_intake_verdict_requires_form_fields() -> None:
    """The classifier's generic form-intake verdict is a first-class request.

    It is not only the sectioned variant: a plan that omits the fields the
    user asked to fill in per run must still be repaired.
    """

    spec = FlowDraftSpecCore(
        flow_name="Rapport",
        steps=[_step("step_a", "Skriv", "Skriv rapporten.")],
    )
    planning_state = PlanningState.empty()
    planning_state.signals = [
        PlanningSignal(
            question_id="form_intake_pattern",
            value="needs_form_fields",
            confidence="high",
            source="model",
            provenance=[
                "model:form_intake_pattern:hash",
                "quote:user_message:msg-1:användaren ska fylla i handläggare och datum",
            ],
        )
    ]
    conversation = [{"role": "user", "content": "Bygg flödet."}]

    issue_ids = {
        issue.id
        for issue in evaluate_critic_invariants(
            build_conversation_critic_context(
                conversation, spec, flow=_edit_flow(), planning_state=planning_state
            )
        )
    }

    assert "runtime_metadata_requires_form_fields" in issue_ids
    remediation = next(
        issue.remediation
        for issue in evaluate_critic_invariants(
            build_conversation_critic_context(
                conversation, spec, flow=_edit_flow(), planning_state=planning_state
            )
        )
        if issue.id == "runtime_metadata_requires_form_fields"
    )
    assert "handläggare och datum" in remediation


def test_sectioned_form_intake_reports_one_missing_form_fields_issue() -> None:
    """One missing contract, one issue: the sectioned rule owns its remediation."""

    spec = FlowDraftSpecCore(
        flow_name="Formulär till rapport",
        steps=[_step("step_a", "Sammanställ rapport", "Sammanställ svaren.")],
    )
    planning_state = PlanningState.empty()
    planning_state.signals = [
        PlanningSignal(
            question_id="form_intake_pattern",
            value="sectioned_form_intake",
            confidence="high",
            source="model",
            provenance=["quote:user_message:msg-1:fritext under varje rubrik"],
        )
    ]

    issue_ids = [
        issue.id
        for issue in evaluate_critic_invariants(
            build_conversation_critic_context(
                [{"role": "user", "content": "Bygg flödet."}],
                spec,
                flow=_edit_flow(),
                planning_state=planning_state,
            )
        )
        if "form_fields" in issue.id
    ]

    assert issue_ids == ["sectioned_form_intake_requires_form_fields"]


def _runtime_metadata_edit_context(*, evidence: list[str]) -> "CriticContext":
    from eneo.flows.ai_builder.ai_builder_critic_invariants import CriticContext
    from eneo.flows.ai_builder.ai_builder_framework_policy import (
        OutputIntentResolution,
    )
    from eneo.flows.ai_builder.planning_state import ResolvedSlot

    return CriticContext(
        spec=FlowDraftSpecCore(
            flow_name="Dokumentanalys",
            steps=[
                _step(
                    "step_a",
                    "Analysera dokument",
                    "Sammanfatta ärendet.",
                    input_type=InputType.DOCUMENT,
                )
            ],
        ),
        flow=_edit_flow(),
        answer_signals={"runtime_metadata_fields": {"basic_runtime_metadata"}},
        text="",
        sectioned_form_intake=False,
        runtime_form_fields_requested=False,
        runtime_form_fields_evidence=(),
        simple_text_transform=False,
        output_intent=OutputIntentResolution(terminal_output=None),
        mixed_audio_doc_input=False,
        resolved_slots={
            "runtime_metadata_fields": ResolvedSlot(
                name="runtime_metadata_fields",
                value="basic_runtime_metadata",
                source="model",
                confidence="high",
                evidence=evidence,
                evidence_level="explicit",
            )
        },
    )


def _runtime_metadata_remediation(context: "CriticContext") -> str:
    return next(
        issue.remediation
        for issue in evaluate_critic_invariants(context)
        if issue.id == "runtime_metadata_requires_form_fields"
    )


def test_the_repair_quotes_the_user_when_the_user_asked_for_the_fields() -> None:
    remediation = _runtime_metadata_remediation(
        _runtime_metadata_edit_context(
            evidence=[
                "quote:user_message:019fd7c0-8030-7712-b7b6-f2e3cc2ad814:"
                "fyller i område och kontaktväg"
            ]
        )
    )

    assert "Användarens ord" in remediation
    assert "fyller i område och kontaktväg" in remediation


def test_an_attachment_excerpt_is_never_repeated_as_the_users_own_words() -> None:
    # A slot can rest on an uploaded file, cited exactly like a message. The
    # repair used to introduce whatever it found with "Användarens ord", which
    # attributes a document's wording to the person reading it.
    remediation = _runtime_metadata_remediation(
        _runtime_metadata_edit_context(
            evidence=[
                "quote:uploaded_file:0192a0f1-1111-7000-8000-000000000001:"
                "Blankett för felanmälan"
            ]
        )
    )

    assert "Användarens ord" not in remediation
    assert "Blankett för felanmälan" not in remediation
