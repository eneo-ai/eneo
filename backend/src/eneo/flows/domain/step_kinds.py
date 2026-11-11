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

import json
from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Final, Literal, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from eneo.flows.domain.contract_from_example import contract_from_example
from eneo.flows.domain.flow import FlowPersistedJsonObject, FlowStep
from eneo.flows.enums import (
    FlowInputSource,
    FlowInputType,
    FlowOutputMode,
    FlowOutputType,
)
from eneo.flows.flow_capability_manifest import is_chain_compatible
from eneo.flows.flow_review_policy import (
    FlowStepReviewPolicy,
    dump_flow_step_review_policy,
)
from eneo.main.exceptions import BadRequestException


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


# What each kind does, in one line.
STEP_KIND_DESCRIPTIONS: Final[Mapping[FlowStepKind, str]] = {
    FlowStepKind.AI: "a model writes text",
    FlowStepKind.STRUCTURED: "a model writes JSON",
    FlowStepKind.COMPOSE: "text put together without a model",
    FlowStepKind.DOCUMENT: (
        "text rendered as a Word document; `pdf` is the other output type it takes"
    ),
    FlowStepKind.TEMPLATE: "a Word template filled in",
    FlowStepKind.TRANSCRIBE: "an uploaded recording transcribed",
    FlowStepKind.SPEAKERS: (
        "the speakers of the transcript before it named, confirmed by a person"
    ),
    FlowStepKind.REVIEW: ("a person reviews and may edit what the step before it gave"),
    FlowStepKind.FETCH_HTTP: "text fetched with an HTTP GET",
    FlowStepKind.TOOL: "an MCP tool's answer",
    FlowStepKind.SEND_HTTP: "the result sent with an HTTP POST",
}


class StepKindUpload(BaseModel):
    """An upload the run brings to the first step."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    format: Literal["document", "file"] = Field(
        description="document: a text document read as text; file: any file."
    )
    required: bool = Field(
        default=True,
        description=(
            "false when the run may go without it (a text field of the run "
            "form then carries the material)."
        ),
    )


class StepKindValues(BaseModel):
    """What a new step of a kind needs. Each kind takes only its own values;
    a value it does not use is refused, never ignored."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    instruction: str | None = Field(
        default=None, description="What the step's model is told to do."
    )
    example: str | dict[str, Any] | None = Field(
        default=None,
        description=(
            "One example of the result as a JSON object (or its text); its keys "
            "become the required fields of the step's output contract, typed "
            "by their values."
        ),
    )
    input_bindings: dict[str, Any] | None = Field(
        default=None,
        description=(
            "What the step reads, shaped as update_step describes it; the step "
            "then reads it as text. Left out, the step reads the step before "
            "it (step 1: the run's input)."
        ),
    )
    review: FlowStepReviewPolicy | None = Field(
        default=None,
        description="A person reviews the step's result before the run goes on.",
    )
    upload: StepKindUpload | None = Field(
        default=None,
        description="Step 1 only: the run brings an upload the step reads.",
    )
    format: Literal["docx", "pdf"] | None = Field(
        default=None,
        description="The file the document step gives; docx when left out.",
    )
    template_asset_id: UUID | None = Field(
        default=None,
        description=(
            "A Word template the flow already has (read_flow shows a Word "
            "step's template); left out, the person uploads one in the step."
        ),
    )
    bindings: dict[str, str] | None = Field(
        default=None,
        description="Per field of the template, the one reference it reads.",
    )
    participants_field: str | None = Field(
        default=None,
        description=(
            "A run form field (list, multiselect or text) naming who took part."
        ),
    )
    speaker_count_field: str | None = Field(
        default=None,
        description="A run form number field with how many speak.",
    )
    infer_names: bool | None = Field(
        default=None,
        description="Let the model propose names and roles from the conversation.",
    )
    url: str = Field(default="", description="The HTTPS address.")
    http: dict[str, Any] | None = Field(
        default=None,
        description=(
            "The rest of the request besides url: auth (its mode, with the "
            "credential left out), timeout_seconds, body, custom_headers, "
            "response_format."
        ),
    )
    tool: dict[str, Any] | None = Field(
        default=None,
        description="The tool: mcp_server_id, tool_id and arguments.",
    )


