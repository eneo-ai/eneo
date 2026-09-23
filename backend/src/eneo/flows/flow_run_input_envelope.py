from __future__ import annotations

from typing import Self

from eneo.flows.domain.flow import FlowPersistedJsonObject
from eneo.flows.domain.step_output import FileBackedStepText, InlineTranscript

EXPECTED_FLOW_VERSION_KEY = "expected_flow_version"
STEP_INPUTS_KEY = "step_inputs"
FLOW_INPUT_TRANSCRIPTION_KEY = "transkribering"
TRANSCRIPT_FORMAT_UNSUPPORTED_MESSAGE = (
    "The run's transcript predates the current format. Start a new run."
)
TRANSCRIPT_REGENERATION_KEY = "transcript_regeneration"
# The run's own speaker-label choice; absent means the flow's default.
SPEAKER_LABELS_KEY = "speaker_labels"

_REMOVED_TOP_LEVEL_RUNTIME_FILE_IDS_KEY = "file_ids"
_PERSISTED_RUNTIME_INPUT_KEYS = frozenset(
    {
        EXPECTED_FLOW_VERSION_KEY,
        FLOW_INPUT_TRANSCRIPTION_KEY,
        SPEAKER_LABELS_KEY,
        TRANSCRIPT_REGENERATION_KEY,
    }
)
FLOW_RUN_RESERVED_INPUT_PAYLOAD_KEYS = _PERSISTED_RUNTIME_INPUT_KEYS | frozenset(
    {STEP_INPUTS_KEY, _REMOVED_TOP_LEVEL_RUNTIME_FILE_IDS_KEY}
)


class FlowRunInputEnvelopePatch:
    __slots__ = ("_merge_payload",)

    _merge_payload: FlowPersistedJsonObject

    def __init__(self) -> None:
        raise TypeError("Use a named Flow run input envelope patch constructor.")

    @classmethod
    def _from_merge_payload(cls, merge_payload: FlowPersistedJsonObject) -> Self:
        patch = cls.__new__(cls)
        patch._merge_payload = dict(merge_payload)
        return patch

    @classmethod
    def transcription(
        cls, *, transcript: FileBackedStepText | InlineTranscript
    ) -> Self:
        return cls._from_merge_payload(
            {FLOW_INPUT_TRANSCRIPTION_KEY: transcript.model_dump(mode="json")}
        )

    def to_merge_dict(self) -> FlowPersistedJsonObject:
        return dict(self._merge_payload)

    def apply_to(
        self, current: FlowPersistedJsonObject | None
    ) -> FlowPersistedJsonObject:
        payload = dict(current or {})
        payload.update(self._merge_payload)
        return payload


def read_semantic_flow_input_payload(
    input_payload_json: FlowPersistedJsonObject | None,
) -> FlowPersistedJsonObject:
    return {
        key: value
        for key, value in (input_payload_json or {}).items()
        if key not in FLOW_RUN_RESERVED_INPUT_PAYLOAD_KEYS
    }


def read_speaker_labels_choice(
    input_payload_json: FlowPersistedJsonObject | None,
) -> bool | None:
    choice = (input_payload_json or {}).get(SPEAKER_LABELS_KEY)
    return choice if isinstance(choice, bool) else None


def build_initial_run_input_envelope(
    *,
    normalized_inline_payload: FlowPersistedJsonObject | None,
    flow_version: int,
    speaker_labels: bool | None = None,
) -> FlowPersistedJsonObject:
    payload = dict(normalized_inline_payload or {})
    payload[EXPECTED_FLOW_VERSION_KEY] = flow_version
    if speaker_labels is not None:
        payload[SPEAKER_LABELS_KEY] = speaker_labels
    return payload
