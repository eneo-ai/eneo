from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    metadata_with_slot_classification,
    slot_classification_metadata_from_attempt,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    BuilderPlan,
    BuilderSession,
    ConversationMessage,
    TargetKind,
)
from eneo.flows.ai_builder.ai_builder_error_contract import AIBuilderBadRequestException
from eneo.flows.ai_builder.ai_builder_plan_edit_context import (
    AIBuilderPlanEditContext,
    AIBuilderSavedFlowStepEditContext,
    ResolvedAIBuilderEditContext,
    _validate_target_step_model,
    build_plan_revision_prompt_block,
    resolve_plan_edit_context,
    scoped_revision_out_of_reach_message,
    validate_scoped_plan_revision,
)
from eneo.flows.ai_builder.ai_builder_proposal_policy import (
    terminal_output_type_for_edit_conversation,
)
from eneo.flows.ai_builder.ai_builder_slot_classification_contract import (
    ClassifiedEvidence,
    ClassifiedSlot,
    SlotClassificationAttempt,
    SlotClassificationInput,
    SlotClassificationResult,
    SlotClassificationSource,
)
from eneo.flows.domain.flow import Flow, FlowStep
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


def _terminal_output_slot_metadata(value: str = "pdf_document") -> dict[str, object]:
    result = SlotClassificationResult(
        slots=(
            ClassifiedSlot(
                slot_name="terminal_output",
                value=value,
                confidence="medium",
                reason="classified terminal output",
                evidence=(
                    ClassifiedEvidence(
                        source_id="user_message:user-1",
                        quote="ändra output filen till pdf",
                    ),
                ),
            ),
        )
    )
    metadata = slot_classification_metadata_from_attempt(
        SlotClassificationAttempt(outcome="resolved", result=result),
        prompt_hash="a" * 64,
        classification_input=SlotClassificationInput(
            sources=(
                SlotClassificationSource(
                    source_id="user_message:user-1",
                    kind="user_message",
                    text="ändra output filen till pdf",
                    message_id="user-1",
                ),
            )
        ),
        model="openai/gpt-test",
        provider="openai",
    )
    result = metadata_with_slot_classification(None, metadata)
    assert result is not None
    return result


def _spec(
    *,
    model_ref: str | None = None,
    output_mode: OutputMode = OutputMode.PASS_THROUGH,
    existing_step_ref: str | None = None,
) -> FlowDraftSpecCore:
    return FlowDraftSpecCore(
        flow_name="Mötesflöde",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                existing_step_ref=existing_step_ref,
                name="Analysera mötet",
                assistant_spec=AssistantSpec(
                    instructions="Analysera transkriptionen.",
                    model_ref=model_ref,
                ),
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
                output_mode=output_mode,
                output_type=OutputType.TEXT,
            )
        ],
    )


def _step_context(**updates) -> AIBuilderPlanEditContext:
    data = {
        "scope": "step",
        "plan_id": uuid4(),
        "target_plan_step_ref": "step_a",
    }
    data.update(updates)
    return AIBuilderPlanEditContext(**data)


def _edit_session(*, latest_plan_id: UUID | None = None) -> BuilderSession:
    return BuilderSession(
        id=uuid4(),
        tenant_id=uuid4(),
        space_id=uuid4(),
        target_kind=TargetKind.EDIT,
        flow_id=uuid4(),
        latest_plan_id=latest_plan_id,
    )


def _saved_flow(*, session: BuilderSession, step_id: UUID, step_order: int = 1) -> Flow:
    assert session.flow_id is not None
    return Flow(
        id=session.flow_id,
        tenant_id=session.tenant_id,
        space_id=session.space_id,
        name="Mötesflöde",
        steps=[
            FlowStep(
                id=step_id,
                flow_id=session.flow_id,
                tenant_id=session.tenant_id,
                assistant_id=uuid4(),
                step_order=step_order,
                user_description="Sammanfatta mötet",
                input_source="flow_input",
                input_type="text",
                output_mode="pass_through",
                output_type="text",
            )
        ],
    )


@pytest.mark.asyncio
async def test_saved_flow_step_scope_resolves_uuid_to_current_step_ref() -> None:
    step_id = uuid4()
    session = _edit_session()
    flow = _saved_flow(session=session, step_id=step_id, step_order=3)

    resolved, prior_plan = await resolve_plan_edit_context(
        repo=cast(object, SimpleNamespace()),
        tenant_id=session.tenant_id,
        session=session,
        flow=flow,
        context=AIBuilderSavedFlowStepEditContext(flow_step_id=step_id),
    )

    assert isinstance(resolved, ResolvedAIBuilderEditContext)
    assert resolved.target_existing_step_ref == "existing_step_3"
    assert resolved.target_step_name == "Sammanfatta mötet"
    assert resolved.target_step_number == 3
    assert prior_plan is None


@pytest.mark.asyncio
async def test_saved_flow_step_scope_rejects_deleted_step() -> None:
    session = _edit_session()
    flow = _saved_flow(session=session, step_id=uuid4())

    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        await resolve_plan_edit_context(
            repo=cast(object, SimpleNamespace()),
            tenant_id=session.tenant_id,
            session=session,
            flow=flow,
            context=AIBuilderSavedFlowStepEditContext(flow_step_id=uuid4()),
        )

    assert getattr(exc_info.value, "code", None).value == "invalid_existing_step_ref"


