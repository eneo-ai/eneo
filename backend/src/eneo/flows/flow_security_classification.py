from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any
from uuid import UUID

from eneo.flows.domain.flow import FlowStep
from eneo.flows.domain.flow_step_validation import FlowStepValidationError
from eneo.flows.enums import FlowOutputMode, flow_output_mode_uses_completion_model
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.step_lineage import build_step_ref_mapping, resolve_step_upstream_orders


class ClassificationCause(StrEnum):
    """What sets the level a step must clear."""

    READS = "reads"
    KNOWLEDGE = "knowledge"
    SPACE = "space"


class ClassificationViolationCode(StrEnum):
    """The refusals of the rule, as the catalog names them."""

    MODEL_BELOW_REQUIRED = FlowApiErrorCode.STEP_SECURITY_CLASSIFICATION_MISMATCH.value
    OUTPUT_WRITE_DOWN = FlowApiErrorCode.STEP_OUTPUT_CLASSIFICATION_WRITE_DOWN.value


@dataclass(frozen=True)
class FlowStepClassificationViolation:
    code: ClassificationViolationCode
    message: str
    # The level the step must reach: the model's level, or the output floor.
    required_level: int
    # The model's level (None: no model, or an unclassified one) or the override.
    current_level: int | None
    cause: ClassificationCause
    # The read steps whose output sits at ``required_level``; only for READS.
    source_step_orders: tuple[int, ...]


@dataclass(frozen=True)
class FlowStepClassificationExplanation:
    step_order: int
    step_id: UUID | None
    reads: tuple[int, ...]
    # The floor the step's inputs set: the space level and what the reads carry.
    input_level: int | None
    knowledge_level: int | None
    required_model_level: int | None
    model_level: int | None
    # Usable space models that clear ``required_model_level`` (all usable models
    # when nothing is required), lowest level first. None when the caller
    # supplied no model list to choose from.
    qualifying_model_ids: tuple[UUID, ...] | None
    effective_output_level: int | None
    # The lowest output override the rule accepts.
    output_floor: int | None
    violation: FlowStepClassificationViolation | None


def _classification_level(classification: Any) -> int | None:
    if classification is None:
        return None
    level = getattr(classification, "security_level", None)
    return level if isinstance(level, int) else None


def _max_level(*levels: int | None) -> int | None:
    present = [level for level in levels if level is not None]
    return max(present) if present else None


def _knowledge_level(assistant: Any) -> int | None:
    levels: list[int] = []
    for item in (
        list(getattr(assistant, "collections", []) or [])
        + list(getattr(assistant, "websites", []) or [])
        + list(getattr(assistant, "integration_knowledge_list", []) or [])
    ):
        embedding_model = getattr(item, "embedding_model", None)
        level = _classification_level(
            getattr(embedding_model, "security_classification", None)
        )
        if level is not None:
            levels.append(level)
    return max(levels) if levels else None


def _model_level(model: Any) -> int | None:
    return _classification_level(getattr(model, "security_classification", None))


def _qualifying_model_ids(
    models: Sequence[Any], required_level: int | None
) -> tuple[UUID, ...]:
    cleared: list[tuple[int, UUID]] = []
    for model in models:
        if not model.can_access:
            continue
        level = _model_level(model)
        if required_level is not None and (level is None or level < required_level):
            continue
        cleared.append((-1 if level is None else level, model.id))
    cleared.sort(key=lambda item: (item[0], str(item[1])))
    return tuple(model_id for _, model_id in cleared)


def _cause_of_level(
    level: int,
    *,
    reads: Sequence[int],
    prior_output_levels_by_order: Mapping[int, int | None],
    knowledge_level: int | None,
) -> tuple[ClassificationCause, tuple[int, ...]]:
    sources = tuple(
        order for order in reads if prior_output_levels_by_order.get(order) == level
    )
    if sources:
        return ClassificationCause.READS, sources
    if knowledge_level == level:
        return ClassificationCause.KNOWLEDGE, ()
    return ClassificationCause.SPACE, ()


