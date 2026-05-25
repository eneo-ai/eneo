from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import pytest

from intric.flows.ai_builder.ai_builder_domain_models import (
    BuilderPlan,
    ConversationMessage,
)
from intric.flows.ai_builder.ai_builder_plan_edit_context import (
    _DOWNSTREAM_INPUT_REPAIR_FIELDS,
    AIBuilderPlanEditContext,
    ScopedStepNotice,
    ScopedStepSpecRevision,
    build_plan_revision_prompt_block,
    resolve_scoped_step_revision_if_requested,
    validate_scoped_plan_revision,
)
from intric.flows.ai_builder.ai_builder_proposal_policy import (
    terminal_output_type_for_conversation,
)
from intric.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderAvailableModelResource,
    build_ai_builder_resource_catalog,
)
from intric.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    FormFieldSpec,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)


def _model_resource(local_id: str, name: str) -> AIBuilderAvailableModelResource:
    return {
        "id": local_id,
        "ref": local_id,
        "name": name,
        "display_name": name,
        "provider": "test",
    }


def _catalog():
    return build_ai_builder_resource_catalog(
        available_models=[
            _model_resource("model-old", "gpt-4o mini"),
            _model_resource("model-nano", "gpt-5.4-nano"),
        ],
        available_kbs=[],
        available_mcps=[],
    )


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


def test_scoped_model_revision_ignores_whole_plan_scope() -> None:
    result = resolve_scoped_step_revision_if_requested(
        context=AIBuilderPlanEditContext(scope="whole_plan", plan_id=uuid4()),
        prior_spec=_spec(),
        latest_user_text="ändra modell till gpt 5.4 nano",
        resource_catalog=_catalog(),
    )

    assert result is None


def test_scoped_model_revision_ignores_model_word_without_model_name() -> None:
    result = resolve_scoped_step_revision_if_requested(
        context=_step_context(),
        prior_spec=_spec(),
        latest_user_text="Modellera om upplägget lite.",
        resource_catalog=_catalog(),
    )

    assert result is None


def test_scoped_model_revision_ignores_current_model_only() -> None:
    result = resolve_scoped_step_revision_if_requested(
        context=_step_context(),
        prior_spec=_spec(model_ref="model.gpt-5-4-nano"),
        latest_user_text="behåll modell gpt 5.4 nano",
        resource_catalog=_catalog(),
    )

    assert result is None


def test_scoped_model_revision_ignores_blank_latest_user_text() -> None:
    result = resolve_scoped_step_revision_if_requested(
        context=_step_context(),
        prior_spec=_spec(model_ref="model.gpt-4o-mini"),
        latest_user_text=" ",
        resource_catalog=_catalog(),
    )

    assert result is None


def test_scoped_model_revision_ignores_ambiguous_models_without_current_model() -> None:
    result = resolve_scoped_step_revision_if_requested(
        context=_step_context(),
        prior_spec=_spec(),
        latest_user_text="byt modell från gpt-4o mini till gpt 5.4 nano",
        resource_catalog=_catalog(),
    )

    assert result is None


def test_scoped_model_revision_uses_existing_step_ref() -> None:
    result = resolve_scoped_step_revision_if_requested(
        context=_step_context(
            target_plan_step_ref=None,
            target_existing_step_ref="existing_step_1",
        ),
        prior_spec=_spec(
            model_ref="model.gpt-4o-mini",
            existing_step_ref="existing_step_1",
        ),
        latest_user_text="byt modell från gpt-4o mini till gpt 5.4 nano",
        resource_catalog=_catalog(),
    )

    assert isinstance(result, ScopedStepSpecRevision)
    assert result.spec.steps[0].assistant_spec.model_ref == "model.gpt-5-4-nano"


def test_scoped_model_revision_transcribe_only_notice_for_unknown_model_text() -> None:
    result = resolve_scoped_step_revision_if_requested(
        context=_step_context(),
        prior_spec=_spec(output_mode=OutputMode.TRANSCRIBE_ONLY),
        latest_user_text="Ändra modell till gpt 5.5",
        resource_catalog=_catalog(),
    )

    assert isinstance(result, ScopedStepNotice)
    assert "transkriberingsmodell" in result.message


def test_scoped_model_revision_transcribe_only_notice_for_model_family_without_model_word() -> (
    None
):
    result = resolve_scoped_step_revision_if_requested(
        context=_step_context(),
        prior_spec=_spec(output_mode=OutputMode.TRANSCRIBE_ONLY),
        latest_user_text="Byt till gpt 5.4 nano",
        resource_catalog=_catalog(),
    )

    assert isinstance(result, ScopedStepNotice)
    assert "transkriberingsmodell" in result.message


def test_scoped_model_revision_pass_through_without_model_word_does_not_short_circuit() -> (
    None
):
    result = resolve_scoped_step_revision_if_requested(
        context=_step_context(),
        prior_spec=_spec(model_ref="model.gpt-4o-mini"),
        latest_user_text="Byt till gpt 5.4 nano",
        resource_catalog=_catalog(),
    )

    assert result is None


def test_scoped_model_revision_completion_step_unknown_model_returns_notice() -> None:
    result = resolve_scoped_step_revision_if_requested(
        context=_step_context(),
        prior_spec=_spec(model_ref="model.gpt-4o-mini"),
        latest_user_text="Ändra modell till gpt 5.5",
        resource_catalog=_catalog(),
    )

    assert isinstance(result, ScopedStepNotice)
    assert "hittar inte den modellen" in result.message
    assert "modellväljaren" in result.message


