from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from eneo.flows.ai_builder.ai_builder_create_compile_context import CreateCompileContext
from eneo.flows.ai_builder.ai_builder_create_compiler import (
    compile_create_intent_to_spec,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    FlowBuilderEditApproval,
    FlowBuilderProposal,
    FlowBuilderProposalContent,
    TargetKind,
)
from eneo.flows.ai_builder.ai_builder_edit_preview_models import (
    EditAdvisory,
    FlowEditDiff,
    StepChange,
)
from eneo.flows.ai_builder.ai_builder_output_sections_signals import (
    RequestedOutputSections,
)
from eneo.flows.ai_builder.ai_builder_proposal_finalization import (
    CompiledProposalFinalizationRequest,
    CompiledProposalFinalizer,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    parse_create_flow_intent_arguments,
)
from eneo.flows.ai_builder.ai_builder_proposal_telemetry import (
    ProposalTurnTelemetry,
)
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    CompiledProposal,
)
from eneo.flows.ai_builder.ai_builder_session_turn import (
    SessionSendLease,
    SessionSendTurn,
)
from eneo.flows.ai_builder.ai_builder_tool_names import PROPOSE_FLOW_TOOL_NAME
from eneo.flows.ai_builder.ai_builder_validation_common import SpecValidationResult
from eneo.flows.ai_builder.ai_builder_validator import validate_spec
from eneo.flows.ai_builder.planning_state import AggregationIntent, ReportDisposition
from eneo.flows.domain.flow import Flow
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)


def _make_turn() -> SessionSendTurn:
    return SessionSendTurn(
        session_id=uuid4(),
        tenant_id=uuid4(),
        lease=SessionSendLease(request_id=uuid4(), lock_token=uuid4()),
        base_planning_state_version=0,
    )


def _make_flow_spec() -> FlowDraftSpecCore:
    return FlowDraftSpecCore(
        flow_name="Grounded flow",
        flow_description="Desc",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Analys",
                assistant_spec=AssistantSpec(
                    instructions="Gör analysen.",
                    model_ref=None,
                    knowledge_refs=[],
                ),
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.TEXT,
            )
        ],
    )


def _structured_underbound_spec(
    *,
    final_input_source: InputSource = InputSource.PREVIOUS_STEP,
) -> FlowDraftSpecCore:
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
                input_source=final_input_source,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.TEXT,
            ),
        ],
    )


def _compiled_outline_proposal() -> CompiledProposal:
    return CompiledProposal(
        content=FlowBuilderProposalContent(
            spec=_make_flow_spec(),
            plan_rationale="Classify incoming text.",
        ),
        validation=SpecValidationResult(),
    )


def _compiled_outline_proposal_with_validation(
    validation: SpecValidationResult,
) -> CompiledProposal:
    compiled = _compiled_outline_proposal()
    return CompiledProposal(
        content=compiled.content,
        validation=validation,
        resource_bindings=compiled.resource_bindings,
        aggregation_intent=compiled.aggregation_intent,
    )


def _compiled_edit_proposal(
    *,
    compiled_spec: FlowDraftSpecCore,
    aggregation_intent: AggregationIntent = "linear",
) -> CompiledProposal:
    edit = FlowBuilderEditApproval(
        diff=FlowEditDiff(
            step_changes=[StepChange(kind="unchanged", step_name="Analys")]
        ),
        base_flow_revision=3,
        advisories=[
            EditAdvisory(
                code="flow_description_update_required",
                message="The flow description should be refreshed.",
                severity="warning",
                field="flow_description",
            )
        ],
    )
    return CompiledProposal(
        content=FlowBuilderProposalContent(
            spec=compiled_spec,
            plan_rationale="Update the flow.",
            edit=edit,
        ),
        validation=SpecValidationResult(),
        aggregation_intent=aggregation_intent,
    )


def _stored_plan_result(*, plan=None, proposal=None):
    return SimpleNamespace(
        plan=plan or MagicMock(id=uuid4()),
        proposal=proposal
        or FlowBuilderProposal(
            content=FlowBuilderProposalContent(spec=_make_flow_spec())
        ),
        new_planning_state_version=1,
    )


