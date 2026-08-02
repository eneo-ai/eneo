from __future__ import annotations

from uuid import uuid4

import pytest

from eneo.flows.ai_builder.ai_builder_architecture_commit import (
    finalize_architecture_commit,
)
from eneo.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from eneo.flows.ai_builder.ai_builder_create_proposal import (
    process_create_intent_arguments,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
)
from eneo.flows.ai_builder.ai_builder_plan_store import build_flow_builder_proposal
from eneo.flows.ai_builder.ai_builder_proposal_intent import FlowInputFieldIntent
from eneo.flows.ai_builder.ai_builder_proposal_policy import (
    build_create_contextual_quality_feedback,
)
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderAvailableModelResource,
    build_ai_builder_resource_catalog,
)
from eneo.flows.ai_builder.ai_builder_runtime_input_fields import (
    DETAILED_CASE_METADATA,
)
from eneo.flows.ai_builder.ai_builder_schema_evidence import build_schema_evidence
from eneo.flows.ai_builder.ai_builder_session_turn import (
    SessionSendLease,
    SessionSendTurn,
)
from eneo.flows.ai_builder.planning_state import (
    ArchitectureCommitDraft,
    PlanningState,
    ResolvedSlot,
    StepTriple,
)
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)
from tests.unittests.flows.ai_builder.authoring_command_assertions import (
    assert_create_spec_prepares_through_authoring_command_async,
)


def _make_turn(
    *,
    session_id=None,
    tenant_id=None,
    base_planning_state_version: int = 0,
) -> SessionSendTurn:
    return SessionSendTurn(
        session_id=session_id or uuid4(),
        tenant_id=tenant_id or uuid4(),
        lease=SessionSendLease(request_id=uuid4(), lock_token=uuid4()),
        base_planning_state_version=base_planning_state_version,
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
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.TEXT,
            ),
        ],
    )


def _model_resource(local_id: str, name: str) -> AIBuilderAvailableModelResource:
    return {
        "id": local_id,
        "ref": local_id,
        "name": name,
        "display_name": name,
        "provider": "test",
    }


def test_create_contextual_quality_feedback_uses_semantic_remediation() -> None:
    feedback = build_create_contextual_quality_feedback(
        conversation=[],
        spec=_structured_fan_in_spec(),
        aggregation_intent="linear",
        resource_catalog=None,
    ).feedback

    assert feedback is not None
    assert "Quality issues" in feedback
    assert "strukturerade" in feedback.casefold()
    for token in (
        "input_source",
        "uses_previous_fields",
        "input_bindings",
        "{{ step_",
    ):
        assert token not in feedback


@pytest.mark.asyncio
async def test_outline_processing_reports_unknown_resource_from_compiled_spec() -> None:
    catalog = build_ai_builder_resource_catalog(
        available_models=[_model_resource("model-1", "gpt-5.4-nano")],
        available_kbs=[],
    )

    result = await process_create_intent_arguments(
        turn=_make_turn(),
        conversation=[ConversationMessage(role="user", content="Bygg ett textflöde.")],
        arguments={
            "flow_name": "Unknown model flow",
            "plan_rationale": "Use a missing model ref.",
            "steps": [
                {
                    "name": "Analysera",
                    "instructions": "Analysera texten.",
                    "model_ref": "missing-fast-model",
                }
            ],
        },
        tool_call_id="call-unknown-resource",
        available_model_refs=catalog.model_refs,
        available_kb_refs=None,
        resource_catalog=catalog,
    )

    assert result.compiled_proposal is None
    assert result.failure_kind == "validation"
    assert result.feedback is not None
    assert "Unknown model reference 'missing-fast-model'" in result.feedback
    assert "step 'step_a'.assistant_spec.model_ref" in result.feedback
    assert "model.gpt-5-4-nano" in result.feedback