@pytest.mark.asyncio
async def test_saved_flow_step_scope_rejects_after_plan_exists() -> None:
    step_id = uuid4()
    session = _edit_session(latest_plan_id=uuid4())
    flow = _saved_flow(session=session, step_id=step_id)

    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        await resolve_plan_edit_context(
            repo=cast(object, SimpleNamespace()),
            tenant_id=session.tenant_id,
            session=session,
            flow=flow,
            context=AIBuilderSavedFlowStepEditContext(flow_step_id=step_id),
        )

    assert getattr(exc_info.value, "code", None).value == "stale_plan_revision"


@pytest.mark.asyncio
async def test_plan_step_scope_rejects_conflicting_target_refs() -> None:
    plan_id = uuid4()
    session = _edit_session(latest_plan_id=plan_id)
    plan = SimpleNamespace(
        id=plan_id,
        session_id=session.id,
        spec=_edit_spec(
            [
                _edit_step(
                    "step_a",
                    "Analyze input",
                    output_type=OutputType.JSON,
                    existing_step_ref="existing_step_1",
                ),
                _edit_step(
                    "step_b",
                    "Create result",
                    output_type=OutputType.TEXT,
                    existing_step_ref="existing_step_2",
                ),
            ]
        ),
    )
    repo = SimpleNamespace(get_plan=AsyncMock(return_value=plan))

    with pytest.raises(AIBuilderBadRequestException) as exc_info:
        await resolve_plan_edit_context(
            repo=cast(object, repo),
            tenant_id=session.tenant_id,
            session=session,
            flow=None,
            context=AIBuilderPlanEditContext(
                scope="step",
                plan_id=plan_id,
                target_plan_step_ref="step_a",
                target_existing_step_ref="existing_step_2",
            ),
        )

    assert getattr(exc_info.value, "code", None).value == "invalid_existing_step_ref"


@pytest.mark.asyncio
async def test_plan_step_scope_derives_canonical_target_identity() -> None:
    plan_id = uuid4()
    session = _edit_session(latest_plan_id=plan_id)
    plan = SimpleNamespace(
        id=plan_id,
        session_id=session.id,
        spec=_edit_spec(
            [
                _edit_step(
                    "step_a",
                    "Analyze input",
                    output_type=OutputType.JSON,
                    existing_step_ref="existing_step_1",
                ),
                _edit_step(
                    "step_b",
                    "Create result",
                    output_type=OutputType.TEXT,
                    existing_step_ref="existing_step_2",
                ),
            ]
        ),
    )
    repo = SimpleNamespace(get_plan=AsyncMock(return_value=plan))

    resolved, _ = await resolve_plan_edit_context(
        repo=cast(object, repo),
        tenant_id=session.tenant_id,
        session=session,
        flow=None,
        context=AIBuilderPlanEditContext(
            scope="step",
            plan_id=plan_id,
            target_plan_step_ref="step_b",
            target_step_name="Stale client label",
            target_step_number=99,
        ),
    )

    assert resolved is not None
    assert resolved.target_plan_step_ref == "step_b"
    assert resolved.target_existing_step_ref == "existing_step_2"
    assert resolved.target_step_name == "Create result"
    assert resolved.target_step_number == 2


@pytest.mark.parametrize(
    "wording",
    [
        "pdf fil",
        "pdf-fil",
        "pdf file",
        "pdf-file",
        "pdffil",
    ],
)
def test_terminal_output_intent_recognizes_pdf_file_wording(
    wording: str,
) -> None:
    conversation = [
        ConversationMessage(role="assistant", content="Här är planen."),
        ConversationMessage(role="user", content=f"utdatat ska vara {wording}"),
    ]

    assert (
        terminal_output_type_for_edit_conversation(
            conversation,
            plan_edit_context=_step_context(target_plan_step_ref="step_b"),
            prior_spec=None,
        )
        == OutputType.PDF
    )


def test_terminal_output_intent_uses_latest_slot_classification_for_plan_edit() -> None:
    conversation = [
        ConversationMessage(role="assistant", content="Här är planen."),
        ConversationMessage(
            role="user",
            content="ändra output filen till pdf",
            metadata=_terminal_output_slot_metadata(),
        ),
    ]

    assert (
        terminal_output_type_for_edit_conversation(
            conversation,
            plan_edit_context=_step_context(target_plan_step_ref="step_b"),
            prior_spec=None,
        )
        == OutputType.PDF
    )


def test_step_scoped_revision_rejects_unchanged_target_step() -> None:
    context = AIBuilderPlanEditContext(
        scope="step",
        plan_id=UUID("00000000-0000-0000-0000-000000000001"),
        target_plan_step_ref="step_b",
    )
    prior = _edit_spec(
        [
            _edit_step("step_a", "Analyze input", output_type=OutputType.JSON),
            _edit_step("step_b", "Create final result", output_type=OutputType.TEXT),
        ]
    )
    proposed = _edit_spec(
        [
            _edit_step("step_a", "Analyze input", output_type=OutputType.JSON),
            _edit_step("step_b", "Create final result", output_type=OutputType.TEXT),
            _edit_step("step_c", "Render PDF", output_type=OutputType.PDF),
        ]
    )

    rejection = validate_scoped_plan_revision(
        target_kind=TargetKind.CREATE,
        context=context,
        prior_spec=prior,
        proposed_spec=proposed,
    )

    assert rejection is not None
    feedback = rejection.feedback
    assert "step_b" in feedback
    assert "was unchanged" in feedback


