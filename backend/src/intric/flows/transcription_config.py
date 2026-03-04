from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID


_ALLOWED_TRANSCRIPTION_LANGUAGES = {"auto", "sv", "en"}


class FlowTranscriptionConfigError(ValueError):
    """Raised when published flow transcription metadata is malformed."""


@dataclass(frozen=True)
class FlowTranscriptionConfig:
    enabled: bool
    model_id: UUID | None
    language: str


def parse_transcription_config(definition_metadata: dict[str, Any] | None) -> FlowTranscriptionConfig:
    wizard: dict[str, Any] = {}
    if isinstance(definition_metadata, dict):
        raw_wizard = definition_metadata.get("wizard")
        if isinstance(raw_wizard, dict):
            wizard = raw_wizard

    enabled = bool(wizard.get("transcription_enabled", False))

    model_id: UUID | None = None
    raw_model = wizard.get("transcription_model")
    if raw_model is not None and not isinstance(raw_model, dict):
        raise FlowTranscriptionConfigError("wizard.transcription_model must be an object when provided.")
    if isinstance(raw_model, dict):
        raw_model_id = raw_model.get("id")
        if raw_model_id is not None and str(raw_model_id).strip() != "":
            try:
                model_id = UUID(str(raw_model_id))
            except (ValueError, TypeError, AttributeError) as exc:
                raise FlowTranscriptionConfigError("wizard.transcription_model.id must be a valid UUID.") from exc

    raw_language = wizard.get("transcription_language", "sv")
    language = "sv" if raw_language is None else str(raw_language).strip().casefold()
    if language == "":
        language = "sv"
    if language not in _ALLOWED_TRANSCRIPTION_LANGUAGES:
        raise FlowTranscriptionConfigError(
            "wizard.transcription_language must be one of: auto, sv, en."
        )

    return FlowTranscriptionConfig(
        enabled=enabled,
        model_id=model_id,
        language=language,
    )


def to_provider_language(language: str) -> str | None:
    normalized = language.casefold().strip()
    if normalized == "auto":
        return None
    return normalized