@pytest.mark.asyncio
async def test_outline_validation_failure_preserves_duplicate_step_name_code() -> None:
    result = await process_create_intent_arguments(
        turn=_make_turn(),
        conversation=[ConversationMessage(role="user", content="Bygg ett textflöde.")],
        arguments={
            "flow_name": "Duplicate names",
            "plan_rationale": "Two semantic steps accidentally share a name.",
            "steps": [
                {
                    "name": "Förbered PDF-innehåll",
                    "instructions": "Sammanfatta texten.",
                },
                {"name": "Förbered PDF-innehåll", "instructions": "Skriv slutrapport."},
            ],
        },
        tool_call_id="call-duplicate-name",
        available_model_refs=None,
        available_kb_refs=None,
    )

    assert result.compiled_proposal is not None
    validation = result.compiled_proposal.validation
    assert not validation.valid
    assert any(error.code == "duplicate_step_name" for error in validation.errors)
    assert any("Duplicate step name" in error.message for error in validation.errors)


@pytest.mark.asyncio
async def test_outline_assembly_rejection_returns_validation_failure_code() -> None:
    state = PlanningState.empty()
    state.resolved_slots["primary_runtime_input"] = ResolvedSlot(
        name="primary_runtime_input",
        value="documents",
        source="structured_answer",
        confidence="high",
    )

    result = await process_create_intent_arguments(
        turn=_make_turn(),
        conversation=[
            ConversationMessage(role="user", content="Bygg ett dokumentflöde.")
        ],
        arguments={
            "flow_name": "Invalid document reader",
            "plan_rationale": "The first step tried to write text from documents.",
            "steps": [
                {
                    "name": "Write summary",
                    "instructions": "Write a summary directly from uploaded documents.",
                    "output_type": "text",
                }
            ],
        },
        tool_call_id="call-assembly-rejection",
        available_model_refs=None,
        available_kb_refs=None,
        planning_state=state,
    )

    assert result.compiled_proposal is None
    assert result.failure_kind == "validation"
    assert result.failure_codes == frozenset(
        {"assembly_source_file_first_step_requires_json"}
    )
    assert result.feedback is not None
    assert "first semantic step" in result.feedback


@pytest.mark.asyncio
async def test_outline_audio_to_docx_returns_compiled_proposal() -> None:
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="audio",
                    output_type="docx",
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=[
                "audio_to_artifact_report",
                "form_field_runtime_inputs",
            ],
            required_capabilities=["input_audio", "output_mode_pass_through"],
        )
    )
    state.resolved_slots["runtime_metadata_fields"] = ResolvedSlot(
        name="runtime_metadata_fields",
        value=DETAILED_CASE_METADATA,
        source="structured_answer",
        confidence="high",
    )
    state.input_fields = [
        FlowInputFieldIntent(
            variable_name="arendenummer",
            label="Ärendenummer",
            provenance="user_confirmed",
        ),
        FlowInputFieldIntent(
            variable_name="handlaggare",
            label="Handläggare",
            provenance="user_confirmed",
        ),
    ]

    result = await process_create_intent_arguments(
        turn=_make_turn(),
        conversation=[
            ConversationMessage(
                role="user",
                content=(
                    "Bygg ett flöde som transkriberar ljud och skapar DOCX. "
                    "Användaren ska fylla i ärendenummer och handläggare vid körning."
                ),
            )
        ],
        arguments={
            "flow_name": "Ljudrapport",
            "plan_rationale": "Skapa en DOCX-rapport från uppladdat ljud.",
            "steps": [
                {
                    "name": "Analysera inspelningen",
                    "instructions": "Extrahera sakuppgifter ur transkriptionen.",
                    "output_type": "json",
                    "output_fields": [
                        {
                            "name": "sakuppgifter",
                            "field_type": "string",
                            "description": "Sakuppgifter ur inspelningen.",
                        }
                    ],
                    "review_mode": "edit",
                },
                {
                    "name": "Skriv rapporten",
                    "instructions": "Skriv rapporten från sakuppgifterna.",
                    "uses_form_fields": ["arendenummer", "handlaggare"],
                    "output_type": "text",
                },
            ],
        },
        tool_call_id="call-audio-docx",
        available_model_refs=None,
        available_kb_refs=None,
        planning_state=state,
    )

    assert result.compiled_proposal is not None
    spec = result.compiled_proposal.content.spec
    assert [field.name for field in spec.form_fields or ()] == [
        "arendenummer",
        "handlaggare",
    ]
    assert spec.steps[0].input_type == InputType.AUDIO
    analysis_step = spec.steps[1]
    report_step = spec.steps[2]
    assert analysis_step.review_policy is not None
    assert analysis_step.review_policy.mode.value == "edit"
    assert report_step.input_bindings is not None
    assert "{{ flow_input.arendenummer }}" in str(report_step.input_bindings)
    assert "{{ flow_input.handlaggare }}" in str(report_step.input_bindings)
    assert spec.steps[-1].output_type == OutputType.DOCX
    assert spec.steps[-1].output_mode == OutputMode.RENDER_VERBATIM
    await assert_create_spec_prepares_through_authoring_command_async(spec)