def test_step_scoped_revision_accepts_changed_target_step() -> None:
    context = AIBuilderPlanEditContext(
        scope="step",
        plan_id=UUID("00000000-0000-0000-0000-000000000001"),
        target_plan_step_ref="step_b",
    )
    prior = _edit_spec(
        [_edit_step("step_b", "Create final result", output_type=OutputType.TEXT)]
    )
    proposed = _edit_spec(
        [_edit_step("step_b", "Create final result", output_type=OutputType.PDF)]
    )

    assert (
        validate_scoped_plan_revision(
            target_kind=TargetKind.CREATE,
            context=context,
            prior_spec=prior,
            proposed_spec=proposed,
        )
        is None
    )


def test_step_scoped_revision_rejects_helper_step_insertion() -> None:
    context = AIBuilderPlanEditContext(
        scope="step",
        plan_id=UUID("00000000-0000-0000-0000-000000000001"),
        target_plan_step_ref="step_b",
    )
    prior = _edit_spec(
        [
            _edit_step("step_a", "Analyze input", output_type=OutputType.JSON),
            _edit_step("step_b", "Create final result", output_type=OutputType.TEXT),
            _edit_step("step_c", "Publish result", output_type=OutputType.TEXT),
        ]
    )
    proposed = _edit_spec(
        [
            _edit_step("step_a", "Analyze input", output_type=OutputType.JSON),
            _edit_step("step_b", "Create final PDF", output_type=OutputType.PDF),
            _edit_step("step_helper", "Prepare PDF", output_type=OutputType.TEXT),
            _edit_step("step_c", "Publish result", output_type=OutputType.TEXT),
        ]
    )

    rejection = validate_scoped_plan_revision(
        target_kind=TargetKind.CREATE,
        context=context,
        prior_spec=prior,
        proposed_spec=proposed,
    )

    assert rejection is not None
    feedback = rejection.feedback
    assert "must not add, remove, or reorder steps" in feedback
    assert "step_helper" in feedback


def test_saved_flow_step_revision_uses_stable_existing_step_refs() -> None:
    context = ResolvedAIBuilderEditContext(
        request=AIBuilderSavedFlowStepEditContext(flow_step_id=uuid4()),
        scope="step",
        target_existing_step_ref="existing_step_2",
        target_step_name="Compare evidence",
        target_step_number=2,
    )
    proposed = _edit_spec(
        [
            _edit_step(
                "step_a",
                "Read evidence",
                output_type=OutputType.TEXT,
                existing_step_ref="existing_step_1",
            ),
            _edit_step(
                "step_b",
                "Compare similarities and differences",
                output_type=OutputType.TEXT,
                existing_step_ref="existing_step_2",
            ),
            _edit_step(
                "step_c",
                "Summarize findings",
                output_type=OutputType.TEXT,
                existing_step_ref="existing_step_3",
            ),
        ]
    )
    prior = proposed.model_copy(deep=True)
    prior.steps = [
        step.model_copy(
            update={
                "plan_step_ref": f"existing_step_{index}",
                **(
                    {
                        "name": "Compare evidence",
                        "assistant_spec": AssistantSpec(
                            instructions="Compare evidence.",
                            model_ref=None,
                            knowledge_refs=[],
                        ),
                    }
                    if index == 2
                    else {}
                ),
            }
        )
        for index, step in enumerate(proposed.steps, start=1)
    ]

    assert (
        validate_scoped_plan_revision(
            target_kind=TargetKind.CREATE,
            context=context,
            prior_spec=prior,
            proposed_spec=proposed,
        )
        is None
    )


def test_step_scoped_revision_rejects_unrelated_step_rewrite() -> None:
    context = AIBuilderPlanEditContext(
        scope="step",
        plan_id=UUID("00000000-0000-0000-0000-000000000001"),
        target_plan_step_ref="step_b",
    )
    prior = _edit_spec(
        [
            _edit_step("step_a", "Analyze input", output_type=OutputType.JSON),
            _edit_step("step_b", "Create final result", output_type=OutputType.TEXT),
            _edit_step("step_c", "Notify reviewer", output_type=OutputType.TEXT),
        ]
    )
    proposed = _edit_spec(
        [
            _edit_step(
                "step_a",
                "Analyze input differently",
                output_type=OutputType.JSON,
            ),
            _edit_step("step_b", "Create final result", output_type=OutputType.PDF),
            _edit_step("step_c", "Notify reviewer", output_type=OutputType.TEXT),
        ]
    )

    rejection = validate_scoped_plan_revision(
        target_kind=TargetKind.CREATE,
        context=context,
        prior_spec=prior,
        proposed_spec=proposed,
    )

    assert rejection is not None
    feedback = rejection.feedback
    assert "unrelated steps" in feedback
    assert "step_a" in feedback


