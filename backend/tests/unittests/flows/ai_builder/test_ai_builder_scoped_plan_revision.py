from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    PROVIDER_TOOL_CALL_ID_MAX_LENGTH,
    metadata_with_slot_classification,
    slot_classification_metadata_from_result,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
    TargetKind,
)
from eneo.flows.ai_builder.ai_builder_events import encode_ai_builder_stream_event
from eneo.flows.ai_builder.ai_builder_plan_edit_context import (
    AIBuilderPlanEditContext,
)
from eneo.flows.ai_builder.ai_builder_proposal_finalization import (
    CompiledProposalFinalizer,
)
from eneo.flows.ai_builder.ai_builder_proposal_telemetry import ProposalTurnTelemetry
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    ToolProcessingResult,
)
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderAvailableModelResource,
    build_ai_builder_resource_catalog,
)
from eneo.flows.ai_builder.ai_builder_scoped_plan_revision import (
    ScopedPlanRevisionRequest,
    process_scoped_step_revision_if_requested,
    run_scoped_plan_revision_attempt,
)
from eneo.flows.ai_builder.ai_builder_slot_classifier import (
    ClassifiedSlot,
    SlotClassificationResult,
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
from tests.unittests.flows.ai_builder.proposal_turn_builders import (
    _builder_plan,
    _make_flow_spec,
    _make_turn,
    _plan_stream_event,
)


def _model_resource(local_id: str, name: str) -> AIBuilderAvailableModelResource:
    return {
        "id": local_id,
        "ref": local_id,
        "name": name,
        "display_name": name,
        "provider": "test",
    }


def _make_finalizer() -> CompiledProposalFinalizer:
    return CompiledProposalFinalizer(
        repo=AsyncMock(),
        quality_retry_warning_codes=frozenset(),
    )


def _make_request(**overrides: object) -> ScopedPlanRevisionRequest:
    defaults = {
        "turn": _make_turn(),
        "conversation": [],
        "new_messages_start": 0,
        "available_model_refs": None,
        "available_kb_refs": None,
        "resource_catalog": None,
        "plan_edit_context": None,
        "prior_plan_for_revision": None,
        "request_id": "req-1",
        "usage_tracker": ProposalTurnTelemetry(
            request_id="req-1",
            model="openai/gpt-5.4",
            target_kind=TargetKind.CREATE,
        ),
        "assistant_metadata": None,
        "flow": None,
    }
    defaults.update(overrides)
    return ScopedPlanRevisionRequest(**defaults)


def _terminal_output_slot_metadata(value: str = "pdf_document") -> dict[str, object]:
    metadata = slot_classification_metadata_from_result(
        SlotClassificationResult(
            slots=(
                ClassifiedSlot(
                    slot_name="terminal_output",
                    value=value,
                    confidence="medium",
                    reason="classified terminal output",
                    evidence=("ändra output filen till pdf",),
                ),
            )
        ),
        prompt_hash="a" * 64,
    )
    result = metadata_with_slot_classification(None, metadata)
    assert result is not None
    return result


@pytest.mark.asyncio
async def test_scoped_revision_skips_existing_flow_edit_context() -> None:
    result = await run_scoped_plan_revision_attempt(
        request=_make_request(flow=SimpleNamespace(id=uuid4())),
        finalizer=_make_finalizer(),
    )

    assert result is None


@pytest.mark.asyncio
async def test_scoped_revision_returns_error_event_for_deterministic_failure() -> None:
    deterministic_failure = ToolProcessingResult(
        feedback="Scoped plan edit target `step_a` disappeared.",
        failure_kind="quality",
    )

    with patch(
        "eneo.flows.ai_builder.ai_builder_scoped_plan_revision."
        "process_scoped_step_revision_if_requested",
        return_value=deterministic_failure,
    ):
        result = await run_scoped_plan_revision_attempt(
            request=_make_request(request_id="req-deterministic-failure"),
            finalizer=_make_finalizer(),
        )

    assert result is not None
    assert len(result.events) == 1
    payload = json.loads(encode_ai_builder_stream_event(result.events[0])["data"])
    assert payload["code"] == "bad_request"
    assert payload["phase"] == "proposal"
    assert payload["request_id"] == "req-deterministic-failure"
    assert "selected step change" in payload["message"]
    assert "selected model change" not in payload["message"]
    assert payload["details"] == {"failure_kind": "quality"}


@pytest.mark.asyncio
async def test_scoped_revision_uses_bounded_server_tool_call_id() -> None:
    prior_spec = _make_flow_spec(model_ref="model.gpt-4o-mini", knowledge_refs=[])
    prior_plan = _builder_plan(prior_spec)
    catalog = build_ai_builder_resource_catalog(
        available_models=[
            _model_resource("model-old", "gpt-4o mini"),
            _model_resource("model-nano", "gpt-5.4-nano"),
        ],
        available_kbs=[],
        available_mcps=[],
    )
    plan_event = _plan_stream_event()
    finalize = AsyncMock(return_value=ToolProcessingResult(events=(plan_event,)))

    with patch.object(
        CompiledProposalFinalizer, "finalize_compiled_proposal", new=finalize
    ):
        result = await run_scoped_plan_revision_attempt(
            request=_make_request(
                conversation=[
                    ConversationMessage(
                        role="user",
                        content="byt modell till gpt 5.4 nano",
                    )
                ],
                prior_plan_for_revision=prior_plan,
                plan_edit_context=AIBuilderPlanEditContext(
                    scope="step",
                    plan_id=prior_plan.id,
                    target_plan_step_ref="step_a",
                ),
                resource_catalog=catalog,
                available_model_refs=catalog.model_refs,
                request_id="00000000-0000-0000-0000-000000000000",
            ),
            finalizer=_make_finalizer(),
        )

    assert result is not None
    assert result.events == (plan_event,)
    request = finalize.await_args.args[0]
    assert request.tool_call_id != (
        "server_scoped_model_revision:00000000-0000-0000-0000-000000000000"
    )
    assert "scoped_step_revision" in request.tool_call_id
    assert len(request.tool_call_id) <= PROVIDER_TOOL_CALL_ID_MAX_LENGTH


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        "kan du ändra så att jag får en pdf fil istället?",
        "utdatat ska vara pdf fil",
    ],
)
async def test_scoped_revision_finalizes_terminal_pdf_revision(message: str) -> None:
    prior_spec = _make_flow_spec(model_ref="model.gpt-4o-mini", knowledge_refs=[])
    prior_plan = _builder_plan(prior_spec)
    plan_event = _plan_stream_event()
    finalize = AsyncMock(return_value=ToolProcessingResult(events=(plan_event,)))

    with patch.object(
        CompiledProposalFinalizer, "finalize_compiled_proposal", new=finalize
    ):
        result = await run_scoped_plan_revision_attempt(
            request=_make_request(
                conversation=[
                    ConversationMessage(
                        role="user",
                        content=message,
                    )
                ],
                prior_plan_for_revision=prior_plan,
                plan_edit_context=AIBuilderPlanEditContext(
                    scope="step",
                    plan_id=prior_plan.id,
                    target_plan_step_ref="step_a",
                ),
                request_id="00000000-0000-0000-0000-000000000001",
            ),
            finalizer=_make_finalizer(),
        )

    assert result is not None
    assert result.events == (plan_event,)
    request = finalize.await_args.args[0]
    assert request.arguments["revision_kind"] == "scoped_step_direct"
    assert request.assistant_content == "Jag har uppdaterat det valda steget."
    assert request.compiled.content.spec.steps[0].output_type == OutputType.PDF
    assert len(request.tool_call_id) <= PROVIDER_TOOL_CALL_ID_MAX_LENGTH