@pytest.mark.asyncio
async def test_committed_unsupported_architecture_hints_raise_typed_error() -> None:
    state = PlanningState.empty()
    state.architecture_commit = finalize_architecture_commit(
        ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="audio",
                    output_type="docx",
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=[
                "audio_to_artifact_report",
                "text_to_artifact_report",
            ],
            required_capabilities=["input_audio", "output_mode_pass_through"],
        )
    )

    with pytest.raises(AIBuilderArchitectureError) as exc_info:
        await process_create_intent_arguments(
            turn=_make_turn(),
            conversation=[
                ConversationMessage(
                    role="user",
                    content="Bygg ett flöde som skapar en DOCX-rapport från ljud.",
                )
            ],
            arguments={
                "flow_name": "Ljudrapport",
                "plan_rationale": "Transkribera ljudet och skriv en rapport.",
                "steps": [
                    {
                        "name": "Skriv rapporten",
                        "instructions": "Skriv rapporten från transkriptionen.",
                    }
                ],
            },
            tool_call_id="call-unsupported-committed-hints",
            available_model_refs=None,
            available_kb_refs=None,
            planning_state=state,
        )

    assert exc_info.value.public_code == "architecture_materialization_failed"
    assert exc_info.value.log_context["failure_code"] == (
        "assembly_unsupported_architecture_hints"
    )


@pytest.mark.asyncio
async def test_outline_processing_uses_confirmed_planning_state_field() -> None:
    state = PlanningState.empty()
    state.resolved_slots = {
        "runtime_metadata_fields": ResolvedSlot(
            name="runtime_metadata_fields",
            value=DETAILED_CASE_METADATA,
            source="structured_answer",
            confidence="high",
        ),
    }
    state.input_fields = [
        FlowInputFieldIntent(
            variable_name="malgrupp",
            label="Målgrupp",
            provenance="user_confirmed",
        )
    ]

    result = await process_create_intent_arguments(
        turn=_make_turn(),
        conversation=[
            ConversationMessage(
                role="user",
                content=(
                    "Bygg ett flöde som använder inmatningsfält för målgrupp "
                    "vid körning och skriver en rapport."
                ),
            )
        ],
        arguments={
            "flow_name": "Målgruppsrapport",
            "plan_rationale": "Anpassa rapporten efter målgrupp.",
            "steps": [
                {
                    "name": "Skriv rapport",
                    "instructions": "Skriv rapporten för vald målgrupp.",
                    "uses_form_fields": ["malgrupp"],
                }
            ],
        },
        tool_call_id="call-runtime-hints",
        available_model_refs=None,
        available_kb_refs=None,
        planning_state=state,
    )

    assert result.compiled_proposal is not None
    spec = result.compiled_proposal.content.spec
    assert spec.form_fields is not None
    assert [field.name for field in spec.form_fields] == ["malgrupp"]
    assert spec.steps[0].input_bindings is not None
    assert "{{ flow_input.malgrupp }}" in spec.steps[0].input_bindings["question"]
    await assert_create_spec_prepares_through_authoring_command_async(spec)


