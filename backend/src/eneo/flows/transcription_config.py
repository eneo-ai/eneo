from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

_ALLOWED_TRANSCRIPTION_LANGUAGES = {"auto", "sv", "en"}
# The language a run transcribes in when the flow names none.
DEFAULT_TRANSCRIPTION_LANGUAGE = "sv"
SPEAKER_SERVICE_KEY = "transcription_speaker_service"
MAX_SPEAKERS_KEY = "transcription_max_speakers"

if TYPE_CHECKING:
    from eneo.spaces.space import Space
    from eneo.transcription_services.models import TranscriptionServiceConnection


class FlowTranscriptionConfigError(ValueError):
    """Raised when published flow transcription metadata is malformed."""


@dataclass(frozen=True)
class FlowTranscriptionConfig:
    enabled: bool
    model_id: UUID | None
    language: str
    diarization: bool
    # The transcription service the author chose: it times the words, and
    # labels the speakers when a run asks. None when the flow chose none or
    # has not chosen; nothing is chosen for it at run time.
    speaker_service_id: UUID | None = None
    # The most speakers the service may label in a run that states no bound;
    # None lets the service count them.
    max_speakers: int | None = None

    @property
    def service_in_use(self) -> UUID | None:
        """The chosen service, while the flow transcribes: it times the words
        of every transcript, whether or not the speakers are labelled."""
        return self.speaker_service_id if self.enabled else None

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
        max_speakers=_max_speakers(wizard.get(MAX_SPEAKERS_KEY)),
    )


def _max_speakers(raw: object) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        raise FlowTranscriptionConfigError(
            f"wizard.{MAX_SPEAKERS_KEY} must be a whole number of at least 1."
        )
    return raw


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


class SpeakerServiceGap(StrEnum):
    """Why no service can label this flow's speakers."""

    # The flow chose no service.
    NOT_CHOSEN = "not_chosen"
    # The service the flow chose is not usable in the space.
    PICKED_UNAVAILABLE = "picked_unavailable"


@dataclass(frozen=True)
class SpeakerServiceResolution:
    connection: TranscriptionServiceConnection | None
    gap: SpeakerServiceGap | None

    @property
    def available(self) -> bool:
        return self.connection is not None


def resolve_speaker_service(
    config: FlowTranscriptionConfig, space: Space
) -> SpeakerServiceResolution:
    """The service this flow chose, as ``space`` may use it now: it times the
    words of the flow's transcripts and labels their speakers when a run asks.

    Only the service the flow's author chose is used: nothing stands in for a
    chosen service the space may no longer use, and nothing is chosen for a
    flow that chose none, whatever the space has."""
    if config.speaker_service_id is None:
        return SpeakerServiceResolution(None, SpeakerServiceGap.NOT_CHOSEN)
    connection = space.usable_transcription_service(config.speaker_service_id)
    return SpeakerServiceResolution(
        connection,
        None if connection is not None else SpeakerServiceGap.PICKED_UNAVAILABLE,
    )


def to_provider_language(language: str) -> str | None:
    normalized = language.casefold().strip()
    if normalized == "auto":
        return None
    return normalized