async def _store_compiled_plan(**kwargs):
    return _stored_plan_result(
        proposal=FlowBuilderProposal(
            content=FlowBuilderProposalContent(spec=kwargs["compiled"].content.spec),
        ),
    )


def _make_finalizer(**overrides) -> CompiledProposalFinalizer:
    defaults = {
        "repo": AsyncMock(),
        "quality_retry_warning_codes": set(),
    }
    defaults.update(overrides)
    return CompiledProposalFinalizer(**defaults)


def _make_request(**overrides) -> CompiledProposalFinalizationRequest:
    defaults = {
        "turn": _make_turn(),
        "conversation": [],
        "new_messages_start": 0,
        "tool_name": PROPOSE_FLOW_TOOL_NAME,
        "target_kind": TargetKind.CREATE,
        "arguments": {"flow_name": "Test", "steps": []},
        "assistant_content": "Här är mitt förslag:",
        "assistant_metadata": None,
        "tool_call_id": "call-outline",
        "metadata_tool_call": MagicMock(),
        "compiled": _compiled_outline_proposal(),
        "resource_catalog": None,
        "flow": None,
        "request_id": "req-finalize",
        "usage_tracker": ProposalTurnTelemetry(
            request_id="req-finalize",
            model="openai/gpt-5.4",
            target_kind=TargetKind.CREATE,
        ),
        "planning_state": None,
        "compile_context": None,
    }
    defaults.update(overrides)
    return CompiledProposalFinalizationRequest(**defaults)


@pytest.mark.asyncio
async def test_finalization_passes_the_compile_context_to_quality() -> None:
    compile_context = CreateCompileContext(
        aggregation_intent="compare",
        ui_language="sv",
    )
    finalizer = _make_finalizer()
    contextual_quality = MagicMock(feedback=None, failure_codes=frozenset())

    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_proposal_finalization."
            "build_create_contextual_quality_feedback",
            return_value=contextual_quality,
        ) as build_quality,
        patch(
            "eneo.flows.ai_builder.ai_builder_proposal_finalization."
            "store_plan_and_update_conversation",
            new=_store_compiled_plan,
        ),
    ):
        result = await finalizer.finalize_compiled_proposal(
            _make_request(compile_context=compile_context)
        )

    assert result.events
    quality_context = build_quality.call_args.kwargs["compile_context"]
    assert quality_context is compile_context
    assert quality_context.aggregation_intent == "compare"


def test_finalization_request_is_frozen_without_retry_snapshot_payload() -> None:
    dataclass_params = CompiledProposalFinalizationRequest.__dataclass_params__

    assert dataclass_params.frozen is True
    assert (
        "assistant_snapshots" not in CompiledProposalFinalizationRequest.__annotations__
    )


@pytest.mark.asyncio
async def test_finalize_compiled_proposal_records_success_once_when_persisted() -> None:
    finalizer = _make_finalizer()
    tracker = ProposalTurnTelemetry(
        request_id="req-success",
        model="openai/gpt-5.4",
        target_kind=TargetKind.CREATE,
    )
    captured_metadata: list[dict[str, object] | None] = []

    async def store_plan(**kwargs):
        captured_metadata.append(kwargs["assistant_metadata"])
        return await _store_compiled_plan(**kwargs)

    with patch(
        "eneo.flows.ai_builder.ai_builder_proposal_finalization.store_plan_and_update_conversation",
        new=store_plan,
    ):
        result = await finalizer.finalize_compiled_proposal(
            _make_request(
                request_id="req-success",
                usage_tracker=tracker,
            )
        )

    assert [event.event for event in result.events] == ["plan"]
    assert tracker.proposal_first_attempt_success is True
    assert tracker.proposal_first_attempt_tool == PROPOSE_FLOW_TOOL_NAME
    assert captured_metadata[0] is not None
    assert captured_metadata[0]["planner_telemetry"]["proposal_first_attempt_success"]


