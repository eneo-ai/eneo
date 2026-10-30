"""The kinds of step an author adds to a flow, and the configuration each
starts with at its place.

A kind is a starting configuration, not a stored property: a saved step has
only its configuration, and the step rules judge that. A kind's
configuration depends on its place: a step that reads the run's input does so
only as step 1, and a later one reads the step before it with a type that step
can give. Whether a kind may stand at a place is never decided here; the save's
own rules decide it (see ``flows.application.flow_step_kinds``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from eneo.flows.domain.flow import FlowPersistedJsonObject, FlowStep
from eneo.flows.enums import (
    FlowInputSource,
    FlowInputType,
    FlowOutputMode,
    FlowOutputType,
)
from eneo.flows.flow_capability_manifest import is_chain_compatible


class FlowStepKind(StrEnum):
    """What a new step does, as the editor's add dialog offers it."""

    AI = "ai"
    STRUCTURED = "structured"
    COMPOSE = "compose"
    DOCUMENT = "document"
    TEMPLATE = "template"
    TRANSCRIBE = "transcribe"
    SPEAKERS = "speakers"
    REVIEW = "review"
    FETCH_HTTP = "fetch_http"
    TOOL = "tool"
    SEND_HTTP = "send_http"


# The input types whose content is uploaded files; only step 1 reads them.
FILE_INPUT_TYPES: Final = frozenset(
    {FlowInputType.DOCUMENT, FlowInputType.FILE, FlowInputType.AUDIO}
)


@dataclass(frozen=True, slots=True)
class StepKindValues:
    """What the author enters for a kind: the URL of an HTTP kind, the tool
    (``mcp_server_id``, ``tool_id``, ``arguments``) of a tool kind."""

    url: str = ""
    tool: Mapping[str, object] | None = None


def step_kind_configuration(
    kind: FlowStepKind,
    *,
    previous_output_type: FlowOutputType | None,
    values: StepKindValues = StepKindValues(),
) -> dict[str, object]:
    """The configuration a step of ``kind`` starts with, after a step that
    gives ``previous_output_type`` (None at step 1). Every configuration
    column is named, so the same configuration replaces a saved step's."""

    # The run's input at step 1, else the step before with a type it gives.
    source, read_type = (
        (FlowInputSource.FLOW_INPUT, FlowInputType.TEXT)
        if previous_output_type is None
        else (
            FlowInputSource.PREVIOUS_STEP,
            FlowInputType.JSON
            if previous_output_type is FlowOutputType.JSON
            else FlowInputType.TEXT,
        )
    )
    match kind:
        case FlowStepKind.AI | FlowStepKind.STRUCTURED:
            return _configuration(
                input_source=source,
                input_type=read_type,
                output_mode=FlowOutputMode.PASS_THROUGH,
                output_type=(
                    FlowOutputType.JSON
                    if kind is FlowStepKind.STRUCTURED
                    else FlowOutputType.TEXT
                ),
            )
        case FlowStepKind.COMPOSE:
            return _configuration(
                input_source=source,
                input_type=FlowInputType.TEXT,
                output_mode=FlowOutputMode.COMPOSE_TEXT,
                output_type=FlowOutputType.TEXT,
            )
        case FlowStepKind.DOCUMENT:
            return _configuration(
                input_source=source,
                input_type=FlowInputType.TEXT,
                output_mode=FlowOutputMode.RENDER_VERBATIM,
                output_type=FlowOutputType.DOCX,
            )
        case FlowStepKind.TEMPLATE:
            return _configuration(
                input_source=source,
                input_type=FlowInputType.TEXT,
                output_mode=FlowOutputMode.TEMPLATE_FILL,
                output_type=FlowOutputType.DOCX,
            )
        case FlowStepKind.TRANSCRIBE:
            return _configuration(
                input_source=FlowInputSource.FLOW_INPUT,
                input_type=FlowInputType.AUDIO,
                input_config={
                    "runtime_input": {
                        "enabled": True,
                        "required": True,
                        "input_format": "audio",
                    }
                },
                output_mode=FlowOutputMode.TRANSCRIBE_ONLY,
                output_type=FlowOutputType.TEXT,
            )
        case FlowStepKind.SPEAKERS:
            # The mapping reads the transcript of the step before it and is
            # always confirmed by a person.
            return _configuration(
                input_source=FlowInputSource.PREVIOUS_STEP,
                input_type=FlowInputType.TEXT,
                output_mode=FlowOutputMode.SPEAKER_MAPPING,
                output_type=FlowOutputType.JSON,
                output_config={
                    "speaker_mapping": {
                        "participants_field": None,
                        "speaker_count_field": None,
                        "infer_names": False,
                    }
                },
                review_policy={"mode": "edit"},
            )
        case FlowStepKind.REVIEW:
            # A person reviews and may edit what the step before it gave.
            json = previous_output_type is FlowOutputType.JSON
            return _configuration(
                input_source=FlowInputSource.PREVIOUS_STEP,
                input_type=FlowInputType.JSON if json else FlowInputType.TEXT,
                output_mode=(
                    FlowOutputMode.COPY_INPUT if json else FlowOutputMode.COMPOSE_TEXT
                ),
                output_type=FlowOutputType.JSON if json else FlowOutputType.TEXT,
                review_policy={"mode": "edit"},
            )
        case FlowStepKind.FETCH_HTTP:
            return _configuration(
                input_source=FlowInputSource.HTTP_GET,
                input_type=FlowInputType.TEXT,
                input_config=_http_config(values.url, direction="input"),
                output_mode=FlowOutputMode.COMPOSE_TEXT,
                output_type=FlowOutputType.TEXT,
            )
        case FlowStepKind.TOOL:
            return _configuration(
                input_source=FlowInputSource.TOOL,
                input_type=FlowInputType.TEXT,
                input_config=(
                    {"tool": dict(values.tool)} if values.tool is not None else None
                ),
                output_mode=FlowOutputMode.COMPOSE_TEXT,
                output_type=FlowOutputType.TEXT,
            )
        case FlowStepKind.SEND_HTTP:
            return _configuration(
                input_source=source,
                input_type=read_type,
                output_mode=FlowOutputMode.HTTP_POST,
                output_type=FlowOutputType.TEXT,
                output_config=_http_config(values.url, direction="output"),
            )


