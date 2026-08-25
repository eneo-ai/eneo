from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from eneo.flows.domain.flow_step_validation import (
    FlowStepValidationError,
    FlowStepValidationView,
)

SPEAKER_MAPPING_CONFIG_KEY = "speaker_mapping"
SPEAKER_MAPPING_PARTICIPANT_FIELD_TYPES = frozenset({"text", "multiselect"})
SPEAKER_MAPPING_SPEAKER_COUNT_FIELD_TYPES = frozenset({"number"})


def _config_field(output_config: object, key: str) -> str | None:
    if not isinstance(output_config, Mapping):
        return None
    block = cast(Mapping[str, object], output_config).get(SPEAKER_MAPPING_CONFIG_KEY)
    if not isinstance(block, Mapping):
        return None
    value = cast(Mapping[str, object], block).get(key)
    return value if isinstance(value, str) and value.strip() else None


def speaker_mapping_speaker_count_field(output_config: object) -> str | None:
    """Optional number form field with the expected speaker count."""
    return _config_field(output_config, "speaker_count_field")


def speaker_mapping_participants_field(output_config: object) -> str | None:
    """The configured participants form field name, or None when unset."""
    if not isinstance(output_config, Mapping):
        return None
    block = cast(Mapping[str, object], output_config).get(SPEAKER_MAPPING_CONFIG_KEY)
    if not isinstance(block, Mapping):
        return None
    value = cast(Mapping[str, object], block).get("participants_field")
    return value if isinstance(value, str) and value.strip() else None


def validate_speaker_mapping_output_config(
    *,
    step: FlowStepValidationView,
    form_field_types: Mapping[str, str],
    require_complete_config: bool,
) -> None:
    """`output_config.speaker_mapping` shape, and at publish a usable field."""
    output_config = step.output_config
    block: object = (
        cast(Mapping[str, object], output_config).get(SPEAKER_MAPPING_CONFIG_KEY)
        if isinstance(output_config, Mapping)
        else None
    )
    if block is None:
        if require_complete_config:
            raise FlowStepValidationError(
                f"Step {step.step_order}: output_config.speaker_mapping must be an "
                "object for output_mode 'speaker_mapping'.",
                step_order=step.step_order,
            )
        return
    if not isinstance(block, Mapping):
        raise FlowStepValidationError(
            f"Step {step.step_order}: output_config.speaker_mapping must be an object.",
            step_order=step.step_order,
        )
    raw_field = cast(Mapping[str, object], block).get("participants_field")
    if raw_field is not None and (
        not isinstance(raw_field, str) or not raw_field.strip()
    ):
        raise FlowStepValidationError(
            f"Step {step.step_order}: output_config.speaker_mapping.participants_field "
            "must be a non-empty string or null.",
            step_order=step.step_order,
        )
    raw_count_field = cast(Mapping[str, object], block).get("speaker_count_field")
    if raw_count_field is not None and (
        not isinstance(raw_count_field, str) or not raw_count_field.strip()
    ):
        raise FlowStepValidationError(
            f"Step {step.step_order}: output_config.speaker_mapping.speaker_count_field "
            "must be a non-empty string or null.",
            step_order=step.step_order,
        )
    if not require_complete_config:
        return
    if (
        isinstance(raw_count_field, str)
        and form_field_types.get(raw_count_field.strip())
        not in SPEAKER_MAPPING_SPEAKER_COUNT_FIELD_TYPES
    ):
        raise FlowStepValidationError(
            f"Step {step.step_order}: output_config.speaker_mapping.speaker_count_field "
            f"'{raw_count_field}' must name a form field of type 'number'.",
            step_order=step.step_order,
        )
    if raw_field is None:
        raise FlowStepValidationError(
            f"Step {step.step_order}: output_config.speaker_mapping.participants_field "
            "must name a form field of type 'text' or 'multiselect'.",
            step_order=step.step_order,
        )
    field_type = form_field_types.get(raw_field.strip())
    if field_type not in SPEAKER_MAPPING_PARTICIPANT_FIELD_TYPES:
        raise FlowStepValidationError(
            f"Step {step.step_order}: output_config.speaker_mapping.participants_field "
            f"'{raw_field}' must name a form field of type 'text' or 'multiselect'.",
            step_order=step.step_order,
        )
