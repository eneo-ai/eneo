from __future__ import annotations

from typing import Any, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.config import JsonDict

from eneo.flows.domain.flow_suggestions import (
    FlowSuggestion,
    FlowSuggestionCode,
    FlowSuggestionFixKind,
    FlowSuggestionImpactBasis,
    FlowSuggestionLevel,
)

_FLOW_ID = "00000000-0000-0000-0000-000000000001"
_FIRST_STEP_ID = "00000000-0000-0000-0000-000000000101"
_SECOND_STEP_ID = "00000000-0000-0000-0000-000000000102"

_DUPLICATE_READ_EXAMPLE: JsonDict = {
    "code": FlowSuggestionCode.DUPLICATE_READ.value,
    "fingerprint": "9b2d3f1a" * 8,
    "steps": [_SECOND_STEP_ID, _FIRST_STEP_ID],
    "params": {
        "producer_step_order": 1,
        "producer_step_id": _FIRST_STEP_ID,
        "contained": False,
        "redundant_reads": [1],
        "reads": [
            {"channel": "input", "site": "input_source", "selector": []},
            {
                "channel": "prompt",
                "site": "assistant_prompt:step_1.output.text",
                "selector": [],
            },
        ],
    },
    "message": (
        "Step 2 reads step 1 twice, as its input (previous_step) and in its "
        "prompt ({{ step_1.output.text }}), so its model receives the same text "
        "twice on every run."
    ),
    "impact": {"basis": "definition", "level": "high"},
    "fix": {"kind": "patch"},
}

FLOW_SUGGESTIONS_EXAMPLE: JsonDict = {
    "flow_id": _FLOW_ID,
    "draft_revision": 4,
    "items": [_DUPLICATE_READ_EXAMPLE],
}


class FlowSuggestionImpactPublic(BaseModel):
    basis: FlowSuggestionImpactBasis = Field(
        description=(
            "What the impact is judged from: `definition`, the draft alone, "
            "which proves the duplication but not its size."
        ),
        examples=["definition"],
    )
    level: FlowSuggestionLevel = Field(
        description=(
            "How much the suggestion is worth acting on: `high` when a whole "
            "result reaches the model twice, `medium` when it does through "
            "`all_previous_steps`, `low` when one read is contained in another."
        ),
        examples=["high"],
    )


class FlowSuggestionFixPublic(BaseModel):
    kind: FlowSuggestionFixKind = Field(
        description=(
            "How the suggestion is acted on: `patch`, a mechanical edit the "
            "core can make; `assisted`, a change that needs judgement, for the "
            "authoring chat to propose; `advice`, explained only."
        ),
        examples=["patch"],
    )


class FlowSuggestionPublic(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": _DUPLICATE_READ_EXAMPLE})

    code: FlowSuggestionCode = Field(
        description=(
            "What the suggestion is about. `duplicate_read`: the same earlier "
            "step reaches the step's model twice, through its input and its "
            "prompt or twice in one of them."
        ),
        examples=["duplicate_read"],
    )
    fingerprint: str = Field(
        description=(
            "The suggestion's identity: a hash of its code, the steps it is "
            "about and the reads that triggered it. The same across edits that "
            "do not touch them; gone when the premise is."
        ),
        examples=["9b2d3f1a" * 8],
    )
    steps: list[UUID] = Field(
        description=(
            "The steps the suggestion is about; the first is the step it is "
            "shown on, the second the step that is read twice."
        ),
    )
    params: dict[str, Any] = Field(
        description=(
            "Typed per code, for a client to render its own text from. For "
            "`duplicate_read`: `producer_step_order`, `producer_step_id`, "
            "`contained` (one read is a field of what the other already "
            "carries), `redundant_reads` (the indexes in `reads` of the reads "
            "the others already carry, never a whole read next to a narrower "
            "one) and `reads`, each with `channel` (`input` or `prompt`), "
            "`site` (`input_source`, `input_bindings.question`, "
            "`input_bindings.source_refs[N]`, `assistant_prompt:<expression>`) "
            'and `selector` (empty for the whole text, `["structured", ...]` '
            "for a structured value or a path in it)."
        ),
    )
    message: str = Field(
        description="One English sentence saying what was found, for API and chat consumers.",
    )
    impact: FlowSuggestionImpactPublic
    fix: FlowSuggestionFixPublic

    @classmethod
    def from_suggestion(cls, suggestion: FlowSuggestion) -> Self:
        return cls(
            code=suggestion.code,
            fingerprint=suggestion.fingerprint,
            steps=list(suggestion.steps),
            params=dict(suggestion.params),
            message=suggestion.message,
            impact=FlowSuggestionImpactPublic(
                basis=suggestion.impact.basis, level=suggestion.impact.level
            ),
            fix=FlowSuggestionFixPublic(kind=suggestion.fix.kind),
        )


class FlowSuggestionsPublic(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": FLOW_SUGGESTIONS_EXAMPLE})

    flow_id: UUID = Field(description="The flow.", examples=[_FLOW_ID])
    draft_revision: int = Field(
        description="The draft revision the suggestions judge.", examples=[4]
    )
    items: list[FlowSuggestionPublic] = Field(
        description=(
            "The suggestions, by impact level (high, medium, low), then step "
            "order; at most 50. Empty when the draft gives none."
        ),
    )

    @classmethod
    def from_suggestions(
        cls,
        *,
        flow_id: UUID,
        draft_revision: int,
        suggestions: tuple[FlowSuggestion, ...],
    ) -> Self:
        return cls(
            flow_id=flow_id,
            draft_revision=draft_revision,
            items=[FlowSuggestionPublic.from_suggestion(s) for s in suggestions],
        )


__all__ = [
    "FLOW_SUGGESTIONS_EXAMPLE",
    "FlowSuggestionFixPublic",
    "FlowSuggestionImpactPublic",
    "FlowSuggestionPublic",
    "FlowSuggestionsPublic",
]
