from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from intric.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
    InputSource,
    InputType,
)

JsonObject = dict[str, Any]


def apply_audio_transcription_defaults(
    *,
    metadata: JsonObject | None,
    spec: FlowDraftSpecCore,
    default_transcription_model_id: UUID | None,
) -> JsonObject | None:
    if not _uses_audio_flow_input(spec):
        return _cleanup_transcription_metadata(metadata)

    updated_metadata = dict(metadata or {})
    wizard = updated_metadata.get("wizard")
    wizard_config: JsonObject = (
        dict(cast(JsonObject, wizard)) if isinstance(wizard, dict) else {}
    )

    wizard_config["transcription_enabled"] = True

    raw_model = wizard_config.get("transcription_model")
    model_config: JsonObject = (
        dict(cast(JsonObject, raw_model)) if isinstance(raw_model, dict) else {}
    )
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


def _uses_audio_flow_input(spec: FlowDraftSpecCore) -> bool:
    return any(
        step.input_source == InputSource.FLOW_INPUT
        and step.input_type == InputType.AUDIO
        for step in spec.steps
    )


_TRANSCRIPTION_WIZARD_KEYS = {
    "transcription_enabled",
    "transcription_model",
    "transcription_language",
}


def _cleanup_transcription_metadata(metadata: JsonObject | None) -> JsonObject | None:
    if not isinstance(metadata, dict):
        return metadata

    wizard = metadata.get("wizard")
    if not isinstance(wizard, dict):
        return metadata

    has_transcription_keys = any(key in wizard for key in _TRANSCRIPTION_WIZARD_KEYS)
    if not has_transcription_keys:
        return metadata

    updated_metadata = dict(metadata)
    updated_wizard = {
        key: value
        for key, value in cast(JsonObject, wizard).items()
        if key not in _TRANSCRIPTION_WIZARD_KEYS
    }

    if updated_wizard:
        updated_metadata["wizard"] = updated_wizard
    else:
        del updated_metadata["wizard"]

    return updated_metadata or None