@pytest.mark.asyncio
async def test_server_owned_json_input_without_consumer_returns_model_feedback() -> (
    None
):
    state = PlanningState.empty()
    state.resolved_slots = {
        "primary_runtime_input": ResolvedSlot(
            name="primary_runtime_input",
            value="json",
            source="structured_answer",
            confidence="high",
        ),
        "terminal_output": ResolvedSlot(
            name="terminal_output",
            value="structured_json",
            source="structured_answer",
            confidence="high",
        ),
        "runtime_metadata_fields": ResolvedSlot(
            name="runtime_metadata_fields",
            value=DETAILED_CASE_METADATA,
            source="structured_answer",
            confidence="high",
        ),
    }
    state.input_schema_evidence = build_schema_evidence(
        json_schema={
            "type": "object",
            "properties": {"case_id": {"type": "string"}},
        },
        source="declared_schema",
        source_file_ids=("00000000-0000-0000-0000-000000000001",),
        confidence="high",
        evidence=["file:00000000-0000-0000-0000-000000000701:input_schema"],
    )
    state.input_fields = [
        FlowInputFieldIntent(
            variable_name="case_type",
            label="Case type",
            provenance="runtime_inferred",
        )
    ]

    result = await process_create_intent_arguments(
        turn=_make_turn(),
        conversation=[],
        arguments={
            "flow_name": "Normalize case JSON",
            "plan_rationale": "Normalize the submitted case.",
            "steps": [
                {
                    "name": "Normalize case",
                    "instructions": "Normalize the submitted case.",
                    "output_type": "json",
                }
            ],
        },
        tool_call_id="call-json-input-schema-with-server-fields",
        available_model_refs=None,
        available_kb_refs=None,
        planning_state=state,
    )

    assert result.failure_kind == "validation"
    assert result.failure_codes == frozenset({"unplaced_form_fields"})
    assert result.feedback is not None
    assert "case_type" in result.feedback


@pytest.mark.asyncio
async def test_unstructured_field_text_does_not_create_hidden_server_contract() -> None:
    state = PlanningState.empty()
    state.resolved_slots["runtime_metadata_fields"] = ResolvedSlot(
        name="runtime_metadata_fields",
        value=DETAILED_CASE_METADATA,
        source="heuristic",
        confidence="high",
    )

    result = await process_create_intent_arguments(
        turn=_make_turn(),
        conversation=[
            ConversationMessage(
                role="user",
                content=(
                    "Bygg ett flöde där användaren fyller i ärendenummer och "
                    "handläggare vid körning."
                ),
            )
        ],
        arguments={
            "flow_name": "Ärendesammanfattning",
            "plan_rationale": "Sammanfatta ärendet.",
            "steps": [
                {
                    "name": "Sammanfatta ärendet",
                    "instructions": "Skriv en tydlig sammanfattning.",
                }
            ],
        },
        tool_call_id="call-no-hidden-field-contract",
        available_model_refs=None,
        available_kb_refs=None,
        planning_state=state,
    )

    assert result.compiled_proposal is not None
    assert result.compiled_proposal.content.spec.form_fields is None


@pytest.mark.asyncio
async def test_confirmed_create_field_preserves_options_and_provenance() -> None:
    state = PlanningState.empty()
    state.input_fields = [
        FlowInputFieldIntent(
            variable_name="priority",
            label="Priority",
            field_type="select",
            required=True,
            options=["Low", "High"],
            provenance="user_confirmed",
        )
    ]

    result = await process_create_intent_arguments(
        turn=_make_turn(),
        conversation=[],
        arguments={
            "flow_name": "Priority response",
            "plan_rationale": "Use the confirmed priority when drafting.",
            "steps": [
                {
                    "name": "Draft response",
                    "instructions": "Draft a response for the selected priority.",
                    "uses_form_fields": ["priority"],
                }
            ],
        },
        tool_call_id="call-confirmed-field",
        available_model_refs=None,
        available_kb_refs=None,
        planning_state=state,
    )

    assert result.compiled_proposal is not None
    fields = result.compiled_proposal.content.spec.form_fields
    assert fields is not None
    assert fields[0].model_dump(exclude_none=True) == {
        "name": "priority",
        "label": "Priority",
        "type": "select",
        "required": True,
        "options": ["Low", "High"],
    }
    assert result.compiled_proposal.content.lint_warnings == []
    assert state.input_fields[0].provenance == "user_confirmed"
    stored_proposal = build_flow_builder_proposal(result.compiled_proposal)
    assert stored_proposal.content.spec.form_fields == fields