@pytest.mark.asyncio
async def test_finalize_compiled_proposal_does_not_record_success_on_quality_reject() -> (
    None
):
    finalizer = _make_finalizer(quality_retry_warning_codes={"json_output_no_contract"})
    validation = SpecValidationResult()
    validation.add_warning(
        step_ref="step_a",
        code="json_output_no_contract",
        message=(
            "Step has output_type 'json' but no output_contract. "
            "Adding one enables structured variable access for downstream steps."
        ),
    )
    tracker = ProposalTurnTelemetry(
        request_id="req-quality",
        model="openai/gpt-5.4",
        target_kind=TargetKind.CREATE,
    )
    store_plan = AsyncMock(return_value=_stored_plan_result())

    with patch(
        "eneo.flows.ai_builder.ai_builder_proposal_finalization.store_plan_and_update_conversation",
        new=store_plan,
    ):
        result = await finalizer.finalize_compiled_proposal(
            _make_request(
                request_id="req-quality",
                usage_tracker=tracker,
                compiled=_compiled_outline_proposal_with_validation(validation),
            )
        )

    assert result.events == ()
    assert result.failure_kind == "quality"
    assert result.failure_codes == frozenset({"json_output_no_contract"})
    assert tracker.proposal_first_attempt_success is None
    store_plan.assert_not_awaited()


@pytest.mark.asyncio
async def test_finalize_compiled_proposal_preserves_citation_validation_family() -> (
    None
):
    validation = SpecValidationResult()
    validation.add_error(
        step_ref="step_a",
        code="citation_mode_unsupported",
        message=(
            "Step 1: citation_mode 'inline_inref_sidecar' requires output_type 'text'."
        ),
    )
    store_plan = AsyncMock(return_value=_stored_plan_result())

    with patch(
        "eneo.flows.ai_builder.ai_builder_proposal_finalization."
        "store_plan_and_update_conversation",
        new=store_plan,
    ):
        result = await _make_finalizer().finalize_compiled_proposal(
            _make_request(
                compiled=_compiled_outline_proposal_with_validation(validation),
            )
        )

    assert result.failure_kind == "validation"
    assert result.failure_codes == frozenset({"citation_mode_unsupported"})
    store_plan.assert_not_awaited()


@pytest.mark.asyncio
async def test_unindexed_array_reference_cannot_reach_plan_persistence() -> None:
    spec = FlowDraftSpecCore(
        flow_name="Array reference",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Extract risks",
                assistant_spec=AssistantSpec(instructions="Extract risks."),
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.JSON,
                output_contract={
                    "type": "object",
                    "properties": {
                        "risks": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {"title": {"type": "string"}},
                            },
                        }
                    },
                },
            ),
            StepSpec(
                plan_step_ref="step_b",
                name="Summarize risk",
                assistant_spec=AssistantSpec(instructions="Summarize one risk."),
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                input_bindings={
                    "question": "{{ step_a.output.structured.risks.title }}"
                },
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.TEXT,
            ),
        ],
    )
    compiled = CompiledProposal(
        content=FlowBuilderProposalContent(spec=spec),
        validation=validate_spec(spec),
    )
    store_plan = AsyncMock(return_value=_stored_plan_result())

    with patch(
        "eneo.flows.ai_builder.ai_builder_proposal_finalization."
        "store_plan_and_update_conversation",
        new=store_plan,
    ):
        result = await _make_finalizer().finalize_compiled_proposal(
            _make_request(compiled=compiled)
        )

    assert result.events == ()
    assert result.failure_kind == "validation"
    assert result.failure_codes == frozenset({"unknown_output_contract_field"})
    store_plan.assert_not_awaited()


