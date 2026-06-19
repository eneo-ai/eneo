from __future__ import annotations

from uuid import UUID

from intric.flows.domain.flow import FlowPersistedJsonObject, clone_json_object
from intric.flows.flow_authoring_spec import (
    FlowDraftSpecCore,
    InputSource,
    InputType,
)


def apply_audio_transcription_defaults(
    *,
    metadata: FlowPersistedJsonObject | None,
    spec: FlowDraftSpecCore,
    default_transcription_model_id: UUID | None,
) -> FlowPersistedJsonObject | None:
    if not _uses_audio_flow_input(spec):
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
