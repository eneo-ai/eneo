from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, cast

from intric.flows.ai_builder.ai_builder_models import (
    FlowDraftSpecCore,
    InputSource,
    OutputMode,
    OutputType,
    StepSpec,
)
from intric.flows.ai_builder.ai_builder_step_capabilities import (
    is_citation_capable_step,
)
from intric.flows.citation_sidecar import resolve_citation_mode
from intric.flows.template_reference_analyzer import (
    TemplateReferenceKind,
    analyze_template,
)

_TEMPLATE_FILL_ONLY_KEYS = frozenset(
    {"bindings", "template_asset_id", "template_file_id"}
)


@dataclass(frozen=True, slots=True)
class StepNormalizationChange:
    code: str
    field_suffix: str
    message: str
    severity: Literal["info", "warning", "error"] = "info"


def normalize_ai_builder_spec(
    spec: FlowDraftSpecCore,
) -> tuple[FlowDraftSpecCore, list[tuple[StepSpec, StepNormalizationChange]]]:
    spec, topology_changes = normalize_ai_builder_step_topology(spec)
    normalized_steps: list[StepSpec] = []
    changes: list[tuple[StepSpec, StepNormalizationChange]] = list(topology_changes)
    mutated = False

    for step in spec.steps:
        normalized_step, step_changes = normalize_ai_builder_step(step)
        normalized_steps.append(normalized_step)
        mutated = mutated or normalized_step is not step
        changes.extend((normalized_step, change) for change in step_changes)

    if not mutated:
        return spec, changes
    return spec.model_copy(update={"steps": normalized_steps}), changes


def normalize_ai_builder_step_topology(
    spec: FlowDraftSpecCore,
) -> tuple[FlowDraftSpecCore, list[tuple[StepSpec, StepNormalizationChange]]]:
    """Normalize redundant Flow graph mechanics before quality validation.

    AI Builder create/edit tasks are allowed to describe semantic data flow, but
    the backend owns token-sensitive topology choices. Most generated linear
    flows do not need `all_previous_steps`; it duplicates context and triggers
    noisy quality warnings. Keep true fan-in when a prompt explicitly references
    several earlier steps, otherwise compile to the lean adjacent edge.
    """

    step_refs = {step.plan_step_ref: index + 1 for index, step in enumerate(spec.steps)}
    form_fields = {
        field.name.strip() for field in (spec.form_fields or []) if field.name.strip()
    }
    all_previous_indexes = [
        index
        for index, step in enumerate(spec.steps)
        if step.input_source == InputSource.ALL_PREVIOUS_STEPS
    ]
    last_all_previous_index = (
        all_previous_indexes[-1] if len(all_previous_indexes) > 1 else None
    )
    normalized_steps: list[StepSpec] = []
    changes: list[tuple[StepSpec, StepNormalizationChange]] = []
    mutated = False

    for index, step in enumerate(spec.steps):
        if _can_rewire_all_previous_to_previous_step(
            step=step,
            step_index=index,
            step_refs=step_refs,
            form_fields=form_fields,
            repeated_all_previous=len(all_previous_indexes) > 1,
            preserve_as_final_fan_in=index == last_all_previous_index,
        ):
            normalized_step = step.model_copy(
                update={"input_source": InputSource.PREVIOUS_STEP}
            )
            normalized_steps.append(normalized_step)
            mutated = True
            changes.append(
                (
                    normalized_step,
                    StepNormalizationChange(
                        code="input_source_all_previous_rewired",
                        field_suffix="input_source",
                        message=(
                            "Rewired redundant all_previous_steps to previous_step "
                            "because no explicit multi-step fan-in was required."
                        ),
                    ),
                )
            )
            continue
        normalized_steps.append(step)

    if not mutated:
        return spec, changes
    return spec.model_copy(update={"steps": normalized_steps}), changes


