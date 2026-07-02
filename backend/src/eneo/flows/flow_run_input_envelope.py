from __future__ import annotations

from dataclasses import dataclass
from typing import Self

from eneo.flows.domain.flow import FlowPersistedJsonObject, RerunStepInputOverride

EXPECTED_FLOW_VERSION_KEY = "expected_flow_version"
STEP_INPUTS_KEY = "step_inputs"
FLOW_INPUT_TRANSCRIPTION_KEY = "transkribering"

_REMOVED_TOP_LEVEL_RUNTIME_FILE_IDS_KEY = "file_ids"
_PERSISTED_RUNTIME_INPUT_KEYS = frozenset(
    {
        EXPECTED_FLOW_VERSION_KEY,
        FLOW_INPUT_TRANSCRIPTION_KEY,
    }
)
FLOW_RUN_RESERVED_INPUT_PAYLOAD_KEYS = _PERSISTED_RUNTIME_INPUT_KEYS | frozenset(
    {STEP_INPUTS_KEY, _REMOVED_TOP_LEVEL_RUNTIME_FILE_IDS_KEY}
)
RERUN_PRESERVED_INPUT_PAYLOAD_KEYS = _PERSISTED_RUNTIME_INPUT_KEYS


@dataclass(frozen=True, slots=True)
class RerunInputOverride:
    inline_payload_json: FlowPersistedJsonObject | None = None
    root_step_input: RerunStepInputOverride | None = None


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
    def transcription(cls, *, transcript: str) -> Self:
        return cls._from_merge_payload({FLOW_INPUT_TRANSCRIPTION_KEY: transcript})

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


def build_initial_run_input_envelope(
    *,
    normalized_inline_payload: FlowPersistedJsonObject | None,
    flow_version: int,
) -> FlowPersistedJsonObject:
    payload = dict(normalized_inline_payload or {})
    payload[EXPECTED_FLOW_VERSION_KEY] = flow_version
    return payload


def build_rerun_execution_input_envelope(
    *,
    current: FlowPersistedJsonObject | None,
    override: RerunInputOverride,
) -> FlowPersistedJsonObject:
    current_payload = dict(current or {})
    if override.inline_payload_json is None:
        payload = {
            key: value
            for key, value in current_payload.items()
            if key not in FLOW_RUN_RESERVED_INPUT_PAYLOAD_KEYS
            or key in RERUN_PRESERVED_INPUT_PAYLOAD_KEYS
        }
    else:
        payload = {
            key: value
            for key, value in current_payload.items()
            if key in RERUN_PRESERVED_INPUT_PAYLOAD_KEYS
        }
        payload.update(override.inline_payload_json)

    return payload
