from __future__ import annotations

from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from eneo.flows.api.flow_models import FlowPublic

MAX_APPLIED_SUGGESTIONS = 50

SuggestionFingerprint = Annotated[str, StringConstraints(min_length=1, max_length=128)]

_FINGERPRINT = "9b2d3f1a" * 8
_OTHER_FINGERPRINT = "4c7e0d2b" * 8


class FlowSuggestionsApplyRequest(BaseModel):
    """The suggestions to apply and the draft revision they were read at."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "expected_revision": 4,
                "fingerprints": [_FINGERPRINT, _OTHER_FINGERPRINT],
            }
        },
    )

    expected_revision: int = Field(
        ge=0,
        description=(
            "The `draft_revision` of the suggestions answer the fingerprints "
            "come from. The batch is fenced on it, as an editor update is."
        ),
        examples=[4],
    )
    fingerprints: list[SuggestionFingerprint] = Field(
        min_length=1,
        max_length=MAX_APPLIED_SUGGESTIONS,
        description=(
            "The `fingerprint` of each suggestion to apply, each once. One "
            "fix is a list of one. They are applied in the order the "
            "suggestions are listed, whatever the order here."
        ),
        examples=[[_FINGERPRINT]],
    )

    @model_validator(mode="after")
    def _each_fingerprint_once(self) -> Self:
        if len(self.fingerprints) != len(set(self.fingerprints)):
            raise ValueError("Name each suggestion once.")
        return self


class FlowSuggestionsAppliedPublic(BaseModel):
    """The flow after the batch and what became of each suggestion."""

    flow: FlowPublic = Field(
        description=(
            "The flow as the editor update answers with it, after the last "
            "fix of the batch."
        )
    )
    applied: list[str] = Field(
        description="The fingerprints whose fixes were applied, in that order.",
        examples=[[_FINGERPRINT]],
    )
    skipped: list[str] = Field(
        description=(
            "The fingerprints the draft no longer had once an earlier fix of "
            "the batch was applied: that fix resolved them, or changed the "
            "steps they were about. Read the suggestions again for what is "
            "left."
        ),
        examples=[[_OTHER_FINGERPRINT]],
    )


__all__ = [
    "MAX_APPLIED_SUGGESTIONS",
    "FlowSuggestionsAppliedPublic",
    "FlowSuggestionsApplyRequest",
]