@pytest.mark.asyncio
async def test_scoped_revision_returns_error_for_finalization_feedback_only() -> None:
    prior_spec = _make_flow_spec(model_ref="model.gpt-4o-mini", knowledge_refs=[])
    prior_plan = _builder_plan(prior_spec)
    finalize = AsyncMock(
        return_value=ToolProcessingResult(
            feedback="quality warning", failure_kind="quality"
        )
    )
    catalog = build_ai_builder_resource_catalog(
        available_models=[
            _model_resource("model-old", "gpt-4o mini"),
            _model_resource("model-nano", "gpt-5.4-nano"),
        ],
        available_kbs=[],
        available_mcps=[],
    )

    with patch.object(
        CompiledProposalFinalizer, "finalize_compiled_proposal", new=finalize
    ):
        result = await run_scoped_plan_revision_attempt(
            request=_make_request(
                conversation=[
                    ConversationMessage(
                        role="user",
                        content="byt modell från gpt-4o mini till gpt 5.4 nano",
                    )
                ],
                prior_plan_for_revision=prior_plan,
                plan_edit_context=AIBuilderPlanEditContext(
                    scope="step",
                    plan_id=prior_plan.id,
                    target_plan_step_ref="step_a",
                ),
                resource_catalog=catalog,
                available_model_refs=catalog.model_refs,
                request_id="req-scoped-finalization-feedback",
            ),
            finalizer=_make_finalizer(),
        )

    assert result is not None
    assert len(result.events) == 1
    payload = json.loads(encode_ai_builder_stream_event(result.events[0])["data"])
    assert payload["code"] == "bad_request"
    assert payload["phase"] == "proposal"
    assert payload["request_id"] == "req-scoped-finalization-feedback"
    assert "selected step change" in payload["message"]
    assert payload["details"] == {"failure_kind": "quality"}


