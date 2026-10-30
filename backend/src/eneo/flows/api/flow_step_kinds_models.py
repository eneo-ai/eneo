from __future__ import annotations

from typing import Any, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.config import JsonDict

from eneo.flows.application.flow_step_kinds import (
    StepKindAnswer,
    StepKindOption,
    StepKindPlace,
)
from eneo.flows.domain.flow_step_validation import FlowGraphIssueCode
from eneo.flows.domain.step_kinds import FlowStepKind
from eneo.flows.enums import (
    FlowInputSource,
    FlowInputType,
    FlowOutputMode,
    FlowOutputType,
)
from eneo.flows.flow_review_policy import FlowStepReviewPolicy

_FLOW_ID = "00000000-0000-0000-0000-000000000001"
_FIRST_STEP_ID = "00000000-0000-0000-0000-000000000101"
_SECOND_STEP_ID = "00000000-0000-0000-0000-000000000102"

_AI_AFTER_FIRST: JsonDict = {
    "input_source": "previous_step",
    "input_type": "text",
    "input_contract": None,
    "output_mode": "pass_through",
    "output_type": "text",
    "output_contract": None,
    "input_bindings": None,
    "input_config": None,
    "output_config": None,
    "review_policy": None,
}
_SEND_HTTP_AFTER_FIRST: JsonDict = {
    **_AI_AFTER_FIRST,
    "output_mode": "http_post",
    "output_config": {
        "url": "",
        "auth": {"mode": "none"},
        "timeout_seconds": 30,
        "body": {"mode": "auto"},
        "custom_headers": [],
        "response_format": None,
    },
}
_TRANSCRIBE_FIRST: JsonDict = {
    "input_source": "flow_input",
    "input_type": "audio",
    "input_contract": None,
    "output_mode": "transcribe_only",
    "output_type": "text",
    "output_contract": None,
    "input_bindings": None,
    "input_config": {
        "runtime_input": {"enabled": True, "required": True, "input_format": "audio"}
    },
    "output_config": None,
    "review_policy": None,
}

_TERMINAL = FlowGraphIssueCode.FLOW_HTTP_POST_OUTPUT_MUST_BE_TERMINAL.value
_REFUSAL_EXAMPLE: JsonDict = {
    "code": _TERMINAL,
    "issue_code": _TERMINAL,
    "step_order": 2,
    "step_id": None,
    "message": "Step 2: output_mode 'http_post' is only supported on the last step.",
}
_HAND_OVER_EXAMPLE: JsonDict = {
    "step_id": _FIRST_STEP_ID,
    "changes": {"input_source": "previous_step"},
}
_AI_OPTION_EXAMPLE: JsonDict = {
    "kind": "ai",
    "allowed": True,
    "refusals": [],
    "configuration": _AI_AFTER_FIRST,
    "step_edits": [],
    "turns_on_transcription": False,
}
_STEP_PLACE_EXAMPLE: JsonDict = {
    "position": 2,
    "step_id": _SECOND_STEP_ID,
    "options": [_AI_OPTION_EXAMPLE],
}

FLOW_STEP_KINDS_EXAMPLE: JsonDict = {
    "flow_id": _FLOW_ID,
    "draft_revision": 4,
    "insertions": [
        {
            "position": 1,
            "step_id": None,
            "options": [
                {
                    "kind": "transcribe",
                    "allowed": True,
                    "refusals": [],
                    "configuration": _TRANSCRIBE_FIRST,
                    "step_edits": [_HAND_OVER_EXAMPLE],
                    "turns_on_transcription": True,
                }
            ],
        },
        {
            "position": 2,
            "step_id": None,
            "options": [
                {
                    "kind": "send_http",
                    "allowed": False,
                    "refusals": [_REFUSAL_EXAMPLE],
                    "configuration": _SEND_HTTP_AFTER_FIRST,
                    "step_edits": [],
                    "turns_on_transcription": False,
                }
            ],
        },
    ],
    "steps": [_STEP_PLACE_EXAMPLE],
}


