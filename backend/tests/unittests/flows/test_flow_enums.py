from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from intric.database.tables.flow_tables import (
    FLOW_RUN_REVIEW_CHECKPOINT_STATE_VALUES,
    FLOW_RUN_STATUS_VALUES,
    FLOW_STEP_ATTEMPT_STATUS_VALUES,
    FLOW_STEP_INPUT_SOURCE_VALUES,
    FLOW_STEP_INPUT_TYPE_VALUES,
    FLOW_STEP_MCP_POLICY_VALUES,
    FLOW_STEP_OUTPUT_MODE_VALUES,
    FLOW_STEP_OUTPUT_TYPE_VALUES,
    FLOW_STEP_RESULT_STATUS_VALUES,
    FLOW_TEMPLATE_ASSET_STATUS_VALUES,
)
from intric.flows.api.flow_models import (
    FlowInputSource,
    FlowInputType,
    FlowMcpPolicy,
    FlowOutputMode,
    FlowOutputType,
)
from intric.flows.domain.flow import FlowStep
from intric.flows.enums import (
    RECONCILABLE_REVIEW_CHECKPOINT_STATES,
    FlowRunReviewCheckpointState,
    FlowRunStatus,
    FlowStepAttemptStatus,
    FlowStepResultStatus,
    FlowTemplateAssetStatus,
)
from intric.flows.flow_authoring_spec import (
    AssistantSpec,
    InputSource,
    InputType,
    StepSpec,
)


def test_shared_flow_enums_match_current_table_constants() -> None:
    assert (
        tuple(item.value for item in FlowInputSource) == FLOW_STEP_INPUT_SOURCE_VALUES
    )
    assert tuple(item.value for item in FlowInputType) == FLOW_STEP_INPUT_TYPE_VALUES
    assert tuple(item.value for item in FlowOutputMode) == FLOW_STEP_OUTPUT_MODE_VALUES
    assert tuple(item.value for item in FlowOutputType) == FLOW_STEP_OUTPUT_TYPE_VALUES
    assert tuple(item.value for item in FlowMcpPolicy) == FLOW_STEP_MCP_POLICY_VALUES
    assert tuple(item.value for item in FlowRunStatus) == FLOW_RUN_STATUS_VALUES
    assert (
        tuple(item.value for item in FlowRunReviewCheckpointState)
        == FLOW_RUN_REVIEW_CHECKPOINT_STATE_VALUES
    )
    assert (
        tuple(item.value for item in FlowStepResultStatus)
        == FLOW_STEP_RESULT_STATUS_VALUES
    )
    assert (
        tuple(item.value for item in FlowStepAttemptStatus)
        == FLOW_STEP_ATTEMPT_STATUS_VALUES
    )
    assert (
        tuple(item.value for item in FlowTemplateAssetStatus)
        == FLOW_TEMPLATE_ASSET_STATUS_VALUES
    )


def test_flow_and_ai_builder_enums_are_exported_from_shared_module() -> None:
    assert FlowInputSource.__module__ == "intric.flows.enums"
    assert FlowInputType.__module__ == "intric.flows.enums"
    assert FlowOutputMode.__module__ == "intric.flows.enums"
    assert FlowOutputType.__module__ == "intric.flows.enums"
    assert FlowMcpPolicy.__module__ == "intric.flows.enums"
    assert InputSource.__module__ == "intric.flows.enums"
    assert InputType.__module__ == "intric.flows.enums"


def test_review_expiry_reconciles_only_unresolved_review_states() -> None:
    assert RECONCILABLE_REVIEW_CHECKPOINT_STATES == frozenset(
        {
            FlowRunReviewCheckpointState.AWAITING_REVIEW,
            FlowRunReviewCheckpointState.EDITED,
        }
    )
    assert FlowRunReviewCheckpointState.APPROVED not in (
        RECONCILABLE_REVIEW_CHECKPOINT_STATES
    )
    assert FlowRunReviewCheckpointState.EXPIRED.value == "expired"


def test_flow_step_round_trips_string_fields_as_shared_enums() -> None:
    step = FlowStep.model_validate(
        {
            "assistant_id": str(uuid4()),
            "step_order": 1,
            "input_source": "flow_input",
            "input_type": "audio",
            "output_mode": "transcribe_only",
            "output_type": "text",
            "mcp_policy": "inherit",
        }
    )

    assert isinstance(step.input_source, FlowInputSource)
    assert isinstance(step.input_type, FlowInputType)
    assert isinstance(step.output_mode, FlowOutputMode)
    assert isinstance(step.output_type, FlowOutputType)
    assert isinstance(step.mcp_policy, FlowMcpPolicy)


def test_ai_builder_step_spec_keeps_builder_subset_restrictions() -> None:
    with pytest.raises(ValidationError):
        StepSpec(
            plan_step_ref="step_a",
            name="HTTP input is not planner-supported",
            assistant_spec=AssistantSpec(instructions="Do something."),
            input_source="http_get",
            input_type="text",
        )

    with pytest.raises(ValidationError):
        StepSpec(
            plan_step_ref="step_a",
            name="Image input is not planner-supported",
            assistant_spec=AssistantSpec(instructions="Do something."),
            input_source="flow_input",
            input_type="image",
        )