def test_step_scoped_revision_rejects_downstream_semantic_rewrite() -> None:
    context = AIBuilderPlanEditContext(
        scope="step",
        plan_id=UUID("00000000-0000-0000-0000-000000000001"),
        target_plan_step_ref="step_b",
    )
    prior = _edit_spec(
        [
            _edit_step("step_a", "Analyze input", output_type=OutputType.JSON),
            _edit_step("step_b", "Create final result", output_type=OutputType.TEXT),
            _edit_step(
                "step_c",
                "Format response",
                input_type=InputType.TEXT,
                output_type=OutputType.TEXT,
            ),
        ]
    )
    proposed = _edit_spec(
        [
            _edit_step("step_a", "Analyze input", output_type=OutputType.JSON),
            _edit_step("step_b", "Create final result", output_type=OutputType.JSON),
            _edit_step(
                "step_c",
                "Rewrite all results",
                input_type=InputType.JSON,
                output_type=OutputType.TEXT,
            ),
        ]
    )

    rejection = validate_scoped_plan_revision(
        target_kind=TargetKind.CREATE,
        context=context,
        prior_spec=prior,
        proposed_spec=proposed,
    )

    assert rejection is not None
    feedback = rejection.feedback
    assert "preserve unrelated steps" in feedback
    assert "step_c" in feedback
    assert "step_c" in feedback


def test_step_scoped_revision_rejects_existing_step_reorder() -> None:
    context = AIBuilderPlanEditContext(
        scope="step",
        plan_id=UUID("00000000-0000-0000-0000-000000000001"),
        target_plan_step_ref="step_b",
    )
    prior = _edit_spec(
        [
            _edit_step("step_a", "Analyze input", output_type=OutputType.JSON),
            _edit_step("step_b", "Create final result", output_type=OutputType.TEXT),
            _edit_step("step_c", "Format response", output_type=OutputType.TEXT),
        ]
    )
    proposed = _edit_spec(
        [
            _edit_step("step_c", "Format response", output_type=OutputType.TEXT),
            _edit_step("step_a", "Analyze input", output_type=OutputType.JSON),
            _edit_step("step_b", "Create final result", output_type=OutputType.PDF),
        ]
    )

    rejection = validate_scoped_plan_revision(
        target_kind=TargetKind.CREATE,
        context=context,
        prior_spec=prior,
        proposed_spec=proposed,
    )

    assert rejection is not None
    feedback = rejection.feedback
    assert "must not add, remove, or reorder steps" in feedback


def test_step_scoped_revision_rejects_duplicate_step_refs() -> None:
    context = AIBuilderPlanEditContext(
        scope="step",
        plan_id=UUID("00000000-0000-0000-0000-000000000001"),
        target_plan_step_ref="step_b",
    )
    prior = _edit_spec(
        [
            _edit_step("step_a", "Analyze input", output_type=OutputType.JSON),
            _edit_step("step_b", "Create final result", output_type=OutputType.TEXT),
        ]
    )
    proposed = _edit_spec(
        [
            _edit_step("step_a", "Analyze input", output_type=OutputType.JSON),
            _edit_step("step_b", "Create final result", output_type=OutputType.PDF),
            _edit_step("step_a", "Duplicate ref", output_type=OutputType.TEXT),
        ]
    )

    rejection = validate_scoped_plan_revision(
        target_kind=TargetKind.CREATE,
        context=context,
        prior_spec=prior,
        proposed_spec=proposed,
    )

    assert rejection is not None
    feedback = rejection.feedback
    assert "Duplicate step refs" in feedback
    assert "step_a" in feedback


def test_step_scoped_revision_allows_descriptive_plan_text_changes() -> None:
    context = AIBuilderPlanEditContext(
        scope="step",
        plan_id=UUID("00000000-0000-0000-0000-000000000001"),
        target_plan_step_ref="step_b",
    )
    prior = _edit_spec(
        [_edit_step("step_b", "Create final result", output_type=OutputType.TEXT)]
    )
    proposed = _edit_spec(
        [_edit_step("step_b", "Create final result", output_type=OutputType.PDF)]
    )
    proposed.flow_name = "Employee review PDF"
    proposed.flow_description = "Create a PDF result."

    assert (
        validate_scoped_plan_revision(
            target_kind=TargetKind.CREATE,
            context=context,
            prior_spec=prior,
            proposed_spec=proposed,
        )
        is None
    )


def _renderer_step(ref: str, output_type: OutputType) -> StepSpec:
    """The terminal document renderer the create compiler appends itself."""
    return _edit_step(
        ref, f"Rendera {output_type.value.upper()}", output_type=output_type
    ).model_copy(update={"output_mode": OutputMode.RENDER_VERBATIM})


def test_step_scoped_revision_accepts_the_compiler_appended_renderer() -> None:
    """A committed document artifact arrives as an appended renderer step.

    The user selected the terminal writing step and asked for a Word file. The
    create compiler answers a committed DOCX terminal by appending its own
    renderer, so the revision the model returns legitimately has one more step
    than the plan it revises, and the selected step itself need not change.
    """
    context = AIBuilderPlanEditContext(
        scope="step",
        plan_id=UUID("00000000-0000-0000-0000-000000000001"),
        target_plan_step_ref="step_b",
    )
    prior = _edit_spec(
        [
            _edit_step("step_a", "Analyze input", output_type=OutputType.JSON),
            _edit_step("step_b", "Create final result", output_type=OutputType.TEXT),
        ]
    )
    proposed = _edit_spec(
        [
            _edit_step("step_a", "Analyze input", output_type=OutputType.JSON),
            _edit_step("step_b", "Create final result", output_type=OutputType.TEXT),
            _renderer_step("step_c", OutputType.DOCX),
        ]
    )

    assert (
        validate_scoped_plan_revision(
            target_kind=TargetKind.CREATE,
            context=context,
            prior_spec=prior,
            proposed_spec=proposed,
        )
        is None
    )


