from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

_ALLOWED_TRANSCRIPTION_LANGUAGES = {"auto", "sv", "en"}
# The language a run transcribes in when the flow names none.
DEFAULT_TRANSCRIPTION_LANGUAGE = "sv"
SPEAKER_SERVICE_KEY = "transcription_speaker_service"


class FlowTranscriptionConfigError(ValueError):
    """Raised when published flow transcription metadata is malformed."""


@dataclass(frozen=True)
class FlowTranscriptionConfig:
    enabled: bool
    model_id: UUID | None
    language: str
    diarization: bool
    # The service that labels speakers, when the author picked one; None means
    # the space's only speaker service, resolved when a run starts.
    speaker_service_id: UUID | None = None

    @property
    def labels_with_the_spaces_service(self) -> bool:
        """Speakers are labelled by the space's only speaker service: labels
        are on and no service is picked."""
        return self.enabled and self.diarization and self.speaker_service_id is None

    @property
    def speaker_service_in_use(self) -> UUID | None:
        """The picked speaker service, while the flow transcribes and labels
        speakers; a pick that is switched off is not used."""
        return self.speaker_service_id if self.enabled and self.diarization else None

    def diarize(self, speaker_labels: bool | None) -> bool:
        """Whether speakers are labelled: the run's own choice, else the flow's."""
        return self.diarization if speaker_labels is None else speaker_labels


def parse_transcription_config(
    definition_metadata: dict[str, Any] | None,
) -> FlowTranscriptionConfig:
    wizard: dict[str, Any] = {}
    if definition_metadata is not None:
        raw_wizard = definition_metadata.get("wizard")
        if isinstance(raw_wizard, dict):
            wizard = cast(dict[str, Any], raw_wizard)

    enabled = bool(wizard.get("transcription_enabled", False))
    model_id = _reference_id(wizard, "transcription_model")

    raw_language = wizard.get("transcription_language", DEFAULT_TRANSCRIPTION_LANGUAGE)
    language = (
        DEFAULT_TRANSCRIPTION_LANGUAGE
        if raw_language is None
        else str(raw_language).strip().casefold()
    )
    if language == "":
        language = DEFAULT_TRANSCRIPTION_LANGUAGE
    if language not in _ALLOWED_TRANSCRIPTION_LANGUAGES:
        raise FlowTranscriptionConfigError(
            "wizard.transcription_language must be one of: auto, sv, en."
        )

    raw_diarization = wizard.get("transcription_diarization", True)
    if not isinstance(raw_diarization, bool):
        raise FlowTranscriptionConfigError(
            "wizard.transcription_diarization must be a boolean when provided."
        )

    return FlowTranscriptionConfig(
        enabled=enabled,
        model_id=model_id,
        language=language,
        diarization=raw_diarization,
        speaker_service_id=_reference_id(wizard, SPEAKER_SERVICE_KEY),
    )


def _reference_id(wizard: dict[str, Any], key: str) -> UUID | None:
    """The id of an optional ``{"id": ...}`` reference; blank reads as none."""
    raw = wizard.get(key)
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise FlowTranscriptionConfigError(
            f"wizard.{key} must be an object when provided."
        )
    raw_id = cast(dict[str, Any], raw).get("id")
    if raw_id is None or str(raw_id).strip() == "":
        return None
    try:
        return UUID(str(raw_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise FlowTranscriptionConfigError(
            f"wizard.{key}.id must be a valid UUID."
        ) from exc


def to_provider_language(language: str) -> str | None:
    normalized = language.casefold().strip()
    if normalized == "auto":
        return None
    return normalized