class FlowStepKindRefusalPublic(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": _REFUSAL_EXAMPLE})

    code: str | None = Field(
        description=(
            "The `code` of the error the draft save refuses the change with, "
            "as `PATCH /flows/{id}/editor/` returns it."
        ),
        examples=[FlowGraphIssueCode.TYPED_IO_INCOMPATIBLE_TYPE_CHAIN.value],
    )
    issue_code: FlowGraphIssueCode | None = Field(
        description=(
            "The step rule that refuses the change, the `context.issue_code` of "
            "the save's error; null for a refusal outside the step rules (a "
            "published flow, a read that would lose its step, a step name)."
        ),
        examples=[_TERMINAL],
    )
    step_order: int | None = Field(
        description=(
            "The step the refusal is about, numbered as after the change; null "
            "when it is about the flow as a whole."
        ),
        examples=[2],
    )
    step_id: UUID | None = Field(
        description=(
            "The saved step the refusal is about; null for the new step and "
            "for the flow as a whole."
        ),
        examples=[_SECOND_STEP_ID],
    )
    message: str = Field(
        description="The save's message, in English.",
        examples=[
            "Step 2: output_mode 'http_post' is only supported on the last step."
        ],
    )


class FlowStepKindConfigurationPublic(BaseModel):
    """A kind's starting configuration at its place. It is valid as
    `new_steps[].configuration` and as `step_edits[].changes` of
    `PATCH /flows/{id}/editor/`."""

    model_config = ConfigDict(json_schema_extra={"example": _AI_AFTER_FIRST})

    input_source: FlowInputSource = Field(
        description=(
            "`flow_input` at step 1 for a kind that reads the run's input, "
            "else the source the kind needs."
        ),
        examples=["previous_step"],
    )
    input_type: FlowInputType = Field(
        description=(
            "The type the kind reads; after a step, one that step's output can give."
        ),
        examples=["text"],
    )
    input_contract: dict[str, Any] | None = Field(
        description="Always null: a kind starts without an input contract.",
        examples=[None],
    )
    output_mode: FlowOutputMode = Field(
        description="What the step does with its input.", examples=["pass_through"]
    )
    output_type: FlowOutputType = Field(
        description="What the step gives the step after it.", examples=["text"]
    )
    output_contract: dict[str, Any] | None = Field(
        description="Always null: a kind starts without an output contract.",
        examples=[None],
    )
    input_bindings: dict[str, Any] | None = Field(
        description="Always null: a kind starts without underlag.", examples=[None]
    )
    input_config: dict[str, Any] | None = Field(
        description=(
            "Uploads for `transcribe`, the HTTP request for `fetch_http` (its "
            "`url` empty for the author to enter), otherwise null. A `tool` "
            "kind's tool is the author's to choose and is not included."
        ),
        examples=[None],
    )
    output_config: dict[str, Any] | None = Field(
        description=(
            "The speaker mapping for `speakers`, the HTTP request for "
            "`send_http` (its `url` empty for the author to enter), otherwise "
            "null."
        ),
        examples=[None],
    )
    review_policy: FlowStepReviewPolicy | None = Field(
        description=(
            '`{"mode": "edit"}` for `review` and `speakers`, which a person '
            "confirms; otherwise null."
        ),
        examples=[None],
    )


class FlowStepKindStepEditPublic(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": _HAND_OVER_EXAMPLE})

    step_id: UUID = Field(
        description="The saved step the change also edits.",
        examples=[_FIRST_STEP_ID],
    )
    changes: dict[str, Any] = Field(
        description=(
            "Its sparse changes, as `step_edits[].changes` of "
            "`PATCH /flows/{id}/editor/`."
        ),
        examples=[{"input_source": "previous_step"}],
    )


class FlowStepKindOptionPublic(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": _AI_OPTION_EXAMPLE})

    kind: FlowStepKind = Field(
        description=(
            "What the step does: `ai` (a model writes text), `structured` (a "
            "model writes JSON), `compose` (text put together without a "
            "model), `document` (text rendered as a Word document; `pdf` is "
            "the other output type it takes), `template` (a Word template "
            "filled in), `transcribe` (an uploaded recording transcribed), "
            "`speakers` (the speakers of the transcript before it named, "
            "confirmed by a person), `review` (a person reviews and may edit "
            "what the step before it gave), `fetch_http` (text fetched with an "
            "HTTP GET), `tool` (an MCP tool's answer), `send_http` (the result "
            "sent with an HTTP POST)."
        ),
        examples=["ai"],
    )
    allowed: bool = Field(
        description=(
            "Whether the draft save accepts the change: true exactly when "
            "`refusals` is empty."
        ),
        examples=[True],
    )
    refusals: list[FlowStepKindRefusalPublic] = Field(
        description=(
            "Every refusal of the save's step rules, in the order the save "
            "meets them; the save's error is the first. Empty when allowed."
        ),
    )
    configuration: FlowStepKindConfigurationPublic = Field(
        description=(
            "The configuration the kind starts with here: of the new step, or "
            "the saved step's new configuration (its name and assistant stay)."
        ),
    )
    step_edits: list[FlowStepKindStepEditPublic] = Field(
        description=(
            "Saved steps the change edits too, as `step_edits` of the editor "
            "update: a step added first takes the run's input over from the "
            "step that was first, which then reads the new step."
        ),
    )
    turns_on_transcription: bool = Field(
        description=(
            "Whether the change also sets `metadata_json.wizard."
            "transcription_enabled` to true: a step that takes audio needs it."
        ),
        examples=[False],
    )

    @classmethod
    def from_option(cls, option: StepKindOption) -> Self:
        change = option.change
        return cls.model_validate(
            {
                "kind": option.kind,
                "allowed": option.allowed,
                "refusals": [
                    {
                        "code": refusal.code,
                        "issue_code": refusal.issue_code,
                        "step_order": refusal.step_order,
                        "step_id": refusal.step_id,
                        "message": refusal.message,
                    }
                    for refusal in option.refusals
                ],
                "configuration": change.configuration,
                "step_edits": [
                    {"step_id": step_id, "changes": changes}
                    for step_id, changes in change.step_edits
                ],
                "turns_on_transcription": change.turns_on_transcription,
            }
        )


class FlowStepKindPlacePublic(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": _STEP_PLACE_EXAMPLE})

    position: int = Field(
        ge=1,
        description=(
            "For an insertion, the place the new step takes (1 is first; the "
            "steps from there on move one place down); for a saved step, its "
            "`step_order`."
        ),
        examples=[2],
    )
    step_id: UUID | None = Field(
        description="The saved step turned to each kind; null for an insertion.",
        examples=[_SECOND_STEP_ID],
    )
    options: list[FlowStepKindOptionPublic] = Field(
        description="Every kind, in the same order at every place.",
    )

    @classmethod
    def from_place(cls, place: StepKindPlace) -> Self:
        return cls(
            position=place.position,
            step_id=place.step_id,
            options=[FlowStepKindOptionPublic.from_option(o) for o in place.options],
        )


class FlowStepKindsPublic(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": FLOW_STEP_KINDS_EXAMPLE})

    flow_id: UUID = Field(description="The flow.", examples=[_FLOW_ID])
    draft_revision: int = Field(
        description=(
            "The draft revision the answer judges; send it as "
            "`expected_revision` with a change it allows."
        ),
        examples=[4],
    )
    insertions: list[FlowStepKindPlacePublic] = Field(
        description=(
            "The place a step can be added that `position` names; empty "
            "when it names none."
        ),
    )
    steps: list[FlowStepKindPlacePublic] = Field(
        description=(
            "The saved step `step_id` names, turned to each kind where it "
            "stands; empty when it names none."
        ),
    )

    @classmethod
    def from_answer(
        cls, *, flow_id: UUID, draft_revision: int, answer: StepKindAnswer
    ) -> Self:
        return cls(
            flow_id=flow_id,
            draft_revision=draft_revision,
            insertions=[
                FlowStepKindPlacePublic.from_place(p) for p in answer.insertions
            ],
            steps=[FlowStepKindPlacePublic.from_place(p) for p in answer.steps],
        )
