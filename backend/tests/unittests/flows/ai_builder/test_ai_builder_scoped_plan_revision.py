from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from eneo.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    PROVIDER_TOOL_CALL_ID_MAX_LENGTH,
)
from eneo.flows.ai_builder.ai_builder_create_compile_context import CreateCompileContext
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
    TargetKind,
)
from eneo.flows.ai_builder.ai_builder_event_models import AIBuilderPlanEvent
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
from eneo.flows.ai_builder.ai_builder_scoped_plan_revision import (
    ScopedPlanRevisionRequest,
    process_scoped_step_revision_if_requested,
    run_scoped_plan_revision_attempt,
)
from eneo.flows.ai_builder.planning_state import PlanningState, ResolvedSlot
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


def _make_finalizer() -> CompiledProposalFinalizer:
    return CompiledProposalFinalizer(
        repo=AsyncMock(),
        quality_retry_warning_codes=frozenset(),
    )


@asynccontextmanager
async def _noop_savepoint() -> AsyncIterator[None]:
    yield


def _make_persisting_repo() -> AsyncMock:
    """Repo double an accepted proposal can actually be stored through."""
    repo = AsyncMock()
    repo.savepoint = _noop_savepoint
    repo.create_plan = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
    repo.commit_turn = AsyncMock(return_value=1)
    return repo


def _make_request(**overrides: object) -> ScopedPlanRevisionRequest:
    defaults = {
        "turn": _make_turn(),
        "conversation": [],
        "new_messages_start": 0,
        "available_model_refs": None,
        "available_kb_refs": None,
        "resource_catalog": None,
        "plan_edit_context": None,
        "prior_spec_for_revision": None,
        "request_id": "req-1",
        "usage_tracker": ProposalTurnTelemetry(
            request_id="req-1",
            model="openai/gpt-5.4",
            target_kind=TargetKind.CREATE,
        ),
        "compile_context": None,
        "planning_state": PlanningState.empty(),
        "assistant_metadata": None,
        "flow": None,
    }
    defaults.update(overrides)
    return ScopedPlanRevisionRequest(**defaults)


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
async def test_scoped_revision_contains_typed_compiler_defect() -> None:
    compiler_error = AIBuilderArchitectureError(
        public_code="architecture_materialization_failed",
        detail="The compiled terminal disagrees with the committed architecture.",
        log_context={"failure_code": "terminal_output_type_mismatch"},
    )
    finalize = AsyncMock()

    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_scoped_plan_revision."
            "process_scoped_step_revision_if_requested",
            side_effect=compiler_error,
        ),
        patch.object(
            CompiledProposalFinalizer,
            "finalize_compiled_proposal",
            new=finalize,
        ),
    ):
        result = await run_scoped_plan_revision_attempt(
            request=_make_request(request_id="req-compiler-defect"),
            finalizer=_make_finalizer(),
        )

    assert result is not None
    assert len(result.events) == 1
    payload = json.loads(encode_ai_builder_stream_event(result.events[0])["data"])
    assert payload["code"] == "architecture_materialization_failed"
    assert payload["phase"] == "proposal"
    assert payload["request_id"] == "req-compiler-defect"
    assert payload["details"]["failure_code"] == "terminal_output_type_mismatch"
    finalize.assert_not_awaited()


@pytest.mark.asyncio
async def test_scoped_revision_uses_bounded_server_tool_call_id() -> None:
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
                        content="kan du ändra så att jag får en pdf fil istället?",
                    )
                ],
                prior_spec_for_revision=prior_plan.spec,
                plan_edit_context=AIBuilderPlanEditContext(
                    scope="step",
                    plan_id=prior_plan.id,
                    target_plan_step_ref="step_a",
                ),
                compile_context=CreateCompileContext(final_output_type=OutputType.PDF),
                request_id="00000000-0000-0000-0000-000000000000",
            ),
            finalizer=_make_finalizer(),
        )

    assert result is not None
    assert result.events == (plan_event,)
    request = finalize.await_args.args[0]
    assert request.tool_call_id != (
        "server_scoped_step_revision:00000000-0000-0000-0000-000000000000"
    )
    assert "scoped_step_revision" in request.tool_call_id
    assert len(request.tool_call_id) <= PROVIDER_TOOL_CALL_ID_MAX_LENGTH