@pytest.mark.asyncio
async def test_scoped_outline_revision_explains_model_change_on_transcription_step() -> (
    None
):
    catalog = build_ai_builder_resource_catalog(
        available_models=[
            _model_resource("model-old", "gpt-4o mini"),
            _model_resource("model-base", "gpt-5.4"),
            _model_resource("model-nano", "gpt-5.4-nano"),
        ],
        available_kbs=[],
        available_mcps=[],
    )
    prior_spec = FlowDraftSpecCore(
        flow_name="Mötesflöde",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Transkribera mötesljud",
                assistant_spec=AssistantSpec(instructions="Transkribera ljudet."),
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.AUDIO,
                output_mode=OutputMode.TRANSCRIBE_ONLY,
                output_type=OutputType.TEXT,
            ),
            StepSpec(
                plan_step_ref="step_b",
                name="Analysera mötet",
                assistant_spec=AssistantSpec(
                    instructions="Analysera transkriptionen.",
                    model_ref="model.gpt-4o-mini",
                ),
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.TEXT,
            ),
        ],
    )
    prior_plan = _builder_plan(prior_spec)

    result = process_scoped_step_revision_if_requested(
        conversation=[
            ConversationMessage(
                role="user",
                content="ändra modell till gpt 5.4 nano",
            )
        ],
        available_model_refs=catalog.model_refs,
        available_kb_refs=None,
        resource_catalog=catalog,
        plan_edit_context=AIBuilderPlanEditContext(
            scope="step",
            plan_id=prior_plan.id,
            target_plan_step_ref="step_a",
            target_step_name="Transkribera mötesljud",
            target_step_number=1,
        ),
        prior_plan_for_revision=prior_plan,
    )

    assert result is not None
    assert result.compiled_proposal is None
    assert result.feedback is None
    assert result.user_message is not None
    assert "transkriberar ljud" in result.user_message
    assert "model.gpt-5-4-nano" not in result.user_message