def run_input_hand_over(
    first: FlowStep, *, new_output_type: FlowOutputType
) -> dict[str, object] | None:
    """The change that turns the first step, when it reads the run's input,
    to reading a step put before it that gives ``new_output_type``; None when
    it does not read the run's input. A type that step cannot read becomes
    the one it can, except an upload type: uploads are the first step's, so
    the step keeps it and the rules judge it."""

    if first.input_source != FlowInputSource.FLOW_INPUT:
        return None
    changes: dict[str, object] = {"input_source": FlowInputSource.PREVIOUS_STEP}
    input_type = FlowInputType(first.input_type)
    if input_type not in FILE_INPUT_TYPES and not is_chain_compatible(
        output_type=new_output_type, input_type=input_type
    ):
        changes["input_type"] = (
            FlowInputType.JSON
            if new_output_type is FlowOutputType.JSON
            else FlowInputType.TEXT
        )
    return changes


def _http_config(url: str, *, direction: str) -> FlowPersistedJsonObject:
    return {
        "url": url,
        "auth": {"mode": "none"},
        "timeout_seconds": 30,
        "body": {"mode": "auto" if direction == "output" else "none"},
        "custom_headers": [],
        "response_format": "text" if direction == "input" else None,
    }


def _configuration(
    *,
    input_source: FlowInputSource,
    input_type: FlowInputType,
    output_mode: FlowOutputMode,
    output_type: FlowOutputType,
    input_config: FlowPersistedJsonObject | None = None,
    output_config: FlowPersistedJsonObject | None = None,
    review_policy: FlowPersistedJsonObject | None = None,
) -> dict[str, object]:
    return {
        "input_source": input_source,
        "input_type": input_type,
        "input_contract": None,
        "output_mode": output_mode,
        "output_type": output_type,
        "output_contract": None,
        "input_bindings": None,
        "input_config": input_config,
        "output_config": output_config,
        "review_policy": review_policy,
    }