@pytest.mark.asyncio
async def test_scoped_revision_rejects_unknown_flow_input_key() -> None:
    prior_spec = FlowDraftSpecCore(
        flow_name="Mötesflöde",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Extrahera agenda",
                assistant_spec=AssistantSpec(
                    instructions="Use {{ flow_input.case_identifier }}.",
                    model_ref="model.gpt-4o-mini",
                ),
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
                name="Skriv protokoll",
                assistant_spec=AssistantSpec(instructions="Skriv protokollet."),
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.JSON,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.TEXT,
            ),
        ],
    )
    prior_plan = _builder_plan(prior_spec)
    repo = AsyncMock()
    repo.savepoint = MagicMock(
        side_effect=AssertionError("invalid scoped revision reached persistence")
    )

    result = await run_scoped_plan_revision_attempt(
        request=_make_request(
            conversation=[
                ConversationMessage(
                    role="user",
                    content="kan du ändra så att jag får en pdf fil istället?",
                )
            ],
            prior_spec_for_revision=prior_plan.spec,
            plan_edit_context=AIBuilderPlanEditContext(
                scope="step",
                plan_id=prior_plan.id,
                target_plan_step_ref="step_f",
            ),
            compile_context=CreateCompileContext(final_output_type=OutputType.PDF),
            request_id="req-invalid-flow-input",
        ),
        finalizer=CompiledProposalFinalizer(
            repo=repo,
            quality_retry_warning_codes=frozenset(),
        ),
    )

    assert result is not None
    assert len(result.events) == 1
    payload = json.loads(encode_ai_builder_stream_event(result.events[0])["data"])
    assert payload["details"] == {"failure_kind": "validation"}


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
                prior_spec_for_revision=prior_plan.spec,
                plan_edit_context=AIBuilderPlanEditContext(
                    scope="step",
                    plan_id=prior_plan.id,
                    target_plan_step_ref="step_a",
                ),
                compile_context=CreateCompileContext(final_output_type=OutputType.PDF),
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
async def test_scoped_revision_critic_reads_committed_docx_mode_not_conversation_text() -> (
    None
):
    """The scoped revision finalizes against the committed planning state.

    The message *rejects* a Word template, which agrees with the committed
    `docx_output_mode=generated_docx` slot but which the negation-blind text
    heuristic reads as `template_fill_docx`. The plan has no `template_fill`
    step, so evaluating the critic on the keyword reading would hard-fail this
    revision with `architecture_critic_invariant_failed` instead of applying
    the output-artifact change.

    The compile context carries the committed DOCX terminal, as production
    always does.
    """
    prior_spec = FlowDraftSpecCore(
        flow_name="Mötesflöde",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Extrahera agenda",
                assistant_spec=AssistantSpec(
                    instructions="Extrahera agenda.",
                    model_ref="model.gpt-4o-mini",
                ),
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
                name="Skriv protokoll",
                assistant_spec=AssistantSpec(instructions="Skriv protokollet."),
                input_source=InputSource.PREVIOUS_STEP,
                input_type=InputType.JSON,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.TEXT,
            ),
        ],
    )
    prior_plan = _builder_plan(prior_spec)
    planning_state = PlanningState.empty()
    for slot_name, value in (
        ("terminal_output", "docx_document"),
        ("docx_output_mode", "generated_docx"),
    ):
        planning_state.resolved_slots[slot_name] = ResolvedSlot(
            name=slot_name,
            value=value,
            source="structured_answer",
            confidence="high",
            evidence=[f"question_answer:{slot_name}"],
        )

    result = await run_scoped_plan_revision_attempt(
        request=_make_request(
            conversation=[
                ConversationMessage(
                    role="user",
                    content=(
                        "ändra slutresultatet till en word-fil, "
                        "men använd ingen word-mall"
                    ),
                )
            ],
            prior_spec_for_revision=prior_plan.spec,
            plan_edit_context=AIBuilderPlanEditContext(
                scope="step",
                plan_id=prior_plan.id,
                target_plan_step_ref="step_f",
                target_step_name="Skriv protokoll",
                target_step_number=2,
            ),
            compile_context=CreateCompileContext(
                final_output_type=OutputType.DOCX,
                final_output_mode=OutputMode.RENDER_VERBATIM,
            ),
            planning_state=planning_state,
            request_id="req-committed-docx-mode",
        ),
        finalizer=CompiledProposalFinalizer(
            repo=_make_persisting_repo(),
            quality_retry_warning_codes=frozenset(),
        ),
    )

    assert result is not None
    plan_event = result.events[0]
    assert isinstance(plan_event, AIBuilderPlanEvent)
    stored_steps = plan_event.data.proposal.spec.steps
    assert stored_steps[0].model_dump(mode="json") == prior_spec.steps[0].model_dump(
        mode="json"
    )
    assert stored_steps[-1].output_type == OutputType.DOCX
    assert all(step.output_mode != OutputMode.TEMPLATE_FILL for step in stored_steps)


@pytest.mark.asyncio
async def test_scoped_revision_returns_error_for_finalization_feedback_only() -> None:
    prior_spec = _make_flow_spec(model_ref="model.gpt-4o-mini", knowledge_refs=[])
    prior_plan = _builder_plan(prior_spec)
    finalize = AsyncMock(
        return_value=ToolProcessingResult(
            feedback="quality warning", failure_kind="quality"
        )
    )

    with patch.object(
        CompiledProposalFinalizer, "finalize_compiled_proposal", new=finalize
    ):
        result = await run_scoped_plan_revision_attempt(
            request=_make_request(
                conversation=[
                    ConversationMessage(
                        role="user",
                        content="kan du ändra så att jag får en pdf fil istället?",
                    )
                ],
                prior_spec_for_revision=prior_plan.spec,
                plan_edit_context=AIBuilderPlanEditContext(
                    scope="step",
                    plan_id=prior_plan.id,
                    target_plan_step_ref="step_a",
                ),
                compile_context=CreateCompileContext(final_output_type=OutputType.PDF),
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
async def test_scoped_outline_revision_leaves_model_requests_to_the_edit_path() -> None:
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
                content="byt modell från gpt-4o mini till gpt 5.4 nano",
            )
        ],
        available_model_refs=None,
        available_kb_refs=None,
        resource_catalog=None,
        plan_edit_context=AIBuilderPlanEditContext(
            scope="step",
            plan_id=prior_plan.id,
            target_plan_step_ref="step_b",
            target_step_name="Analysera mötet",
            target_step_number=2,
        ),
        prior_spec_for_revision=prior_plan.spec,
        terminal_output_type=OutputType.TEXT,
    )

    # No deterministic revision and no keyword refusal: the model is immutable
    # in the edit contract, so the normal edit path answers the user.
    assert result is None


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
        prior_spec_for_revision=prior_plan.spec,
        terminal_output_type=OutputType.PDF,
    )

    assert result is not None
    assert result.compiled_proposal is not None
    revised_steps = result.compiled_proposal.content.spec.steps
    assert revised_steps[0].model_dump(mode="json") == prior_spec.steps[0].model_dump(
        mode="json"
    )
    assert revised_steps[1].output_type == OutputType.PDF
    assert revised_steps[1].output_contract is None
