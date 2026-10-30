from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from eneo.flows.domain.flow import (
    FlowPersistedJsonObject,
    FlowStep,
    clone_json_object,
)
from eneo.flows.domain.flow_step_validation import FlowGraphIssueCode
from eneo.flows.domain.runtime_input import parse_runtime_input_config
from eneo.flows.domain.speaker_mapping_config import steps_require_speaker_labels
from eneo.flows.flow_authoring_spec import InputSource, InputType
from eneo.flows.transcription_config import (
    DEFAULT_TRANSCRIPTION_LANGUAGE,
    MAX_SPEAKERS_KEY,
    SPEAKER_SERVICE_KEY,
    FlowTranscriptionConfig,
    FlowTranscriptionConfigError,
    parse_transcription_config,
)
from eneo.main.exceptions import BadRequestException

if TYPE_CHECKING:
    from eneo.spaces.space import Space


class AudioInputStep(Protocol):
    """The three values of a step that say it takes audio: read from the steps a
    flow ends with (a compiled step, a validation view) or from a spec's."""

    @property
    def input_source(self) -> str: ...

    @property
    def input_type(self) -> str: ...

    @property
    def input_config(self) -> FlowPersistedJsonObject | None: ...


def apply_audio_transcription_defaults(
    *,
    metadata: FlowPersistedJsonObject | None,
    steps: Sequence[AudioInputStep],
    default_transcription_model_id: UUID | None,
) -> FlowPersistedJsonObject | None:
    """`steps` are the steps the flow ends with, not the caller's description of
    them: a sparse edit never states the columns it does not name."""

    if not requires_audio_transcription(steps):
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
        wizard_config["transcription_language"] = DEFAULT_TRANSCRIPTION_LANGUAGE

    updated_metadata["wizard"] = wizard_config
    return updated_metadata


def lacks_speaker_service_choice(metadata: FlowPersistedJsonObject | None) -> bool:
    """Whether the flow transcribes and its author has made no choice of
    service: its wizard has no ``transcription_speaker_service``. A stored
    null is the author's choice of none. A malformed choice is no answer
    here; the write's validation refuses it."""
    try:
        config = parse_transcription_config(metadata)
    except FlowTranscriptionConfigError:
        return False
    wizard = clone_json_object((metadata or {}).get("wizard")) or {}
    return config.enabled and SPEAKER_SERVICE_KEY not in wizard


def fill_default_speaker_service(
    *,
    metadata: FlowPersistedJsonObject | None,
    space: Space,
) -> FlowPersistedJsonObject | None:
    """The metadata a draft is written with: the organisation's default
    transcription service becomes the flow's own choice when the flow
    transcribes, its author has made no choice, and its space may use the
    default.

    The choice is stored, so the flow runs with it as with one its author
    made; nothing reads the default at publish or run time. A choice is never
    replaced, a choice of none included, and with no usable default the
    author chooses."""
    default = space.default_transcription_service
    if default is None or not lacks_speaker_service_choice(metadata):
        return metadata
    filled = dict(metadata or {})
    filled["wizard"] = {
        **(clone_json_object(filled.get("wizard")) or {}),
        SPEAKER_SERVICE_KEY: {"id": str(default.id)},
    }
    return filled


def transcription_config_for_write(
    metadata: FlowPersistedJsonObject | None,
) -> FlowTranscriptionConfig:
    """The transcription choice a write states, refused when malformed: a flow
    without audio steps would otherwise store it unread."""
    try:
        return parse_transcription_config(metadata)
    except FlowTranscriptionConfigError as exc:
        code = FlowGraphIssueCode.FLOW_AUDIO_TRANSCRIPTION_INVALID.value
        raise BadRequestException(
            str(exc), code=code, context={"issue_code": code}
        ) from exc


def kept_speaker_service_id(metadata: FlowPersistedJsonObject | None) -> UUID | None:
    """The service a saved draft chose and uses; None when it chose none or
    its stored choice is unreadable."""
    try:
        return parse_transcription_config(metadata).service_in_use
    except FlowTranscriptionConfigError:
        return None


def require_chosen_speaker_service(
    config: FlowTranscriptionConfig, *, steps: Iterable[FlowStep], space: Space
) -> None:
    """Refuse to publish a flow that asks for speaker labels and chose no
    service to label them: nothing is ever chosen for it. It asks when a step
    requires the labels, or when its own setting is on in a space that has a
    service to choose; in a space with none that setting labels nothing and
    the flow simply transcribes."""
    if not config.enabled or config.speaker_service_id is not None:
        return
    if steps_require_speaker_labels(steps):
        message = (
            "A step in this flow needs speakers identified; choose which "
            "speaker identification service the flow uses."
        )
    elif config.diarization and space.usable_transcription_services:
        message = (
            "Choose which speaker identification service the flow uses, or "
            "switch speaker identification off."
        )
    else:
        return
    code = FlowGraphIssueCode.FLOW_SPEAKER_SERVICE_NOT_CHOSEN.value
    raise BadRequestException(message, code=code, context={"issue_code": code})


def require_usable_speaker_service(service_id: UUID, *, space: Space) -> None:
    """Refuse a chosen transcription service the space may not use."""
    if space.usable_transcription_service(service_id) is None:
        code = FlowGraphIssueCode.FLOW_SPEAKER_SERVICE_UNAVAILABLE.value
        raise BadRequestException(
            "The chosen transcription service is not available in this space: "
            "it is not granted to the space, is turned off, or is below the "
            "space's security classification.",
            code=code,
            context={"issue_code": code, "speaker_service_id": str(service_id)},
        )


def requires_audio_transcription(steps: Sequence[AudioInputStep]) -> bool:
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
    SPEAKER_SERVICE_KEY,
    MAX_SPEAKERS_KEY,
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