# The values each kind takes, those it cannot do without first.
STEP_KIND_VALUES: Final[Mapping[FlowStepKind, tuple[str, ...]]] = {
    FlowStepKind.AI: ("instruction", "input_bindings", "review", "upload"),
    FlowStepKind.STRUCTURED: (
        "instruction",
        "example",
        "input_bindings",
        "review",
        "upload",
    ),
    FlowStepKind.COMPOSE: ("input_bindings",),
    FlowStepKind.DOCUMENT: ("input_bindings", "format"),
    FlowStepKind.TEMPLATE: ("template_asset_id", "bindings"),
    FlowStepKind.TRANSCRIBE: (),
    FlowStepKind.SPEAKERS: (
        "participants_field",
        "speaker_count_field",
        "infer_names",
    ),
    FlowStepKind.REVIEW: ("review",),
    FlowStepKind.FETCH_HTTP: ("url", "http"),
    FlowStepKind.TOOL: ("tool",),
    FlowStepKind.SEND_HTTP: ("url", "http", "instruction"),
}
STEP_KIND_REQUIRED_VALUES: Final[Mapping[FlowStepKind, tuple[str, ...]]] = {
    FlowStepKind.AI: ("instruction",),
    FlowStepKind.STRUCTURED: ("instruction", "example"),
    FlowStepKind.FETCH_HTTP: ("url",),
    FlowStepKind.TOOL: ("tool",),
    FlowStepKind.SEND_HTTP: ("url",),
}


def check_step_kind_values(kind: FlowStepKind, values: StepKindValues) -> None:
    """Refuse values ``kind`` does not use and values it cannot do without."""

    takes = STEP_KIND_VALUES[kind]
    unused = sorted(
        name
        for name in values.model_fields_set
        if name not in takes and getattr(values, name) is not None
    )
    missing = [
        name
        for name in STEP_KIND_REQUIRED_VALUES.get(kind, ())
        if getattr(values, name) in (None, "")
    ]
    if not unused and not missing:
        return
    message = f"A {kind.value} step takes " + (
        ", ".join(takes) + "." if takes else "no values."
    )
    if unused:
        message += f" It does not use {', '.join(unused)}: leave it out."
    if missing:
        message += f" It needs {', '.join(missing)}."
    raise BadRequestException(message, code="flow_step_kind_values_invalid")


def step_kind_configuration(
    kind: FlowStepKind,
    *,
    previous_output_type: FlowOutputType | None,
    values: StepKindValues = StepKindValues(),
) -> dict[str, object]:
    """The configuration a step of ``kind`` starts with, after a step that
    gives ``previous_output_type`` (None at step 1), with the ``values`` the
    kind takes laid on it. Every configuration column is named, so the same
    configuration replaces a saved step's. An ``example`` that gives no
    contract raises ``ExampleProblemError``."""

    configuration = _kind_configuration(
        kind, previous_output_type=previous_output_type, values=values
    )
    takes = STEP_KIND_VALUES[kind]

    def given(name: str) -> Any:
        return getattr(values, name) if name in takes else None

    if (bindings := given("input_bindings")) is not None:
        # Named reads are read as text, whatever the step before it gives.
        configuration["input_bindings"] = bindings
        configuration["input_type"] = FlowInputType.TEXT
    if (review := given("review")) is not None:
        configuration["review_policy"] = dump_flow_step_review_policy(review)
    if (upload := given("upload")) is not None:
        configuration["input_type"] = FlowInputType(upload.format)
        configuration["input_config"] = {
            "runtime_input": {
                "enabled": True,
                "required": upload.required,
                "input_format": upload.format,
            }
        }
    if (example := given("example")) is not None:
        text = example if isinstance(example, str) else json.dumps(example)
        configuration["output_contract"] = contract_from_example(text).contract
    if given("format") == "pdf":
        configuration["output_type"] = FlowOutputType.PDF
    template_asset_id, template_bindings = (
        given("template_asset_id"),
        given("bindings"),
    )
    if template_asset_id is not None or template_bindings is not None:
        configuration["output_config"] = {
            **(
                {"template_asset_id": str(template_asset_id)}
                if template_asset_id is not None
                else {}
            ),
            "bindings": template_bindings or {},
        }
    if kind is FlowStepKind.SPEAKERS:
        configuration["output_config"] = {
            "speaker_mapping": {
                "participants_field": values.participants_field,
                "speaker_count_field": values.speaker_count_field,
                "infer_names": bool(values.infer_names),
            }
        }
    if (http := given("http")) is not None:
        key = "input_config" if kind is FlowStepKind.FETCH_HTTP else "output_config"
        request = cast(FlowPersistedJsonObject, configuration[key])
        configuration[key] = {**request, **http, "url": values.url}
    return configuration


def _kind_configuration(
    kind: FlowStepKind,
    *,
    previous_output_type: FlowOutputType | None,
    values: StepKindValues,
) -> dict[str, object]:
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