def explain_step_security_classification(
    *,
    step_order: int,
    step_id: UUID | None = None,
    upstream_step_orders: Sequence[int],
    output_mode: FlowOutputMode | str,
    output_classification_override: int | None,
    prior_output_levels_by_order: Mapping[int, int | None],
    assistant: Any,
    space: Any,
    security_enabled: bool,
    completion_models: Sequence[Any] | None = None,
) -> FlowStepClassificationExplanation:
    """Derive one step's classification facts and the rule violation, if any.

    ``upstream_step_orders`` are the prior steps the step actually reads
    (``step_lineage.resolve_step_upstream_orders``): explicit underlag decides
    alone, otherwise the input source. The model requirement applies only to
    output modes that run a completion model. A deterministic step (rendering,
    template fill, compose) has no model to clear the floor with, yet its
    output still carries the classification of what flowed into it.

    ``security_enabled`` is the organization's switch. While it is off the
    stored levels stay on the rows but none of them applies: not the space's,
    the model's, the knowledge's or a step's output override.

    This is the one computation of the rule: the raising check and the editor's
    preview both read its result.
    """
    reads = tuple(upstream_step_orders)
    baseline_level = (
        _classification_level(getattr(space, "security_classification", None))
        if security_enabled
        else None
    )
    input_level = _max_level(
        baseline_level,
        *(prior_output_levels_by_order.get(order) for order in reads),
    )
    knowledge_level = _knowledge_level(assistant) if security_enabled else None
    model_level = (
        _model_level(getattr(assistant, "completion_model", None))
        if security_enabled
        else None
    )
    if not security_enabled:
        output_classification_override = None

    output_floor = _max_level(input_level, knowledge_level)
    required_model_level = (
        output_floor if flow_output_mode_uses_completion_model(output_mode) else None
    )

    violation: FlowStepClassificationViolation | None = None
    if required_model_level is not None and (
        model_level is None or model_level < required_model_level
    ):
        cause, sources = _cause_of_level(
            required_model_level,
            reads=reads,
            prior_output_levels_by_order=prior_output_levels_by_order,
            knowledge_level=knowledge_level,
        )
        violation = FlowStepClassificationViolation(
            code=ClassificationViolationCode.MODEL_BELOW_REQUIRED,
            message=(
                f"Step {step_order}: assistant model does not meet the required "
                "security classification."
            ),
            required_level=required_model_level,
            current_level=model_level,
            cause=cause,
            source_step_orders=sources,
        )
    elif (
        output_classification_override is not None
        and output_floor is not None
        and output_classification_override < output_floor
    ):
        cause, sources = _cause_of_level(
            output_floor,
            reads=reads,
            prior_output_levels_by_order=prior_output_levels_by_order,
            knowledge_level=knowledge_level,
        )
        violation = FlowStepClassificationViolation(
            code=ClassificationViolationCode.OUTPUT_WRITE_DOWN,
            message=(
                f"Step {step_order}: output classification override would lower "
                "the effective classification of the step output."
            ),
            required_level=output_floor,
            current_level=output_classification_override,
            cause=cause,
            source_step_orders=sources,
        )

    return FlowStepClassificationExplanation(
        step_order=step_order,
        step_id=step_id,
        reads=reads,
        input_level=input_level,
        knowledge_level=knowledge_level,
        required_model_level=required_model_level,
        model_level=model_level,
        qualifying_model_ids=(
            _qualifying_model_ids(completion_models, required_model_level)
            if completion_models is not None
            else None
        ),
        effective_output_level=_max_level(output_floor, output_classification_override),
        output_floor=output_floor,
        violation=violation,
    )


def classification_refusal(
    explanation: FlowStepClassificationExplanation,
) -> FlowStepValidationError:
    """The refusal for an explained violation, in the flow validation error shape.

    ``issue_code`` and ``step_order`` are the identity clients route a refusal
    by; the rest are the facts they need to say what to change.
    """
    violation = explanation.violation
    if violation is None:
        raise ValueError("The explained step has no violation to refuse.")
    context: dict[str, object] = {
        "issue_code": violation.code.value,
        "step_order": explanation.step_order,
        "required_level": violation.required_level,
        "current_level": violation.current_level,
        "cause": violation.cause.value,
        "source_step_orders": list(violation.source_step_orders),
    }
    if explanation.step_id is not None:
        context["step_id"] = str(explanation.step_id)
    if (
        violation.code is ClassificationViolationCode.MODEL_BELOW_REQUIRED
        and explanation.qualifying_model_ids is not None
    ):
        context["qualifying_model_ids"] = [
            str(model_id) for model_id in explanation.qualifying_model_ids
        ]
    return FlowStepValidationError(
        violation.message,
        step_order=explanation.step_order,
        code=violation.code.value,
        context=context,
    )


