from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from eneo.flows.domain.flow import FlowPersistedJsonObject, clone_json_object
from eneo.flows.domain.flow_step_validation import FlowStepValidationView
from eneo.flows.domain.runtime_input import parse_runtime_input_config
from eneo.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
    InputSource,
    InputType,
    StepSpec,
)


def apply_audio_transcription_defaults(
    *,
    metadata: FlowPersistedJsonObject | None,
    spec: FlowDraftSpecCore,
    default_transcription_model_id: UUID | None,
) -> FlowPersistedJsonObject | None:
    if not requires_audio_transcription(spec.steps):
        return _cleanup_transcription_metadata(metadata)

    updated_metadata = dict(metadata or {})
    wizard_config = clone_json_object(updated_metadata.get("wizard")) or {}

    wizard_config["transcription_enabled"] = True

    model_config = clone_json_object(wizard_config.get("transcription_model")) or {}
    model_id = model_config.get("id")
    if (
        model_id is None or str(model_id).strip() == ""
    ) and default_transcription_model_id:
        wizard_config["transcription_model"] = {
            "id": str(default_transcription_model_id)
        }

    raw_language = wizard_config.get("transcription_language")
    if raw_language is None or str(raw_language).strip() == "":
        wizard_config["transcription_language"] = "auto"

    updated_metadata["wizard"] = wizard_config
    return updated_metadata


def requires_audio_transcription(
    steps: Sequence[StepSpec | FlowStepValidationView],
) -> bool:
    for step in steps:
        if (
            step.input_source == InputSource.FLOW_INPUT
            and step.input_type == InputType.AUDIO
        ):
            return True
        runtime_input = parse_runtime_input_config(step.input_config)
        if runtime_input.enabled and runtime_input.input_format == "audio":
            return True
    return False


_TRANSCRIPTION_WIZARD_KEYS = {
    "transcription_enabled",
    "transcription_model",
    "transcription_language",
    "transcription_diarization",
}


def _cleanup_transcription_metadata(
    metadata: FlowPersistedJsonObject | None,
) -> FlowPersistedJsonObject | None:
    if not isinstance(metadata, dict):
        return metadata

    wizard_config = clone_json_object(metadata.get("wizard"))
    if wizard_config is None:
        return metadata

    has_transcription_keys = any(
        key in wizard_config for key in _TRANSCRIPTION_WIZARD_KEYS
    )
    if not has_transcription_keys:
        return metadata

    updated_metadata = dict(metadata)
    updated_wizard = {
        key: value
        for key, value in wizard_config.items()
        if key not in _TRANSCRIPTION_WIZARD_KEYS
    }

    if updated_wizard:
        updated_metadata["wizard"] = updated_wizard
    else:
        del updated_metadata["wizard"]

    return updated_metadata or None