@pytest.mark.asyncio
async def test_confirmed_create_field_set_rejects_model_proposed_addition() -> None:
    state = PlanningState.empty()
    state.input_fields = [
        FlowInputFieldIntent(
            variable_name="case_type",
            label="Case type",
            provenance="user_confirmed",
        )
    ]

    result = await process_create_intent_arguments(
        turn=_make_turn(),
        conversation=[],
        arguments={
            "flow_name": "Case response",
            "plan_rationale": "Use runtime case details.",
            "input_fields": [
                {"name": "case_type", "label": "Case type"},
                {"name": "tone", "label": "Tone"},
            ],
            "steps": [
                {
                    "name": "Draft response",
                    "instructions": "Draft the response.",
                    "uses_form_fields": ["case_type", "tone"],
                }
            ],
        },
        tool_call_id="call-unconfirmed-field-addition",
        available_model_refs=None,
        available_kb_refs=None,
        planning_state=state,
    )

    assert result.compiled_proposal is None
    assert result.failure_kind == "validation"
    assert result.failure_codes == frozenset({"unconfirmed_runtime_form_fields"})


@pytest.mark.asyncio
async def test_model_proposed_create_shadow_drop_is_visible() -> None:
    state = PlanningState.empty()
    state.resolved_slots["primary_runtime_input"] = ResolvedSlot(
        name="primary_runtime_input",
        value="text",
        source="structured_answer",
        confidence="high",
    )

    result = await process_create_intent_arguments(
        turn=_make_turn(),
        conversation=[],
        arguments={
            "flow_name": "Text summary",
            "plan_rationale": "Summarize the primary text.",
            "input_fields": [{"name": "text", "label": "Text", "type": "text"}],
            "steps": [
                {
                    "name": "Summarize",
                    "instructions": "Summarize the text.",
                    "uses_form_fields": ["text"],
                }
            ],
        },
        tool_call_id="call-shadow-field",
        available_model_refs=None,
        available_kb_refs=None,
        planning_state=state,
    )

    assert result.compiled_proposal is not None
    assert result.compiled_proposal.content.spec.form_fields is None
    assert [
        (warning.code, warning.field_name, warning.field_provenance)
        for warning in result.compiled_proposal.content.lint_warnings
    ] == [("primary_input_shadow_form_field_dropped", "text", "model_proposed")]


@pytest.mark.asyncio
async def test_confirmed_create_shadow_field_is_rejected_explicitly() -> None:
    state = PlanningState.empty()
    state.resolved_slots["primary_runtime_input"] = ResolvedSlot(
        name="primary_runtime_input",
        value="text",
        source="structured_answer",
        confidence="high",
    )
    state.input_fields = [
        FlowInputFieldIntent(
            variable_name="text",
            label="Text",
            provenance="user_confirmed",
        )
    ]

    result = await process_create_intent_arguments(
        turn=_make_turn(),
        conversation=[],
        arguments={
            "flow_name": "Text summary",
            "plan_rationale": "Summarize the primary text.",
            "steps": [
                {
                    "name": "Summarize",
                    "instructions": "Summarize the text.",
                    "uses_form_fields": ["text"],
                }
            ],
        },
        tool_call_id="call-confirmed-shadow-field",
        available_model_refs=None,
        available_kb_refs=None,
        planning_state=state,
    )

    assert result.compiled_proposal is None
    assert result.failure_kind == "validation"
    assert result.failure_codes == frozenset({"confirmed_form_field_incompatible"})
