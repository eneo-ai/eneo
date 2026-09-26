from __future__ import annotations

from typing import Self
from uuid import UUID

from pydantic import TypeAdapter
from typing_extensions import NotRequired, TypedDict

from eneo.flows.domain.flow import FlowPersistedJsonObject
from eneo.flows.domain.step_output import FileBackedStepText, InlineTranscript
from eneo.main.models import NOT_PROVIDED, NotProvided

EXPECTED_FLOW_VERSION_KEY = "expected_flow_version"
STEP_INPUTS_KEY = "step_inputs"
FLOW_INPUT_TRANSCRIPTION_KEY = "transkribering"
TRANSCRIPT_FORMAT_UNSUPPORTED_MESSAGE = (
    "The run's transcript predates the current format. Start a new run."
)
TRANSCRIPT_REGENERATION_KEY = "transcript_regeneration"
# The speaker-label setting settled at admission whenever the flow offers one:
# true when the flow requires labels, else the run's choice, else the flow's
# default then. Absent when the run recorded no setting (the flow offers none,
# or the run predates recording it); execution then uses its version's
# default, and the public read is null.
SPEAKER_LABELS_KEY = "speaker_labels"
# The speaker-count bound settled at admission for a run that labels speakers:
# a positive integer, or null for automatic. Absent when the run labels none.
MAX_SPEAKERS_KEY = "max_speakers"


class StepInputFacts(TypedDict):
    """What a run settled about one step's submitted files."""

    live_transcript_id: NotRequired[UUID]
    # The step's files are the ordered parts of one recording.
    single_recording: NotRequired[bool]


_STEP_INPUT_FACTS = TypeAdapter(dict[UUID, StepInputFacts])


def _read_step_input_facts(
    input_payload_json: FlowPersistedJsonObject | None,
) -> dict[UUID, StepInputFacts]:
    values = (input_payload_json or {}).get(STEP_INPUTS_KEY)
    if not isinstance(values, dict):
        return {}
    return _STEP_INPUT_FACTS.validate_python(values)


_REMOVED_TOP_LEVEL_RUNTIME_FILE_IDS_KEY = "file_ids"
_PERSISTED_RUNTIME_INPUT_KEYS = frozenset(
    {
        EXPECTED_FLOW_VERSION_KEY,
        FLOW_INPUT_TRANSCRIPTION_KEY,
        MAX_SPEAKERS_KEY,
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


def read_live_transcript_ids(
    input_payload_json: FlowPersistedJsonObject | None,
) -> dict[UUID, UUID]:
    return {
        step_id: facts["live_transcript_id"]
        for step_id, facts in _read_step_input_facts(input_payload_json).items()
        if "live_transcript_id" in facts
    }


def read_single_recording_steps(
    input_payload_json: FlowPersistedJsonObject | None,
) -> frozenset[UUID]:
    return frozenset(
        step_id
        for step_id, facts in _read_step_input_facts(input_payload_json).items()
        if facts.get("single_recording")
    )


def read_max_speakers_decision(
    input_payload_json: FlowPersistedJsonObject | None,
) -> int | None | NotProvided:
    """The speaker-count bound the run settled, None for automatic, or
    NOT_PROVIDED when the run settled none because it labels no speakers."""
    payload = input_payload_json or {}
    if MAX_SPEAKERS_KEY not in payload:
        return NOT_PROVIDED
    return read_max_speakers(payload)


def read_max_speakers(input_payload_json: FlowPersistedJsonObject | None) -> int | None:
    """The upper bound on speakers the transcription service may find, if any."""
    bound = (input_payload_json or {}).get(MAX_SPEAKERS_KEY)
    if isinstance(bound, bool) or not isinstance(bound, int) or bound < 1:
        return None
    return bound


def build_initial_run_input_envelope(
    *,
    normalized_inline_payload: FlowPersistedJsonObject | None,
    flow_version: int,
    speaker_labels: bool | None = None,
    max_speakers: int | None | NotProvided = NOT_PROVIDED,
    live_transcript_ids: dict[UUID, UUID] | None = None,
    single_recording_steps: frozenset[UUID] = frozenset(),
) -> FlowPersistedJsonObject:
    payload = dict(normalized_inline_payload or {})
    payload[EXPECTED_FLOW_VERSION_KEY] = flow_version
    if speaker_labels is not None:
        payload[SPEAKER_LABELS_KEY] = speaker_labels
    if not isinstance(max_speakers, NotProvided):
        payload[MAX_SPEAKERS_KEY] = max_speakers
    step_facts: dict[str, dict[str, object]] = {}
    for step_id, transcript_id in (live_transcript_ids or {}).items():
        step_facts.setdefault(str(step_id), {})["live_transcript_id"] = str(
            transcript_id
        )
    for step_id in single_recording_steps:
        step_facts.setdefault(str(step_id), {})["single_recording"] = True
    if step_facts:
        payload[STEP_INPUTS_KEY] = step_facts
    return payload
