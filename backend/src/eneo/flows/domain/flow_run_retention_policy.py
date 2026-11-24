from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, TypeAlias
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    computed_field,
)

from eneo.data_retention.constants import MAX_RETENTION_DAYS, MIN_RETENTION_DAYS
from eneo.data_retention.domain.rules import (
    RetentionExceedsSpaceError,
    RetentionRule,
    fewer_days,
    resolve_period,
)
from eneo.policy_levels import PolicyLevel, Resolved, admits


class FlowRunRetentionPolicy(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        json_schema_extra={"example": {"days": 30}},
    )

    days: Annotated[
        StrictInt,
        Field(
            ge=MIN_RETENTION_DAYS,
            le=MAX_RETENTION_DAYS,
            description=(
                "Age in days after which completed Flow run history becomes "
                "eligible for an explicit administrator purge. At most the Space's "
                "time, which caps every Flow in the Space. Eligibility alone never "
                "deletes data."
            ),
        ),
    ]


class FlowRunRetentionContributors(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    space: FlowRunRetentionPolicy | None = Field(
        description="The Space's time, the cap for every Flow in the Space."
    )
    flow: FlowRunRetentionPolicy | None = Field(
        description="The Flow's own time, or null when it has none."
    )


class FlowRunRetentionOff(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    state: Literal["off"] = "off"
    effective_days: None = None
    source: Literal["none"] = "none"
    contributors: FlowRunRetentionContributors


class FlowRunRetentionConfigured(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    state: Literal["configured"] = "configured"
    effective_days: int
    source: Literal["space", "flow"] = Field(
        description=(
            "The level whose time applies: the Flow's own when it is at most the "
            "Space's, otherwise the Space's."
        )
    )
    contributors: FlowRunRetentionContributors


FlowRunRetentionProjection: TypeAlias = Annotated[
    FlowRunRetentionOff | FlowRunRetentionConfigured,
    Field(discriminator="state"),
]


class FlowRunRetentionScope(StrEnum):
    ORGANIZATION = "organization"
    SPACE = "space"
    FLOW = "flow"


class FlowRunRetentionPolicySettings(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        json_schema_extra={
            "example": {
                "scope": "flow",
                "scope_id": "00000000-0000-0000-0000-000000000301",
                "local_policy": {"days": 3},
                "inherited_policy": {"days": 7},
                "effective": {
                    "state": "configured",
                    "effective_days": 3,
                    "source": "flow",
                    "contributors": {"space": {"days": 7}, "flow": {"days": 3}},
                },
            }
        },
    )

    scope: Literal[FlowRunRetentionScope.FLOW] = Field(
        description="Level whose local policy is being inspected: the Flow."
    )
    scope_id: UUID = Field(description="Flow identifier.")
    local_policy: FlowRunRetentionPolicy | None = Field(
        description="The Flow's own time, or null when it follows its Space."
    )
    inherited_policy: FlowRunRetentionPolicy | None = Field(
        description=(
            "The Space's time, which caps this Flow, or null when the Space has none."
        )
    )
    effective: FlowRunRetentionProjection = Field(
        description=(
            "The time that applies: the Flow's own when it is at most the Space's, "
            "otherwise the Space's."
        )
    )


class FlowRunRetentionSpaceTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    id: UUID = Field(description="Space available for Flow retention administration.")
    name: str = Field(description="Current Space name.")


class FlowRunRetentionSpaceTargetPage(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        json_schema_extra={
            "example": {
                "items": [
                    {
                        "id": "00000000-0000-0000-0000-000000000201",
                        "name": "Procurement",
                    }
                ],
                "count": 1,
                "has_more": False,
            }
        },
    )

    items: list[FlowRunRetentionSpaceTarget]
    has_more: bool

    @computed_field(description="Number of Spaces returned in this page.")
    @property
    def count(self) -> int:
        return len(self.items)


class FlowRunRetentionFlowTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    id: UUID = Field(description="Flow available for retention administration.")
    space_id: UUID = Field(description="Space that owns the Flow.")
    name: str = Field(description="Current Flow name.")
    retired: bool = Field(
        description=(
            "True when the Flow is deleted. A deleted Flow is listed only while it "
            "still has run history, which its retention rule governs; it can no "
            "longer run."
        )
    )
    held: bool = Field(
        description=(
            "True while the Flow or any of its runs has an active legal hold: that "
            "history is not deleted, whatever the retention policy says."
        )
    )


class FlowRunRetentionFlowTargetPage(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        json_schema_extra={
            "example": {
                "items": [
                    {
                        "id": "00000000-0000-0000-0000-000000000301",
                        "space_id": "00000000-0000-0000-0000-000000000201",
                        "name": "Supplier assessment",
                        "retired": False,
                        "held": False,
                    }
                ],
                "count": 1,
                "has_more": False,
            }
        },
    )

    items: list[FlowRunRetentionFlowTarget]
    has_more: bool

    @computed_field(description="Number of Flows returned in this page.")
    @property
    def count(self) -> int:
        return len(self.items)


def flow_run_history_period(
    *, space_days: int | None, flow_days: int | None
) -> Resolved[int]:
    """The Flow run history period that applies, by the rule's declaration."""
    return resolve_period(
        RetentionRule.FLOW_RUN_HISTORY,
        {PolicyLevel.SPACE: space_days, PolicyLevel.FLOW: flow_days},
    )


def _policy(days: int | None) -> FlowRunRetentionPolicy | None:
    return None if days is None else FlowRunRetentionPolicy(days=days)


def resolve_flow_run_retention_policy(
    *, space_days: int | None, flow_days: int | None
) -> FlowRunRetentionProjection:
    contributors = FlowRunRetentionContributors(
        space=_policy(space_days), flow=_policy(flow_days)
    )
    period = flow_run_history_period(space_days=space_days, flow_days=flow_days)
    if period.value is None:
        return FlowRunRetentionOff(contributors=contributors)
    return FlowRunRetentionConfigured(
        effective_days=period.value,
        source="flow" if period.origin is PolicyLevel.FLOW else "space",
        contributors=contributors,
    )


def require_within_space_cap(*, space_days: int | None, days: int | None) -> None:
    """Refuse a Flow time longer than its Space's; equal is allowed."""
    parent = flow_run_history_period(space_days=space_days, flow_days=None)
    if admits(parent, days, stricter=fewer_days):
        return
    assert parent.bound is not None and parent.bound_origin is not None
    raise RetentionExceedsSpaceError(
        cap_days=parent.bound, cap_origin=parent.bound_origin
    )


def flow_run_retention_policy_settings(
    *, flow_id: UUID, space_days: int | None, flow_days: int | None
) -> FlowRunRetentionPolicySettings:
    return FlowRunRetentionPolicySettings(
        scope=FlowRunRetentionScope.FLOW,
        scope_id=flow_id,
        local_policy=_policy(flow_days),
        inherited_policy=_policy(space_days),
        effective=resolve_flow_run_retention_policy(
            space_days=space_days, flow_days=flow_days
        ),
    )