@pytest.mark.asyncio
async def test_scoped_outline_revision_changes_model_on_selected_ai_step() -> None:
    catalog = build_ai_builder_resource_catalog(
        available_models=[
            _model_resource("model-old", "gpt-4o mini"),
            _model_resource("model-nano", "gpt-5.4-nano"),
        ],
        available_kbs=[],
        available_mcps=[],
    )
    old_model_ref = "model.gpt-4o-mini"
    new_model_ref = "model.gpt-5-4-nano"
    prior_spec = FlowDraftSpecCore(
        flow_name="Mötesflöde",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Transkribera mötesljud",
                assistant_spec=AssistantSpec(instructions="Transkribera ljudet."),
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.AUDIO,
                output_mode=OutputMode.TRANSCRIBE_ONLY,
                output_type=OutputType.TEXT,
            ),
            StepSpec(
                plan_step_ref="step_b",
                name="Analysera mötet",
                assistant_spec=AssistantSpec(
                    instructions="Analysera transkriptionen.",
                    model_ref=old_model_ref,
                ),
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.TEXT,
            ),
        ],
    )
    prior_plan = _builder_plan(prior_spec)

    result = process_scoped_step_revision_if_requested(
        conversation=[
            ConversationMessage(
                role="user",
                content="byt modell från gpt-4o mini till gpt 5.4 nano",
            )
        ],
        available_model_refs=catalog.model_refs,
        available_kb_refs=None,
        resource_catalog=catalog,
        plan_edit_context=AIBuilderPlanEditContext(
            scope="step",
            plan_id=prior_plan.id,
            target_plan_step_ref="step_b",
            target_step_name="Analysera mötet",
            target_step_number=2,
        ),
        prior_plan_for_revision=prior_plan,
    )

    assert result is not None
    assert result.compiled_proposal is not None
    assert result.feedback is None
    assert (
        result.compiled_proposal.content.plan_rationale
        == "Bytte modell på det valda steget."
    )
    assert result.compiled_proposal.content.assumptions == []
    revised_steps = result.compiled_proposal.content.spec.steps
    assert revised_steps[0].model_dump(mode="json") == prior_spec.steps[0].model_dump(
        mode="json"
    )
    assert revised_steps[1].assistant_spec.model_ref == new_model_ref


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        "kan du ändra så att jag får en pdf fil istället?",
        "utdatat ska vara pdf fil",
    ],
)
async def test_scoped_outline_revision_changes_selected_terminal_step_to_pdf(
    message: str,
) -> None:
    prior_spec = FlowDraftSpecCore(
        flow_name="Mötesflöde",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Extrahera agenda",
                assistant_spec=AssistantSpec(instructions="Extrahera agenda."),
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.JSON,
                output_contract={
                    "type": "object",
                    "properties": {"agenda": {"type": "array"}},
                },
            ),
            StepSpec(
                plan_step_ref="step_f",
                name="Sätt ihop slutligt strukturerat textresultat",
                assistant_spec=AssistantSpec(
                    instructions="Skriv ett strukturerat textprotokoll.",
                    model_ref="model.gpt-5-4-mini",
                ),
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.TEXT,
            ),
        ],
    )
    prior_plan = _builder_plan(prior_spec)

    result = process_scoped_step_revision_if_requested(
        conversation=[
            ConversationMessage(
                role="user",
                content=message,
            )
        ],
        available_model_refs=None,
        available_kb_refs=None,
        resource_catalog=None,
        plan_edit_context=AIBuilderPlanEditContext(
            scope="step",
            plan_id=prior_plan.id,
            target_plan_step_ref="step_f",
            target_step_name="Sätt ihop slutligt strukturerat textresultat",
            target_step_number=2,
        ),
        prior_plan_for_revision=prior_plan,
    )

    assert result is not None
    assert result.compiled_proposal is not None
    revised_steps = result.compiled_proposal.content.spec.steps
    assert revised_steps[0].model_dump(mode="json") == prior_spec.steps[0].model_dump(
        mode="json"
    )
    assert revised_steps[1].output_type == OutputType.PDF
    assert revised_steps[1].output_contract is None


@pytest.mark.asyncio
async def test_scoped_outline_revision_uses_slot_classification_for_pdf_edit() -> None:
    prior_spec = FlowDraftSpecCore(
        flow_name="Mötesflöde",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Extrahera agenda",
                assistant_spec=AssistantSpec(instructions="Extrahera agenda."),
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.JSON,
                output_contract={
                    "type": "object",
                    "properties": {"agenda": {"type": "array"}},
                },
            ),
            StepSpec(
                plan_step_ref="step_f",
                name="Sätt ihop slutligt strukturerat textresultat",
                assistant_spec=AssistantSpec(
                    instructions="Skriv ett strukturerat textprotokoll.",
                    model_ref="model.gpt-5-4-mini",
                ),
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.TEXT,
            ),
        ],
    )
    prior_plan = _builder_plan(prior_spec)

    result = process_scoped_step_revision_if_requested(
        conversation=[
            ConversationMessage(
                role="user",
                content="ändra output filen till pdf",
                metadata=_terminal_output_slot_metadata(),
            )
        ],
        available_model_refs=None,
        available_kb_refs=None,
        resource_catalog=None,
        plan_edit_context=AIBuilderPlanEditContext(
            scope="step",
            plan_id=prior_plan.id,
            target_plan_step_ref="step_f",
            target_step_name="Sätt ihop slutligt strukturerat textresultat",
            target_step_number=2,
        ),
        prior_plan_for_revision=prior_plan,
    )

    assert result is not None
    assert result.compiled_proposal is not None
    revised_steps = result.compiled_proposal.content.spec.steps
    assert revised_steps[0].model_dump(mode="json") == prior_spec.steps[0].model_dump(
        mode="json"
    )
    assert revised_steps[1].output_type == OutputType.PDF