@pytest.mark.asyncio
async def test_finalize_compiled_proposal_preserves_contextual_quality_issue_codes() -> (
    None
):
    finalizer = _make_finalizer()
    tracker = ProposalTurnTelemetry(
        request_id="req-contextual-quality",
        model="openai/gpt-5.4",
        target_kind=TargetKind.CREATE,
    )
    store_plan = AsyncMock(return_value=_stored_plan_result())
    compiled = CompiledProposal(
        content=FlowBuilderProposalContent(
            spec=_structured_underbound_spec(),
            plan_rationale="Compose a structured report.",
        ),
        validation=SpecValidationResult(),
    )

    with patch(
        "eneo.flows.ai_builder.ai_builder_proposal_finalization.store_plan_and_update_conversation",
        new=store_plan,
    ):
        result = await finalizer.finalize_compiled_proposal(
            _make_request(
                request_id="req-contextual-quality",
                usage_tracker=tracker,
                compiled=compiled,
            )
        )

    assert result.events == ()
    assert result.failure_kind == "quality"
    assert (
        "final_text_step_must_reference_relevant_structured_outputs"
        in result.failure_codes
    )
    assert result.feedback is not None
    assert "Quality issues" in result.feedback
    store_plan.assert_not_awaited()


@pytest.mark.parametrize(
    "report_disposition",
    ["per_source_sections", "synthesized_overview", "both"],
)
@pytest.mark.parametrize(
    "requested_output_sections",
    [
        RequestedOutputSections.empty(),
        RequestedOutputSections(
            sections=(
                "Résumé",
                "Findings",
                "Analysis",
                "Recommendations",
            ),
            confidence="high",
        ),
    ],
    ids=["no-named-sections", "named-sections"],
)
@pytest.mark.asyncio
async def test_finalize_compiler_lowered_report_needs_no_planner_repair(
    report_disposition: ReportDisposition,
    requested_output_sections: RequestedOutputSections,
) -> None:
    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Source report",
            "plan_rationale": "Extract source evidence and render the report.",
            "steps": [
                {
                    "name": "Read documents",
                    "instructions": "Extract source-grounded evidence.",
                    "output_fields": [
                        {
                            "name": "documents",
                            "field_type": "array",
                            "description": "One record per source.",
                            "children": [
                                {
                                    "name": "summary",
                                    "field_type": "string",
                                    "description": "Source summary.",
                                }
                            ],
                        }
                    ],
                },
                {
                    "name": "Write report",
                    "instructions": "Write the requested report.",
                },
            ],
        }
    )
    compile_context = CreateCompileContext(
        runtime_input_type=InputType.DOCUMENT,
        final_output_type=OutputType.PDF,
        final_output_mode=OutputMode.RENDER_VERBATIM,
        report_disposition=report_disposition,
        requested_output_sections=requested_output_sections,
        runtime_max_files=4,
        ui_language="en",
    )
    spec = compile_create_intent_to_spec(intent, context=compile_context)
    if requested_output_sections.sections:
        compose_bindings = str(spec.steps[-2].input_bindings)
        assert all(
            section in compose_bindings
            for section in requested_output_sections.sections
        )
    compiled = CompiledProposal(
        content=FlowBuilderProposalContent(
            spec=spec,
            plan_rationale="Extract source evidence and render the report.",
        ),
        validation=validate_spec(spec),
    )
    store_plan = AsyncMock(return_value=_stored_plan_result())

    with patch(
        "eneo.flows.ai_builder.ai_builder_proposal_finalization."
        "store_plan_and_update_conversation",
        new=store_plan,
    ):
        result = await _make_finalizer().finalize_compiled_proposal(
            _make_request(
                compiled=compiled,
                compile_context=compile_context,
            )
        )

    assert result.feedback is None
    assert [event.event for event in result.events] == ["plan"]
    store_plan.assert_awaited_once()


