from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from pydantic.config import JsonDict

from eneo.flows.enums import (
    FLOW_RUN_STATUS_CAPABILITIES,
    FLOW_RUN_STATUS_FILTER_ORDER,
    FlowRunStatus,
)


def _flow_run_status_capabilities_public_example() -> JsonDict:
    return {
        "statuses": [
            {
                "status": capability.status.value,
                "is_active": capability.is_active,
                "should_poll": capability.should_poll,
                "is_terminal": capability.is_terminal,
                "is_cancellable": capability.is_cancellable,
                "is_awaiting_review": capability.is_awaiting_review,
                "can_request_redispatch": capability.can_request_redispatch,
                "is_rerun_eligible": capability.is_rerun_eligible,
            }
            for capability in FLOW_RUN_STATUS_CAPABILITIES.values()
        ],
        "filter_order": [status.value for status in FLOW_RUN_STATUS_FILTER_ORDER],
    }


FLOW_RUN_STATUS_CAPABILITIES_PUBLIC_EXAMPLE = (
    _flow_run_status_capabilities_public_example()
)


class FlowRunStatusCapabilityPublic(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    status: FlowRunStatus = Field(
        description="Flow run status value this capability row describes."
    )
    is_active: bool = Field(
        description=(
            "True for statuses where the worker is expected to continue execution "
            "without waiting for human review."
        )
    )
    should_poll: bool = Field(
        description=(
            "True for statuses where client applications should continue polling "
            "for the next run state. Includes `awaiting_review` so review UIs can "
            "detect edits, approvals, expiries, and resumes."
        )
    )
    is_terminal: bool = Field(
        description=(
            "True when the run lifecycle is complete and normal polling can stop."
        )
    )
    is_cancellable: bool = Field(
        description=(
            "True when the cancel endpoint "
            "`POST /flows/{id}/runs/{run_id}/cancel/` is valid."
        )
    )
    is_awaiting_review: bool = Field(
        description=(
            "True only for `awaiting_review`, where clients should load the active "
            "review checkpoint before resuming the run."
        )
    )
    can_request_redispatch: bool = Field(
        description=(
            "True when clients may show a redispatch action for this status. "
            "Redispatch is still server-gated by staleness; a queued run that is "
            "not stale returns `redispatched_count: 0`."
        )
    )
    is_rerun_eligible: bool = Field(
        description=(
            "True when a completed or failed run may enter step-rerun validation. "
            "The rerun endpoint still validates the target step, run revision, "
            "permissions, and any replacement inputs."
        )
    )


class FlowRunStatusCapabilitiesPublic(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"example": FLOW_RUN_STATUS_CAPABILITIES_PUBLIC_EXAMPLE},
    )

    statuses: list[FlowRunStatusCapabilityPublic] = Field(
        description=(
            "Canonical status capability table. API consumers should branch on "
            "these booleans instead of hard-coding status groups."
        )
    )
    filter_order: list[FlowRunStatus] = Field(
        description=(
            "Recommended status filter order for run-history UIs. Contains every "
            "FlowRunStatus exactly once."
        )
    )


def flow_run_status_capabilities_public() -> FlowRunStatusCapabilitiesPublic:
    return FlowRunStatusCapabilitiesPublic(
        statuses=[
            FlowRunStatusCapabilityPublic.model_validate(capability)
            for capability in FLOW_RUN_STATUS_CAPABILITIES.values()
        ],
        filter_order=list(FLOW_RUN_STATUS_FILTER_ORDER),
    )
