"""Legal hold ("rättslig spärr") on Flow run history.

A hold keeps the history it covers from the purge and the debug redaction,
whatever the retention policy says, until it is released or its end date
passes. It is placed on a whole Flow (all of its runs, also runs created later)
or on named runs.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, cast
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    computed_field,
)
from pydantic.config import JsonDict

MAX_FLOW_RETENTION_HOLD_REASON_LENGTH = 512
MAX_FLOW_RETENTION_HOLD_RUNS = 100
MAX_FLOW_RETENTION_HOLD_PAGE_SIZE = 200

FLOW_RETENTION_HOLD_RUN_NOT_IN_FLOW_CODE = "flow_retention_hold_run_not_in_flow"
FLOW_RETENTION_HOLD_END_NOT_IN_FUTURE_CODE = "flow_retention_hold_end_not_in_future"
FLOW_RETENTION_HOLD_ALREADY_RELEASED_CODE = "flow_retention_hold_already_released"
FLOW_RETENTION_HOLD_REVIEW_OUT_OF_RANGE_CODE = "flow_retention_hold_review_out_of_range"
FLOW_RETENTION_HOLD_REVIEW_NOT_LATER_CODE = "flow_retention_hold_review_not_later"
FLOW_RETENTION_HOLD_NOT_ACTIVE_CODE = "flow_retention_hold_not_active"

FlowRetentionHoldReason = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=MAX_FLOW_RETENTION_HOLD_REASON_LENGTH,
    ),
]


_HOLD_EXAMPLE: JsonDict = {
    "id": "00000000-0000-0000-0000-000000000901",
    "flow_id": "00000000-0000-0000-0000-000000000301",
    "flow_name": "Supplier assessment",
    "flow_retired": False,
    "space_id": "00000000-0000-0000-0000-000000000201",
    "flow_run_id": None,
    "reason": "Pending disclosure request 2026-114",
    "ends_at": None,
    "review_by": "2027-04-01T21:59:59Z",
    "review_overdue": False,
    "created_at": "2026-10-04T08:00:00Z",
    "created_by": {
        "type": "user",
        "id": "00000000-0000-0000-0000-000000000101",
        "name": "anna",
    },
    "released_at": None,
    "released_by": None,
    "release_reason": None,
    "active": True,
    "scope": "flow",
}


class FlowRetentionHoldStatusFilter(StrEnum):
    ACTIVE = "active"
    ALL = "all"


class FlowRetentionHoldCreateRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "flow_id": "00000000-0000-0000-0000-000000000301",
                "run_ids": None,
                "reason": "Pending disclosure request 2026-114",
                "review_by": "2027-04-01T21:59:59Z",
                "ends_at": None,
            }
        },
    )

    flow_id: UUID = Field(
        description=(
            "Flow whose history is held. A deleted Flow that still has run history "
            "is accepted."
        )
    )
    run_ids: (
        Annotated[
            list[UUID],
            Field(min_length=1, max_length=MAX_FLOW_RETENTION_HOLD_RUNS),
        ]
        | None
    ) = Field(
        default=None,
        description=(
            "Omit to hold every run of the Flow, including runs created later. "
            "Give 1-100 run ids to hold only those runs; each must belong to the "
            f"Flow (`{FLOW_RETENTION_HOLD_RUN_NOT_IN_FLOW_CODE}`). One hold is "
            "created per run."
        ),
    )
    reason: FlowRetentionHoldReason = Field(
        description="Why the history must be kept, 1-512 characters after trimming."
    )
    review_by: AwareDatetime = Field(
        description=(
            "When the hold must be reviewed: in the future and at most the "
            "Organization's flow_retention_hold_max_review_days ahead (default 365; "
            f"`{FLOW_RETENTION_HOLD_REVIEW_OUT_OF_RANGE_CODE}`). The hold does not "
            "end at this date; it is shown as review overdue until the review date "
            "is extended or the hold is released."
        )
    )
    ends_at: AwareDatetime | None = Field(
        default=None,
        description=(
            "Optional time when the hold stops by itself. It must be in the future "
            f"(`{FLOW_RETENTION_HOLD_END_NOT_IN_FUTURE_CODE}`). Omit to keep the hold "
            "until it is released."
        ),
    )


class FlowRetentionHoldReleaseRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"example": {"reason": "Disclosure request answered"}},
    )

    reason: FlowRetentionHoldReason = Field(
        description="Why the hold is released, 1-512 characters after trimming."
    )


class FlowRetentionHoldExtendReviewRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "review_by": "2027-10-01T21:59:59Z",
                "reason": "The disclosure request is still being handled",
            }
        },
    )

    review_by: AwareDatetime = Field(
        description=(
            "The new review date: later than the current one "
            f"(`{FLOW_RETENTION_HOLD_REVIEW_NOT_LATER_CODE}`), in the future and at "
            "most flow_retention_hold_max_review_days ahead "
            f"(`{FLOW_RETENTION_HOLD_REVIEW_OUT_OF_RANGE_CODE}`)."
        )
    )
    reason: FlowRetentionHoldReason = Field(
        description="Why the hold is still needed, 1-512 characters after trimming."
    )


class FlowRetentionHoldReviewLimit(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        json_schema_extra={"example": {"days": 365, "is_default": True}},
    )

    days: int = Field(
        description=(
            "How far ahead, in days, a review date may be set when a hold is placed "
            "or its review is moved."
        )
    )
    is_default: bool = Field(description="True while the default of 365 days applies.")


class FlowRetentionHoldReviewLimitUpdate(BaseModel):
    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"example": {"days": 180}}
    )

    days: Annotated[int, Field(strict=True, ge=1, le=2555)] | None = Field(
        description="1-2555 days, or null to return to the default of 365 days."
    )


class FlowRetentionHoldActor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: str = Field(
        description="Kind of actor recorded when the action happened, e.g. user."
    )
    id: str | None = Field(description="Identifier recorded for the actor.")
    name: str | None = Field(
        description="Display name recorded when the action happened."
    )


class FlowRetentionHold(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, json_schema_extra={"example": _HOLD_EXAMPLE}
    )

    id: UUID
    flow_id: UUID = Field(description="Flow whose history the hold covers.")
    flow_name: str = Field(description="Current Flow name.")
    flow_retired: bool = Field(description="True when the Flow is deleted.")
    space_id: UUID = Field(description="Space that owns the Flow.")
    flow_run_id: UUID | None = Field(
        description=(
            "The held run, or null when the hold covers every run of the Flow, "
            "including runs created later."
        )
    )
    reason: str = Field(description="Why the history is held.")
    review_by: datetime = Field(
        description="When the hold must be reviewed. Passing it does not end the hold."
    )
    review_overdue: bool = Field(
        description="True while the hold is active and its review date has passed."
    )
    ends_at: datetime | None = Field(
        description="When the hold stops by itself, or null for no end date."
    )
    created_at: datetime = Field(description="When the hold was placed.")
    created_by: FlowRetentionHoldActor | None = Field(
        description="Who placed the hold, as recorded at that time."
    )
    released_at: datetime | None = Field(
        description="When the hold was released, or null."
    )
    released_by: FlowRetentionHoldActor | None = Field(
        description="Who released the hold, as recorded at that time."
    )
    release_reason: str | None = Field(description="Why the hold was released.")
    active: bool = Field(
        description=(
            "True while the hold stops deletion: not released and its end date, if "
            "any, has not passed."
        )
    )

    @computed_field(  # type: ignore[prop-decorator]
        description="flow: every run of the Flow; run: one named run."
    )
    @property
    def scope(self) -> Literal["flow", "run"]:
        return "flow" if self.flow_run_id is None else "run"


class FlowRetentionHoldPage(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        json_schema_extra={
            "example": {
                "items": [_HOLD_EXAMPLE],
                "has_more": False,
                "review_limit_days": 365,
            }
        },
    )

    items: list[FlowRetentionHold]
    has_more: bool = Field(description="True when another page follows.")
    review_limit_days: int = Field(
        description=(
            "How far ahead, in days, a review date may be set when a hold is placed "
            "or its review is moved (flow_retention_hold_max_review_days)."
        )
    )


class FlowRetentionHoldPlacement(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        json_schema_extra={"example": {"holds": [_HOLD_EXAMPLE]}},
    )

    holds: list[FlowRetentionHold] = Field(
        description="The holds created: one for a Flow hold, one per named run."
    )


def flow_retention_hold_actor(snapshot: object) -> FlowRetentionHoldActor | None:
    """Narrow a stored actor snapshot to type, id and name; None when unreadable."""
    if not isinstance(snapshot, dict):
        return None
    fields = cast(dict[str, object], snapshot)
    actor_type = fields.get("type")
    if not isinstance(actor_type, str) or not actor_type:
        return None
    actor_id = fields.get("id")
    name = fields.get("name")
    return FlowRetentionHoldActor(
        type=actor_type,
        id=actor_id if isinstance(actor_id, str) else None,
        name=name if isinstance(name, str) else None,
    )
