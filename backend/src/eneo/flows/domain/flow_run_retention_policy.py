from __future__ import annotations

import base64
import binascii
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, TypeAlias
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    ValidationError,
    computed_field,
    field_validator,
)

from eneo.data_retention.constants import MAX_RETENTION_DAYS, MIN_RETENTION_DAYS
from eneo.flows.enums import FlowRunStatus


class FlowRunRetentionMode(StrEnum):
    PRESERVE = "preserve"
    REVIEW_REQUIRED = "review_required"


FLOW_RUN_RETENTION_MODE_VALUES = tuple(mode.value for mode in FlowRunRetentionMode)


class FlowRunRetentionPolicy(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        json_schema_extra={"example": {"mode": "review_required", "days": 60}},
    )

    mode: FlowRunRetentionMode = Field(
        description=(
            "Preserve makes records eligible only for an explicit administrator "
            "purge. Review_required additionally requires human approval before "
            "that purge. Neither mode schedules automatic deletion."
        )
    )
    days: Annotated[
        StrictInt,
        Field(
            ge=MIN_RETENTION_DAYS,
            le=MAX_RETENTION_DAYS,
            description=(
                "Age in days after which completed Flow run history becomes eligible "
                "under this policy. Eligibility alone never deletes data."
            ),
        ),
    ]