@pytest.mark.asyncio
async def test_finalize_single_composer_text_report_needs_no_planner_repair() -> None:
    """One composer may write every requested section.

    How many writing steps a report needs is the model's semantic judgement,
    so a single-composer plan finalizes without planner repair feedback.
    """

    intent = parse_create_flow_intent_arguments(
        {
            "flow_name": "Consultation reply",
            "plan_rationale": "Draft the reply from the uploaded material.",
            "steps": [
                {
                    "name": "Read the material",
                    "instructions": "Extract the facts the reply must build on.",
                    "output_fields": [
                        {
                            "name": "underlag",
                            "field_type": "string",
                            "description": "Facts from the uploaded material.",
                        }
                    ],
                },
                {
                    "name": "Write the reply",
                    "instructions": (
                        "Write the complete reply draft under the requested headings."
                    ),
                },
            ],
        }
    )
    compile_context = CreateCompileContext(
        runtime_input_type=InputType.DOCUMENT,
        final_output_type=OutputType.TEXT,
        requested_output_sections=RequestedOutputSections(
            sections=("Bakgrund", "Bedömning", "Åtgärder", "Risker"),
            confidence="high",
        ),
        ui_language="sv",
    )
    spec = compile_create_intent_to_spec(intent, context=compile_context)
    compiled = CompiledProposal(
        content=FlowBuilderProposalContent(
            spec=spec,
            plan_rationale="Draft the reply from the uploaded material.",
        ),
        validation=validate_spec(spec),
    )
    store_plan = AsyncMock(return_value=_stored_plan_result())

    with patch(
        "eneo.flows.ai_builder.ai_builder_proposal_finalization."
        "store_plan_and_update_conversation",
        new=store_plan,
    ):
        result = await _make_finalizer().finalize_compiled_proposal(
            _make_request(compiled=compiled, compile_context=compile_context)
        )

    assert result.feedback is None
    assert [event.event for event in result.events] == ["plan"]
    store_plan.assert_awaited_once()


@pytest.mark.asyncio
async def test_edit_of_single_composer_report_needs_no_planner_repair() -> None:
    """Editing an existing report keeps the same judgement as creating one.

    Contextual quality runs the full critic registry on the edit path too, so
    an already-compiled one-composer report must finalize without repair
    feedback there as well.
    """

    spec = FlowDraftSpecCore(
        flow_name="Remissvar",
        flow_description="Skriver ett utkast till remissvar.",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Läs underlaget",
                assistant_spec=AssistantSpec(instructions="Läs underlaget."),
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.DOCUMENT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.JSON,
                output_contract={
                    "type": "object",
                    "properties": {"underlag": {"type": "string"}},
                },
            ),
            StepSpec(
                plan_step_ref="step_b",
                name="Skriv utkastet",
                assistant_spec=AssistantSpec(
                    instructions="Skriv hela utkastet under de begärda rubrikerna."
                ),
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.TEXT,
            ),
        ],
    )
    compile_context = CreateCompileContext(
        runtime_input_type=InputType.DOCUMENT,
        final_output_type=OutputType.TEXT,
        requested_output_sections=RequestedOutputSections(
            sections=("Bakgrund", "Bedömning", "Åtgärder", "Risker"),
            confidence="high",
        ),
        ui_language="sv",
    )
    store_plan = AsyncMock(return_value=_stored_plan_result())

    with patch(
        "eneo.flows.ai_builder.ai_builder_proposal_finalization."
        "store_plan_and_update_conversation",
        new=store_plan,
    ):
        result = await _make_finalizer().finalize_compiled_proposal(
            _make_request(
                target_kind=TargetKind.EDIT,
                compiled=_compiled_edit_proposal(compiled_spec=spec),
                compile_context=compile_context,
                conversation=[
                    {
                        "role": "user",
                        "content": (
                            "Rapporten ska ha rubrikerna Bakgrund, Bedömning, "
                            "Åtgärder och Risker."
                        ),
                    }
                ],
                flow=Flow(
                    id=uuid4(),
                    tenant_id=uuid4(),
                    space_id=uuid4(),
                    name="Remissvar",
                    description="Skriver ett utkast till remissvar.",
                    metadata_json={"ai_builder": {"description": {}}},
                    steps=[],
                    draft_revision=3,
                ),
            )
        )

    assert result.feedback is None
    store_plan.assert_awaited_once()