def evaluate_step_security_classification(
    *,
    step_order: int,
    step_id: UUID | None = None,
    upstream_step_orders: Sequence[int],
    output_mode: FlowOutputMode | str,
    output_classification_override: int | None,
    prior_output_levels_by_order: Mapping[int, int | None],
    assistant: Any,
    space: Any,
    security_enabled: bool,
    completion_models: Sequence[Any] | None = None,
) -> FlowStepClassificationExplanation:
    """Check one step's classification: the explanation, or its refusal."""
    explanation = explain_step_security_classification(
        step_order=step_order,
        step_id=step_id,
        upstream_step_orders=upstream_step_orders,
        output_mode=output_mode,
        output_classification_override=output_classification_override,
        prior_output_levels_by_order=prior_output_levels_by_order,
        assistant=assistant,
        space=space,
        security_enabled=security_enabled,
        completion_models=completion_models,
    )
    if explanation.violation is not None:
        raise classification_refusal(explanation)
    return explanation


def _explain_steps(
    *,
    steps: Sequence[FlowStep],
    assistants_by_id: Mapping[UUID, Any],
    space: Any,
    security_enabled: bool,
) -> Iterator[FlowStepClassificationExplanation]:
    """Each step's facts in step order, each floored by the steps before it.

    Lazy, so a caller that stops at a refusal never evaluates the steps after it.
    The space's models are not read here: they only serve to name what would
    fix a refusal, and a caller asks for that when it needs it.
    """
    step_ref_mapping = build_step_ref_mapping(
        {"step_order": item.step_order, "user_description": item.user_description}
        for item in steps
    )
    prior_output_levels: dict[int, int | None] = {}
    for step in sorted(steps, key=lambda item: item.step_order):
        assistant = assistants_by_id[step.assistant_id]
        explanation = explain_step_security_classification(
            step_order=step.step_order,
            step_id=step.id,
            upstream_step_orders=resolve_step_upstream_orders(
                input_source=step.input_source,
                step_order=step.step_order,
                input_bindings=step.input_bindings,
                prompt_template=(
                    assistant.get_prompt_text()
                    if flow_output_mode_uses_completion_model(step.output_mode)
                    else None
                ),
                output_mode=step.output_mode,
                input_config=step.input_config,
                output_config=step.output_config,
                step_ref_mapping=step_ref_mapping,
                max_prior_step_order=step.step_order - 1,
            ),
            output_mode=step.output_mode,
            output_classification_override=step.output_classification_override,
            prior_output_levels_by_order=prior_output_levels,
            assistant=assistant,
            space=space,
            security_enabled=security_enabled,
        )
        prior_output_levels[step.step_order] = explanation.effective_output_level
        yield explanation


def explain_flow_security_classification(
    *,
    steps: Sequence[FlowStep],
    assistants_by_id: Mapping[UUID, Any],
    space: Any,
    security_enabled: bool,
) -> list[FlowStepClassificationExplanation]:
    """Every step's full explanation, models that would qualify included."""
    completion_models = getattr(space, "completion_models", ())
    qualifying_by_level: dict[int | None, tuple[UUID, ...]] = {}
    explained: list[FlowStepClassificationExplanation] = []
    for explanation in _explain_steps(
        steps=steps,
        assistants_by_id=assistants_by_id,
        space=space,
        security_enabled=security_enabled,
    ):
        level = explanation.required_model_level
        if level not in qualifying_by_level:
            qualifying_by_level[level] = _qualifying_model_ids(completion_models, level)
        explained.append(
            replace(explanation, qualifying_model_ids=qualifying_by_level[level])
        )
    return explained


def require_flow_security_classification(
    *,
    steps: Sequence[FlowStep],
    assistants_by_id: Mapping[UUID, Any],
    space: Any,
    security_enabled: bool,
) -> None:
    """The save-time check: the first step's refusal, or nothing.

    A write pays only for the levels: it stops at the first refusal and reads
    the space's models once, to name the ones that would fix that refusal.
    """
    for explanation in _explain_steps(
        steps=steps,
        assistants_by_id=assistants_by_id,
        space=space,
        security_enabled=security_enabled,
    ):
        violation = explanation.violation
        if violation is None:
            continue
        if violation.code is ClassificationViolationCode.MODEL_BELOW_REQUIRED:
            explanation = replace(
                explanation,
                qualifying_model_ids=_qualifying_model_ids(
                    getattr(space, "completion_models", ()),
                    explanation.required_model_level,
                ),
            )
        raise classification_refusal(explanation)


def evidence_classification_level(
    step_output_levels: Mapping[int, int | None],
) -> int:
    """The level a reader of this run's evidence must clear.

    The highest effective output level across the run's steps, 0 when nothing
    in the run is classified. Recorded on the run when it starts, so that a
    later reader (a person, an export, the AI builder's review) is held to the
    rule that applied when the evidence was produced rather than to whatever
    the flow or space says at reading time. A run recorded before this rule
    carries no level, and readers treat that as unknown, not as 0.
    """
    return max(
        (level for level in step_output_levels.values() if level is not None),
        default=0,
    )
