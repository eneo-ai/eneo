from __future__ import annotations

from datetime import datetime
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from pydantic.config import JsonDict

from eneo.flows.domain.flow_suggestion_dismissal import (
    SUGGESTION_FINGERPRINT_PATTERN,
    FlowSuggestionDismissal,
)
from eneo.flows.domain.flow_suggestions import FlowSuggestionCode

SuggestionFingerprint = Annotated[
    str, StringConstraints(pattern=SUGGESTION_FINGERPRINT_PATTERN)
]

_FLOW_ID = "00000000-0000-0000-0000-000000000001"
_USER_ID = "00000000-0000-0000-0000-000000000301"
_FINGERPRINT = "9b2d3f1a" * 8
_DISMISSED_AT = "2026-10-25T09:30:00Z"


class FlowSuggestionDismissalRequest(BaseModel):
    """The suggestion's code, as the suggestions answer names it."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"example": {"code": "duplicate_read"}},
    )

    code: FlowSuggestionCode = Field(
        description=(
            "The `code` of the suggestion the fingerprint names. A code the "
            "definition proves must be the code of one of the draft's "
            "suggestions now; a code only runs prove is taken as given."
        ),
        examples=["duplicate_read"],
    )


class FlowSuggestionDismissedPublic(BaseModel):
    """Who dismissed a suggestion of the flow and when."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {"dismissed_by": _USER_ID, "dismissed_at": _DISMISSED_AT}
        }
    )

    dismissed_by: UUID | None = Field(
        description=(
            "The user who dismissed it; null when that user no longer exists."
        ),
        examples=[_USER_ID],
    )
    dismissed_at: datetime = Field(
        description="When it was dismissed.", examples=[_DISMISSED_AT]
    )

    @classmethod
    def from_dismissal(cls, dismissal: FlowSuggestionDismissal) -> Self:
        return cls(
            dismissed_by=dismissal.dismissed_by, dismissed_at=dismissal.dismissed_at
        )


FLOW_SUGGESTION_DISMISSAL_EXAMPLE: JsonDict = {
    "flow_id": _FLOW_ID,
    "fingerprint": _FINGERPRINT,
    "code": "duplicate_read",
    "dismissed_by": _USER_ID,
    "dismissed_at": _DISMISSED_AT,
}


class FlowSuggestionDismissalPublic(BaseModel):
    """A dismissal of one suggestion of a flow."""

    model_config = ConfigDict(
        json_schema_extra={"example": FLOW_SUGGESTION_DISMISSAL_EXAMPLE}
    )

    flow_id: UUID = Field(description="The flow.", examples=[_FLOW_ID])
    fingerprint: str = Field(
        description="The fingerprint of the suggestion dismissed.",
        examples=[_FINGERPRINT],
    )
    code: str = Field(
        description="The code of the suggestion, as it was dismissed.",
        examples=["duplicate_read"],
    )
    dismissed_by: UUID | None = Field(
        description=(
            "The user who dismissed it; null when that user no longer exists."
        ),
        examples=[_USER_ID],
    )
    dismissed_at: datetime = Field(
        description="When it was dismissed.", examples=[_DISMISSED_AT]
    )

    @classmethod
    def of(cls, *, flow_id: UUID, dismissal: FlowSuggestionDismissal) -> Self:
        return cls(
            flow_id=flow_id,
            fingerprint=dismissal.fingerprint,
            code=dismissal.code,
            dismissed_by=dismissal.dismissed_by,
            dismissed_at=dismissal.dismissed_at,
        )


__all__ = [
    "FLOW_SUGGESTION_DISMISSAL_EXAMPLE",
    "FlowSuggestionDismissalPublic",
    "FlowSuggestionDismissalRequest",
    "FlowSuggestionDismissedPublic",
    "SuggestionFingerprint",
]