def _can_rewire_all_previous_to_previous_step(
    *,
    step: StepSpec,
    step_index: int,
    step_refs: dict[str, int],
    form_fields: set[str],
    repeated_all_previous: bool,
    preserve_as_final_fan_in: bool,
) -> bool:
    if step_index == 0:
        return False
    if step.input_source != InputSource.ALL_PREVIOUS_STEPS:
        return False

    question = _question_binding(step)
    if question is None:
        return repeated_all_previous and not preserve_as_final_fan_in

    references = analyze_template(
        question,
        step_refs=step_refs,
        form_field_names=form_fields,
    )
    referenced_step_orders = {
        reference.step_order
        for reference in references
        if reference.kind is TemplateReferenceKind.STEP
        and reference.step_order is not None
    }
    if len(referenced_step_orders) > 1:
        return False

    previous_step_order = step_index
    if referenced_step_orders == {previous_step_order}:
        return True
    if not referenced_step_orders:
        return repeated_all_previous and not preserve_as_final_fan_in
    return False


def normalize_ai_builder_step(
    step: StepSpec,
) -> tuple[StepSpec, list[StepNormalizationChange]]:
    changes: list[StepNormalizationChange] = []
    if not all(
        hasattr(step, attribute)
        for attribute in ("output_mode", "output_type", "output_config", "model_copy")
    ):
        return step, changes

    output_mode = step.output_mode
    output_type = step.output_type
    output_config = _as_output_config_dict(step.output_config)
    updates: dict[str, Any] = {}

    if output_mode == OutputMode.TEMPLATE_FILL and output_type != OutputType.DOCX:
        output_mode = OutputMode.PASS_THROUGH
        updates["output_mode"] = output_mode
        changes.append(
            StepNormalizationChange(
                code="output_mode_template_fill_reset",
                field_suffix="output_mode",
                message=(
                    "Template fill reset to pass_through because only DOCX steps can keep "
                    "output_mode 'template_fill'."
                ),
            )
        )

    if output_config is not None:
        next_output_config = dict(output_config)
        if output_mode != OutputMode.TEMPLATE_FILL:
            removed_template_keys = sorted(
                key for key in _TEMPLATE_FILL_ONLY_KEYS if key in next_output_config
            )
            for key in removed_template_keys:
                del next_output_config[key]
            if removed_template_keys:
                changes.append(
                    StepNormalizationChange(
                        code="output_config_template_fill_keys_cleared",
                        field_suffix="output_config",
                        message=(
                            "Removed template-fill-only output_config fields because this step "
                            "no longer uses output_mode 'template_fill'."
                        ),
                    )
                )

        citation_mode = resolve_citation_mode(next_output_config)
        if citation_mode == "inline_inref_sidecar" and not is_citation_capable_step(
            output_type=str(output_type),
            output_mode=str(output_mode),
            output_config=next_output_config,
        ):
            del next_output_config["citation_mode"]
            changes.append(
                StepNormalizationChange(
                    code="output_config_citation_mode_cleared",
                    field_suffix="output_config.citation_mode",
                    message=(
                        "Removed citation_mode because only LLM-backed text steps can keep "
                        "inline citation tracking."
                    ),
                )
            )

        normalized_output_config = next_output_config or None
        if normalized_output_config != step.output_config:
            updates["output_config"] = normalized_output_config

    if not updates:
        return step, changes
    return step.model_copy(update=updates), changes


def supports_inline_inref_citation(
    *,
    output_type: OutputType,
    output_mode: OutputMode,
) -> bool:
    return is_citation_capable_step(
        output_type=str(output_type),
        output_mode=str(output_mode),
        output_config={"citation_mode": "inline_inref_sidecar"},
    )


def _as_output_config_dict(output_config: Any) -> dict[str, Any] | None:
    if not isinstance(output_config, dict):
        return None
    typed_output_config = cast(dict[object, Any], output_config)
    normalized: dict[str, Any] = {}
    for key, value in typed_output_config.items():
        normalized[str(key)] = value
    return normalized


def _question_binding(step: StepSpec) -> str | None:
    if not isinstance(step.input_bindings, dict):
        return None
    question = step.input_bindings.get("question")
    if isinstance(question, str) and question.strip():
        return question
    return None