def test_step_scoped_revision_keeps_a_mixed_request_whole() -> None:
    """Both halves of "change this step and make the result a Word file" land."""
    context = AIBuilderPlanEditContext(
        scope="step",
        plan_id=UUID("00000000-0000-0000-0000-000000000001"),
        target_plan_step_ref="step_b",
    )
    prior = _edit_spec(
        [
            _edit_step("step_a", "Analyze input", output_type=OutputType.JSON),
            _edit_step("step_b", "Create final result", output_type=OutputType.TEXT),
        ]
    )
    proposed = _edit_spec(
        [
            _edit_step("step_a", "Analyze input", output_type=OutputType.JSON),
            _edit_step(
                "step_b",
                "Create final result",
                output_type=OutputType.TEXT,
                instructions="Always name the decision date.",
            ),
            _renderer_step("step_c", OutputType.DOCX),
        ]
    )

    assert (
        validate_scoped_plan_revision(
            target_kind=TargetKind.CREATE,
            context=context,
            prior_spec=prior,
            proposed_spec=proposed,
        )
        is None
    )


def test_step_scoped_revision_accepts_a_renderer_the_architecture_dropped() -> None:
    """Returning to a text result removes the renderer the compiler owned."""
    context = AIBuilderPlanEditContext(
        scope="step",
        plan_id=UUID("00000000-0000-0000-0000-000000000001"),
        target_plan_step_ref="step_b",
    )
    prior = _edit_spec(
        [
            _edit_step("step_b", "Create final result", output_type=OutputType.TEXT),
            _renderer_step("step_c", OutputType.DOCX),
        ]
    )
    proposed = _edit_spec(
        [_edit_step("step_b", "Create final result", output_type=OutputType.TEXT)]
    )

    assert (
        validate_scoped_plan_revision(
            target_kind=TargetKind.CREATE,
            context=context,
            prior_spec=prior,
            proposed_spec=proposed,
        )
        is None
    )


def test_step_scoped_revision_accepts_a_renderer_that_changed_artifact() -> None:
    """PDF instead of Word is a server-owned change to the same renderer."""
    context = AIBuilderPlanEditContext(
        scope="step",
        plan_id=UUID("00000000-0000-0000-0000-000000000001"),
        target_plan_step_ref="step_b",
    )
    prior = _edit_spec(
        [
            _edit_step("step_b", "Create final result", output_type=OutputType.TEXT),
            _renderer_step("step_c", OutputType.DOCX),
        ]
    )
    proposed = _edit_spec(
        [
            _edit_step("step_b", "Create final result", output_type=OutputType.TEXT),
            _renderer_step("step_c", OutputType.PDF),
        ]
    )

    assert (
        validate_scoped_plan_revision(
            target_kind=TargetKind.CREATE,
            context=context,
            prior_spec=prior,
            proposed_spec=proposed,
        )
        is None
    )


def test_step_scoped_revision_still_rejects_a_model_authored_extra_step() -> None:
    """Only the server's renderer may appear; a helper step is still drift."""
    context = AIBuilderPlanEditContext(
        scope="step",
        plan_id=UUID("00000000-0000-0000-0000-000000000001"),
        target_plan_step_ref="step_b",
    )
    prior = _edit_spec(
        [
            _edit_step("step_a", "Analyze input", output_type=OutputType.JSON),
            _edit_step("step_b", "Create final result", output_type=OutputType.TEXT),
        ]
    )
    proposed = _edit_spec(
        [
            _edit_step("step_a", "Analyze input", output_type=OutputType.JSON),
            _edit_step(
                "step_b",
                "Create final result",
                output_type=OutputType.TEXT,
                instructions="Always name the decision date.",
            ),
            _edit_step("step_c", "Prepare Word content", output_type=OutputType.TEXT),
        ]
    )

    rejection = validate_scoped_plan_revision(
        target_kind=TargetKind.CREATE,
        context=context,
        prior_spec=prior,
        proposed_spec=proposed,
    )

    assert rejection is not None
    feedback = rejection.feedback
    assert "must not add, remove, or reorder steps" in feedback


def test_a_create_revision_cannot_be_asked_to_reproduce_unrelated_steps() -> None:
    """The model never sees the other steps, so repeating the ask is waste.

    A create-mode revision returns a whole plan, but the prompt and history
    give it each other step's name and types only — never their compiled
    content. A preservation failure there is out of the model's reach; the same
    failure on a saved-Flow edit is ordinary drift it can correct.
    """
    context = AIBuilderPlanEditContext(
        scope="step",
        plan_id=UUID("00000000-0000-0000-0000-000000000001"),
        target_plan_step_ref="step_b",
    )
    prior = _edit_spec(
        [
            _edit_step("step_a", "Analyze input", output_type=OutputType.JSON),
            _edit_step("step_b", "Create final result", output_type=OutputType.TEXT),
        ]
    )
    proposed = _edit_spec(
        [
            _edit_step(
                "step_a",
                "Analyze input",
                output_type=OutputType.JSON,
                instructions="Paraphrased by the model.",
            ),
            _edit_step(
                "step_b",
                "Create final result",
                output_type=OutputType.TEXT,
                instructions="Always name the decision date.",
            ),
        ]
    )

    created = validate_scoped_plan_revision(
        target_kind=TargetKind.CREATE,
        context=context,
        prior_spec=prior,
        proposed_spec=proposed,
    )
    edited = validate_scoped_plan_revision(
        target_kind=TargetKind.EDIT,
        context=context,
        prior_spec=prior,
        proposed_spec=proposed,
    )

    assert created is not None and edited is not None
    assert "preserve unrelated steps" in created.feedback
    assert created.model_can_fix is False
    assert edited.model_can_fix is True


