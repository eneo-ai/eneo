from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, cast

from intric.flows.ai_builder.ai_builder_models import (
    FlowDraftSpecCore,
    OutputMode,
    OutputType,
    StepSpec,
)
from intric.flows.ai_builder.ai_builder_step_capabilities import (
    is_citation_capable_step,
)
from intric.flows.citation_sidecar import resolve_citation_mode

_TEMPLATE_FILL_ONLY_KEYS = frozenset({"bindings", "template_asset_id", "template_file_id"})


@dataclass(frozen=True, slots=True)
class StepNormalizationChange:
    code: str
    field_suffix: str
    message: str
    severity: Literal["info", "warning", "error"] = "info"


def normalize_ai_builder_spec(
    spec: FlowDraftSpecCore,
) -> tuple[FlowDraftSpecCore, list[tuple[StepSpec, StepNormalizationChange]]]:
    normalized_steps: list[StepSpec] = []
    changes: list[tuple[StepSpec, StepNormalizationChange]] = []
    mutated = False

    for step in spec.steps:
        normalized_step, step_changes = normalize_ai_builder_step(step)
        normalized_steps.append(normalized_step)
        mutated = mutated or normalized_step is not step
        changes.extend((normalized_step, change) for change in step_changes)

    if not mutated:
        return spec, changes
    return spec.model_copy(update={"steps": normalized_steps}), changes


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
        if (
            citation_mode == "inline_inref_sidecar"
            and not is_citation_capable_step(
                output_type=str(output_type),
                output_mode=str(output_mode),
                output_config=next_output_config,
            )
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
