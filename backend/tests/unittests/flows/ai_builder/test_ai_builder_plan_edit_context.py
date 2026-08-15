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
    ScopedStepNotice,
    ScopedStepSpecRevision,
    build_plan_revision_prompt_block,
    resolve_plan_edit_context,
    resolve_scoped_step_revision_if_requested,
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
    "text",
    [
        "byt modell till gpt 5.4 nano",
        "Change model to gpt 5.5",
        "Byt till claude",
        "Ändra instruktionen så att modellen alltid anger källor",
        "Modellera om upplägget lite",
    ],
)
def test_model_wording_never_produces_a_deterministic_scoped_revision(
    text: str,
) -> None:
    # No keyword family owns model intent here. Immutability is enforced by the
    # modify contract and by validate_scoped_plan_revision, not by this resolver.
    result = resolve_scoped_step_revision_if_requested(
        context=_step_context(),
        prior_spec=_spec(model_ref="model.gpt-4o-mini"),
        latest_user_text=text,
        ui_language="sv",
    )

    assert result is None


def test_scoped_revision_ignores_whole_plan_scope() -> None:
    result = resolve_scoped_step_revision_if_requested(
        context=AIBuilderPlanEditContext(scope="whole_plan", plan_id=uuid4()),
        prior_spec=_spec(),
        latest_user_text="kan du ändra så att jag får en pdf fil istället?",
        ui_language="sv",
        requested_terminal_output_type=OutputType.PDF,
    )

    assert result is None


def test_scoped_revision_ignores_blank_latest_user_text() -> None:
    result = resolve_scoped_step_revision_if_requested(
        context=_step_context(),
        prior_spec=_spec(),
        latest_user_text="",
        ui_language="sv",
        requested_terminal_output_type=OutputType.PDF,
    )

    assert result is None


@pytest.mark.parametrize(
    ("message", "output_type"),
    [
        ("kan du ändra så att jag får en pdf fil istället?", OutputType.PDF),
        ("Change the final file to docx", OutputType.DOCX),
    ],
)
def test_scoped_step_revision_changes_terminal_output_artifact(
    message: str,
    output_type: OutputType,
) -> None:
    prior = _edit_spec(
        [
            _edit_step("step_a", "Analyze input", output_type=OutputType.JSON),
            _edit_step("step_b", "Create final result", output_type=OutputType.TEXT),
        ]
    )

    result = resolve_scoped_step_revision_if_requested(
        context=_step_context(target_plan_step_ref="step_b"),
        prior_spec=prior,
        latest_user_text=message,
        ui_language=None,
        requested_terminal_output_type=output_type,
    )

    assert isinstance(result, ScopedStepSpecRevision)
    assert result.spec.steps[0].model_dump(mode="json") == prior.steps[0].model_dump(
        mode="json"
    )
    assert result.spec.steps[1].output_type == output_type
    assert result.spec.steps[1].output_contract is None


def test_scoped_step_revision_changes_terminal_output_for_pdf_file_wording() -> None:
    context = _step_context(target_plan_step_ref="step_b")
    prior = _edit_spec(
        [
            _edit_step("step_a", "Analyze input", output_type=OutputType.JSON),
            _edit_step("step_b", "Create final result", output_type=OutputType.TEXT),
        ]
    )
    conversation = [
        ConversationMessage(
            role="user",
            content="Bygg ett flöde som skapar ett strukturerat textresultat.",
        ),
        ConversationMessage(role="assistant", content="Här är planen."),
        ConversationMessage(role="user", content="utdatat ska vara pdf fil"),
    ]
    output_type = terminal_output_type_for_edit_conversation(
        conversation,
        plan_edit_context=context,
        prior_spec=None,
    )

    result = resolve_scoped_step_revision_if_requested(
        context=context,
        prior_spec=prior,
        latest_user_text="utdatat ska vara pdf fil",
        ui_language=None,
        requested_terminal_output_type=output_type,
    )

    assert output_type == OutputType.PDF
    assert isinstance(result, ScopedStepSpecRevision)
    assert result.spec.steps[1].output_type == OutputType.PDF


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


def test_scoped_step_revision_uses_slot_classification_for_pdf_output_edit() -> None:
    context = _step_context(target_plan_step_ref="step_b")
    prior = _edit_spec(
        [
            _edit_step("step_a", "Analyze input", output_type=OutputType.JSON),
            _edit_step("step_b", "Create final result", output_type=OutputType.TEXT),
        ]
    )
    conversation = [
        ConversationMessage(
            role="user",
            content="ändra output filen till pdf",
            metadata=_terminal_output_slot_metadata(),
        )
    ]

    result = resolve_scoped_step_revision_if_requested(
        context=context,
        prior_spec=prior,
        latest_user_text="ändra output filen till pdf",
        ui_language=None,
        requested_terminal_output_type=terminal_output_type_for_edit_conversation(
            conversation,
            plan_edit_context=context,
            prior_spec=None,
        ),
    )

    assert isinstance(result, ScopedStepSpecRevision)
    assert result.spec.steps[1].output_type == OutputType.PDF