@pytest.mark.asyncio
async def test_finalize_compare_edit_uses_compiled_aggregation_intent() -> None:
    store_plan = AsyncMock(return_value=_stored_plan_result())

    with patch(
        "eneo.flows.ai_builder.ai_builder_proposal_finalization."
        "store_plan_and_update_conversation",
        new=store_plan,
    ):
        result = await _make_finalizer().finalize_compiled_proposal(
            _make_request(
                target_kind=TargetKind.EDIT,
                compiled=_compiled_edit_proposal(
                    compiled_spec=_structured_underbound_spec(
                        final_input_source=InputSource.ALL_PREVIOUS_STEPS
                    ),
                    aggregation_intent="compare",
                ),
                flow=MagicMock(),
            )
        )

    assert [event.event for event in result.events] == ["plan"]
    store_plan.assert_awaited_once()


@pytest.mark.asyncio
async def test_finalize_compiled_proposal_accepts_retry_metadata_without_recorder() -> (
    None
):
    finalizer = _make_finalizer()
    tracker = ProposalTurnTelemetry(
        request_id="req-retry",
        model="openai/gpt-5.4",
        target_kind=TargetKind.CREATE,
    )
    retry_metadata = {"planner_telemetry": {"request_id": "req-retry"}}
    captured_metadata: list[dict[str, object] | None] = []

    async def store_plan(**kwargs):
        captured_metadata.append(kwargs["assistant_metadata"])
        return await _store_compiled_plan(**kwargs)

    with patch(
        "eneo.flows.ai_builder.ai_builder_proposal_finalization.store_plan_and_update_conversation",
        new=store_plan,
    ):
        result = await finalizer.finalize_compiled_proposal(
            _make_request(
                assistant_content="Här är mitt korrigerade förslag:",
                assistant_metadata=retry_metadata,
                metadata_tool_call=None,
                request_id="req-retry",
                usage_tracker=tracker,
            )
        )

    assert [event.event for event in result.events] == ["plan"]
    assert tracker.proposal_first_attempt_success is None
    assert captured_metadata == [retry_metadata]


@pytest.mark.asyncio
async def test_finalize_compiled_proposal_allows_missing_usage_tracker() -> None:
    finalizer = _make_finalizer()
    captured_metadata: list[dict[str, object] | None] = []

    async def store_plan(**kwargs):
        captured_metadata.append(kwargs["assistant_metadata"])
        return await _store_compiled_plan(**kwargs)

    with patch(
        "eneo.flows.ai_builder.ai_builder_proposal_finalization.store_plan_and_update_conversation",
        new=store_plan,
    ):
        result = await finalizer.finalize_compiled_proposal(
            _make_request(
                assistant_metadata={"existing": True},
                usage_tracker=None,
            )
        )

    assert [event.event for event in result.events] == ["plan"]
    assert captured_metadata[0] == {"existing": True}


@pytest.mark.asyncio
async def test_finalize_compiled_proposal_keeps_compiled_edit_without_description_repair() -> (
    None
):
    finalizer = _make_finalizer()
    original_spec = _make_flow_spec()
    captured_compiled: list[CompiledProposal] = []

    async def store_plan(**kwargs):
        captured_compiled.append(kwargs["compiled"])
        return await _store_compiled_plan(**kwargs)

    with patch(
        "eneo.flows.ai_builder.ai_builder_proposal_finalization.store_plan_and_update_conversation",
        new=store_plan,
    ):
        result = await finalizer.finalize_compiled_proposal(
            _make_request(
                tool_name=PROPOSE_FLOW_TOOL_NAME,
                compiled=_compiled_edit_proposal(compiled_spec=original_spec),
                flow=SimpleNamespace(
                    description="Old generated description.",
                    metadata_json={"ai_builder": {"description": {}}},
                    steps=[],
                ),
            )
        )

    assert result.events
    captured = captured_compiled[0]
    assert captured.content.spec.flow_description == original_spec.flow_description
    captured_edit = captured.content.edit
    assert captured_edit is not None
    assert [advisory.code for advisory in captured_edit.advisories] == [
        "flow_description_update_required"
    ]