class FlowRunRetentionContributors(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    organization: FlowRunRetentionPolicy | None
    space: FlowRunRetentionPolicy | None
    flow: FlowRunRetentionPolicy | None


FlowRunRetentionSource: TypeAlias = Literal["organization", "space", "flow", "none"]
FlowRunRetentionConfiguredSource: TypeAlias = Literal["organization", "space", "flow"]


class FlowRunRetentionOff(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    state: Literal["off"] = "off"
    mode: None = None
    effective_days: None = None
    source: Literal["none"] = "none"
    contributors: FlowRunRetentionContributors


class FlowRunRetentionConfigured(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    state: Literal["configured"] = "configured"
    mode: FlowRunRetentionMode
    effective_days: int
    source: Literal["organization", "space", "flow"]
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
                "local_policy": {"mode": "preserve", "days": 90},
                "inherited_policy": {"mode": "review_required", "days": 60},
                "effective": {
                    "state": "configured",
                    "mode": "preserve",
                    "effective_days": 90,
                    "source": "flow",
                    "contributors": {
                        "organization": {"mode": "preserve", "days": 30},
                        "space": {"mode": "review_required", "days": 60},
                        "flow": {"mode": "preserve", "days": 90},
                    },
                },
            }
        },
    )

    scope: FlowRunRetentionScope = Field(
        description="Level whose local policy is being inspected."
    )
    scope_id: UUID = Field(description="Organization, Space, or Flow identifier.")
    local_policy: FlowRunRetentionPolicy | None = Field(
        description="Policy stored at this level, or null when it inherits."
    )
    inherited_policy: FlowRunRetentionPolicy | None = Field(
        description=(
            "Nearest complete parent policy, or null when no parent policy exists."
        )
    )
    effective: FlowRunRetentionProjection = Field(
        description=(
            "Resolved policy after applying Flow, Space, then Organization precedence."
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


class FlowRunRetentionReviewItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, from_attributes=True)

    run_id: UUID = Field(description="Terminal Flow run awaiting retention review.")
    flow_id: UUID = Field(description="Flow that owns the run.")
    flow_name: str = Field(description="Current Flow name for administrator context.")
    space_id: UUID = Field(description="Space that owns the Flow.")
    space_name: str = Field(description="Current Space name for administrator context.")
    status: FlowRunStatus = Field(description="Terminal run status.")
    retention_anchor: datetime = Field(
        description=(
            "Timestamp from which the policy age is measured: finished_at when "
            "available, otherwise created_at."
        )
    )
    eligible_since: datetime = Field(
        description=(
            "Timestamp when the effective review_required age threshold was reached. "
            "This is review eligibility, not approval or deletion."
        )
    )
    effective_policy: FlowRunRetentionPolicy = Field(
        description="Complete review_required policy effective for this run."
    )
    policy_source: FlowRunRetentionConfiguredSource = Field(
        description="Most-specific level that supplied the effective policy."
    )


class FlowRunRetentionReviewCursor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    retention_anchor: datetime
    run_id: UUID

    @field_validator("retention_anchor")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Flow retention review cursor anchor needs a timezone.")
        return value

    def serialize(self) -> str:
        encoded = base64.urlsafe_b64encode(self.model_dump_json().encode()).decode()
        return f"v1.{encoded.rstrip('=')}"

    @classmethod
    def deserialize(cls, value: str) -> "FlowRunRetentionReviewCursor":
        if not value.startswith("v1."):
            raise ValueError("Invalid Flow retention review cursor.")
        encoded = value.removeprefix("v1.")
        padding = "=" * (-len(encoded) % 4)
        try:
            payload = base64.b64decode(
                encoded + padding,
                altchars=b"-_",
                validate=True,
            )
            return cls.model_validate_json(payload)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("Invalid Flow retention review cursor.") from exc


class FlowRunRetentionReviewPage(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        json_schema_extra={
            "example": {
                "items": [
                    {
                        "run_id": "00000000-0000-0000-0000-000000000501",
                        "flow_id": "00000000-0000-0000-0000-000000000301",
                        "flow_name": "Supplier assessment",
                        "space_id": "00000000-0000-0000-0000-000000000201",
                        "space_name": "Procurement",
                        "status": "completed",
                        "retention_anchor": "2026-05-01T10:00:00Z",
                        "eligible_since": "2026-06-30T10:00:00Z",
                        "effective_policy": {
                            "mode": "review_required",
                            "days": 60,
                        },
                        "policy_source": "space",
                    }
                ],
                "count": 1,
                "has_more": True,
                "next_cursor": (
                    "v1.eyJyZXRlbnRpb25fYW5jaG9yIjoiMjAyNi0wNS0wMVQxMDowMDowMFoi"
                    "LCJydW5faWQiOiIwMDAwMDAwMC0wMDAwLTAwMDAtMDAwMC0wMDAwMDAw"
                    "MDA1MDEifQ"
                ),
            }
        },
    )

    items: list[FlowRunRetentionReviewItem] = Field(
        description=(
            "Runs eligible for administrator review. Run inputs and outputs are "
            "deliberately omitted."
        )
    )
    has_more: bool = Field(description="Whether another page exists after this page.")
    next_cursor: str | None = Field(
        description="Opaque cursor for the next page, or null on the final page."
    )

    @computed_field(description="Number of review items returned in this page.")
    @property
    def count(self) -> int:
        return len(self.items)


class FlowRunRetentionPolicyStorageError(ValueError):
    """Persisted Flow retention state violates the complete-policy invariant."""


def flow_run_retention_policy_from_storage(
    *,
    mode: str | None,
    days: int | None,
) -> FlowRunRetentionPolicy | None:
    if mode is None and days is None:
        return None
    if mode is None or days is None:
        raise FlowRunRetentionPolicyStorageError(
            "Persisted Flow retention policy requires both mode and days."
        )
    try:
        return FlowRunRetentionPolicy.model_validate({"mode": mode, "days": days})
    except ValidationError as error:
        raise FlowRunRetentionPolicyStorageError(
            "Persisted Flow retention policy contains an unsupported value."
        ) from error


def resolve_flow_run_retention_policy(
    *,
    organization_policy: FlowRunRetentionPolicy | None,
    space_policy: FlowRunRetentionPolicy | None,
    flow_policy: FlowRunRetentionPolicy | None,
) -> FlowRunRetentionProjection:
    contributors = FlowRunRetentionContributors(
        organization=organization_policy,
        space=space_policy,
        flow=flow_policy,
    )
    if flow_policy is not None:
        return FlowRunRetentionConfigured(
            mode=flow_policy.mode,
            effective_days=flow_policy.days,
            source="flow",
            contributors=contributors,
        )
    if space_policy is not None:
        return FlowRunRetentionConfigured(
            mode=space_policy.mode,
            effective_days=space_policy.days,
            source="space",
            contributors=contributors,
        )
    if organization_policy is not None:
        return FlowRunRetentionConfigured(
            mode=organization_policy.mode,
            effective_days=organization_policy.days,
            source="organization",
            contributors=contributors,
        )
    return FlowRunRetentionOff(contributors=contributors)


def effective_flow_run_retention_policy(
    projection: FlowRunRetentionProjection,
) -> FlowRunRetentionPolicy | None:
    if projection.state == "off":
        return None
    return FlowRunRetentionPolicy(
        mode=projection.mode,
        days=projection.effective_days,
    )


def flow_run_retention_policy_settings(
    *,
    scope: FlowRunRetentionScope,
    scope_id: UUID,
    organization_policy: FlowRunRetentionPolicy | None,
    space_policy: FlowRunRetentionPolicy | None = None,
    flow_policy: FlowRunRetentionPolicy | None = None,
) -> FlowRunRetentionPolicySettings:
    if scope is FlowRunRetentionScope.ORGANIZATION:
        local_policy = organization_policy
        inherited_policy = None
    elif scope is FlowRunRetentionScope.SPACE:
        local_policy = space_policy
        inherited_policy = organization_policy
    else:
        local_policy = flow_policy
        inherited_policy = effective_flow_run_retention_policy(
            resolve_flow_run_retention_policy(
                organization_policy=organization_policy,
                space_policy=space_policy,
                flow_policy=None,
            )
        )
    return FlowRunRetentionPolicySettings(
        scope=scope,
        scope_id=scope_id,
        local_policy=local_policy,
        inherited_policy=inherited_policy,
        effective=resolve_flow_run_retention_policy(
            organization_policy=organization_policy,
            space_policy=space_policy,
            flow_policy=flow_policy,
        ),
    )