@pytest.mark.parametrize(
    ("ui_language", "expected"),
    [
        ("sv", "Redigera hela planen"),
        ("en", "Edit the whole plan"),
    ],
)
def test_the_user_is_told_which_scope_can_carry_the_change(
    ui_language: str, expected: str
) -> None:
    assert expected in scoped_revision_out_of_reach_message(ui_language=ui_language)


def test_a_saved_flow_renderer_is_judged_like_any_other_step() -> None:
    """Only a create-compiled renderer is server owned.

    A saved Flow's modify contract offers the model that step's name, its
    instructions and its types, so rewriting it while another step is selected
    is ordinary drift.
    """
    context = ResolvedAIBuilderEditContext(
        request=AIBuilderSavedFlowStepEditContext(flow_step_id=uuid4()),
        scope="step",
        target_existing_step_ref="existing_step_1",
    )
    prior = _edit_spec(
        [
            _edit_step(
                "step_a",
                "Create final result",
                output_type=OutputType.TEXT,
                existing_step_ref="existing_step_1",
            ),
            _renderer_step("step_b", OutputType.DOCX).model_copy(
                update={"existing_step_ref": "existing_step_2"}
            ),
        ]
    )
    proposed = _edit_spec(
        [
            _edit_step(
                "step_a",
                "Create final result",
                output_type=OutputType.TEXT,
                existing_step_ref="existing_step_1",
                instructions="Always name the decision date.",
            ),
            _renderer_step("step_b", OutputType.DOCX)
            .model_copy(update={"existing_step_ref": "existing_step_2"})
            .model_copy(update={"name": "Renamed by the model"}),
        ]
    )

    rejection = validate_scoped_plan_revision(
        target_kind=TargetKind.EDIT,
        context=context,
        prior_spec=prior,
        proposed_spec=proposed,
    )

    assert rejection is not None
    feedback = rejection.feedback
    assert "preserve unrelated steps" in feedback


def test_an_ordinary_step_cannot_inherit_a_dropped_renderer_ref() -> None:
    """Losing the renderer must not license a new step in its place."""
    context = AIBuilderPlanEditContext(
        scope="step",
        plan_id=UUID("00000000-0000-0000-0000-000000000001"),
        target_plan_step_ref="step_a",
    )
    prior = _edit_spec(
        [
            _edit_step("step_a", "Create final result", output_type=OutputType.TEXT),
            _renderer_step("step_b", OutputType.DOCX),
        ]
    )
    proposed = _edit_spec(
        [
            _edit_step(
                "step_a",
                "Create final result",
                output_type=OutputType.TEXT,
                instructions="Always name the decision date.",
            ),
            _edit_step("step_b", "Publish the result", output_type=OutputType.TEXT),
        ]
    )

    rejection = validate_scoped_plan_revision(
        target_kind=TargetKind.CREATE,
        context=context,
        prior_spec=prior,
        proposed_spec=proposed,
    )

    assert rejection is not None
    feedback = rejection.feedback
    assert "must not add, remove, or reorder steps" in feedback


def test_step_scoped_revision_rejects_runtime_form_field_changes() -> None:
    context = AIBuilderPlanEditContext(
        scope="step",
        plan_id=UUID("00000000-0000-0000-0000-000000000001"),
        target_plan_step_ref="step_b",
    )
    prior = _edit_spec(
        [_edit_step("step_b", "Create final result", output_type=OutputType.TEXT)]
    )
    proposed = _edit_spec(
        [_edit_step("step_b", "Create final result", output_type=OutputType.PDF)],
        form_fields=[
            FormFieldSpec(
                name="new_input",
                type="text",
                label="New input",
                required=True,
            )
        ],
    )

    rejection = validate_scoped_plan_revision(
        target_kind=TargetKind.CREATE,
        context=context,
        prior_spec=prior,
        proposed_spec=proposed,
    )

    assert rejection is not None
    feedback = rejection.feedback
    assert "runtime form fields" in feedback


def test_plan_revision_terminal_output_intent_uses_latest_user_message() -> None:
    context = AIBuilderPlanEditContext(
        scope="step",
        plan_id=UUID("00000000-0000-0000-0000-000000000001"),
        target_plan_step_ref="step_b",
    )
    conversation = [
        ConversationMessage(
            role="user",
            content="Bygg ett flöde som skapar en PDF-rapport.",
        ),
        ConversationMessage(role="assistant", content="Här är planen."),
        ConversationMessage(
            role="user",
            content="Byt namn på steget till tydligare rubrik.",
        ),
    ]

    assert (
        terminal_output_type_for_edit_conversation(
            conversation,
            plan_edit_context=context,
            prior_spec=None,
        )
        is None
    )


