from __future__ import annotations

from uuid import uuid4

from intric.flows.ai_builder.ai_builder_plan_edit_context import (
    AIBuilderPlanEditContext,
    ScopedStepModelSpecRevision,
    resolve_scoped_step_model_revision_if_requested,
)
from intric.flows.ai_builder.ai_builder_resource_catalog import (
    build_ai_builder_resource_catalog,
)
from intric.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)


def _catalog():
    return build_ai_builder_resource_catalog(
        available_models=[
            {"id": "model-old", "name": "gpt-4o mini"},
            {"id": "model-nano", "name": "gpt-5.4-nano"},
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
    result = resolve_scoped_step_model_revision_if_requested(
        context=AIBuilderPlanEditContext(scope="whole_plan", plan_id=uuid4()),
        prior_spec=_spec(),
        latest_user_text="ändra modell till gpt 5.4 nano",
        resource_catalog=_catalog(),
    )

    assert result is None


def test_scoped_model_revision_ignores_model_word_without_model_name() -> None:
    result = resolve_scoped_step_model_revision_if_requested(
        context=_step_context(),
        prior_spec=_spec(),
        latest_user_text="Modellera om upplägget lite.",
        resource_catalog=_catalog(),
    )

    assert result is None


def test_scoped_model_revision_ignores_current_model_only() -> None:
    result = resolve_scoped_step_model_revision_if_requested(
        context=_step_context(),
        prior_spec=_spec(model_ref="model.gpt-5-4-nano"),
        latest_user_text="behåll modell gpt 5.4 nano",
        resource_catalog=_catalog(),
    )

    assert result is None


def test_scoped_model_revision_ignores_blank_latest_user_text() -> None:
    result = resolve_scoped_step_model_revision_if_requested(
        context=_step_context(),
        prior_spec=_spec(model_ref="model.gpt-4o-mini"),
        latest_user_text=" ",
        resource_catalog=_catalog(),
    )

    assert result is None


def test_scoped_model_revision_ignores_ambiguous_models_without_current_model() -> None:
    result = resolve_scoped_step_model_revision_if_requested(
        context=_step_context(),
        prior_spec=_spec(),
        latest_user_text="byt modell från gpt-4o mini till gpt 5.4 nano",
        resource_catalog=_catalog(),
    )

    assert result is None


def test_scoped_model_revision_uses_existing_step_ref() -> None:
    result = resolve_scoped_step_model_revision_if_requested(
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

    assert isinstance(result, ScopedStepModelSpecRevision)
    assert result.spec.steps[0].assistant_spec.model_ref == "model.gpt-5-4-nano"