@pytest.mark.parametrize(
    ("message", "terminal_output_value"),
    [
        ("flera pdf filer ska vara input", "pdf_document"),
        ("flera docx filer ska vara input", "docx_document"),
    ],
)
def test_scoped_step_revision_does_not_patch_input_file_mentions(
    message: str,
    terminal_output_value: str,
) -> None:
    context = _step_context(target_plan_step_ref="step_b")
    prior = _edit_spec(
        [
            _edit_step("step_a", "Analyze input", output_type=OutputType.JSON),
            _edit_step("step_b", "Create final result", output_type=OutputType.TEXT),
        ]
    )
    conversation = [
        ConversationMessage(
            role="user",
            content=message,
            metadata=_terminal_output_slot_metadata(terminal_output_value),
        )
    ]

    result = resolve_scoped_step_revision_if_requested(
        context=context,
        prior_spec=prior,
        latest_user_text=message,
        ui_language=None,
        requested_terminal_output_type=terminal_output_type_for_edit_conversation(
            conversation,
            plan_edit_context=context,
            prior_spec=None,
        ),
    )

    assert result is None


def test_scoped_step_revision_keeps_matching_terminal_output_as_noop() -> None:
    prior = _edit_spec(
        [
            _edit_step("step_a", "Analyze input", output_type=OutputType.JSON),
            _edit_step("step_b", "Create final result", output_type=OutputType.PDF),
        ]
    )

    result = resolve_scoped_step_revision_if_requested(
        context=_step_context(target_plan_step_ref="step_b"),
        prior_spec=prior,
        latest_user_text="kan du ändra så att jag får en pdf fil istället?",
        ui_language=None,
        requested_terminal_output_type=OutputType.PDF,
    )

    assert result is None


@pytest.mark.parametrize(
    "message",
    [
        "kan du ändra så att jag får en pdf fil istället?",
        "utdatat ska vara pdf fil",
    ],
)
def test_scoped_step_revision_warns_when_output_artifact_target_is_not_terminal(
    message: str,
) -> None:
    prior = _edit_spec(
        [
            _edit_step("step_a", "Analyze input", output_type=OutputType.JSON),
            _edit_step("step_b", "Create final result", output_type=OutputType.TEXT),
        ]
    )

    result = resolve_scoped_step_revision_if_requested(
        context=_step_context(target_plan_step_ref="step_a"),
        prior_spec=prior,
        latest_user_text=message,
        ui_language=None,
        requested_terminal_output_type=OutputType.PDF,
    )

    assert isinstance(result, ScopedStepNotice)
    assert "slutsteget" in result.message


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

    feedback = validate_scoped_plan_revision(
        context=context,
        prior_spec=prior,
        proposed_spec=proposed,
    )

    assert feedback is not None
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

    feedback = validate_scoped_plan_revision(
        context=context,
        prior_spec=prior,
        proposed_spec=proposed,
    )

    assert feedback is not None
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

    feedback = validate_scoped_plan_revision(
        context=context,
        prior_spec=prior,
        proposed_spec=proposed,
    )

    assert feedback is not None
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

    feedback = validate_scoped_plan_revision(
        context=context,
        prior_spec=prior,
        proposed_spec=proposed,
    )

    assert feedback is not None
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

    feedback = validate_scoped_plan_revision(
        context=context,
        prior_spec=prior,
        proposed_spec=proposed,
    )

    assert feedback is not None
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

    feedback = validate_scoped_plan_revision(
        context=context,
        prior_spec=prior,
        proposed_spec=proposed,
    )

    assert feedback is not None
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
            context=context,
            prior_spec=prior,
            proposed_spec=proposed,
        )
        is None
    )


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

    feedback = validate_scoped_plan_revision(
        context=context,
        prior_spec=prior,
        proposed_spec=proposed,
    )

    assert feedback is not None
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

    feedback = validate_scoped_plan_revision(
        context=_step_context(target_plan_step_ref="step_b"),
        prior_spec=prior,
        proposed_spec=proposed,
    )

    assert feedback is not None
    assert "step_b" in feedback
    assert "model picker" in feedback


def test_whole_plan_outline_revision_is_not_model_guarded_yet() -> None:
    # Recorded residual, not an endorsement: an outline step has no stable
    # identity across a restructuring, so a whole-plan revision cannot tell a
    # reorder apart from a model change. Guarding it needs stable carried-step
    # identity (follow-up). A saved Flow does not rely on this: its modify
    # contract carries no model_ref at all.
    prior, proposed = _model_revision_specs(proposed_model_ref="model.gpt-5-4")

    assert (
        validate_scoped_plan_revision(
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