def test_plan_revision_terminal_output_intent_accepts_current_pdf_edit() -> None:
    context = AIBuilderPlanEditContext(
        scope="step",
        plan_id=UUID("00000000-0000-0000-0000-000000000001"),
        target_plan_step_ref="step_b",
    )
    conversation = [
        ConversationMessage(
            role="user",
            content="Bygg ett flöde som skapar ett strukturerat textresultat.",
        ),
        ConversationMessage(role="assistant", content="Här är planen."),
        ConversationMessage(
            role="user",
            content="Ändra så att jag får ut en pdf fil istället för text.",
        ),
    ]

    assert (
        terminal_output_type_for_edit_conversation(
            conversation,
            plan_edit_context=context,
            prior_spec=None,
        )
        == OutputType.PDF
    )


def test_whole_flow_edit_terminal_output_intent_can_use_full_requirements() -> None:
    conversation = [
        ConversationMessage(
            role="user",
            content="Bygg ett flöde som skapar en PDF-rapport.",
        ),
        ConversationMessage(role="assistant", content="Vill du bygga planen?"),
        ConversationMessage(role="user", content="Ja, bygg planen."),
    ]

    assert (
        terminal_output_type_for_edit_conversation(
            conversation,
            plan_edit_context=None,
            prior_spec=None,
        )
        == OutputType.PDF
    )


def test_step_scoped_context_requires_a_stable_step_ref() -> None:
    with pytest.raises(ValueError, match="target_plan_step_ref"):
        AIBuilderPlanEditContext(
            scope="step",
            plan_id=UUID("00000000-0000-0000-0000-000000000001"),
        )


def test_a_revision_that_can_decline_is_told_when_to_use_it() -> None:
    """One directive, two cases: model only declines, mixed still edits."""
    context = AIBuilderPlanEditContext(
        scope="step",
        plan_id=UUID("00000000-0000-0000-0000-000000000001"),
        target_plan_step_ref="step_a",
    )
    prior = _edit_spec(
        [_edit_step("step_a", "Create final result", output_type=OutputType.TEXT)]
    )

    declining = build_plan_revision_prompt_block(
        context=context, prior_spec=prior, can_decline=True
    )
    proposing = build_plan_revision_prompt_block(
        context=context, prior_spec=prior, can_decline=False
    )

    assert declining is not None and proposing is not None
    assert "decline_flow_change" in declining
    assert "model is chosen in the picker" in declining
    assert "decline_flow_change" not in proposing


def test_revision_prompt_names_the_target_step_and_prior_refs() -> None:
    context = AIBuilderPlanEditContext(
        scope="step",
        plan_id=UUID("00000000-0000-0000-0000-000000000001"),
        target_plan_step_ref="step_b",
        target_step_name="Create final result",
    )
    prior_plan = cast(
        BuilderPlan,
        SimpleNamespace(
            id=context.plan_id,
            spec=_edit_spec(
                [
                    _edit_step("step_a", "Analyze input", output_type=OutputType.JSON),
                    _edit_step(
                        "step_b",
                        "Create final result",
                        output_type=OutputType.TEXT,
                    ),
                ]
            ),
        ),
    )

    prompt = build_plan_revision_prompt_block(
        context=context, prior_spec=prior_plan.spec
    )

    assert prompt is not None
    assert "Scope: one selected step" in prompt
    assert "step_b (Create final result)" in prompt
    assert "step_a: Analyze input" in prompt
    assert "step_b: Create final result" in prompt
    # The revision guidance is where the picker-only rule is explained, for both
    # proposed-plan and saved-Flow revisions.
    assert "modellväljare/model picker" in prompt


def _model_revision_specs(
    *,
    proposed_model_ref: str | None,
    proposed_instructions: str | None = None,
) -> tuple[FlowDraftSpecCore, FlowDraftSpecCore]:
    prior = _edit_spec(
        [
            _edit_step(
                "step_a",
                "Analyze input",
                output_type=OutputType.JSON,
                model_ref="model.gpt-4o-mini",
            ),
            _edit_step(
                "step_b",
                "Create final result",
                output_type=OutputType.TEXT,
                model_ref="model.gpt-4o-mini",
            ),
        ]
    )
    proposed = _edit_spec(
        [
            prior.steps[0],
            _edit_step(
                "step_b",
                "Create final result",
                output_type=OutputType.TEXT,
                model_ref=proposed_model_ref,
                instructions=proposed_instructions,
            ),
        ]
    )
    return prior, proposed


@pytest.mark.parametrize(
    "proposed_model_ref, proposed_instructions",
    [
        ("model.gpt-5-4", None),
        ("model.gpt-5-4", "Create final result with sources."),
        (None, None),
    ],
)
def test_step_scoped_edit_rejects_a_model_change_on_the_selected_step(
    proposed_model_ref: str | None,
    proposed_instructions: str | None,
) -> None:
    prior, proposed = _model_revision_specs(
        proposed_model_ref=proposed_model_ref,
        proposed_instructions=proposed_instructions,
    )

    rejection = validate_scoped_plan_revision(
        target_kind=TargetKind.CREATE,
        context=_step_context(target_plan_step_ref="step_b"),
        prior_spec=prior,
        proposed_spec=proposed,
    )

    assert rejection is not None
    feedback = rejection.feedback
    assert "step_b" in feedback
    assert "model picker" in feedback