def test_scoped_model_revision_completion_step_unknown_model_uses_english_notice() -> (
    None
):
    result = resolve_scoped_step_revision_if_requested(
        context=_step_context(),
        prior_spec=_spec(model_ref="model.gpt-4o-mini"),
        latest_user_text="Change model to gpt 5.5",
        resource_catalog=_catalog(),
    )

    assert isinstance(result, ScopedStepNotice)
    assert "cannot find that model" in result.message
    assert "model picker" in result.message


def test_scoped_model_revision_completion_step_does_not_hijack_prompt_edit_with_model_family_word() -> (
    None
):
    result = resolve_scoped_step_revision_if_requested(
        context=_step_context(),
        prior_spec=_spec(model_ref="model.gpt-4o-mini"),
        latest_user_text="Byt till gpt kod för den här funktionen",
        resource_catalog=_catalog(),
    )

    assert result is None


def test_scoped_model_revision_transcribe_only_ignores_prompt_edit_with_model_family_word() -> (
    None
):
    result = resolve_scoped_step_revision_if_requested(
        context=_step_context(),
        prior_spec=_spec(output_mode=OutputMode.TRANSCRIBE_ONLY),
        latest_user_text="Change the GPT prompt slightly",
        resource_catalog=_catalog(),
    )

    assert result is None


def test_scoped_model_revision_transcribe_only_tokenizes_exact_words() -> None:
    for text in ["Modellera om upplägget lite", "Använd en kort lista", "gptproof"]:
        result = resolve_scoped_step_revision_if_requested(
            context=_step_context(),
            prior_spec=_spec(output_mode=OutputMode.TRANSCRIBE_ONLY),
            latest_user_text=text,
            resource_catalog=_catalog(),
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
        resource_catalog=None,
        requested_terminal_output_type=output_type,
    )

    assert isinstance(result, ScopedStepSpecRevision)
    assert result.kind == "output_artifact"
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
    output_type = terminal_output_type_for_conversation(
        conversation,
        plan_edit_context=context,
        prior_plan=None,
    )

    result = resolve_scoped_step_revision_if_requested(
        context=context,
        prior_spec=prior,
        latest_user_text="utdatat ska vara pdf fil",
        resource_catalog=None,
        requested_terminal_output_type=output_type,
    )

    assert output_type == OutputType.PDF
    assert isinstance(result, ScopedStepSpecRevision)
    assert result.kind == "output_artifact"
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
        terminal_output_type_for_conversation(
            conversation,
            plan_edit_context=_step_context(target_plan_step_ref="step_b"),
            prior_plan=None,
        )
        == OutputType.PDF
    )


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
        resource_catalog=None,
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
        resource_catalog=None,
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


def test_step_scoped_revision_allows_direct_successor_input_repair() -> None:
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
                "Format response",
                input_type=InputType.JSON,
                output_type=OutputType.TEXT,
            ),
        ]
    )

    assert (
        validate_scoped_plan_revision(
            context=context,
            prior_spec=prior,
            proposed_spec=proposed,
        )
        is None
    )


def test_step_scoped_revision_allows_downstream_input_repair() -> None:
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
                "Review intermediate result",
                output_type=OutputType.TEXT,
            ),
            _edit_step(
                "step_d",
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
                "Review intermediate result",
                output_type=OutputType.TEXT,
            ),
            _edit_step(
                "step_d",
                "Format response",
                input_type=InputType.JSON,
                output_type=OutputType.TEXT,
            ),
        ]
    )

    assert (
        validate_scoped_plan_revision(
            context=context,
            prior_spec=prior,
            proposed_spec=proposed,
        )
        is None
    )


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
    assert "downstream input wiring" in feedback
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
    assert "preserve the order" in feedback


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


def test_downstream_input_repair_fields_are_valid_step_fields() -> None:
    assert _DOWNSTREAM_INPUT_REPAIR_FIELDS <= set(StepSpec.model_fields)


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
        terminal_output_type_for_conversation(
            conversation,
            plan_edit_context=context,
            prior_plan=None,
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
        terminal_output_type_for_conversation(
            conversation,
            plan_edit_context=context,
            prior_plan=None,
        )
        == OutputType.PDF
    )


def test_initial_plan_terminal_output_intent_can_use_full_requirements() -> None:
    conversation = [
        ConversationMessage(
            role="user",
            content="Bygg ett flöde som skapar en PDF-rapport.",
        ),
        ConversationMessage(role="assistant", content="Vill du bygga planen?"),
        ConversationMessage(role="user", content="Ja, bygg planen."),
    ]

    assert (
        terminal_output_type_for_conversation(
            conversation,
            plan_edit_context=None,
            prior_plan=None,
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
        context=context,
        prior_plan=prior_plan,
    )

    assert prompt is not None
    assert "Scope: one selected step" in prompt
    assert "step_b (Create final result)" in prompt
    assert "step_a: Analyze input" in prompt
    assert "step_b: Create final result" in prompt


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
) -> StepSpec:
    return StepSpec(
        plan_step_ref=ref,
        existing_step_ref=existing_step_ref,
        name=name,
        assistant_spec=AssistantSpec(
            instructions=f"{name}.",
            model_ref=None,
            knowledge_refs=[],
            mcp_server_refs=[],
            mcp_tool_refs=[],
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