def test_step_scoped_model_check_is_correct_when_the_step_order_also_drifted() -> None:
    # Both guards are live on one proposal: a step was inserted AND the selected
    # step's model changed. The model check pairs the target with itself by ref,
    # so it is right either way; the structural complaint is the one the user
    # needs, and it comes first.
    prior = _edit_spec(
        [
            _edit_step(
                "step_a",
                "Analyze input",
                output_type=OutputType.JSON,
                model_ref="model.gpt-4o-mini",
            ),
            _edit_step(
                "step_b",
                "Create final result",
                output_type=OutputType.TEXT,
                model_ref="model.gpt-4o-mini",
            ),
        ]
    )
    proposed = _edit_spec(
        [
            prior.steps[0],
            _edit_step(
                "step_b",
                "Create final result",
                output_type=OutputType.TEXT,
                model_ref="model.gpt-5-4",
            ),
            _edit_step(
                "step_c",
                "Summarize",
                output_type=OutputType.TEXT,
                model_ref="model.gpt-4o-mini",
            ),
        ]
    )

    rejection = validate_scoped_plan_revision(
        target_kind=TargetKind.CREATE,
        context=_step_context(target_plan_step_ref="step_b"),
        prior_spec=prior,
        proposed_spec=proposed,
    )

    assert rejection is not None
    feedback = rejection.feedback
    assert "must not add, remove, or reorder steps" in feedback

    assert (
        _validate_target_step_model(
            prior_target=prior.steps[1],
            proposed_target=proposed.steps[1],
            target_ref="step_b",
        )
        is not None
    )


def test_step_scoped_model_check_does_not_accuse_a_step_after_an_insertion() -> None:
    # Steps on different models, a step inserted at the front, and no model
    # changed anywhere. Pairing by position would compare step_b against step_a
    # and invent a model change; pairing by target ref cannot.
    prior = _edit_spec(
        [
            _edit_step(
                "step_a",
                "Analyze input",
                output_type=OutputType.JSON,
                model_ref="model.gpt-4o-mini",
            ),
            _edit_step(
                "step_b",
                "Create final result",
                output_type=OutputType.TEXT,
                model_ref="model.gpt-5-4",
            ),
        ]
    )
    proposed = _edit_spec(
        [
            _edit_step(
                "step_new",
                "Collect sources",
                output_type=OutputType.JSON,
                model_ref="model.gpt-4o-mini",
            ),
            *prior.steps,
        ]
    )

    assert (
        _validate_target_step_model(
            prior_target=prior.steps[1],
            proposed_target=proposed.steps[2],
            target_ref="step_b",
        )
        is None
    )

    rejection = validate_scoped_plan_revision(
        target_kind=TargetKind.CREATE,
        context=_step_context(target_plan_step_ref="step_b"),
        prior_spec=prior,
        proposed_spec=proposed,
    )
    assert rejection is not None
    feedback = rejection.feedback
    assert "model picker" not in feedback


def test_whole_plan_outline_revision_is_not_model_guarded_yet() -> None:
    # Recorded residual, not an endorsement: an outline step has no stable
    # identity across a restructuring, so a whole-plan revision cannot tell a
    # reorder apart from a model change. Guarding it needs stable carried-step
    # identity (follow-up). A saved Flow does not rely on this: its modify
    # contract carries no model_ref at all.
    prior, proposed = _model_revision_specs(proposed_model_ref="model.gpt-5-4")

    assert (
        validate_scoped_plan_revision(
            target_kind=TargetKind.CREATE,
            context=_step_context(scope="whole_plan"),
            prior_spec=prior,
            proposed_spec=proposed,
        )
        is None
    )


def test_step_scoped_edit_accepts_an_instruction_change_that_keeps_the_model() -> None:
    prior, proposed = _model_revision_specs(
        proposed_model_ref="model.gpt-4o-mini",
        proposed_instructions="Create final result with sources.",
    )

    assert (
        validate_scoped_plan_revision(
            target_kind=TargetKind.CREATE,
            context=_step_context(target_plan_step_ref="step_b"),
            prior_spec=prior,
            proposed_spec=proposed,
        )
        is None
    )


def _edit_spec(
    steps: list[StepSpec],
    *,
    form_fields: list[FormFieldSpec] | None = None,
) -> FlowDraftSpecCore:
    return FlowDraftSpecCore(
        flow_name="Employee review",
        flow_description="",
        steps=steps,
        form_fields=form_fields,
    )


def _edit_step(
    ref: str,
    name: str,
    *,
    input_type: InputType = InputType.TEXT,
    output_type: OutputType,
    existing_step_ref: str | None = None,
    model_ref: str | None = None,
    instructions: str | None = None,
) -> StepSpec:
    return StepSpec(
        plan_step_ref=ref,
        existing_step_ref=existing_step_ref,
        name=name,
        assistant_spec=AssistantSpec(
            instructions=instructions or f"{name}.",
            model_ref=model_ref,
            knowledge_refs=[],
        ),
        input_source=InputSource.PREVIOUS_STEP
        if ref != "step_a"
        else InputSource.FLOW_INPUT,
        input_type=input_type,
        output_mode=OutputMode.PASS_THROUGH,
        output_type=output_type,
        input_bindings=None,
        input_contract=None,
        output_contract=None,
        input_config=None,
        output_config=None,
    )
